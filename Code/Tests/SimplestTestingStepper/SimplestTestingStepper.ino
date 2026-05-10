#include <AccelStepper.h>

AccelStepper base(AccelStepper::DRIVER, 5, 4);
AccelStepper hingeright(AccelStepper::DRIVER, 7, 6);
AccelStepper hingeleft(AccelStepper::DRIVER, 9, 8);

void setup() {
    base.setMaxSpeed(1600.0);
    base.setAcceleration(800.0);
    

    hingeright.setMaxSpeed(1600.0);
    hingeright.setAcceleration(800.0);
   

    hingeleft.setMaxSpeed(1600.0);
    hingeleft.setAcceleration(800.0);


    base.moveTo(10000);  // 2 full revolutions at 200 steps/rev
    hingeleft.moveTo(10000);  // 2 full revolutions at 200 steps/rev
    hingeright.moveTo(10000);  // 2 full revolutions at 200 steps/rev

}

void loop() {
    if (base.distanceToGo() == 0 || hingeleft.distanceToGo() == 0 || hingeright.distanceToGo() == 0) {
        base.moveTo(-base.currentPosition());  // bounce back
        hingeleft.moveTo(-base.currentPosition());
        hingeright.moveTo(-base.currentPosition());
    }
    
    base.run();
    hingeright.run();
    hingeleft.run();
}