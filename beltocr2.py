########################################################################
# Document: beltocr2.py
# Project: SCALE Automated Vision System
# Institution: University of St. Thomas
# Contributors: Dan Walczak, Bennett Nelson, Erik Perez, 
#               Louis Stevenson, Ryan Bercich, Theodore Thorpe
# Description: 
#   TODO: add description...
########################################################################

#!/usr/bin/env python3  #needs to be on line 1 for shebang to work 
import os
import subprocess
import selectors
import cv2
import numpy as np
from difflib import SequenceMatcher
import re
import math
import time
from typing import Dict, List, Tuple

# --- Paths & Files ---
SAVE_FOLDER        = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE     = os.path.join(SAVE_FOLDER, "latest_detection.txt")
CIRCUIT_FILE       = os.path.join(SAVE_FOLDER, "Circuits.txt")
PART_FILE          = os.path.join(SAVE_FOLDER, "Parts.txt")  # (unused here; left for future)
FINAL_MASKED_IMAGE = os.path.join(SAVE_FOLDER, "masked_blob.png")
ROTATED_OUTPUT     = os.path.join(SAVE_FOLDER, "rotated_blob.png")
ROTATED_OUTPUT_180 = os.path.join(SAVE_FOLDER, "rotated_blob_180.png")
FINAL_OCR_OUTPUT   = os.path.join(SAVE_FOLDER, "final_oriented_chip.png")
REQUEST_FILE       = os.path.join(SAVE_FOLDER, "chip_request_input.txt")

# Hailo's official PaddleOCR application performs both text detection and
# recognition on the Hailo-8L. The setup script supplies its model/resource
# environment. Both paths may be overridden for a different installation.
HAILO_APPS_SETUP = os.environ.get(
    "HAILO_APPS_SETUP", "/home/scalepi/hailo-apps/setup_env.sh"
)
HAILO_OCR_EXECUTABLE = os.environ.get(
    "HAILO_OCR_EXECUTABLE",
    "/home/scalepi/hailo-apps/venv_hailo_apps/bin/hailo-ocr",
)
HAILO_ARCH = os.environ.get("HAILO_ARCH", "hailo8l")
HAILO_OCR_TIMEOUT = float(os.environ.get("HAILO_OCR_TIMEOUT", "120"))
HAILO_OCR_INPUT = os.path.join(SAVE_FOLDER, "hailo_ocr_input.png")
HAILO_OCR_MAX_FRAMES = int(os.environ.get("HAILO_OCR_MAX_FRAMES", "3"))
OCR_ORIENTATION_SKIP_SCORE = float(
    os.environ.get("OCR_ORIENTATION_SKIP_SCORE", "0.45")
)
MIN_PART_MATCH_SCORE = float(os.environ.get("MIN_PART_MATCH_SCORE", "0.45"))

CYAN = "\033[96m"
RESET = "\033[0m"


def ocr_print(message):
    """Print a consistently tagged OCR console message."""
    print(f"{CYAN}[OCR]{RESET} {message}")

# --- Known Parts Fallback ---
KNOWN_PARTS = [
    "P8436 DM74S240N", "SN74LS5IN M18034",
    "LM745", "SN74185AN", "SN7414N",
    "M73AF LF 356BN", "DM7414N"
]

# ===== Helpers for FRAME format (now supports legacy/no-FRAME too) =====
FRAME_RE  = re.compile(r'^\s*FRAME\s*=\s*(\d+)\s*$', re.IGNORECASE)
CROP_RE   = re.compile(r'^\s*Cropped Photo Location:\s*(.+?),\s*(.+?)\s*$', re.IGNORECASE)
COORDS_RE = re.compile(
    r'^\s*Coordinates of the Detection Box:\s*\(([-0-9.]+),\s*([-0-9.]+)\)\s*->\s*\(([-0-9.]+),\s*([-0-9.]+)\)\s*$',
    re.IGNORECASE
)
TIME_OFFSET_RE = re.compile(r'^\s*Time_Offset:\s*([0-9.]+)\s*$', re.IGNORECASE)

# Global dict to store time offsets per frame
frame_time_offsets = {}

def _infer_frame_from_paths(full_path: str, crop_path: str) -> int:
    bn_full = os.path.basename(full_path or "")
    bn_crop = os.path.basename(crop_path or "")
    # Heuristics: treat chip2.* or chip_cropped_2_* as Frame 2
    if "chip2" in bn_full.lower() or "_2_" in bn_crop.lower():
        return 2
    return 1

def parse_detection_frames(detection_file: str) -> Dict[int, List[Tuple[str, str, Tuple[float,float,float,float]]]]:
    """
    Parse latest_detection.txt into:
      { frame_no: [ (full_img_path, crop_img_path, (x1,y1,x2,y2)), ... ] }

    Works with:
    - New format with explicit 'FRAME=1/2' headers, OR
    - Legacy format without FRAME headers; in that case, infer frame by filenames.
    """
    frames: Dict[int, List[Tuple[str, str, Tuple[float,float,float,float]]]] = {}
    if not os.path.exists(detection_file):
        return frames

    cur_frame: int = None
    saw_frame_header = False
    pending_full: Tuple[str, str] = None
    pending_frame: int = None

    with open(detection_file, "r") as f:
        for line in f:
            m = FRAME_RE.match(line)
            if m:
                cur_frame = int(m.group(1))
                saw_frame_header = True
                frames.setdefault(cur_frame, [])
                pending_full = None
                pending_frame = None
                continue

            m = CROP_RE.match(line)
            if m:
                full_path, crop_path = m.group(1).strip(), m.group(2).strip()
                pending_full = (full_path, crop_path)
                # If no explicit frame header, infer from filenames
                pending_frame = cur_frame if cur_frame is not None else _infer_frame_from_paths(full_path, crop_path)
                frames.setdefault(pending_frame, [])
                continue

            m = TIME_OFFSET_RE.match(line)
            if m and cur_frame is not None:
                frame_time_offsets[cur_frame] = float(m.group(1))
                continue

            m = COORDS_RE.match(line)
            if m and pending_full is not None and pending_frame is not None:
                x1, y1, x2, y2 = map(float, (m.group(1), m.group(2), m.group(3), m.group(4)))
                frames[pending_frame].append((pending_full[0], pending_full[1], (x1, y1, x2, y2)))
                pending_full = None
                pending_frame = None

    # If no frames detected at all, return empty (caller will handle)
    return frames

# Motor Model 
def calculate_distance(t: float) -> float:
    if t <= 0:
        return 0.0
    elif t <= 2.61:
        return 0.0274 * (t**2) + 2.0731 * t + 0.2780
    else:
        dist_at_2_61 = 0.0274 * (2.61**2) + 2.0731 * 2.61 + 0.2780
        return dist_at_2_61 + 2.2163 * (t - 2.61)

def calculate_required_run_time(max_time_offset: float) -> float:
    offset_distance = 4.0
    base_distance = 18.75 + offset_distance
    dist_at_2_61 = 0.0274 * (2.61**2) + 2.0731 * 2.61 + 0.2780
    
    distance_already_traveled = calculate_distance(max_time_offset)
    remaining_distance = max(0.0, base_distance - distance_already_traveled)
    
    if remaining_distance <= 0:
        return 0.0
    elif remaining_distance <= dist_at_2_61:
        a = 0.0274
        b = 2.0731
        c = 0.2780 - remaining_distance
        discriminant = b**2 - 4*a*c
        if discriminant < 0:
            return 0.0
        else:
            t = (-b + math.sqrt(discriminant)) / (2*a)
            return max(0.0, t)
    else:
        return 2.61 + (remaining_distance - dist_at_2_61) / 2.2163

def load_circuit_parts(circuit_name):
    circuit_name = circuit_name.upper()
    try:
        with open(CIRCUIT_FILE, 'r') as f:
            text = f.read()
    except FileNotFoundError:
        return []  # minimal safety
    m = re.search(rf"{circuit_name}\s*=\s*\[([^\]]+)\]", text, re.IGNORECASE)
    parts = []
    if m:
        block = m.group(1)
        entries = re.findall(r'\d+\.\s*([^()]+)\(',block)
        for part_name in entries:
            parts.append(part_name.strip().upper())
    return parts

def best_part_match(ocr_text, known_parts=KNOWN_PARTS):
    best_score, best_part = 0.0, None
    for part in known_parts:
        score = SequenceMatcher(None, ocr_text.upper(), part.upper()).ratio()
        if score > best_score:
            best_score, best_part = score, part
    return best_part, best_score

def prepare_hailo_ocr_image(image_path):
    """Create a large, dark-text-on-light image for PaddleOCR detection."""
    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"Could not load OCR input image: {image_path}")

    prepared = cv2.bitwise_not(gray)
    prepared = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(prepared)

    target_height = 320
    scale = max(1.0, target_height / max(1, prepared.shape[0]))
    prepared = cv2.resize(
        prepared,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_LANCZOS4,
    )
    prepared = cv2.copyMakeBorder(
        prepared, 64, 64, 64, 64, cv2.BORDER_CONSTANT, value=255
    )
    if not cv2.imwrite(HAILO_OCR_INPUT, prepared):
        raise RuntimeError(f"Could not write prepared OCR image: {HAILO_OCR_INPUT}")
    return HAILO_OCR_INPUT


def run_hailo_ocr(image_path):
    """Run Hailo's PaddleOCR pipeline and return its recognized text lines."""
    total_started = time.perf_counter()
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"OCR input image not found: {image_path}")
    if not os.path.isfile(HAILO_APPS_SETUP):
        raise FileNotFoundError(f"Hailo Apps setup script not found: {HAILO_APPS_SETUP}")
    if not os.path.isfile(HAILO_OCR_EXECUTABLE):
        raise FileNotFoundError(f"hailo-ocr executable not found: {HAILO_OCR_EXECUTABLE}")

    preprocess_started = time.perf_counter()
    prepared_image_path = prepare_hailo_ocr_image(image_path)
    preprocess_seconds = time.perf_counter() - preprocess_started

    shell_script = (
        'cd "$(dirname "$1")" && '
        'source "$1" >/dev/null && '
        'export PYTHONUNBUFFERED=1 && '
        'exec "$2" --arch "$3" --input "$4"'
    )
    cmd = [
        "/bin/bash", "-lc", shell_script, "hailo-ocr-runner",
        HAILO_APPS_SETUP, HAILO_OCR_EXECUTABLE, HAILO_ARCH, prepared_image_path,
    ]
    inference_started = time.perf_counter()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines = []
    frame_count = 0
    saw_ocr = False
    stopped_early = False
    deadline = time.monotonic() + HAILO_OCR_TIMEOUT
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(cmd, HAILO_OCR_TIMEOUT)
            if not selector.select(timeout=0.25):
                continue
            line = process.stdout.readline()
            if not line:
                continue
            output_lines.append(line)
            if "OCR Detection:" in line:
                saw_ocr = True
            if "Frame count:" in line:
                frame_count += 1
                # A new frame means all callback lines from the previous frame
                # have arrived. Static-image OCR cannot improve after repeats.
                if (saw_ocr and frame_count >= 2) or frame_count >= HAILO_OCR_MAX_FRAMES:
                    stopped_early = True
                    process.terminate()
                    break
        try:
            remainder, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            remainder, _ = process.communicate()
        if remainder:
            output_lines.append(remainder)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise RuntimeError(
            f"Hailo OCR timed out after {HAILO_OCR_TIMEOUT:.0f}s for {image_path}"
        ) from exc
    finally:
        selector.close()

    inference_seconds = time.perf_counter() - inference_started
    combined_output = "".join(output_lines)
    if process.returncode != 0 and not stopped_early:
        tail = "\n".join(combined_output.splitlines()[-20:])
        raise RuntimeError(
            f"Hailo OCR failed with exit code {process.returncode} for {image_path}:\n{tail}"
        )

    texts = re.findall(
        r"OCR Detection:\s*Text:\s*'(.*?)'\s+Confidence:",
        combined_output,
    )
    texts = [text.strip() for text in texts if text.strip()]
    texts = list(dict.fromkeys(texts))  # imagefreeze may report the same line per frame
    if not texts:
        ocr_print(f"Warning: Hailo OCR found no text in {image_path}")
    text = " ".join(texts)
    total_seconds = time.perf_counter() - total_started
    ocr_print(
        f"Timing {os.path.basename(image_path)}: "
        f"preprocess={preprocess_seconds:.3f}s, "
        f"hailo={inference_seconds:.3f}s, total={total_seconds:.3f}s"
    )
    return text, len(text)

def mask_and_rotate(original_image):
    gray = cv2.imread(original_image, cv2.IMREAD_GRAYSCALE)
    color = cv2.imread(original_image, cv2.IMREAD_COLOR)
    if gray is None or color is None:
        raise ValueError(f"Could not load: {original_image}")

    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Closing is less likely than opening to erase narrow chip edges.  Try both
    # polarities because the belt/background can be either lighter or darker
    # than the package depending on the capture setup.
    kernel = np.ones((3, 3), np.uint8)
    candidates = []
    image_area = gray.size
    image_center = np.array([gray.shape[1] / 2.0, gray.shape[0] / 2.0])

    for binary in (thresh, cv2.bitwise_not(thresh)):
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            contour_area = cv2.contourArea(contour)
            if not 0.05 * image_area < contour_area < 0.95 * image_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            center = np.array([x + w / 2.0, y + h / 2.0])
            center_distance = np.linalg.norm(center - image_center)
            rect = cv2.minAreaRect(contour)
            rect_area = max(1.0, rect[1][0] * rect[1][1])
            rectangularity = min(1.0, contour_area / rect_area)
            diagonal = max(1.0, np.linalg.norm(image_center))
            centrality = max(0.1, 1.0 - center_distance / diagonal)
            # A chip is normally the largest central, solid rectangular object.
            # Rectangularity prevents a large irregular background patch from
            # winning merely because it has more pixels.
            score = contour_area * rectangularity * centrality
            candidates.append((score, contour))

    if candidates:
        blob = max(candidates, key=lambda item: item[0])[1]
    else:
        # The object detector already supplied a chip crop. If segmentation is
        # uncertain, retaining that entire crop is safer than stopping OCR or
        # selecting a character-shaped contour.
        inset = max(1, int(round(min(gray.shape[:2]) * 0.01)))
        blob = np.array([[
            [inset, inset],
            [gray.shape[1] - inset - 1, inset],
            [gray.shape[1] - inset - 1, gray.shape[0] - inset - 1],
            [inset, gray.shape[0] - inset - 1],
        ]], dtype=np.int32)
        ocr_print(
            f"Warning: chip contour was uncertain; using full crop for {original_image}"
        )

    mask = np.zeros_like(gray)
    cv2.drawContours(mask, [blob], -1, 255, thickness=-1)
    white_bg = np.full_like(color, 255)
    mask_color = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    masked = np.where(mask_color==255, color, white_bg)
    cv2.imwrite(FINAL_MASKED_IMAGE, masked)

    (cx, cy), (wb, hb), angle = cv2.minAreaRect(blob)
    if wb < hb:
        angle += 90

    # Preserve the detector's complete crop and use the contour only for its
    # angle. Perspective-cropping to an imperfect contour can remove readable
    # text. Expand the rotation canvas so corners are never clipped.
    image_h, image_w = color.shape[:2]
    rotation_center = (image_w / 2.0, image_h / 2.0)
    rotation = cv2.getRotationMatrix2D(rotation_center, angle, 1.0)
    abs_cos = abs(rotation[0, 0])
    abs_sin = abs(rotation[0, 1])
    rotated_w = int(round(image_h * abs_sin + image_w * abs_cos))
    rotated_h = int(round(image_h * abs_cos + image_w * abs_sin))
    rotation[0, 2] += rotated_w / 2.0 - rotation_center[0]
    rotation[1, 2] += rotated_h / 2.0 - rotation_center[1]
    rotated = cv2.warpAffine(
        color,
        rotation,
        (rotated_w, rotated_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    if rotated.shape[0] > rotated.shape[1]:
        rotated = cv2.rotate(rotated, cv2.ROTATE_90_CLOCKWISE)

    # Enhancement, inversion, resizing, and final padding happen once in
    # prepare_hailo_ocr_image(). Keep this image close to the camera data.
    border = max(8, int(round(min(rotated.shape[:2]) * 0.04)))
    rotated = cv2.copyMakeBorder(
        rotated, border, border, border, border,
        cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )
    cv2.imwrite(ROTATED_OUTPUT, rotated)

    rotated_180 = cv2.rotate(rotated, cv2.ROTATE_180)
    cv2.imwrite(ROTATED_OUTPUT_180, rotated_180)
    return angle, wb, hb

def run_ocr_and_select():
    orientation_started = time.perf_counter()
    text0, _ = run_hailo_ocr(ROTATED_OUTPUT)
    _, r0 = best_part_match(text0)
    if text0 and r0 >= OCR_ORIENTATION_SKIP_SCORE:
        ocr_print(
            f"Skipped 180-degree pass; first-pass match={r0:.2f}"
        )
        return ROTATED_OUTPUT, text0

    text180, _ = run_hailo_ocr(ROTATED_OUTPUT_180)
    _, r180 = best_part_match(text180)
    selected = ((ROTATED_OUTPUT_180, text180) if r180 > r0
                else (ROTATED_OUTPUT, text0))
    ocr_print(
        f"Both orientations completed in "
        f"{time.perf_counter() - orientation_started:.3f}s"
    )
    return selected

def is_duplicate_point(pt, seen, threshold=0.01):
    return any(abs(pt[0]-x)<threshold and abs(pt[1]-y)<threshold for x,y in seen)

def update_detection_file(raw_text, angle, crop_index, chip_middle, frame_no, time_offset=0.0, wb=0.0, hb=0.0):
    # Read the user’s request (circuit or manual parts)
    circuit_name = None
    manual_parts = []
    if os.path.exists(REQUEST_FILE):
        with open(REQUEST_FILE, 'r') as rf:
            for line in rf:
                line = line.strip()
                if line.upper().startswith("REQUESTED CIRCUIT:"):
                    circuit_name = line.split(":", 1)[1].strip().upper()
                elif line.upper().startswith("REQUESTED PART:"):
                    manual_parts = [
                        p.strip().upper()
                        for p in line.split(":", 1)[1].split(",")
                        if p.strip()
                    ]

    # Choose parts list
    if circuit_name:
        parts_list = load_circuit_parts(circuit_name)
        source_desc = circuit_name
    else:
        parts_list = manual_parts
        source_desc = ", ".join(manual_parts) if manual_parts else "None"

    # OCR and best-match against KNOWN_PARTS
    best_part, score = best_part_match(raw_text)

    mid_str    = f"({chip_middle[0]:.6f}, {chip_middle[1]:.6f})"
    reliable_part = best_part if score >= MIN_PART_MATCH_SCORE else None
    match_disp = (
        reliable_part
        if reliable_part and reliable_part.upper() in parts_list
        else "None"
    )
    y_offset_cm = calculate_distance(time_offset)

    if raw_text and reliable_part:
        ocr_print(f"Detected chip: {reliable_part} (match ratio={score:.2f})")
    elif raw_text:
        ocr_print(
            f"OCR text was not a reliable chip match (best ratio={score:.2f})"
        )

    # Append block (with Frame: N)
    with open(DETECTION_FILE, "a") as f:
        f.write(f"Frame: {frame_no}\n")
        f.write(f"Time_Offset: {time_offset:.2f}\n")
        f.write(f"Y_Offset_cm: {y_offset_cm:.4f}\n")
        f.write(f"{crop_index}. Raw OCR Text: {raw_text}\n")
        f.write(f"Angle of error: {angle:.2f}°\n")
        f.write(f"Chip Middle Point: {mid_str}\n")
        f.write(f"Chip Area: {wb * hb:.2f}\n")
        f.write(f"Closest known part: {reliable_part or 'None'}\n")
        f.write(f"Match ratio: {score:.2f}\n")
        f.write(f"Requested Part(s): {source_desc}\n")
        f.write(f"Match parts for mapping: {match_disp}\n")
        f.write("-----------------------------------\n\n")

    ocr_print(f"Detection file updated for Frame {frame_no}, crop {crop_index}.")


def main():
    os.makedirs(SAVE_FOLDER, exist_ok=True)

    # Parse the detection file (supports FRAME= headers or legacy format)
    frames = parse_detection_frames(DETECTION_FILE)
    if not frames:
        ocr_print("Warning: No crops found in detection file; nothing to OCR.")
        return

    # CLEAR THE FILE! We only want to save the final OCR results, 
    # otherwise the raw vision text will corrupt the arm script's regex.
    open(DETECTION_FILE, "w").close()

    # Write the global maximum time offset at the top of the file so the motor script
    # knows how long the belt ran during vision, even if the final frame timed out with no crops.
    global_max_offset = max(frame_time_offsets.values()) if frame_time_offsets else 0.0
    required_run_time = calculate_required_run_time(global_max_offset)
    with open(DETECTION_FILE, "a") as f:
        f.write(f"Global_Max_Time_Offset: {global_max_offset:.2f}\n")
        f.write(f"Required_Belt_Run_Time: {required_run_time:.4f}\n\n")

    for frame_no in sorted(frames.keys()):     # process FRAME=1, then FRAME=2
        seen: List[Tuple[float, float]] = []   # reset duplicate tracker for each frame
        crops = frames[frame_no]               # list of (full, crop, (x1,y1,x2,y2))
        for idx, (full_path, crop_path, (x1,y1,x2,y2)) in enumerate(crops, start=1):
            mid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

            if is_duplicate_point(mid, seen, threshold=0.01):
                continue
            seen.append(mid)
            # added width and height to the mask and rotate function
            angle, wb, hb = mask_and_rotate(crop_path)

            best_img, raw_text = run_ocr_and_select()
            cv2.imwrite(FINAL_OCR_OUTPUT, cv2.imread(best_img))

            t_offset = frame_time_offsets.get(frame_no, 0.0)
            update_detection_file(raw_text, angle, idx, mid, frame_no, t_offset, wb, hb)

if __name__ == "__main__":
    main()
