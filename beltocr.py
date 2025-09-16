#!/usr/bin/env python3
import os
import cv2
import numpy as np
import easyocr
from difflib import SequenceMatcher
import re

SAVE_FOLDER        = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE     = os.path.join(SAVE_FOLDER, "latest_detection.txt")
CIRCUIT_FILE       = os.path.join(SAVE_FOLDER, "Circuits.txt")
PART_FILE          = os.path.join(SAVE_FOLDER, "Parts.txt") #NOTE File still needs to be fully updated/created
FINAL_MASKED_IMAGE = os.path.join(SAVE_FOLDER, "masked_blob.png")
ROTATED_OUTPUT     = os.path.join(SAVE_FOLDER, "rotated_blob.png")
ROTATED_OUTPUT_180 = os.path.join(SAVE_FOLDER, "rotated_blob_180.png")
FINAL_OCR_OUTPUT   = os.path.join(SAVE_FOLDER, "final_oriented_chip.png")
REQUEST_FILE       = os.path.join(SAVE_FOLDER, "chip_request_input.txt")

KNOWN_PARTS = [
    "P8436 DM74S240N", "SN74LS5IN M18034",
    "LM745", "SN74185AN", "SN7414N",
    "M73AF LF 356BN", "DM7414N"
]

def load_circuit_parts(circuit_name):
    circuit_name = circuit_name.upper()
    with open(CIRCUIT_FILE, 'r') as f:
        text = f.read()
    m = re.search(rf"{circuit_name}\s*=\s*\[([^\]]+)\]", text, re.IGNORECASE)
    parts = []
    if m:
        block = m.group(1)
        entries = re.findall(r'"([^"]+)"', block)
        for entry in entries:
            pm = re.search(r'\d+\.\s*(.+?)\s*\(', entry)
            if pm:
                parts.append(pm.group(1).strip().upper())
    return parts

def best_part_match(ocr_text, known_parts=KNOWN_PARTS):
    best_score, best_part = 0.0, None
    for part in known_parts:
        score = SequenceMatcher(None, ocr_text.upper(), part.upper()).ratio()
        if score > best_score:
            best_score, best_part = score, part
    return best_part, best_score

def run_ocr_once(reader, image_path):
    results = reader.readtext(image_path)
    text = " ".join(res[1] for res in results)
    return text, len(text)

def mask_and_rotate(original_image):
    gray = cv2.imread(original_image, cv2.IMREAD_GRAYSCALE)
    color = cv2.imread(original_image, cv2.IMREAD_COLOR)
    if gray is None or color is None:
        raise ValueError(f"Could not load: {original_image}")
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
    if wb < hb: angle += 90
    M = cv2.getRotationMatrix2D((cx,cy), angle, 1.0)
    rotated = cv2.warpAffine(masked, M, (masked.shape[1], masked.shape[0]),
                             flags=cv2.INTER_CUBIC, borderValue=(255,255,255))
    cv2.imwrite(ROTATED_OUTPUT, rotated)
    rotated_180 = cv2.rotate(rotated, cv2.ROTATE_180)
    cv2.imwrite(ROTATED_OUTPUT_180, rotated_180)
    return angle

def run_ocr_and_select():
    reader = easyocr.Reader(['en'], gpu=False)
    text0, _ = run_ocr_once(reader, ROTATED_OUTPUT)
    text180, _ = run_ocr_once(reader, ROTATED_OUTPUT_180)
    _, r0 = best_part_match(text0)
    _, r180 = best_part_match(text180)
    return ROTATED_OUTPUT_180 if r180 > r0 else ROTATED_OUTPUT

def extract_middle_point_from_detection_file(index):
    with open(DETECTION_FILE, 'r') as f:
        lines = f.readlines()
    count = 0
    for i, line in enumerate(lines):
        if line.startswith("Cropped Photo Location:"):
            count += 1
            if count == index and i+1 < len(lines):
                m = re.search(r"\(([\d.]+),\s*([\d.]+)\)", lines[i+1])
                if m:
                    return float(m.group(1)), float(m.group(2))
    return 0.0, 0.0

def is_duplicate_point(pt, seen, threshold=0.01):
    return any(abs(pt[0]-x)<threshold and abs(pt[1]-y)<threshold for x,y in seen)

# def update_detection_file(angle, index, chip_middle):
#     #NOTE: lines 105-112 were added to read from chip_request_input.txt instead of being hardcoded
#     with open(filerequest, 'r') as file:
#         line = file.read()
#         requested_parts = []
#         #print(f"\n\n{line}\n\n")
#         if line.startswith("Requested Part:"):
#             requested_parts = [p.strip() for p in line.split(":", 1)[1].split(",") if p.strip()]
#             #print(f"\n\n{requested_parts}\n\n")
#     circuit_name = "CIRCUIT1"
#     circuit_parts = load_circuit_parts(circuit_name)

#     reader = easyocr.Reader(['en'], gpu=False)
#     raw_text, _ = run_ocr_once(reader, FINAL_OCR_OUTPUT)
#     best_part, score = best_part_match(raw_text)

#     mid_str = f"({chip_middle[0]:.6f}, {chip_middle[1]:.6f})"
#     part_disp = best_part or "None"
#     match_disp = part_disp if part_disp.upper() in circuit_parts else "None"

#     with open(DETECTION_FILE, "a") as f:
#         f.write(f"1. Raw OCR Text: {raw_text}\n")
#         f.write(f"2. Angle of error: {angle:.2f}°\n")
#         f.write(f"3. Chip Middle Point: {mid_str}\n")
#         f.write(f"4. Closest known part: {part_disp}\n")
#         f.write(f"5. Match ratio: {score:.2f}\n")
#         f.write(f"6. Requested Part(s): {circuit_name}\n")
#         f.write(f"7. Match parts for mapping: {match_disp}\n")
#         f.write("-----------------------------------\n\n")
#     print("✅ Detection file updated.")

def update_detection_file(angle, index, chip_middle):
    # ————————————— Read the user’s request from the absolute path —————————————
    circuit_name = None
    manual_parts = []
    with open(REQUEST_FILE, 'r') as rf:
        for line in rf:
            line = line.strip()
            if line.upper().startswith("REQUESTED CIRCUIT:"):
                circuit_name = line.split(":", 1)[1].strip().upper()
            elif line.upper().startswith("REQUESTED PART:"):
                # split comma-sep, filter out empty, uppercase for matching
                manual_parts = [
                    p.strip().upper()
                    for p in line.split(":", 1)[1].split(",")
                    if p.strip()
                ]

    # ————————————— Decide which list to use —————————————
    if circuit_name:
        parts_list = load_circuit_parts(circuit_name)
        source_desc = circuit_name
    else:
        parts_list = manual_parts
        source_desc = ", ".join(manual_parts) if manual_parts else "None"

    # ————————————— OCR & best-match as before —————————————
    reader    = easyocr.Reader(['en'], gpu=False)
    raw_text, _ = run_ocr_once(reader, FINAL_OCR_OUTPUT)
    best_part, score = best_part_match(raw_text)

    mid_str   = f"({chip_middle[0]:.6f}, {chip_middle[1]:.6f})"
    match_disp = best_part if best_part and best_part.upper() in parts_list else "None"

    # ————————————— Append to your detection file —————————————
    with open(DETECTION_FILE, "a") as f:
        f.write(f"1. Raw OCR Text: {raw_text}\n")
        f.write(f"2. Angle of error: {angle:.2f}°\n")
        f.write(f"3. Chip Middle Point: {mid_str}\n")
        f.write(f"4. Closest known part: {best_part or 'None'}\n")
        f.write(f"5. Match ratio: {score:.2f}\n")
        f.write(f"6. Requested Part(s): {source_desc}\n")
        f.write(f"7. Match parts for mapping: {match_disp}\n")
        f.write("-----------------------------------\n\n")

    print("✅ Detection file updated.")


def get_all_cropped_paths():
    paths = []
    with open(DETECTION_FILE) as f:
        for line in f:
            if line.startswith("Cropped Photo Location:"):
                parts = line.split(":",1)[1].split(",")
                if len(parts)>1:
                    paths.append(parts[1].strip())
    return paths

def main():
    seen = []
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    for idx, path in enumerate(get_all_cropped_paths(), start=1):
        mid = extract_middle_point_from_detection_file(idx)
        if is_duplicate_point(mid, seen):
            continue
        seen.append(mid)
        angle = mask_and_rotate(path)
        best_img = run_ocr_and_select()
        cv2.imwrite(FINAL_OCR_OUTPUT, cv2.imread(best_img))
        update_detection_file(angle, idx, mid)

if __name__ == "__main__":
    main()
