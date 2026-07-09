#!/usr/bin/env python3
"""
Run the Roboflow hosted workflow for integrated circuit defect detection.

Examples:
    python defectdetect.py
    python defectdetect.py --image savephototest/chip_cropped_1.png
    python defectdetect.py --image orin_nano/pcb_ic_dataset --max-images 10

The default API key, workspace, and workflow ID match the Roboflow workflow
provided for this project. They can be overridden with command line options or
environment variables when needed.
"""

import argparse
import json
import os
import struct
import sys
import time
from pathlib import Path

try:
    from inference_sdk import InferenceHTTPClient
except ImportError:
    InferenceHTTPClient = None


DEFAULT_API_URL = "https://serverless.roboflow.com"
DEFAULT_API_KEY = "PN65LbBAqB50oBN9VoAI"
DEFAULT_WORKSPACE = "ryans-workspace-wugmo"
DEFAULT_WORKFLOW_ID = "integrated-circuit-ic-swcjc"
DEFAULT_SAVE_FOLDER = "/home/scalepi/Desktop/savephototest"
DEFAULT_FLAG_OUTPUT = os.path.join(DEFAULT_SAVE_FOLDER, "defect_flag.txt")
DEFAULT_THRESHOLD = 0.0
IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
NON_DEFECT_LABELS = {"good", "ok", "pass", "passed", "normal", "no_defect", "no defect", "none"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a Roboflow workflow on a local image or folder of images."
    )
    parser.add_argument(
        "--image",
        "--images",
        dest="image_path",
        default=os.path.join(DEFAULT_SAVE_FOLDER, "chip_cropped_1.png"),
        help="Image file or folder of images to send to the workflow.",
    )
    parser.add_argument(
        "--output",
        default="roboflow_workflow_results",
        help="Folder where JSON workflow results are saved.",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("ROBOFLOW_API_URL", DEFAULT_API_URL),
        help="Roboflow inference server URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("ROBOFLOW_API_KEY", DEFAULT_API_KEY),
        help="Roboflow API key. Can also be set with ROBOFLOW_API_KEY.",
    )
    parser.add_argument(
        "--workspace",
        default=os.getenv("ROBOFLOW_WORKSPACE", DEFAULT_WORKSPACE),
        help="Roboflow workspace name.",
    )
    parser.add_argument(
        "--workflow-id",
        default=os.getenv("ROBOFLOW_WORKFLOW_ID", DEFAULT_WORKFLOW_ID),
        help="Roboflow workflow ID.",
    )
    parser.add_argument(
        "--image-input-name",
        default=os.getenv("ROBOFLOW_IMAGE_INPUT_NAME", "image"),
        help="Workflow image input name. The provided workflow uses 'image'.",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="Optional cap when --image points to a folder.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable Roboflow workflow cache.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the full JSON result for every image.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.getenv("ROBOFLOW_DEFECT_THRESHOLD", DEFAULT_THRESHOLD)),
        help="Minimum confidence needed to mark a defect.",
    )
    parser.add_argument(
        "--flag-output",
        default=os.getenv("DEFECT_FLAG_FILE", DEFAULT_FLAG_OUTPUT),
        help="Path where the pass/fail flag for the arm is written.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=int(os.getenv("ROBOFLOW_RETRIES", "2")),
        help="Retry count when the workflow returns no parseable predictions.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=float(os.getenv("ROBOFLOW_RETRY_DELAY", "1.0")),
        help="Seconds to wait between Roboflow retries.",
    )
    return parser.parse_args()


def collect_images(path, max_images=None):
    image_path = Path(path)
    if image_path.is_file():
        return [image_path]

    if not image_path.is_dir():
        raise FileNotFoundError(f"Image path does not exist: {image_path}")

    images = sorted(
        p for p in image_path.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if max_images is not None:
        images = images[:max_images]
    return images


def safe_output_name(image_path):
    return (
        image_path.name.replace(" ", "_")
        .replace("#", "num")
        .replace(":", "-")
    )


def read_image_size(image_path):
    path = Path(image_path)
    try:
        with path.open("rb") as file:
            header = file.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                width, height = struct.unpack(">II", header[16:24])
                return width, height

            if header[:2] == b"\xff\xd8":
                file.seek(2)
                while True:
                    marker_start = file.read(1)
                    if not marker_start:
                        break
                    if marker_start != b"\xff":
                        continue
                    marker = file.read(1)
                    while marker == b"\xff":
                        marker = file.read(1)
                    if marker in (b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"):
                        segment = file.read(7)
                        if len(segment) == 7:
                            height, width = struct.unpack(">HH", segment[3:7])
                            return width, height
                        break
                    length_bytes = file.read(2)
                    if len(length_bytes) != 2:
                        break
                    length = struct.unpack(">H", length_bytes)[0]
                    if length < 2:
                        break
                    file.seek(length - 2, os.SEEK_CUR)
    except OSError:
        pass
    return None, None


def run_workflow(client, args, image_path):
    return client.run_workflow(
        workspace_name=args.workspace,
        workflow_id=args.workflow_id,
        images={
            args.image_input_name: str(image_path),
        },
        use_cache=not args.no_cache,
    )


def workflow_has_predictions(result):
    return any(True for _ in iter_prediction_dicts(result))


def run_workflow_with_retries(client, args, image_path):
    last_result = None
    attempts = max(1, args.retries + 1)
    for attempt in range(1, attempts + 1):
        result = run_workflow(client, args, image_path)
        last_result = result
        if workflow_has_predictions(result):
            return result, attempt, False
        if attempt < attempts:
            print(
                f"  Empty Roboflow predictions on attempt {attempt}/{attempts}; "
                f"retrying in {args.retry_delay:.1f}s..."
            )
            time.sleep(args.retry_delay)
    return last_result, attempts, True


CONFIDENCE_KEYS = ("confidence", "score", "probability", "prob")
LABEL_KEYS = ("class", "label", "class_name", "prediction_type", "top", "predicted_class")
CONFIDENCE_MAP_KEYS = ("predictions", "class_confidences", "confidences", "probabilities", "probability")


def is_numberish(value):
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def iter_prediction_dicts(value, parent_key=""):
    if isinstance(value, dict):
        if (
            parent_key.lower() in CONFIDENCE_MAP_KEYS
            and value
            and all(is_numberish(v) for v in value.values())
        ):
            for label, confidence in value.items():
                yield {"label": label, "confidence": confidence}
            return

        if any(k in value for k in CONFIDENCE_KEYS) and any(k in value for k in LABEL_KEYS):
            yield value
        for key, child in value.items():
            yield from iter_prediction_dicts(child, str(key))
    elif isinstance(value, list):
        for child in value:
            yield from iter_prediction_dicts(child, parent_key)


def prediction_label(prediction):
    for key in LABEL_KEYS:
        value = prediction.get(key)
        if value is not None:
            return str(value)
    return "unknown"


def prediction_confidence(prediction):
    for key in CONFIDENCE_KEYS:
        value = prediction.get(key)
        if value is None:
            continue
        try:
            if isinstance(value, str) and value.strip().endswith("%"):
                return float(value.strip().rstrip("%")) / 100.0
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def is_defect_label(label):
    normalized = label.strip().lower().replace("-", "_")
    return normalized not in NON_DEFECT_LABELS


def summarize_defects(results_by_image, threshold):
    matches = []
    for image_path, result in results_by_image:
        for prediction in iter_prediction_dicts(result):
            label = prediction_label(prediction)
            confidence = prediction_confidence(prediction)
            if confidence >= threshold and is_defect_label(label):
                matches.append({
                    "image": str(image_path),
                    "label": label,
                    "confidence": confidence,
                })

    matches.sort(key=lambda item: item["confidence"], reverse=True)
    return matches


def summarize_predictions(results_by_image):
    predictions = []
    for image_path, result in results_by_image:
        for prediction in iter_prediction_dicts(result):
            predictions.append({
                "image": str(image_path),
                "label": prediction_label(prediction),
                "confidence": prediction_confidence(prediction),
            })

    predictions.sort(key=lambda item: item["confidence"], reverse=True)
    return predictions


def write_defect_flag(path, defect_matches, threshold, all_predictions=None, run_info=None):
    flag_path = Path(path)
    flag_path.parent.mkdir(parents=True, exist_ok=True)

    run_info = run_info or {}
    top = defect_matches[0] if defect_matches else None
    top_prediction = all_predictions[0] if all_predictions else None
    prediction_count = len(all_predictions or [])
    status = "DEFECT_DETECTED" if top else ("NO_DEFECT_ABOVE_THRESHOLD" if prediction_count else "NO_PREDICTIONS")
    lines = [
        f"DEFECT_DETECTED={'1' if top else '0'}",
        f"DEFECT_STATUS={status}",
        f"THRESHOLD={threshold:.2f}",
        f"PREDICTION_COUNT={prediction_count}",
    ]
    for key in (
        "LOCAL_IMAGE_WIDTH",
        "LOCAL_IMAGE_HEIGHT",
        "LOCAL_IMAGE_BYTES",
        "RESULT_JSON",
        "ROBOFLOW_ATTEMPTS",
        "ROBOFLOW_EMPTY_PREDICTIONS",
    ):
        if key in run_info:
            lines.append(f"{key}={run_info[key]}")
    if top:
        lines.extend([
            f"DEFECT_LABEL={top['label']}",
            f"DEFECT_CONFIDENCE={top['confidence']:.4f}",
            f"DEFECT_IMAGE={top['image']}",
        ])
    else:
        lines.extend([
            "DEFECT_LABEL=None",
            "DEFECT_CONFIDENCE=0.0000",
            "DEFECT_IMAGE=None",
        ])
    if top_prediction:
        lines.extend([
            f"TOP_PREDICTION_LABEL={top_prediction['label']}",
            f"TOP_PREDICTION_CONFIDENCE={top_prediction['confidence']:.4f}",
            f"TOP_PREDICTION_IMAGE={top_prediction['image']}",
        ])
    else:
        lines.extend([
            "TOP_PREDICTION_LABEL=None",
            "TOP_PREDICTION_CONFIDENCE=0.0000",
            "TOP_PREDICTION_IMAGE=None",
        ])

    flag_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Defect flag written: {flag_path}")


def main():
    args = parse_args()

    if InferenceHTTPClient is None:
        print("Missing dependency: inference_sdk")
        print("Install it with: pip install inference-sdk")
        return 2

    try:
        images = collect_images(args.image_path, args.max_images)
    except FileNotFoundError as exc:
        print(exc)
        return 2

    if not images:
        print(f"No images found in {args.image_path}")
        return 2

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = InferenceHTTPClient(
        api_url=args.api_url,
        api_key=args.api_key,
    )

    print(f"Running workflow '{args.workflow_id}' in workspace '{args.workspace}'")
    print(f"Testing {len(images)} image(s)")

    error_count = 0
    results_by_image = []
    run_info = {}
    for index, image_path in enumerate(images, start=1):
        print(f"[{index}/{len(images)}] {image_path}")
        width, height = read_image_size(image_path)
        image_bytes = image_path.stat().st_size
        print(f"  Local image: {width}x{height}, {image_bytes} bytes")
        if index == 1:
            run_info["LOCAL_IMAGE_WIDTH"] = width if width is not None else "unknown"
            run_info["LOCAL_IMAGE_HEIGHT"] = height if height is not None else "unknown"
            run_info["LOCAL_IMAGE_BYTES"] = image_bytes
        try:
            result, attempts_used, empty_predictions = run_workflow_with_retries(client, args, image_path)
        except Exception as exc:
            error_count += 1
            print(f"  ERROR: {exc}")
            continue

        result_path = output_dir / f"{safe_output_name(image_path)}.json"
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if index == 1:
            run_info["RESULT_JSON"] = str(result_path)
            run_info["ROBOFLOW_ATTEMPTS"] = attempts_used
            run_info["ROBOFLOW_EMPTY_PREDICTIONS"] = int(empty_predictions)
        print(f"  Saved: {result_path}")
        results_by_image.append((image_path, result))

        if args.print_json:
            print(json.dumps(result, indent=2))
        else:
            print(result)

    all_predictions = summarize_predictions(results_by_image)
    defect_matches = summarize_defects(results_by_image, args.threshold)
    write_defect_flag(args.flag_output, defect_matches, args.threshold, all_predictions, run_info)
    if defect_matches:
        top = defect_matches[0]
        print(
            f"DEFECT DETECTED: {top['label']} "
            f"({top['confidence']:.2f}) in {top['image']}"
        )
    else:
        print("No defect detected above threshold.")

    print(f"Done. Success: {len(images) - error_count}, errors: {error_count}")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
