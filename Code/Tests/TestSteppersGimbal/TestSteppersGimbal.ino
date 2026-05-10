#include <AccelStepper.h>

// DRIVER mode: Step, Direction
AccelStepper base(AccelStepper::DRIVER, 5, 4);
AccelStepper hingeright(AccelStepper::DRIVER, 7, 6);
AccelStepper hingeleft(AccelStepper::DRIVER, 9, 8);

// Step size per key press
const int STEP_SIZE = 200;

void setup()
{
    Serial.begin(9600);
    Serial.println("Controls: W/S = hinge, A/D = base");

    base.setMaxSpeed(1600.0);
    base.setAcceleration(1500.0);

    hingeright.setMaxSpeed(1600.0);
    hingeright.setAcceleration(1500.0);

    hingeleft.setMaxSpeed(1600.0);
    hingeleft.setAcceleration(1500.0);
}

void move(long baseSteps, long hingeSteps) {
    base.move(baseSteps);
    hingeright.move(hingeSteps);
    hingeleft.move(-hingeSteps);

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
        Serial.print("Base: "); Serial.print(base.currentPosition());
        Serial.print("  Hinge: "); Serial.println(hingeright.currentPosition());
    }
}

void loop()
{
    handleSerial();
}
