"""
Clean HDMI Video Feed from Canon 80D via capture card.

Returns raw frames (numpy arrays) with zero overlays — ready for AI model inference.
Provides programmatic start/stop control for the feed.

HARDWARE SETUP:
    Canon 80D HDMI out -> HDMI capture card -> USB -> Computer

CAMERA SETUP (do once on the Canon 80D):
    1. Set dial to Movie mode (video camera icon)
    2. Menu > Wrench tab 3 > HDMI > Output: Auto
    3. Menu > Wrench tab 3 > HDMI > Clean HDMI output: Enable
       (This removes all camera UI — AF points, exposure bar, etc.)
    4. Set to Manual Focus (MF switch on lens) to prevent AF hunting
    5. Disable image stabilization if on a tripod

USAGE:
    # As a module — integrate into your AI pipeline
    from hdmi_video_feed import CameraFeed

    feed = CameraFeed(device=0, width=1920, height=1080)
    feed.start()

    frame = feed.get_frame()    # numpy array (H, W, 3) BGR
    if frame is not None:
        # pass to your YOLO model, etc.
        results = model(frame)

    feed.stop()

    # Standalone — preview the feed and verify it's clean
    python hdmi_video_feed.py
    python hdmi_video_feed.py --device 1         # different capture card index
    python hdmi_video_feed.py --width 1280 --height 720
"""

import cv2
import time
import threading
import argparse
import numpy as np


class CameraFeed:
    """Threaded HDMI capture card reader with start/stop control."""

    def __init__(self, device=0, width=1920, height=1080, fps=30):
        self._device = device
        self._width = width
        self._height = height
        self._fps = fps

        self._cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    @property
    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return

        self._cap = cv2.VideoCapture(self._device)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Could not open capture device {self._device}. "
                "Check that the HDMI capture card is connected and the camera is on."
            )

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self._cap.get(cv2.CAP_PROP_FPS)
        print(f"Feed opened: {actual_w}x{actual_h} @ {actual_fps:.0f}fps (device {self._device})")

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        with self._lock:
            self._frame = None
        print("Feed stopped.")

    def get_frame(self):
        """Return the latest frame as a numpy array (H, W, 3) BGR, or None."""
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def _capture_loop(self):
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.001)
                continue
            with self._lock:
                self._frame = frame


def main():
    parser = argparse.ArgumentParser(description="Preview clean HDMI feed from Canon 80D")
    parser.add_argument("--device", type=int, default=0, help="Capture card device index")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    feed = CameraFeed(device=args.device, width=args.width, height=args.height, fps=args.fps)
    feed.start()

    print("\n" + "=" * 60)
    print("CONTROLS (click the preview window FIRST, then press keys):")
    print("  q      = quit")
    print("  s      = save current frame")
    print("  space  = pause/resume preview")
    print("  ESC    = quit")
    print("Or press Ctrl+C in this terminal to quit anytime.")
    print("=" * 60 + "\n")

    window_name = "HDMI Feed (preview only - AI gets raw frames)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    paused = False
    frame_count = 0
    t_start = time.time()
    last_frame = None

    try:
        while True:
            if not paused:
                frame = feed.get_frame()
                if frame is not None:
                    last_frame = frame
            else:
                frame = last_frame

            if frame is None:
                time.sleep(0.01)
                continue

            frame_count += 1
            elapsed = time.time() - t_start
            live_fps = frame_count / elapsed if elapsed > 0 else 0

            display = frame.copy()
            h, w = display.shape[:2]
            info = f"{w}x{h} | {live_fps:.1f} fps"
            if paused:
                info += " | PAUSED"
            cv2.putText(display, info, (10, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            cv2.imshow(window_name, display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:  # q or ESC
                print("Quit key pressed.")
                break
            elif key == ord("s"):
                ts = time.strftime("%Y%m%d_%H%M%S")
                filename = f"capture_{ts}.jpg"
                cv2.imwrite(filename, frame)
                print(f"Saved: {filename}")
            elif key == ord(" "):
                paused = not paused
                print("Paused" if paused else "Resumed")

            # Detect if window was closed via the red close button
            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    print("Window closed.")
                    break
            except cv2.error:
                break

    except KeyboardInterrupt:
        print("\nCtrl+C — quitting.")

    feed.stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
