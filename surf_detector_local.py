"""
Surf Detector — Local Inference (No API call limits)
Uses ultralytics YOLOv8 to run 100% on your machine after a one-time weight download.

Compatible with Python 3.13+ (no inference-sdk dependency)

SETUP (run once in your terminal):
    pip install ultralytics opencv-python requests

USAGE:
    python surf_detector_local.py                  # uses INPUT_VIDEO below
    python surf_detector_local.py myvideo.mp4      # pass video as argument
    python surf_detector_local.py 0                # use webcam
"""

import sys
import os
import subprocess
import time
from pathlib import Path

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────
ROBOFLOW_API_KEY  = "hzQb3lNzNfJQj1wIZdTi"   # Only used ONCE to download weights
ROBOFLOW_MODEL_ID = "surf-pose-estimation-ysbb5"
ROBOFLOW_VERSION  = "1"

INPUT_VIDEO  = "your_surf_video.mp4"  # Or pass as CLI arg. Use "0" for webcam.
OUTPUT_VIDEO = "surf_detected_local.mp4"
WEIGHTS_FILE = "surf_pose_estimation.pt"  # Saved locally after first download

CONFIDENCE   = 0.40   # Detection threshold
SHOW_WINDOW  = False  # Set True to preview in a window while processing (requires display)

# Colours per class (BGR)
COLOURS = {
    "surfer": (0, 200, 255),  # Orange
    "person": (50, 220, 50),  # Green
}
DEFAULT_COLOUR = (200, 200, 200)


# ─────────────────────────────────────────────
#  DEPENDENCY CHECK
# ─────────────────────────────────────────────
def ensure_deps():
    missing = []
    for pkg, imp in [("ultralytics", "ultralytics"), ("cv2", "cv2"), ("requests", "requests")]:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg if pkg != "cv2" else "opencv-python")
    if missing:
        print(f"Installing: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing + ["-q"])
        print("Done. Re-run the script.\n")
        sys.exit(0)


# ─────────────────────────────────────────────
#  WEIGHT DOWNLOAD (one-time)
# ─────────────────────────────────────────────
def download_weights(api_key, model_id, version, dest_path):
    """Download YOLOv8 .pt weights from Roboflow (runs once, then cached locally)."""
    import requests

    print(f"📥  Downloading model weights from Roboflow...")
    print(f"    Model: {model_id} v{version}")

    url = (
        f"https://api.roboflow.com/{model_id}/{version}?"
        f"api_key={api_key}&format=yolov8pytorch"
    )

    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"\n❌  Roboflow API error {resp.status_code}: {resp.text[:300]}")
        print("    Check your API key and model ID.")
        sys.exit(1)

    data = resp.json()

    # Roboflow returns a signed S3 URL for the weights
    weights_url = data.get("model", {}).get("weights_url") or data.get("weights")
    if not weights_url:
        # Some models return export link differently
        export_url = (
            f"https://api.roboflow.com/{model_id}/{version}/yolov8pytorch?"
            f"api_key={api_key}"
        )
        resp2 = requests.get(export_url, timeout=30)
        data2 = resp2.json()
        weights_url = data2.get("model", {}).get("weights") or data2.get("link")

    if not weights_url:
        print("\n⚠️  Could not retrieve weights URL automatically.")
        print("    Manual fallback: go to https://universe.roboflow.com/surf-pose-estimation/surf-pose-estimation-ysbb5")
        print("    → Deploy → Download weights → YOLOv8 PyTorch → save as surf_pose_estimation.pt")
        print("    Then re-run this script.\n")
        sys.exit(1)

    print(f"    Downloading weights file...")
    r = requests.get(weights_url, stream=True, timeout=120)
    total = int(r.headers.get("content-length", 0))
    downloaded = 0

    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded / total * 100
                print(f"\r    {pct:.0f}% ({downloaded//1024}KB / {total//1024}KB)", end="", flush=True)

    print(f"\n✅  Weights saved to: {dest_path}\n")


# ─────────────────────────────────────────────
#  DRAWING HELPERS
# ─────────────────────────────────────────────
def draw_boxes(frame, results, class_names):
    """Draw YOLOv8 detections onto a frame."""
    import cv2

    for box in results[0].boxes:
        cls_id = int(box.cls[0])
        conf   = float(box.conf[0])
        label  = class_names[cls_id] if cls_id < len(class_names) else str(cls_id)
        colour = COLOURS.get(label, DEFAULT_COLOUR)

        x1, y1, x2, y2 = map(int, box.xyxy[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)

        text = f"{label} {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), colour, -1)
        cv2.putText(frame, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    return frame


def draw_stats(frame, frame_num, total, fps, n_surfers, n_persons):
    """Overlay stats top-left."""
    import cv2

    lines = [
        f"Frame: {frame_num}" + (f"/{total}" if total else ""),
        f"FPS:   {fps:.1f}",
        f"Surfers: {n_surfers}  Persons: {n_persons}",
    ]
    for i, line in enumerate(lines):
        y = 30 + i * 26
        cv2.putText(frame, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
        cv2.putText(frame, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,0), 1)
    return frame


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main():
    ensure_deps()

    import cv2
    from ultralytics import YOLO

    # Resolve input source
    source = sys.argv[1] if len(sys.argv) > 1 else INPUT_VIDEO
    is_webcam = source == "0" or source.isdigit()
    cap_source = int(source) if is_webcam else source

    # Download weights if not already on disk
    if not Path(WEIGHTS_FILE).exists():
        if ROBOFLOW_API_KEY == "YOUR_API_KEY_HERE":
            print("\n⚠️  Set ROBOFLOW_API_KEY at the top of the script.")
            print("   (Only needed once to download the weights file.)\n")
            sys.exit(1)
        download_weights(ROBOFLOW_API_KEY, ROBOFLOW_MODEL_ID, ROBOFLOW_VERSION, WEIGHTS_FILE)
    else:
        print(f"✅  Using cached weights: {WEIGHTS_FILE}\n")

    # Load model
    print(f"🔧  Loading YOLOv8 model...")
    model = YOLO(WEIGHTS_FILE)
    class_names = model.names  # {0: 'person', 1: 'surfer'} etc.
    print(f"    Classes: {class_names}\n")

    # Open video
    cap = cv2.VideoCapture(cap_source)
    if not cap.isOpened():
        print(f"❌  Could not open source: {source}")
        sys.exit(1)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not is_webcam else 0
    fps_in       = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    label = f"webcam" if is_webcam else source
    print(f"🎥  Source : {label}")
    print(f"    Size   : {width}x{height} @ {fps_in:.1f} fps")
    if total_frames:
        print(f"    Frames : {total_frames}")
    print(f"    Output : {OUTPUT_VIDEO}\n")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, fps_in, (width, height))

    frame_num  = 0
    t_start    = time.time()
    fps_smooth = 0.0

    print("🏄  Running... (Ctrl+C to stop)\n")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_num += 1
            t0 = time.time()

            # Run inference locally — zero API calls
            results = model(frame, conf=CONFIDENCE, verbose=False)

            # Count detections per class
            n_surfers = sum(
                1 for b in results[0].boxes
                if class_names.get(int(b.cls[0]), "").lower() == "surfer"
            )
            n_persons = sum(
                1 for b in results[0].boxes
                if class_names.get(int(b.cls[0]), "").lower() == "person"
            )

            # Draw
            frame = draw_boxes(frame, results, class_names)

            # Smooth FPS
            elapsed = time.time() - t0
            fps_smooth = 0.9 * fps_smooth + 0.1 * (1.0 / elapsed if elapsed > 0 else fps_in)

            frame = draw_stats(frame, frame_num, total_frames, fps_smooth, n_surfers, n_persons)

            writer.write(frame)

            if SHOW_WINDOW:
                cv2.imshow("Surf Detector", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("\nStopped by user.")
                    break

            # Console progress every 30 frames
            if frame_num % 30 == 0:
                total_elapsed = time.time() - t_start
                avg_fps = frame_num / total_elapsed
                if total_frames:
                    eta = (total_elapsed / frame_num) * (total_frames - frame_num)
                    pct = frame_num / total_frames * 100
                    print(f"  [{pct:5.1f}%] Frame {frame_num}/{total_frames} | "
                          f"FPS: {avg_fps:.1f} | ETA: {eta:.0f}s | "
                          f"🏄 Surfers: {n_surfers}  👤 Persons: {n_persons}")
                else:
                    print(f"  Frame {frame_num} | FPS: {avg_fps:.1f} | "
                          f"🏄 Surfers: {n_surfers}  👤 Persons: {n_persons}")

    except KeyboardInterrupt:
        print("\n⏹  Interrupted.")

    cap.release()
    writer.release()
    if SHOW_WINDOW:
        cv2.destroyAllWindows()

    total_time = time.time() - t_start
    print(f"\n✅  Done! {frame_num} frames in {total_time:.1f}s "
          f"(avg {frame_num/total_time:.1f} FPS)")
    print(f"    Saved: {OUTPUT_VIDEO}\n")


if __name__ == "__main__":
    main()
