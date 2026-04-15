# ============================================================
# train_graph_classifier.py
# Train a YOLOv8 model on your Roboflow dataset (graphs-sw685, v2)
# ============================================================

# --- Imports ---
from roboflow import Roboflow
from ultralytics import YOLO
import os

# --- 1️⃣  Download dataset from Roboflow ---
rf = Roboflow(api_key="bc61nNGpY1eaHF22wsvz")
project = rf.workspace("scale-research").project("graphs-sw685")
version = project.version(2)
dataset = version.download("yolov8")   # creates ./datasets/graphs-sw685-2/
print(f"✅ Dataset downloaded at: {dataset.location}")

# --- 2️⃣  Initialize YOLOv8 model ---
# 'yolov8n.pt' = nano model (fast); try yolov8s.pt for higher accuracy
model = YOLO("yolov8n.pt")

# --- 3️⃣  Train the model ---
results = model.train(
    data=os.path.join(dataset.location, "data.yaml"),  # dataset YAML path
    epochs=50,             # increase for more accuracy
    imgsz=640,             # image resolution
    batch=16,              # reduce if you hit GPU memory limits
    name="graph_classifier",  # output folder name
    project="runs/train"   # where results are stored
)

print("\n✅ Training complete!")
print(f"📁 Results saved to: {results.save_dir}")
print("🧠  Best weights -> runs/train/graph_classifier/weights/best.pt")

