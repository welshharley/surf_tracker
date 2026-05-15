#!/usr/bin/env python3
"""
BNO055 IMU class for the surf tracker.

Use as a library (from another script):
    from imu import IMU
    imu = IMU()
    bearing = imu.heading()       # camera's true world bearing, deg (0-360)

Use as a standalone calibration / streaming tool:
    python3 imu.py                # stream the corrected heading
    python3 imu.py --calibrate    # walk through full sensor + mounting + location setup

Three JSON files live alongside this script:
    bno055_calibration.json     - sensor offsets (set once, persistent)
    camera_mounting_offset.json - mechanical offset between IMU and camera optical axis
    location.json               - magnetic declination for your region

Install once:
    pip install adafruit-circuitpython-bno055 adafruit-blinka

Wire the BNO055 to the Pi's I2C-1 bus:
    BNO VCC -> Pi pin 1  (3.3V)
    BNO GND -> Pi pin 6  (GND)
    BNO SDA -> Pi pin 3  (GPIO 2 / SDA)
    BNO SCL -> Pi pin 5  (GPIO 3 / SCL)
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import board
import busio
import adafruit_bno055


CONFIG_DIR    = Path(__file__).parent
CALIB_FILE    = CONFIG_DIR / "bno055_calibration.json"
MOUNTING_FILE = CONFIG_DIR / "camera_mounting_offset.json"
LOCATION_FILE = CONFIG_DIR / "location.json"

DEFAULT_DECLINATION = 12.5     # Sydney
DEFAULT_LOCATION    = "Sydney"


class IMU:
    """BNO055 wrapper that returns the camera's TRUE world bearing.

    Loads saved sensor calibration, mounting offset, and declination on init,
    so .heading() works immediately if calibration files exist.
    """

    def __init__(self, address: int = 0x29, load_saved_calibration: bool = True):
        # Connect to the chip
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self.sensor = adafruit_bno055.BNO055_I2C(i2c, address=address)
        except Exception as e:
            raise RuntimeError(
                f"Could not connect to BNO055: {e}\n"
                f"Check wiring and that I2C is enabled (sudo raspi-config -> Interface Options)."
            )

        # Mounting offset + declination - default if no saved config
        self.mounting_offset_deg = 0.0
        self.declination_deg     = DEFAULT_DECLINATION
        self.location_name       = DEFAULT_LOCATION
        self._load_offsets()

        # Restore saved sensor calibration if present
        if load_saved_calibration:
            self.load_saved_calibration()

    # ── Hardware-level helpers ──────────────────────────────────────────────
    def load_saved_calibration(self) -> bool:
        """Push saved sensor offsets back into the BNO055. Returns True if loaded."""
        if not CALIB_FILE.exists():
            return False
        offsets = json.load(open(CALIB_FILE))
        self.sensor.mode = adafruit_bno055.CONFIG_MODE
        self.sensor.offsets_accelerometer = tuple(offsets["accel_offset"])
        self.sensor.offsets_magnetometer  = tuple(offsets["mag_offset"])
        self.sensor.offsets_gyroscope     = tuple(offsets["gyro_offset"])
        self.sensor.radius_accelerometer  = offsets["accel_radius"]
        self.sensor.radius_magnetometer   = offsets["mag_radius"]
        self.sensor.mode = adafruit_bno055.NDOF_MODE
        time.sleep(0.5)
        return True

    def _load_offsets(self):
        """Read mounting + location JSONs into instance vars."""
        if MOUNTING_FILE.exists():
            self.mounting_offset_deg = json.load(open(MOUNTING_FILE))["offset_deg"]
        if LOCATION_FILE.exists():
            d = json.load(open(LOCATION_FILE))
            self.declination_deg = d.get("magnetic_declination_deg", DEFAULT_DECLINATION)
            self.location_name   = d.get("name", DEFAULT_LOCATION)

    def reload_offsets(self):
        """Re-read mounting + location JSONs (call after recalibrating)."""
        self._load_offsets()

    # ── Read methods (use these from your bridge code) ──────────────────────
    @property
    def raw_heading(self) -> Optional[float]:
        """IMU's own X-axis heading vs magnetic north, in degrees. None if no fix."""
        return self.sensor.euler[0]

    def heading(self) -> Optional[float]:
        """Camera's TRUE world bearing in degrees (0 = N, 90 = E).
        Returns None if the IMU isn't producing a valid reading yet."""
        raw = self.sensor.euler[0]
        if raw is None:
            return None
        return (raw - self.mounting_offset_deg + self.declination_deg) % 360

    @property
    def calibration_status(self) -> Tuple[int, int, int, int]:
        """(sys, gyro, accel, mag), each 0-3."""
        return self.sensor.calibration_status

    @property
    def is_calibrated(self) -> bool:
        """True if gyro, accel, and mag are all at status 3."""
        _, gyro, accel, mag = self.sensor.calibration_status
        return mag == 3 and accel == 3 and gyro == 3

    # ── Calibration workflows ───────────────────────────────────────────────
    def calibrate_sensors(self):
        """Walk the user through BNO055 self-calibration; save resulting offsets."""
        if self.is_calibrated:
            print("Sensor already fully calibrated. Skipping figure-8.")
            return

        print("\n=== Sensor calibration ===")
        print("Move the IMU until every status reaches 3:")
        print("  Gyro:   leave stationary on a flat surface for ~5s")
        print("  Accel:  slowly rotate through 6 orientations, holding each face for 2s")
        print("  Mag:    wave in a slow figure-8 in 3D, several times")
        print()

        while True:
            sys_, gyro, accel, mag = self.sensor.calibration_status
            print(f"\rsys={sys_} gyro={gyro} accel={accel} mag={mag}    ", end="", flush=True)
            if mag == 3 and accel == 3 and gyro == 3:
                break
            time.sleep(0.5)
        print("\nFully calibrated.")

        offsets = {
            "accel_offset": list(self.sensor.offsets_accelerometer),
            "mag_offset":   list(self.sensor.offsets_magnetometer),
            "gyro_offset":  list(self.sensor.offsets_gyroscope),
            "accel_radius": self.sensor.radius_accelerometer,
            "mag_radius":   self.sensor.radius_magnetometer,
        }
        with open(CALIB_FILE, "w") as f:
            json.dump(offsets, f, indent=2)
        print(f"Saved {CALIB_FILE.name}")

    def calibrate_mounting(self):
        """Capture the offset between IMU heading axis and camera optical axis."""
        print("\n=== Camera mounting offset ===")
        print("Aim the camera at a known reference bearing.")
        print("Use a TRUE-north source (phone compass set to true north, or sight a known landmark).")

        s = input("True bearing the camera is now pointing at (degrees) [0]: ").strip()
        true_bearing = float(s) if s else 0.0

        input("Hold the camera steady on the bearing, then press Enter to capture...")

        samples = []
        for _ in range(10):
            h = self.sensor.euler[0]
            if h is not None:
                samples.append(h)
            time.sleep(0.05)
        if not samples:
            sys.exit("IMU returned no valid heading. Re-run --calibrate from scratch.")
        raw = sum(samples) / len(samples)

        mounting_offset = (raw - true_bearing) % 360
        with open(MOUNTING_FILE, "w") as f:
            json.dump({
                "offset_deg": mounting_offset,
                "raw_at_calibration": raw,
                "true_bearing_at_calibration": true_bearing,
            }, f, indent=2)
        print(f"Mounting offset = {mounting_offset:.2f}° saved to {MOUNTING_FILE.name}")
        self.mounting_offset_deg = mounting_offset

    def calibrate_location(self):
        print("\n=== Location / magnetic declination ===")
        print("Look it up at https://www.ngdc.noaa.gov/geomag/calculators/magcalc.shtml")
        print("Common Australian values: Sydney +12.5°, Melbourne +11.5°, Perth ~0°")

        name = input(f"Location name [{self.location_name}]: ").strip() or self.location_name
        s = input(f"Declination in degrees (positive = east) [{self.declination_deg}]: ").strip()
        declination = float(s) if s else self.declination_deg

        with open(LOCATION_FILE, "w") as f:
            json.dump({"name": name, "magnetic_declination_deg": declination}, f, indent=2)
        print(f"Saved {LOCATION_FILE.name}")
        self.declination_deg = declination
        self.location_name   = name

    def calibrate_all(self):
        """Walk through every calibration step in order."""
        self.calibrate_sensors()
        self.calibrate_mounting()
        self.calibrate_location()
        print("\nAll done.")

    # ── Standalone streaming mode ───────────────────────────────────────────
    def stream(self):
        """Print true heading continuously until Ctrl-C."""
        missing = [f.name for f in (CALIB_FILE, MOUNTING_FILE, LOCATION_FILE) if not f.exists()]
        if missing:
            sys.exit(f"Missing config files: {missing}\nRun with --calibrate first.")

        print("Streaming heading. Ctrl-C to quit.")
        try:
            while True:
                raw = self.raw_heading
                true = self.heading()
                if raw is not None and true is not None:
                    print(f"\rraw={raw:6.1f}°  true={true:6.1f}°    ", end="", flush=True)
                else:
                    print("\rwaiting for valid heading...                  ", end="", flush=True)
                time.sleep(0.2)
        except KeyboardInterrupt:
            print()


# ── CLI entry point ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="BNO055 calibration and read tool.")
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run the full calibration routine. Without this flag, the script "
             "loads saved config and streams the camera's true heading.",
    )
    args = parser.parse_args()

    imu = IMU()

    if args.calibrate:
        imu.calibrate_all()
        print("Run again without --calibrate to stream the heading.")
    else:
        imu.stream()


if __name__ == "__main__":
    main()
