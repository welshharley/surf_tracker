"""
Surf Pose Estimation - Video Tester
Model: https://universe.roboflow.com/surf-pose-estimation/surf-pose-estimation-ysbb5
Classes: person, surfer
"""

import cv2
import os
import sys
import time
from pathlib import Path

# ─────────────────────────────────────────────
#  CONFIGURATION — Edit these values
# ─────────────────────────────────────────────
ROBOFLOW_API_KEY = "hzQb3lNzNfJQj1wIZdTi"   # Get free key at https://app.roboflow.com
MODEL_ID         = "surf-pose-estimation-ysbb5/1"
CONFIDENCE       = 0.40                  # Detection threshold (0.0 – 1.0)
INPUT_VIDEO      = "TestVid01.mp4" # Path to your input video
OUTPUT_VIDEO     = "surf_detected.mp4"   # Output file name
PROCESS_EVERY_N  = 2                     # Run inference every N frames (1 = all frames, higher = faster)

# Colours per class  (BGR format for OpenCV)
COLOURS = {
    "surfer": (0, 200, 255),   # Orange
    "person": (50, 255, 50),   # Green
}
DEFAULT_COLOUR = (200, 200, 200)


def install_deps():
    """Install required packages if missing."""
    import subprocess
    packages = ["inference-sdk", "opencv-python-headless"]
    for pkg in packages:
        try:
            __import__(pkg.replace("-", "_").split("-headless")[0])
        except ImportError:
            print(f"Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


def draw_detections(frame, predictions, scale_x=1.0, scale_y=1.0):
    """Draw bounding boxes and labels on a frame."""
    for pred in predictions:
        x      = int(pred["x"] * scale_x)
        y      = int(pred["y"] * scale_y)
        w      = int(pred["width"] * scale_x)
        h      = int(pred["height"] * scale_y)
        label  = pred.get("class", "unknown")
        conf   = pred.get("confidence", 0)
        colour = COLOURS.get(label, DEFAULT_COLOUR)

        x1, y1 = x - w // 2, y - h // 2
        x2, y2 = x + w // 2, y + h // 2

        # Bounding box
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)

        # Label background + text
        text    = f"{label} {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), colour, -1)
        cv2.putText(frame, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    return frame


def overlay_stats(frame, frame_num, total, fps_proc, detection_count):
    """Overlay processing stats in the top-right corner."""
    progress = f"Frame {frame_num}/{total}"
    fps_text = f"Proc FPS: {fps_proc:.1f}"
    det_text = f"Detections: {detection_count}"

    for i, line in enumerate([progress, fps_text, det_text]):
        cv2.putText(frame, line, (10, 30 + i * 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, line, (10, 30 + i * 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 1, cv2.LINE_AA)
    return frame


def run_inference_on_video(api_key, model_id, input_path, output_path,
                           confidence, process_every_n):
    """Main processing loop."""
    install_deps()

    from inference_sdk import InferenceHTTPClient

    if not os.path.isfile(input_path):
        print(f"\n❌  Input video not found: {input_path}")
        print("    Update INPUT_VIDEO at the top of this script.")
        sys.exit(1)

    print(f"\n🏄  Surf Pose Estimation — Video Tester")
    print(f"    Model   : {model_id}")
    print(f"    Input   : {input_path}")
    print(f"    Output  : {output_path}")
    print(f"    Conf    : {confidence}")
    print(f"    Every N : {process_every_n} frames\n")

    # Connect to Roboflow
    client = InferenceHTTPClient(
        api_url="https://serverless.roboflow.com",
        api_key=api_key
    )

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print("❌  Could not open video.")
        sys.exit(1)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"    Video   : {width}x{height} @ {fps:.1f} fps  ({total_frames} frames)")

    # Roboflow model expects 640px input; scale detections back to original size
    INFER_SIZE = 640
    scale_x    = width  / INFER_SIZE
    scale_y    = height / INFER_SIZE

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    last_predictions = []
    frame_num        = 0
    t_start          = time.time()
    surfer_count     = 0
    person_count     = 0

    print("    Processing frames...\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_num += 1
        should_infer = (frame_num % process_every_n == 0)

        if should_infer:
            # Resize for inference
            small = cv2.resize(frame, (INFER_SIZE, INFER_SIZE))
            _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
            img_bytes = buf.tobytes()

            try:
                result = client.infer(img_bytes, model_id=model_id)
                preds  = result.get("predictions", [])
                # Filter by confidence
                last_predictions = [p for p in preds if p.get("confidence", 0) >= confidence]
                surfer_count = sum(1 for p in last_predictions if p["class"] == "surfer")
                person_count = sum(1 for p in last_predictions if p["class"] == "person")
            except Exception as e:
                print(f"    ⚠  Frame {frame_num}: inference error — {e}")
                last_predictions = []

        # Draw on original-resolution frame
        frame = draw_detections(frame, last_predictions, scale_x, scale_y)

        elapsed    = time.time() - t_start
        fps_proc   = frame_num / elapsed if elapsed > 0 else 0
        det_count  = len(last_predictions)
        frame      = overlay_stats(frame, frame_num, total_frames, fps_proc, det_count)

        writer.write(frame)

        # Progress print every 50 frames
        if frame_num % 50 == 0:
            pct = frame_num / total_frames * 100
            eta = (elapsed / frame_num) * (total_frames - frame_num)
            print(f"    [{pct:5.1f}%] Frame {frame_num}/{total_frames} | "
                  f"FPS: {fps_proc:.1f} | ETA: {eta:.0f}s | "
                  f"Surfers: {surfer_count} | Persons: {person_count}")

    cap.release()
    writer.release()

    total_time = time.time() - t_start
    print(f"\n✅  Done! Processed {frame_num} frames in {total_time:.1f}s")
    print(f"    Output saved to: {output_path}\n")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if ROBOFLOW_API_KEY == "YOUR_API_KEY_HERE":
        print("\n⚠️  Set your ROBOFLOW_API_KEY at the top of this script.")
        print("   Get a free key at: https://app.roboflow.com  (Settings → API)\n")
        sys.exit(1)

    run_inference_on_video(
        api_key       = ROBOFLOW_API_KEY,
        model_id      = MODEL_ID,
        input_path    = INPUT_VIDEO,
        output_path   = OUTPUT_VIDEO,
        confidence    = CONFIDENCE,
        process_every_n = PROCESS_EVERY_N,
    )
