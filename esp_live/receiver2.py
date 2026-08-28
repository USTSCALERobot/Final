import argparse
import socket
import struct
from pathlib import Path
import time

import cv2
import numpy as np
from ultralytics import YOLO

from collections import defaultdict

ROOT = Path(__file__).resolve().parent


def recv_all(sock, size):
    data = b""
    while len(data) < size:
        packet = sock.recv(size - len(data))
        if not packet:
            return None
        data += packet
    return data


def find_weights(explicit_weights: str | None) -> Path:
    if explicit_weights:
        return Path(explicit_weights).expanduser().resolve()

    candidates = [
        ROOT / "weights" / "best.pt",
        ROOT / "best.pt",
        ROOT.parent / "runs" / "esp_live" / "weights" / "best.pt",
        ROOT.parent / "runs" / "esp_live" / "weights" / "last.pt",
    ]
    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Could not find a model weights file. Put best.pt in pi5_package/weights/ or pass --weights."
    )

'''solution for latency issues'''

class LatestFrame:
    """Holds only the most recently decoded frame. Never queues."""
 
    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._frame_id = 0
 
    def set(self, frame):
        with self._lock:
            self._frame = frame
            self._frame_id += 1
 
    def get(self, last_seen_id):
        """Returns (frame, frame_id) only if it's newer than last_seen_id, else (None, last_seen_id)."""
        with self._lock:
            if self._frame_id == last_seen_id:
                return None, last_seen_id
            return self._frame, self._frame_id
 
 
def receiver_thread(conn, latest: LatestFrame, stop_event: threading.Event):
    """Reads frames as fast as the socket delivers them and always overwrites
    the shared slot, so the main/inference loop can never fall behind on a
    backlog -- it just always sees the newest frame available."""
    while not stop_event.is_set():
        header = recv_all(conn, 4)
        if not header:
            break
 
        size = struct.unpack("!I", header)[0]
        jpeg = recv_all(conn, size)
        if jpeg is None or len(jpeg) != size:
            print("Receiver: bad frame, stopping")
            break
 
        img_array = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            continue
 
        latest.set(frame)
 
    stop_event.set()
 

def main():
    parser = argparse.ArgumentParser(
        description="Receive JPEG frames over TCP from ESP32 and run YOLO inference"
    )
    parser.add_argument("--weights", default=None, help="Path to YOLO .pt weights file")
    parser.add_argument("--host", default="10.42.0.1", help="Host address to bind on the Pi")
    parser.add_argument("--port", type=int, default=5000, help="TCP port")
    parser.add_argument("--imgsz", type=int, default=512, help="Input image size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--device", default="cpu", help="Inference device, e.g. cpu") #use hailo module to run inference
    parser.add_argument("--display", action="store_true", help="Show annotated frames")
    args = parser.parse_args()

    weights_path = find_weights(args.weights)
    print(f"Loading model: {weights_path}")
    model = YOLO(str(weights_path))

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(1)

    print(f"Waiting for ESP32 on {args.host}:{args.port}...")
    conn, addr = server.accept()
    print(f"Connected to {addr}")

    latest = LatestFrame()
    stop_event = threading.Event()
    reader = threading.Thread(target=receiver_thread, args=(conn, latest, stop_event), daemon=True)
    reader.start()
    
    midpoints_x = defaultdict(list)

    if args.display:
        cv2.namedWindow("ESP32 camera + inference", cv2.WINDOW_NORMAL)

    last_frame_id = 0
    start_time = time.time()


    try:
        
        while time.time() < start_time + args.duration and not stop_event.is_set():
            frame, last_frame_id = latest.get(last_frame_id)

            if frame is None:
                # No new frame since we last checked -- don't burn CPU spinning,
                # but this is a short poll, not a fixed per-frame throttle.
                time.sleep(0.005)
                continue
 
            results = model(frame, imgsz=args.imgsz, conf=args.conf, stream=False, device=args.device)

            '''bounding boxes'''
            boxes = results[0].boxes
            if boxes is not None and len(boxes) > 0:
                xyxy = boxes.xyxy.cpu().numpy()      # (N, 4) array: x1, y1, x2, y2 in pixels
                cls  = boxes.cls.cpu().numpy()       # (N,) class indices

                for (x1, y1, x2, y2), c in zip(xyxy, cls):
                    label = model.names[int(c)]
                    mid_x = (x1 + x2) / 2
                    midpoints_x[label].append(mid_x)

            '''window'''
            if args.display:
                annotated = results[0].plot()
                cv2.imshow("ESP32 camera + inference", annotated)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

            time.sleep(0)

    finally:
        stop_event.set()
        conn.close()
        server.close()
        if args.display:
            cv2.destroyAllWindows()

        for label, xs in midpoints_x.items(): #once the main loop is over, left with avg x midpoint coordinates
            avg_x = sum(xs) / len(xs)
            print(f"{label}: avg midpoint x = {avg_x: .1f} over {len(xs)} detections")
            if label == "IC" and (avg_x < 300 or avg_x > 350):
                print("IC is out of bounds")


if __name__ == "__main__":
    main()
