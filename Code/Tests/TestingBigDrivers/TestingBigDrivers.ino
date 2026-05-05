#include <AccelStepper.h>

const int stepPin = 3;
const int dirPin = 4;
const int enPin = 5;

// Define as a 'DRIVER' (1) for Pulse/Dir hardware
AccelStepper stepper(AccelStepper::DRIVER, stepPin, dirPin);

void setup() {
  stepper.setEnablePin(enPin);
  stepper.setPinsInverted(false, false, true); // Invert enable if active-low
  stepper.enableOutputs();
  
  stepper.setMaxSpeed(2000);
  stepper.setAcceleration(1500);
  stepper.moveTo(100); // Move 2000 steps
}

void loop() {
  stepper.run(); // Non-blocking motor movement
}
