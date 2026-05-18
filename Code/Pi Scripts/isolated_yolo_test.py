"""
isolated_yolo_test.py
─────────────────────
Mac-side standalone test rig for the surf-tracker (no Heltec, no LoRa, no GPS).

Reads HDMI video from a Canon 80D via a USB capture card, runs the trained
YOLOv8 surfer detector on each frame, finds the highest-confidence surfer,
computes the horizontal AND vertical pixel offsets from frame center, converts
them to pan + tilt angle deltas, and sends step-count commands over USB serial
to an Arduino that drives THREE steppers (base + two mirrored hinge motors).

Pairs with:
  Code/Arduino Scripts/IsolatedYoloTest/IsolatedYoloTest.ino

Hardware chain:
  Canon 80D ─(HDMI)→ capture card ─(USB)→ Mac ─(USB)→ Arduino
                                                          ├─ DRV8825 → base stepper
                                                          ├─ DRV8825 → hinge-right stepper
                                                          └─ DRV8825 → hinge-left stepper

Serial protocol (one command per line, '\n' terminator):
  M <base_steps> <hinge_steps>    Move base + hinge by relative step counts.
                                  +hinge_steps drives hinge-right CW and
                                  hinge-left CCW (mirrored) to tilt one way.

Usage:
  cd /Users/harleywelsh/Documents/git/surf_tracker
  venv/bin/python3 "Code/Pi Scripts/isolated_yolo_test.py"

You'll be prompted ONCE for the starting heading (cosmetic — for absolute
heading readout). Press 'q' in the video window or Ctrl+C in the terminal
to exit.

Before first run:
  1. Set CAMERA_HFOV_DEG to match the lens you're using (see table below).
     Vertical FOV is auto-computed from HFOV + frame aspect ratio.
  2. Set HDMI_DEVICE_INDEX — try 0 first; if you see the Mac's webcam instead
     of the HDMI feed, increment to 1, 2, etc. The helper below prints what's
     attached:
       venv/bin/python3 -c "import cv2;
       [print(i, cv2.VideoCapture(i).isOpened()) for i in range(5)]"
  3. Make sure STEPS_PER_REV * MICROSTEPS matches the jumpers on your DRV8825.
  4. If the BASE pans the wrong way when surfer is right-of-center, flip
     INVERT_BASE below (or swap the DRV8825 motor coil A1/A2).
  5. If the HINGE tilts the wrong way when surfer is above center, flip
     INVERT_HINGE below.
"""

import cv2
import glob
import math
import os
import serial
import sys
import time
from ultralytics import YOLO

# ── CONFIG ──────────────────────────────────────────────────────────────────

# Path to the trained YOLO model, resolved relative to this script's location
# so it works regardless of which directory you launch from.
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
MODEL_PATH   = os.path.join(PROJECT_ROOT, "runs/surfdetection02/weights/best.pt")

# Detection — model classes: 0=person, 1=surfer
SURFER_CLASS_ID = 1
PERSON_CLASS_ID = 0

# Two thresholds: surfer is the primary target with a stricter threshold.
# Person is the fallback when no confident surfer is in frame (model
# occasionally classifies a surfer as just a person), so use a lower bar.
SURFER_CONF_THRESHOLD = 0.5
PERSON_CONF_THRESHOLD = 0.3

# Video input — the HDMI capture device. Edit if the wrong device opens.
HDMI_DEVICE_INDEX = 0

# Canon 80D APS-C horizontal FOV by focal length (approximate):
#   18mm=67°  24mm=53°  35mm=38°  50mm=26°  85mm=16°  135mm=10°  200mm=7°
CAMERA_HFOV_DEG = 67.0

# Stepper — must match IsolatedYoloTest.ino's microstepping jumpers
STEPS_PER_REV = 200
MICROSTEPS    = 16
STEPS_PER_DEG = (STEPS_PER_REV * MICROSTEPS) / 360.0   # = 8.888 at 1/16 microstep

# Ignore tiny corrections (avoids motor twitching from detection noise).
# Separate thresholds so the hinge can be less twitchy than the base if its
# mechanics are heavier / laggier.
MIN_PAN_DEG  = 0.5     # base / horizontal
MIN_TILT_DEG = 1.0     # hinge / vertical — raise if hinge still jitters

# Flip if a motor moves the wrong way. Either change this or swap motor coils.
INVERT_BASE  = False
INVERT_HINGE = False

# Serial
SERIAL_BAUD = 115200


def find_arduino_port():
    """First USB-serial device that looks like an Arduino on macOS."""
    candidates = sorted(
        glob.glob('/dev/cu.usbmodem*')      # Uno R3, Leonardo, Micro, native USB
        + glob.glob('/dev/cu.usbserial*')   # Nano (CH340 / FTDI)
        + glob.glob('/dev/cu.SLAB_USBtoUART*')
    )
    if not candidates:
        sys.exit("No Arduino USB-serial device found. Plug it in and try again.")
    return candidates[0]


def vfov_from_hfov(hfov_deg, frame_w, frame_h):
    """Derive vertical FOV from horizontal FOV + frame aspect ratio.

    Uses the proper pinhole-camera formula:
      VFOV = 2 * atan( (h/w) * tan(HFOV/2) )
    """
    half_h = math.radians(hfov_deg / 2)
    half_v = math.atan((frame_h / frame_w) * math.tan(half_h))
    return 2 * math.degrees(half_v)


def main():
    # 1. Cosmetic starting heading
    try:
        current_heading = float(input("Enter current camera heading (0-360°, degrees from N): "))
    except ValueError:
        sys.exit("Heading must be a number.")
    current_heading %= 360

    # 2. Serial to Arduino
    port = find_arduino_port()
    print(f"Opening Arduino on {port} @ {SERIAL_BAUD}")
    ser = serial.Serial(port, SERIAL_BAUD, timeout=0.1)
    time.sleep(2)   # let the Arduino's auto-reset complete
    ser.reset_input_buffer()

    # 3. HDMI capture
    print(f"Opening video device index {HDMI_DEVICE_INDEX}")
    cap = cv2.VideoCapture(HDMI_DEVICE_INDEX)
    if not cap.isOpened():
        sys.exit(f"Couldn't open video device {HDMI_DEVICE_INDEX}. Try 1 or 2.")

    # 4. YOLO model
    print(f"Loading model: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)

    print("\nRunning. Press 'q' in the video window or Ctrl+C in terminal to quit.\n")
    last_print = time.time()
    frames_since_print = 0
    vfov_deg = None     # computed from first valid frame

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Frame read failed.")
                time.sleep(0.1)
                continue

            h, w = frame.shape[:2]
            frame_center_x = w / 2
            frame_center_y = h / 2

            # Derive VFOV from the first real frame so the user only ever sets HFOV
            if vfov_deg is None:
                vfov_deg = vfov_from_hfov(CAMERA_HFOV_DEG, w, h)
                print(f"Frame {w}x{h}  HFOV={CAMERA_HFOV_DEG:.1f}°  "
                      f"VFOV={vfov_deg:.1f}°")

            # Inference — both classes, gated at the lower (person) threshold.
            # We'll apply the per-class thresholds when picking the target below.
            results = model.predict(
                source=frame, conf=PERSON_CONF_THRESHOLD,
                classes=[SURFER_CLASS_ID, PERSON_CLASS_ID],
                device="mps", verbose=False,
            )[0]

            # Prefer the highest-confidence SURFER above SURFER_CONF_THRESHOLD.
            # If none qualifies, fall back to the highest-confidence PERSON
            # above PERSON_CONF_THRESHOLD.
            best_surfer = None      # (idx, conf)
            best_person = None
            chosen_idx   = None
            chosen_class = None

            if results.boxes is not None and len(results.boxes) > 0:
                boxes = results.boxes
                for i in range(len(boxes)):
                    cls_id   = int(boxes.cls[i].item())
                    conf_val = float(boxes.conf[i].item())
                    if cls_id == SURFER_CLASS_ID and conf_val >= SURFER_CONF_THRESHOLD:
                        if best_surfer is None or conf_val > best_surfer[1]:
                            best_surfer = (i, conf_val)
                    elif cls_id == PERSON_CLASS_ID and conf_val >= PERSON_CONF_THRESHOLD:
                        if best_person is None or conf_val > best_person[1]:
                            best_person = (i, conf_val)

                if best_surfer is not None:
                    chosen_idx, chosen_class = best_surfer[0], SURFER_CLASS_ID
                elif best_person is not None:
                    chosen_idx, chosen_class = best_person[0], PERSON_CLASS_ID

            if chosen_idx is not None:
                x1, y1, x2, y2 = boxes.xyxy[chosen_idx].tolist()
                surfer_cx = (x1 + x2) / 2
                surfer_cy = (y1 + y2) / 2
                target_label = "surfer" if chosen_class == SURFER_CLASS_ID else "person"
                # Box colour: green for surfer (primary), yellow for person (fallback)
                box_colour = (0, 255, 0) if chosen_class == SURFER_CLASS_ID else (0, 255, 255)

                # Pixel offsets → angular offsets
                pan_deg  = ((surfer_cx - frame_center_x) / w) * CAMERA_HFOV_DEG
                tilt_deg = ((surfer_cy - frame_center_y) / h) * vfov_deg
                # Note: tilt_deg > 0 means surfer is BELOW center (image y grows down)

                base_steps = 0
                hinge_steps = 0

                if abs(pan_deg) >= MIN_PAN_DEG:
                    move_pan = -pan_deg if INVERT_BASE else pan_deg
                    base_steps = int(round(move_pan * STEPS_PER_DEG))
                    current_heading = (current_heading + move_pan) % 360

                if abs(tilt_deg) >= MIN_TILT_DEG:
                    move_tilt = -tilt_deg if INVERT_HINGE else tilt_deg
                    hinge_steps = int(round(move_tilt * STEPS_PER_DEG))

                if base_steps != 0 or hinge_steps != 0:
                    ser.write(f"M {base_steps} {hinge_steps}\n".encode())
                    print(f"{target_label}@({surfer_cx:.0f},{surfer_cy:.0f})/{w}x{h}  "
                          f"pan={pan_deg:+.1f}° tilt={tilt_deg:+.1f}°  "
                          f"steps base={base_steps:+d} hinge={hinge_steps:+d}  "
                          f"heading={current_heading:.1f}°")

                # Visualise the chosen detection (green=surfer, yellow=person fallback)
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)),
                              box_colour, 2)
                cv2.putText(frame, target_label, (int(x1), int(y1) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_colour, 2)
                cv2.circle(frame, (int(surfer_cx), int(surfer_cy)), 5,
                           (0, 0, 255), -1)

            # Crosshairs for reference
            cv2.line(frame, (int(frame_center_x), 0),
                     (int(frame_center_x), h), (255, 255, 255), 1)
            cv2.line(frame, (0, int(frame_center_y)),
                     (w, int(frame_center_y)), (255, 255, 255), 1)
            cv2.imshow("Surf tracker", frame)

            # FPS once per second
            frames_since_print += 1
            now = time.time()
            if now - last_print >= 1.0:
                fps = frames_since_print / (now - last_print)
                cv2.setWindowTitle("Surf tracker", f"Surf tracker — {fps:.1f} FPS")
                frames_since_print = 0
                last_print = now

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        cap.release()
        cv2.destroyAllWindows()
        print("Closed.")


if __name__ == "__main__":
    main()
