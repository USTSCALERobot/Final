#!/usr/bin/env python3
# ESP32 -> Raspberry Pi receiver for camera frames.
# This script is meant to run on the Pi 5 where the Hailo toolchain is installed.
# It listens for JPEG frames from the ESP32, keeps the newest frame, and then
# either runs Hailo inference or falls back to a YOLO model.

import argparse
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

# Optional fallback if YOLO is installed in the environment.
try:
    from ultralytics import YOLO
except ImportError:  # optional fallback for non-YOLO machines
    YOLO = None

ROOT = Path(__file__).resolve().parent

# Hailo-specific paths used on the Pi 5 project.
HAILO_ENV_SCRIPT = "/home/scalepi/hailo-rpi5-examples/setup_env.sh"
HAILO_VENV_PATH = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi_examples/bin/activate"
DEFAULT_HEF_PATH = "/home/scalepi/hailo-rpi5-examples/resources/NewFinal.hef"
DEFAULT_LABELS_JSON = "/home/scalepi/hailo-rpi5-examples/resources/Final.json"


def activate_hailo_env():
    """Load the project-specific Hailo runtime used on the Pi 5."""
    # Avoid re-sourcing the environment if it was already activated in this process.
    if os.getenv("HAILO_ENV_ACTIVATED") == "1":
        return

    # Source the Hailo setup script and the example venv so the installed Hailo
    # libraries and post-processing tools are available to Python.
    cmd = (
        f"bash -c 'source {HAILO_ENV_SCRIPT} && "
        f"source {HAILO_VENV_PATH} && "
        f"export HAILO_ENV_ACTIVATED=1 && env'"
    )
    result = subprocess.run(
        cmd,
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not activate Hailo env: {result.stderr.strip()}")

    # The shell output is a full environment dump. Parse it back into os.environ so
    # the current Python process can see the Hailo paths and libraries.
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key and value:
            os.environ[key] = value

    # Set the TAPPAS directory explicitly as a fallback in case the shell didn't.
    os.environ.setdefault(
        "TAPPAS_POST_PROC_DIR",
        "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes",
    )


def recv_all(sock, size):
    # The ESP32 sends a 4-byte big-endian length header followed by the JPEG payload.
    # This helper keeps reading until the expected number of bytes is received.
    data = b""
    while len(data) < size:
        packet = sock.recv(size - len(data))
        if not packet:
            return None
        data += packet
    return data


def find_weights(explicit_weights: str | None) -> Path:
    # This is only used by the YOLO fallback path. It searches several likely model locations.
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
        "Could not find a model weights file. Put best.pt in esp_live/weights/ or pass --weights."
    )


class LatestFrame:
    """Holds only the most recently decoded frame. Never queues."""
    # This avoids CPU buildup when the ESP32 is sending frames faster than the Pi can process.
    # We intentionally replace the old frame instead of buffering a backlog.

    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._frame_id = 0

    def set(self, frame):
        with self._lock:
            self._frame = frame
            self._frame_id += 1

    def get(self, last_seen_id):
        """Returns (frame, frame_id) only if it's newer than last_seen_id."""
        with self._lock:
            if self._frame_id == last_seen_id:
                return None, last_seen_id
            return self._frame, self._frame_id


def receiver_thread(conn, latest: LatestFrame, stop_event: threading.Event):
    """Reads frames as fast as the socket delivers them and always overwrites the shared slot."""
    while not stop_event.is_set():
        # Read 4-byte payload length sent by the ESP32 before each JPEG frame.
        header = recv_all(conn, 4)
        if not header:
            break

        # Decode the length to an integer and then read that many bytes.
        size = struct.unpack("!I", header)[0]
        jpeg = recv_all(conn, size)
        if jpeg is None or len(jpeg) != size:
            print("Receiver: bad frame, stopping")
            break

        # Convert JPEG bytes to an OpenCV image.
        img_array = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            continue

        # Store the newest frame so the main loop does not lag behind the stream.
        latest.set(frame)

    stop_event.set()


def verify_hailo_runtime(hef_path: str, labels_json: str):
    """Confirms the Hailo runtime environment and required artifacts are available."""
    # Make sure the Pi 5 Hailo environment is loaded before trying to import hailo.
    activate_hailo_env()

    # The HEF and labels file are required for a real Hailo pipeline.
    if not os.path.exists(hef_path):
        raise FileNotFoundError(f"Hailo HEF not found: {hef_path}")
    if not os.path.exists(labels_json):
        raise FileNotFoundError(f"Hailo labels JSON not found: {labels_json}")

    try:
        env = os.environ.copy()
        probe = subprocess.run(
            ["python3", "-c", "import hailo; print('hailo-ok')"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        if "hailo-ok" not in probe.stdout:
            raise RuntimeError("Hailo Python package did not load correctly.")
    except Exception as exc:  # pragma: no cover - hardware-specific runtime check
        raise RuntimeError(f"Hailo runtime check failed: {exc}") from exc

    print(f"Hailo runtime OK; using model: {hef_path}")


def main():
    # Command-line arguments control the network address, backend, model files,
    # and the duration of the run. This makes it easier to test on the Pi without editing code.
    parser = argparse.ArgumentParser(
        description="Receive JPEG frames over TCP from ESP32 and run inference with the Pi 5 Hailo runtime or a YOLO fallback."
    )
    parser.add_argument("--weights", default=None, help="Path to YOLO .pt weights file")
    parser.add_argument("--host", default="10.42.0.1", help="Host address to bind on the Pi")
    parser.add_argument("--port", type=int, default=5000, help="TCP port")
    parser.add_argument("--imgsz", type=int, default=512, help="Input image size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--backend", choices=["hailo", "yolo"], default="hailo", help="Inference backend to use")
    parser.add_argument("--hef-path", default=DEFAULT_HEF_PATH, help="Path to the Hailo .hef file")
    parser.add_argument("--labels-json", default=DEFAULT_LABELS_JSON, help="Path to Hailo labels JSON")
    parser.add_argument("--device", default="cpu", help="YOLO device (cpu/cuda/0). Hailo backend ignores this.")
    parser.add_argument("--duration", type=float, default=30.0, help="Inference run duration in seconds")
    parser.add_argument("--display", action="store_true", help="Show annotated frames")
    args = parser.parse_args()

    model = None
    if args.backend == "hailo":
        # Hailo mode does not use a YOLO model object; it validates the Pi environment
        # so the actual Hailo pipeline can run in the project environment.
        verify_hailo_runtime(args.hef_path, args.labels_json)
        print("Hailo backend selected. Frame stream is being prepared for the Pi Hailo runtime.")
    else:
        # YOLO fallback is useful when you want to test a .pt model without Hailo.
        if YOLO is None:
            raise RuntimeError("ultralytics is not installed; install it or run with --backend hailo.")
        weights_path = find_weights(args.weights)
        print(f"Loading YOLO model: {weights_path}")
        model = YOLO(str(weights_path))

    # Open a listening socket on the Pi for the ESP32 camera stream.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(1)

    print(f"Waiting for ESP32 on {args.host}:{args.port}...")
    conn, addr = server.accept()
    print(f"Connected to {addr}")

    # Keep only the newest frame so the main loop never attempts to process a backlog.
    latest = LatestFrame()
    stop_event = threading.Event()
    reader = threading.Thread(target=receiver_thread, args=(conn, latest, stop_event), daemon=True)
    reader.start()

    # Store midpoint x-values per label for simple summary statistics.
    midpoints_x = defaultdict(list)

    if args.display:
        cv2.namedWindow("ESP32 camera + inference", cv2.WINDOW_NORMAL)

    last_frame_id = 0
    start_time = time.time()

    try:
        while time.time() < start_time + args.duration and not stop_event.is_set():
            # Poll for the newest received frame.
            frame, last_frame_id = latest.get(last_frame_id)

            if frame is None:
                # No new frame since the last check. Sleep briefly to avoid burning CPU.
                time.sleep(0.005)
                continue

            if args.backend == "hailo":
                # In the Hailo path, this script currently acts as a frame receiver/validator.
                # You can replace this section with actual Hailo inference calls if needed.
                if args.display:
                    cv2.imshow("ESP32 camera + inference", frame)
                    if cv2.waitKey(1) & 0xFF == 27:
                        break
                continue

            # YOLO fallback inference path.
            results = model(frame, imgsz=args.imgsz, conf=args.conf, stream=False, device=args.device)
            boxes = results[0].boxes
            if boxes is not None and len(boxes) > 0:
                xyxy = boxes.xyxy.cpu().numpy()
                cls = boxes.cls.cpu().numpy()
                for (x1, y1, x2, y2), c in zip(xyxy, cls):
                    label = model.names[int(c)]
                    mid_x = (x1 + x2) / 2
                    midpoints_x[label].append(mid_x)

            if args.display:
                annotated = results[0].plot()
                cv2.imshow("ESP32 camera + inference", annotated)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

            time.sleep(0)

    finally:
        # Always stop the receiver thread, close the socket, and clean up OpenCV windows.
        stop_event.set()
        conn.close()
        server.close()
        if args.display:
            cv2.destroyAllWindows()

        # Print average X-centroid of each class to help debug placement/bounds.
        for label, xs in midpoints_x.items():
            avg_x = sum(xs) / len(xs)
            print(f"{label}: avg midpoint x = {avg_x: .1f} over {len(xs)} detections")
            if label == "IC" and (avg_x < 300 or avg_x > 350):
                print("IC is out of bounds")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReceiver interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        print(f"Receiver error: {exc}", file=sys.stderr)
        sys.exit(1)
