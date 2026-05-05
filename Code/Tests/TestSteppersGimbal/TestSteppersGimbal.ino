#include <AccelStepper.h>

AccelStepper base(AccelStepper::DRIVER, 5, 4);
AccelStepper hingeright(AccelStepper::DRIVER, 7, 6);
AccelStepper hingeleft(AccelStepper::DRIVER, 9, 8);

// --- Rotation limits (in steps) ---
const long BASE_MIN  = -100;
const long BASE_MAX  =  100;
const long HINGE_MIN = -30;
const long HINGE_MAX =  27;

// Step size per key press
const int STEP_SIZE = 1;

// Tracked absolute positions
long posBase  = 0;
long posHinge = 0;  // hingeright and hingeleft mirror each other

void setup()
{
    Serial.begin(9600);
    Serial.println("Controls: W/S = hinge, A/D = base");

    base.setMaxSpeed(1000.0);
    base.setAcceleration(500.0);

    hingeright.setMaxSpeed(1000.0);
    hingeright.setAcceleration(500.0);

    hingeleft.setMaxSpeed(1000.0);
    hingeleft.setAcceleration(500.0);
}

long clamp(long value, long minVal, long maxVal) {
    if (value < minVal) return minVal;
    if (value > maxVal) return maxVal;
    return value;
}

void move(long baseSteps, long hingeSteps) {
    long newBase  = clamp(posBase  + baseSteps,  BASE_MIN,  BASE_MAX);
    long newHinge = clamp(posHinge + hingeSteps, HINGE_MIN, HINGE_MAX);

    long actualBaseSteps  = newBase  - posBase;
    long actualHingeSteps = newHinge - posHinge;

    posBase  = newBase;
    posHinge = newHinge;

    base.move(actualBaseSteps);
    hingeright.move(actualHingeSteps);
    hingeleft.move(-actualHingeSteps);

    while (base.distanceToGo() != 0 || hingeright.distanceToGo() != 0 || hingeleft.distanceToGo() != 0) {
        base.run();
        hingeright.run();
        hingeleft.run();
    }
}

void handleSerial() {
    if (Serial.available() > 0) {
        char key = Serial.read();
        switch (key) {
            case 'w': case 'W': move(0,  STEP_SIZE); break;  // hinge forward
            case 's': case 'S': move(0, -STEP_SIZE); break;  // hinge back
            case 'a': case 'A': move(-STEP_SIZE, 0); break;  // base left
            case 'd': case 'D': move( STEP_SIZE, 0); break;  // base right
        }
        Serial.print("Base: "); Serial.print(posBase);
        Serial.print("  Hinge: "); Serial.println(posHinge);
    }
}

void loop()
{
    handleSerial();
    // move(0, 20);
    // delay(500);
    // move(10, -40);
    // delay(500);
    // move(-10, 20);
    // delay(500);
}
