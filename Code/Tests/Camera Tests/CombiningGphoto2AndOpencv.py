import cv2
import subprocess
from datetime import datetime

# -----------------------------
# Utility: run terminal command
# -----------------------------
def run_cmd(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())
    return result

# -----------------------------
# DSLR control via gphoto2 USB
# -----------------------------
def take_photo():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"photo_{timestamp}.jpg"
    command = ["gphoto2", "--capture-image-and-download", "--filename", filename]
    print(f"Taking photo: {filename}")
    run_cmd(command)

def autofocus():
    print("Trying autofocus / half-press...")
    command = ["gphoto2", "--set-config", "eosremoterelease=Half Press"]
    run_cmd(command)

def release_focus():
    command = ["gphoto2", "--set-config", "eosremoterelease=Release Half"]
    run_cmd(command)

def set_iso(value):
    command = ["gphoto2", "--set-config", f"iso={value}"]
    print(f"Setting ISO to {value}")
    run_cmd(command)

def try_start_camera_video():
    """
    Attempts to start internal camera recording over USB.
    Exact config names vary by Canon model/firmware.
    These are common patterns to test.
    """
    possible_commands = [
        ["gphoto2", "--set-config", "movierecordtarget=Card"],
        ["gphoto2", "--set-config", "movierecordtarget=None"],
        ["gphoto2", "--set-config", "eosmovie=1"],
    ]

    print("Trying to start internal camera recording...")
    for cmd in possible_commands:
        result = run_cmd(cmd)
        if result.returncode == 0:
            print("A start-video command appears to have worked.")
            return True

    print("Could not confirm internal camera recording start.")
    return False

def try_stop_camera_video():
    possible_commands = [
        ["gphoto2", "--set-config", "eosmovie=0"],
    ]

    print("Trying to stop internal camera recording...")
    for cmd in possible_commands:
        result = run_cmd(cmd)
        if result.returncode == 0:
            print("A stop-video command appears to have worked.")
            return True

    print("Could not confirm internal camera recording stop.")
    return False

# -----------------------------
# HDMI feed helpers
# -----------------------------
def save_hdmi_frame(frame):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"frame_{timestamp}.jpg"
    cv2.imwrite(filename, frame)
    print(f"Saved HDMI frame: {filename}")

def start_hdmi_recording(frame_width, frame_height, fps=30):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"hdmi_recording_{timestamp}.mp4"

    # mp4v is widely available and simple to use
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(filename, fourcc, fps, (frame_width, frame_height))

    if not writer.isOpened():
        print("Failed to open VideoWriter.")
        return None, None

    print(f"Started HDMI recording: {filename}")
    return writer, filename

def draw_overlay(frame, hdmi_recording, hdmi_filename, camera_recording):
    status_lines = [
        "q = quit",
        "s = save HDMI frame",
        "p = take photo via USB",
        "a = autofocus half-press",
        "d = release half-press",
        "i = ISO 100",
        "v = start/stop HDMI recording",
        "c = start/stop internal camera recording",
    ]

    y = 30
    for line in status_lines:
        cv2.putText(frame, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        y += 28

    hdmi_text = "HDMI REC: ON" if hdmi_recording else "HDMI REC: OFF"
    cam_text = "CAM REC: ON" if camera_recording else "CAM REC: OFF"

    cv2.putText(frame, hdmi_text, (20, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255) if hdmi_recording else (200, 200, 200), 2)
    cv2.putText(frame, cam_text, (20, y + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255) if camera_recording else (200, 200, 200), 2)

    if hdmi_filename:
        cv2.putText(frame, hdmi_filename, (20, y + 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

# -----------------------------
# Main
# -----------------------------
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Could not open capture card video feed.")
    raise SystemExit

# Optional: try to set desired resolution/FPS
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cap.set(cv2.CAP_PROP_FPS, 30)

video_writer = None
video_filename = None
hdmi_recording = False
camera_recording = False

print("Controls:")
print("  q = quit")
print("  s = save HDMI frame")
print("  p = take DSLR photo via USB/gphoto2")
print("  a = autofocus / half press")
print("  d = release half press")
print("  i = set ISO 100")
print("  v = start/stop HDMI recording to MP4")
print("  c = try start/stop internal camera recording")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to read frame from capture card.")
        break

    # Write frame to HDMI video file if recording
    if hdmi_recording and video_writer is not None:
        video_writer.write(frame)

    display_frame = frame.copy()
    draw_overlay(display_frame, hdmi_recording, video_filename, camera_recording)
    cv2.imshow("Canon HDMI Feed", display_frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord('q'):
        break

    elif key == ord('s'):
        save_hdmi_frame(frame)

    elif key == ord('p'):
        take_photo()

    elif key == ord('a'):
        autofocus()

    elif key == ord('d'):
        release_focus()

    elif key == ord('i'):
        set_iso("100")

    elif key == ord('v'):
        if not hdmi_recording:
            frame_height, frame_width = frame.shape[:2]
            video_writer, video_filename = start_hdmi_recording(frame_width, frame_height, fps=30)
            if video_writer is not None:
                hdmi_recording = True
        else:
            hdmi_recording = False
            if video_writer is not None:
                video_writer.release()
                video_writer = None
                print(f"Stopped HDMI recording: {video_filename}")
                video_filename = None

    elif key == ord('c'):
        if not camera_recording:
            camera_recording = try_start_camera_video()
        else:
            stopped = try_stop_camera_video()
            if stopped:
                camera_recording = False

cap.release()

if video_writer is not None:
    video_writer.release()

cv2.destroyAllWindows()
