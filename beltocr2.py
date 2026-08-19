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
import cv2
import numpy as np
from difflib import SequenceMatcher
import re
import math
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

# ===== Your existing utilities (kept) =====
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

def run_hailo_ocr(image_path):
    """Run Hailo's PaddleOCR pipeline and return its recognized text lines."""
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"OCR input image not found: {image_path}")
    if not os.path.isfile(HAILO_APPS_SETUP):
        raise FileNotFoundError(f"Hailo Apps setup script not found: {HAILO_APPS_SETUP}")
    if not os.path.isfile(HAILO_OCR_EXECUTABLE):
        raise FileNotFoundError(f"hailo-ocr executable not found: {HAILO_OCR_EXECUTABLE}")

    # Arguments after argv[0] are passed positionally so paths never need shell
    # interpolation or manual quoting.
    shell_script = 'source "$1" >/dev/null && exec "$2" --arch "$3" --input "$4"'
    cmd = [
        "/bin/bash", "-lc", shell_script, "hailo-ocr-runner",
        HAILO_APPS_SETUP, HAILO_OCR_EXECUTABLE, HAILO_ARCH, image_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=HAILO_OCR_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Hailo OCR timed out after {HAILO_OCR_TIMEOUT:.0f}s for {image_path}"
        ) from exc

    combined_output = "\n".join((result.stdout, result.stderr))
    if result.returncode != 0:
        tail = "\n".join(combined_output.splitlines()[-20:])
        raise RuntimeError(
            f"Hailo OCR failed with exit code {result.returncode} for {image_path}:\n{tail}"
        )

    texts = re.findall(
        r"OCR Detection:\s*Text:\s*'(.*?)'\s+Confidence:",
        combined_output,
    )
    texts = [text.strip() for text in texts if text.strip()]
    if not texts:
        print(f"Warning: Hailo OCR found no text in {image_path}")
    text = " ".join(texts)
    return text, len(text)

def mask_and_rotate(original_image):
    gray = cv2.imread(original_image, cv2.IMREAD_GRAYSCALE)
    color = cv2.imread(original_image, cv2.IMREAD_COLOR)
    if gray is None or color is None:
        raise ValueError(f"Could not load: {original_image}")

    crop_h, crop_w = color.shape[:2]

    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = np.ones((3,3), np.uint8)
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = gray.size
    valid = [c for c in contours if cv2.contourArea(c) < 0.9*area]
    blob = max(valid if valid else contours, key=cv2.contourArea)

    mask = np.zeros_like(gray)
    cv2.drawContours(mask, [blob], -1, 255, thickness=-1)
    white_bg = np.full_like(color, 255)
    mask_color = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    masked = np.where(mask_color==255, color, white_bg)
    cv2.imwrite(FINAL_MASKED_IMAGE, masked)

    (cx, cy), (wb, hb), angle = cv2.minAreaRect(blob)
    

    if wb < hb:
        angle += 90
    M = cv2.getRotationMatrix2D((cx,cy), angle, 1.0)
    rotated = cv2.warpAffine(masked, M, (masked.shape[1], masked.shape[0]),
                             flags=cv2.INTER_CUBIC, borderValue=(255,255,255))
    cv2.imwrite(ROTATED_OUTPUT, rotated)

    rotated_180 = cv2.rotate(rotated, cv2.ROTATE_180)
    cv2.imwrite(ROTATED_OUTPUT_180, rotated_180)
    return angle, wb, hb

def run_ocr_and_select():
    text0, _ = run_hailo_ocr(ROTATED_OUTPUT)
    text180, _ = run_hailo_ocr(ROTATED_OUTPUT_180)
    _, r0 = best_part_match(text0)
    _, r180 = best_part_match(text180)
    if r180 > r0:
        return ROTATED_OUTPUT_180, text180
    return ROTATED_OUTPUT, text0

def is_duplicate_point(pt, seen, threshold=0.01):
    return any(abs(pt[0]-x)<threshold and abs(pt[1]-y)<threshold for x,y in seen)

# ===== Updated: append with Frame line (unchanged logic, now gets frame_no robustly) =====
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

    # OCR and best-match against KNOWN_PARTS (as before)
    best_part, score = best_part_match(raw_text)

    mid_str    = f"({chip_middle[0]:.6f}, {chip_middle[1]:.6f})"
    match_disp = best_part if best_part and best_part.upper() in parts_list else "None"
    y_offset_cm = calculate_distance(time_offset)

    # Append block (with Frame: N)
    with open(DETECTION_FILE, "a") as f:
        f.write(f"Frame: {frame_no}\n")
        f.write(f"Time_Offset: {time_offset:.2f}\n")
        f.write(f"Y_Offset_cm: {y_offset_cm:.4f}\n")
        f.write(f"{crop_index}. Raw OCR Text: {raw_text}\n")
        f.write(f"Angle of error: {angle:.2f}°\n")
        f.write(f"Chip Middle Point: {mid_str}\n")
        f.write(f"Chip Area: {wb * hb:.2f}\n")
        f.write(f"Closest known part: {best_part or 'None'}\n")
        f.write(f"Match ratio: {score:.2f}\n")
        f.write(f"Requested Part(s): {source_desc}\n")
        f.write(f"Match parts for mapping: {match_disp}\n")
        f.write("-----------------------------------\n\n")

    print(f" Detection file updated for Frame {frame_no}, crop {crop_index}.")

# ===== Main now processes by FRAME (or inferred frames) =====
def main():
    os.makedirs(SAVE_FOLDER, exist_ok=True)

    # Parse the detection file (supports FRAME= headers or legacy format)
    frames = parse_detection_frames(DETECTION_FILE)
    if not frames:
        print("Warning: No crops found in detection file; nothing to OCR.")
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
