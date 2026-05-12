#!/usr/bin/env python3
"""
BNO055 IMU calibration + read tool.

Without --calibrate:  loads saved config, streams the camera's true heading.
With --calibrate:     walks through full setup and writes three JSON files
                      alongside this script:

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

import board
import busio
import adafruit_bno055


CONFIG_DIR = Path(__file__).parent
CALIB_FILE    = CONFIG_DIR / "bno055_calibration.json"
MOUNTING_FILE = CONFIG_DIR / "camera_mounting_offset.json"
LOCATION_FILE = CONFIG_DIR / "location.json"

DEFAULT_DECLINATION = 12.5    # Sydney
DEFAULT_LOCATION    = "Sydney"


# ── Connection ──────────────────────────────────────────────────────────────
def connect_imu():
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        return adafruit_bno055.BNO055_I2C(i2c, address=0x29)
    except Exception as e:
        sys.exit(
            f"Could not connect to BNO055: {e}\n"
            f"Check wiring and that I2C is enabled (sudo raspi-config -> Interface Options)."
        )


# ── Saved-calibration restore ───────────────────────────────────────────────
def load_existing_calibration(sensor):
    """Push saved sensor offsets into the BNO055. Returns True if a file was loaded."""
    if not CALIB_FILE.exists():
        return False
    offsets = json.load(open(CALIB_FILE))
    sensor.mode = adafruit_bno055.CONFIG_MODE
    sensor.offsets_accelerometer = tuple(offsets["accel_offset"])
    sensor.offsets_magnetometer  = tuple(offsets["mag_offset"])
    sensor.offsets_gyroscope     = tuple(offsets["gyro_offset"])
    sensor.radius_accelerometer  = offsets["accel_radius"]
    sensor.radius_magnetometer   = offsets["mag_radius"]
    sensor.mode = adafruit_bno055.NDOF_MODE
    time.sleep(0.5)
    return True


# ── Calibration routines ────────────────────────────────────────────────────
def calibrate_sensors(sensor):
    """Walk through BNO055 self-calibration; save resulting offsets.
    Skips the figure-8 dance if a saved profile already brings everything to 3."""
    if CALIB_FILE.exists():
        load_existing_calibration(sensor)
        _, gyro, accel, mag = sensor.calibration_status
        if mag == 3 and accel == 3 and gyro == 3:
            print("Sensor already fully calibrated (loaded from file). Skipping figure-8.")
            return

    print("\n=== Sensor calibration ===")
    print("Move the IMU until every status reaches 3:")
    print("  Gyro:   leave stationary on a flat surface for ~5s")
    print("  Accel:  slowly rotate through 6 orientations, holding each face for 2s")
    print("  Mag:    wave in a slow figure-8 in 3D, several times")
    print()

    while True:
        sys_, gyro, accel, mag = sensor.calibration_status
        print(f"\rsys={sys_} gyro={gyro} accel={accel} mag={mag}    ", end="", flush=True)
        if mag == 3 and accel == 3 and gyro == 3:
            break
        time.sleep(0.5)
    print("\nFully calibrated.")

    offsets = {
        "accel_offset": list(sensor.offsets_accelerometer),
        "mag_offset":   list(sensor.offsets_magnetometer),
        "gyro_offset":  list(sensor.offsets_gyroscope),
        "accel_radius": sensor.radius_accelerometer,
        "mag_radius":   sensor.radius_magnetometer,
    }
    with open(CALIB_FILE, "w") as f:
        json.dump(offsets, f, indent=2)
    print(f"Saved {CALIB_FILE.name}")


def calibrate_mounting(sensor):
    """Capture the offset between the IMU's heading axis and the camera's optical axis."""
    print("\n=== Camera mounting offset ===")
    print("Aim the camera at a known reference bearing.")
    print("Use a TRUE-north source (phone compass set to true north, or sight a known landmark).")

    s = input("True bearing the camera is now pointing at (degrees) [0]: ").strip()
    true_bearing = float(s) if s else 0.0

    input("Hold the camera steady on the bearing, then press Enter to capture...")

    # Average a few readings to reduce noise
    samples = []
    for _ in range(10):
        h = sensor.euler[0]
        if h is not None:
            samples.append(h)
        time.sleep(0.05)
    if not samples:
        sys.exit("IMU returned no valid heading. Re-run --calibrate from scratch.")
    raw = sum(samples) / len(samples)

    mounting_offset = (raw - true_bearing) % 360
    payload = {
        "offset_deg": mounting_offset,
        "raw_at_calibration": raw,
        "true_bearing_at_calibration": true_bearing,
    }
    with open(MOUNTING_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Mounting offset = {mounting_offset:.2f}° saved to {MOUNTING_FILE.name}")


def calibrate_location():
    print("\n=== Location / magnetic declination ===")
    print("Look it up at https://www.ngdc.noaa.gov/geomag/calculators/magcalc.shtml")
    print("Common Australian values: Sydney +12.5°, Melbourne +11.5°, Perth ~0°")

    existing_decl = DEFAULT_DECLINATION
    existing_name = DEFAULT_LOCATION
    if LOCATION_FILE.exists():
        d = json.load(open(LOCATION_FILE))
        existing_decl = d.get("magnetic_declination_deg", DEFAULT_DECLINATION)
        existing_name = d.get("name", DEFAULT_LOCATION)

    name = input(f"Location name [{existing_name}]: ").strip() or existing_name
    s = input(f"Declination in degrees (positive = east) [{existing_decl}]: ").strip()
    declination = float(s) if s else existing_decl

    with open(LOCATION_FILE, "w") as f:
        json.dump({"name": name, "magnetic_declination_deg": declination}, f, indent=2)
    print(f"Saved {LOCATION_FILE.name}")


# ── Read mode ───────────────────────────────────────────────────────────────
def true_heading(sensor):
    """Convert the IMU's raw magnetic heading into a true world bearing."""
    raw = sensor.euler[0]
    if raw is None:
        return None
    mounting    = json.load(open(MOUNTING_FILE))["offset_deg"]
    declination = json.load(open(LOCATION_FILE))["magnetic_declination_deg"]
    return (raw - mounting + declination) % 360


def stream_mode(sensor):
    missing = [f.name for f in (CALIB_FILE, MOUNTING_FILE, LOCATION_FILE) if not f.exists()]
    if missing:
        sys.exit(f"Missing config files: {missing}\nRun with --calibrate first.")

    load_existing_calibration(sensor)

    print("Streaming heading. Ctrl-C to quit.")
    try:
        while True:
            raw = sensor.euler[0]
            true = true_heading(sensor)
            if raw is not None and true is not None:
                print(f"\rraw={raw:6.1f}°  true={true:6.1f}°    ", end="", flush=True)
            else:
                print("\rwaiting for valid heading...                  ", end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()


# ── Entry point ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="BNO055 calibration and read tool.")
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run the full calibration routine. Without this flag, the script "
             "loads saved config and streams the camera's true heading.",
    )
    args = parser.parse_args()

    sensor = connect_imu()

    if args.calibrate:
        calibrate_sensors(sensor)
        calibrate_mounting(sensor)
        calibrate_location()
        print("\nAll done. Run again without --calibrate to stream the heading.")
    else:
        stream_mode(sensor)


if __name__ == "__main__":
    main()
