from ultralytics import YOLO

best_model = "runs/surfdetection02/weights/best.pt"

model = YOLO(best_model)

VIDEO_PATH = "TestVid04.mp4" 

# Run inference on the video
# 'show=True' will display the video with detections in a new window
# 'save=True' will save the output video with annotations to the 'runs/detect' directory

#results = model.predict(source=VIDEO_PATH, show=True, save=True)
#results =  model("TestImg01.jpg")
#results[0].show()


results = model.predict(source="TestVid04.MP4", conf=0.3, device="mps", show=True, save=True)
