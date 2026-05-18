/*
  IsolatedYoloTest.ino
  ────────────────────
  Standalone Arduino-side firmware for the surf-tracker test rig (no Heltec,
  no LoRa, no GPS). Receives "M <base_steps> <hinge_steps>\n" commands over
  USB serial from the Mac and drives three DRV8825-driven steppers:
    - base   (pan)
    - hingeR (tilt, mirrored with hingeL)
    - hingeL (tilt, mirrored with hingeR — moves opposite to hingeR)

  Pairs with:
    Code/Pi Scripts/isolated_yolo_test.py

  Serial protocol (one command per line, '\n' terminator, 115200 baud):
    M <base_steps> <hinge_steps>
       Relative move. +base_steps pans clockwise (viewed from above).
       +hinge_steps drives hingeR by +N and hingeL by -N (mirrored tilt).
       Either value may be 0 to move only one axis. Backwards-compatible:
       "M <base_steps>" alone is accepted with hinge implicitly 0.

    S  Print one-line status: "pos base=... hingeR=... hingeL=..."

  Hardware:
    Arduino Uno / Nano / Mega (anything with HardwareSerial)
    3 × DRV8825 stepper drivers
    3 × NEMA17 steppers, 200 steps/rev
    1/16 microstepping on DRV8825: M2 = HIGH, M0 = M1 = LOW (or left floating)
    DRV8825 VMOT: 12-24V external supply
    DRV8825 logic GND  ⇒  ARDUINO GND  (required common reference)
    DRV8825 RESET, SLEEP  ⇒  tie HIGH (to 5V) — otherwise driver is disabled

  Pin wiring (edit if your board uses different pins):
    Base   STEP / DIR   →  D5  / D6
    HingeR STEP / DIR   →  D8  / D9
    HingeL STEP / DIR   →  D10 / D11
    Shared ENABLE       →  D7   (LOW = motors energised)

  Required library:
    AccelStepper
    Install via Arduino IDE: Tools → Manage Libraries → search "AccelStepper"
*/

#include <AccelStepper.h>

// ── Pin assignments ────────────────────────────────────────────────────────
const int BASE_STEP = 5;
const int BASE_DIR  = 6;
const int EN_PIN    = 7;          // Shared ENABLE for all three drivers.

const int HR_STEP   = 8;
const int HR_DIR    = 9;

const int HL_STEP   = 10;
const int HL_DIR    = 11;

// ── Motion config (keep in sync with isolated_yolo_test.py) ────────────────
// Base is light and unloaded; hinges lift the camera weight against gravity
// so they get a lower speed/accel to keep torque headroom and avoid stalling.
const float BASE_MAX_SPEED  = 1600.0;   // steps/sec
const float BASE_ACCEL      = 400.0;    // steps/sec^2
const float HINGE_MAX_SPEED = 800.0;    // steps/sec
const float HINGE_ACCEL     = 600.0;    // steps/sec^2

AccelStepper base(AccelStepper::DRIVER, BASE_STEP, BASE_DIR);
AccelStepper hr  (AccelStepper::DRIVER, HR_STEP,   HR_DIR);
AccelStepper hl  (AccelStepper::DRIVER, HL_STEP,   HL_DIR);

void setup() {
  Serial.begin(115200);

  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW);      // LOW = enabled on DRV8825/A4988

  base.setMaxSpeed(BASE_MAX_SPEED);
  base.setAcceleration(BASE_ACCEL);
  hr.setMaxSpeed(HINGE_MAX_SPEED);
  hr.setAcceleration(HINGE_ACCEL);
  hl.setMaxSpeed(HINGE_MAX_SPEED);
  hl.setAcceleration(HINGE_ACCEL);

  Serial.println("Ready");
}

void loop() {
  // Service all three steppers every loop — AccelStepper.run() is non-blocking
  // and only emits a STEP pulse when one is due.
  base.run();
  hr.run();
  hl.run();

  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) return;

    char cmd = line.charAt(0);

    if (cmd == 'M') {
      // Strip "M " then split on whitespace into base + (optional) hinge.
      String args = line.substring(1);
      args.trim();

      long baseSteps  = 0;
      long hingeSteps = 0;

      int sep = args.indexOf(' ');
      if (sep == -1) {
        baseSteps = args.toInt();
        hingeSteps = 0;             // backwards-compat: only base provided
      } else {
        baseSteps  = args.substring(0, sep).toInt();
        hingeSteps = args.substring(sep + 1).toInt();
      }

      base.move(baseSteps);
      hr.move( hingeSteps);
      hl.move(-hingeSteps);         // mirrored — opposite direction to hingeR

      Serial.print("ack M ");
      Serial.print(baseSteps);
      Serial.print(' ');
      Serial.println(hingeSteps);

    } else if (cmd == 'S') {
      Serial.print("pos base=");   Serial.print(base.currentPosition());
      Serial.print(" hingeR=");    Serial.print(hr.currentPosition());
      Serial.print(" hingeL=");    Serial.println(hl.currentPosition());

    } else {
      Serial.print("err unknown: ");
      Serial.println(line);
    }
  }
}
