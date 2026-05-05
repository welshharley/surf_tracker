import cv2
import subprocess
import numpy as np

def mjpeg_stream():
    cmd = ["gphoto2", "--stdout", "--capture-movie"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    buffer = b""

    try:
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break

            buffer += chunk

            start = buffer.find(b'\xff\xd8')  # JPEG start
            end = buffer.find(b'\xff\xd9')    # JPEG end

            if start != -1 and end != -1 and end > start:
                jpg = buffer[start:end+2]
                buffer = buffer[end+2:]

                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    yield frame
    finally:
        proc.terminate()
        proc.wait()

for frame in mjpeg_stream():
    cv2.imshow("Canon 80D Live View", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cv2.destroyAllWindows()
