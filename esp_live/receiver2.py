import argparse
import socket
import struct
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

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


def main():
    parser = argparse.ArgumentParser(
        description="Receive JPEG frames over TCP from ESP32 and run YOLO inference"
    )
    parser.add_argument("--weights", default=None, help="Path to YOLO .pt weights file")
    parser.add_argument("--host", default="10.42.0.1", help="Host address to bind on the Pi")
    parser.add_argument("--port", type=int, default=5000, help="TCP port")
    parser.add_argument("--imgsz", type=int, default=512, help="Input image size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--device", default="cpu", help="Inference device, e.g. cpu")
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

    if args.display:
        cv2.namedWindow("ESP32 camera + inference", cv2.WINDOW_NORMAL)

    try:
        while True:
            header = recv_all(conn, 4)
            if not header:
                break

            size = struct.unpack("!I", header)[0]
            jpeg = recv_all(conn, size)
            if jpeg is None:
                break
            if len(jpeg) != size:
                print(f"Received {len(jpeg)} bytes, expected {size}")
                break

            img_array = np.frombuffer(jpeg, dtype=np.uint8)
            frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if frame is None:
                print("Could not decode JPEG frame")
                continue

            results = model(frame, imgsz=args.imgsz, conf=args.conf, stream=False, device=args.device)
            annotated = results[0].plot()

            if args.display:
                cv2.imshow("ESP32 camera + inference", annotated)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

    finally:
        conn.close()
        server.close()
        if args.display:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()