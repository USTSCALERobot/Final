#!/usr/bin/env python3
"""Test chip images with Hailo OCR on Linux or PaddleOCR locally."""

import argparse
import os
import sys

import beltocr2


def configure_local_outputs():
    """Keep beltocr2's shared intermediate images inside this repository."""
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "savephototest")
    beltocr2.SAVE_FOLDER = output_dir
    beltocr2.FINAL_MASKED_IMAGE = os.path.join(output_dir, "masked_blob.png")
    beltocr2.ROTATED_OUTPUT = os.path.join(output_dir, "rotated_blob.png")
    beltocr2.ROTATED_OUTPUT_180 = os.path.join(output_dir, "rotated_blob_180.png")
    beltocr2.FINAL_OCR_OUTPUT = os.path.join(output_dir, "final_oriented_chip.png")
    beltocr2.HAILO_OCR_INPUT = os.path.join(output_dir, "hailo_ocr_input.png")


def create_local_ocr():
    # Paddle's oneDNN executor can fail on some Windows/Paddle combinations
    # with ConvertPirAttribute2RuntimeAttribute. The ordinary CPU kernels are
    # slower but considerably more portable for this small test utility.
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")
    os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")

    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError(
            "Local PaddleOCR is not installed. Run: "
            "python -m pip install paddlepaddle paddleocr"
        ) from exc

    # PaddleOCR 3.x parameters, followed by compatibility with PaddleOCR 2.x.
    try:
        return PaddleOCR(
            lang="en",
            device="cpu",
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except TypeError:
        return PaddleOCR(lang="en", use_angle_cls=False, use_gpu=False)


def extract_paddle_text(result):
    """Extract recognized strings from both PaddleOCR 2.x and 3.x results."""
    texts = []

    def visit(value):
        if value is None:
            return
        if hasattr(value, "json"):
            json_value = value.json
            visit(json_value() if callable(json_value) else json_value)
            return
        if isinstance(value, dict):
            for key in ("rec_texts", "texts"):
                if key in value:
                    found = value[key]
                    if isinstance(found, str):
                        texts.append(found)
                    else:
                        texts.extend(str(item) for item in found if str(item).strip())
                    return
            if "res" in value:
                visit(value["res"])
            return
        if isinstance(value, (list, tuple)):
            # PaddleOCR 2.x recognition item: [box, (text, confidence)].
            if (
                len(value) == 2
                and isinstance(value[1], (list, tuple))
                and len(value[1]) >= 2
                and isinstance(value[1][0], str)
            ):
                texts.append(value[1][0])
                return
            for item in value:
                visit(item)

    visit(result)
    return " ".join(dict.fromkeys(text.strip() for text in texts if text.strip()))


def run_local_ocr(ocr, image_path):
    prepared_path = beltocr2.prepare_hailo_ocr_image(image_path)
    if hasattr(ocr, "predict"):
        result = ocr.predict(input=prepared_path)
    else:
        result = ocr.ocr(prepared_path, cls=False)
    return extract_paddle_text(result)


def run_local_ocr_and_select(ocr):
    text0 = run_local_ocr(ocr, beltocr2.ROTATED_OUTPUT)
    _, score0 = beltocr2.best_part_match(text0)

    if text0 and score0 >= beltocr2.OCR_ORIENTATION_SKIP_SCORE:
        return beltocr2.ROTATED_OUTPUT, text0

    text180 = run_local_ocr(ocr, beltocr2.ROTATED_OUTPUT_180)
    _, score180 = beltocr2.best_part_match(text180)
    if score180 > score0:
        return beltocr2.ROTATED_OUTPUT_180, text180
    return beltocr2.ROTATED_OUTPUT, text0


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run beltocr2's rotation, preprocessing, OCR, and known-part "
            "matching on one or more input images."
        )
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "hailo", "paddle"),
        default="auto",
        help="OCR backend (default: Hailo on Linux when available, otherwise PaddleOCR).",
    )
    parser.add_argument(
        "images",
        nargs="+",
        help="Path(s) to chip crop images to test.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=beltocr2.MIN_PART_MATCH_SCORE,
        help=(
            "Minimum score considered a reliable match "
            f"(default: {beltocr2.MIN_PART_MATCH_SCORE:.2f})."
        ),
    )
    return parser.parse_args()


def test_image(image_path, min_score, backend, local_ocr=None):
    print(f"\n{'=' * 72}")
    print(f"Input image: {image_path}")

    angle, width, height = beltocr2.mask_and_rotate(image_path)
    if backend == "hailo":
        selected_image, raw_text = beltocr2.run_ocr_and_select()
    else:
        selected_image, raw_text = run_local_ocr_and_select(local_ocr)
    closest_part, score = beltocr2.best_part_match(raw_text)

    print(f"Selected orientation: {os.path.basename(selected_image)}")
    print(f"Detected chip angle: {angle:.2f} degrees")
    print(f"Detected chip size: {width:.1f} x {height:.1f} pixels")
    print(f"Raw OCR text: {raw_text or '<no text detected>'}")

    if closest_part is None:
        print("Closest known part: <none>")
        print("Match score: 0.00")
    else:
        status = "RELIABLE" if score >= min_score else "LOW CONFIDENCE"
        print(f"Closest known part: {closest_part}")
        print(f"Match score: {score:.2f} ({status}, threshold={min_score:.2f})")


def main():
    args = parse_args()
    configure_local_outputs()
    os.makedirs(beltocr2.SAVE_FOLDER, exist_ok=True)

    backend = args.backend
    if backend == "auto":
        backend = (
            "hailo"
            if os.name != "nt" and os.path.isfile(beltocr2.HAILO_OCR_EXECUTABLE)
            else "paddle"
        )

    local_ocr = create_local_ocr() if backend == "paddle" else None
    print(f"OCR backend: {backend}")

    had_error = False
    for image_path in args.images:
        if not os.path.isfile(image_path):
            print(f"\nError: input image not found: {image_path}", file=sys.stderr)
            had_error = True
            continue

        try:
            test_image(image_path, args.min_score, backend, local_ocr)
        except Exception as exc:
            print(f"OCR failed for {image_path}: {exc}", file=sys.stderr)
            had_error = True

    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
