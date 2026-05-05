import cv2
import subprocess
import numpy as np
import time
import io

def capture_live_view_frame():
    # Command to capture a live view frame to stdout
    command = ["gphoto2", "--capture-movie", "--stdout"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Read the raw image data (e.g., Motion JPEG frame)
    # The exact data format may require adjustment
    # For simple still frame capture in live view, a different approach is better

def capture_still_live_view():
    # This approach captures one JPEG frame from live view to memory
    command = ["gphoto2", "--capture-preview", "--stdout"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()

    # Convert the raw data to an OpenCV image format
    if stdout:
        image_data = np.frombuffer(stdout, dtype=np.uint8)
        frame = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
        return frame
    return None

# Main loop for streaming
while True:
    frame = capture_still_live_view()
    if frame is not None:
        cv2.imshow('Canon 80D Live View', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    time.sleep(0.05) # Small delay to prevent overwhelming the system

cv2.destroyAllWindows()
