import time
from ultralytics import YOLO

MODEL = "best_full_integer_quant_edgetpu.tflite"
VIDEO = "TestVid04.mp4"

model = YOLO(MODEL)

print("Warm-up (first inference loads the model onto the TPU)...")
model.predict(source=VIDEO, imgsz=320, conf=0.4, save=False,
              verbose=False, stream=False)

print("Timed run...")
t0 = time.time()
results = model.predict(source=VIDEO, imgsz=320, conf=0.4,
                        save=True, stream=True, verbose=False)
n = sum(1 for _ in results)
dt = time.time() - t0
print(f"{n} frames in {dt:.1f}s -> {n/dt:.1f} FPS")
print("Annotated video saved under runs/detect/")
