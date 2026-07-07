#!/usr/bin/env python3
"""
Run the Roboflow hosted workflow for integrated circuit defect detection.

Examples:
    python defectdetect.py
    python defectdetect.py --image savephototest/chip.png
    python defectdetect.py --image orin_nano/pcb_ic_dataset --max-images 10

The default API key, workspace, and workflow ID match the Roboflow workflow
provided for this project. They can be overridden with command line options or
environment variables when needed.
"""

import argparse
import json
import os
import sys
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
DEFAULT_THRESHOLD = 0.70
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
        default=os.path.join(DEFAULT_SAVE_FOLDER, "chip.png"),
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


def run_workflow(client, args, image_path):
    return client.run_workflow(
        workspace_name=args.workspace,
        workflow_id=args.workflow_id,
        images={
            args.image_input_name: str(image_path),
        },
        use_cache=not args.no_cache,
    )


def iter_prediction_dicts(value):
    if isinstance(value, dict):
        if "confidence" in value and any(k in value for k in ("class", "label", "class_name", "prediction_type")):
            yield value
        for child in value.values():
            yield from iter_prediction_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_prediction_dicts(child)


def prediction_label(prediction):
    for key in ("class", "label", "class_name", "prediction_type"):
        value = prediction.get(key)
        if value is not None:
            return str(value)
    return "unknown"


def prediction_confidence(prediction):
    try:
        return float(prediction.get("confidence", 0.0))
    except (TypeError, ValueError):
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


def write_defect_flag(path, defect_matches, threshold):
    flag_path = Path(path)
    flag_path.parent.mkdir(parents=True, exist_ok=True)

    top = defect_matches[0] if defect_matches else None
    lines = [
        f"DEFECT_DETECTED={'1' if top else '0'}",
        f"THRESHOLD={threshold:.2f}",
    ]
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
    for index, image_path in enumerate(images, start=1):
        print(f"[{index}/{len(images)}] {image_path}")
        try:
            result = run_workflow(client, args, image_path)
        except Exception as exc:
            error_count += 1
            print(f"  ERROR: {exc}")
            continue

        result_path = output_dir / f"{safe_output_name(image_path)}.json"
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"  Saved: {result_path}")
        results_by_image.append((image_path, result))

        if args.print_json:
            print(json.dumps(result, indent=2))
        else:
            print(result)

    defect_matches = summarize_defects(results_by_image, args.threshold)
    write_defect_flag(args.flag_output, defect_matches, args.threshold)
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
