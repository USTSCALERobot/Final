#!/usr/bin/env python3
import cv2
import numpy as np
import easyocr
import argparse
from difflib import SequenceMatcher

# A list of known part numbers for matching
KNOWN_PARTS = ["TAIWAN 8005BG SN74LS03J", "asjfhak eiwh SN75LS00", "HTML GIVE SN84LS32", "S", "TEST LM7456"]

def best_part_match(ocr_text, known_parts):
    """
    Compare 'ocr_text' against each known part and return
    the best matching part + the match ratio (0.0 to 1.0).
    """
    best_score = 0.0
    best_part = None
    for part in known_parts:
        ratio = SequenceMatcher(None, ocr_text.upper(), part.upper()).ratio()
        if ratio > best_score:
            best_score = ratio
            best_part = part
    return best_part, best_score

def isolate_chip_and_remove_background(gray_img, padding=5):
    """
    Threshold the image and return a cropped region containing the largest contour (the chip).
    Also return the mask for reference if needed.
    """
    # 1) Otsu threshold (binary inverse so chip is white, background is black)
    _, bin_inv = cv2.threshold(gray_img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # 2) Find contours
    contours, _ = cv2.findContours(bin_inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("No contours found. Check thresholding or image quality.")

    # 3) Take the largest contour
    largest_contour = max(contours, key=cv2.contourArea)

    # 4) Create a mask from the largest contour
    mask = np.zeros_like(gray_img)
    cv2.drawContours(mask, [largest_contour], -1, 255, thickness=cv2.FILLED)

    # 5) Crop bounding rectangle + padding
    x, y, w, h = cv2.boundingRect(largest_contour)
    x = max(0, x - padding)
    y = max(0, y - padding)
    w = min(gray_img.shape[1] - x, w + padding * 2)
    h = min(gray_img.shape[0] - y, h + padding * 2)
    
    # 6) Crop out the chip region
    cropped_chip = gray_img[y:y+h, x:x+w]
    cropped_mask = mask[y:y+h, x:x+w]

    # 7) Replace background with white (optional step to clarify text)
    white_bg = np.full_like(cropped_chip, 255)
    final_chip = np.where(cropped_mask == 255, cropped_chip, white_bg)

    return final_chip, largest_contour

def rotate_chip_to_long_side_bottom(gray_img, contour):
    """
    Use minAreaRect to find the orientation of the chip and rotate it
    so the longer side is placed horizontally.
    Returns the rotated-and-cropped chip in an upright orientation (0°).
    """
    rot_rect = cv2.minAreaRect(contour)
    (cx, cy), (w, h), angle = rot_rect

    # Ensure the longer side is horizontal
    if w < h:
        angle += 90

    # Create rotation matrix
    M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    rotated = cv2.warpAffine(gray_img, M, (gray_img.shape[1], gray_img.shape[0]), 
                             flags=cv2.INTER_CUBIC)

    # Re-find largest contour in the rotated image for tight crop
    _, bin_rotated = cv2.threshold(rotated, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(bin_rotated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        raise ValueError("No contours found after rotation.")
    largest_c = max(cnts, key=cv2.contourArea)
    rx, ry, rw, rh = cv2.boundingRect(largest_c)
    chip_upright = rotated[ry:ry+rh, rx:rx+rw]

    return chip_upright

def run_ocr_once(easyocr_reader, image):
    """
    Run EasyOCR on a single image. Returns the recognized text (concatenated)
    and total number of recognized characters.
    """
    results = easyocr_reader.readtext(image)
    extracted_text = " ".join([res[1] for res in results])
    return extracted_text, len(extracted_text)

def main():
    # --- Parse command-line arguments ---
    parser = argparse.ArgumentParser(description="OCR Script for Chip Orientation Detection")
    parser.add_argument("--image", type=str, default="/home/scalepi/Desktop/savephototest/chip_cropped.png",
                        help="Path to the input cropped chip image")
    parser.add_argument("--save_path", type=str, default="/home/scalepi/Desktop/testOCR/rotationtest.png",
                        help="Path to save the final correctly oriented chip image")
    args = parser.parse_args()

    image_path = args.image
    save_path = args.save_path

    # --------------------------- #
    # 0. Load grayscale image
    # --------------------------- #
    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("Could not load image.")

    # If the image is in portrait mode, rotate it
    if gray.shape[0] > gray.shape[1]:
        gray = cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)

    # --------------------------- #
    # 1. Isolate the chip
    # --------------------------- #
    cropped_chip, largest_contour = isolate_chip_and_remove_background(gray)

    # --------------------------- #
    # 2. Re-threshold & re-find contour on the cropped chip
    # --------------------------- #
    _, bin_cropped = cv2.threshold(cropped_chip, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours_cropped, _ = cv2.findContours(bin_cropped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours_cropped:
        raise ValueError("No contours found in cropped chip.")

    chip_contour = max(contours_cropped, key=cv2.contourArea)

    # --------------------------- #
    # 3. Rotate so longer side is horizontal (0°)
    # --------------------------- #
    chip_upright_0deg = rotate_chip_to_long_side_bottom(cropped_chip, chip_contour)

    # --------------------------- #
    # 4. Also produce a 180° version
    # --------------------------- #
    chip_upright_180deg = cv2.rotate(chip_upright_0deg, cv2.ROTATE_180)

    # --------------------------- #
    # 5. Run EasyOCR only twice
    # --------------------------- #
    reader = easyocr.Reader(['en'], gpu=False)  # GPU=False for RPi typically

    text_0deg, score_0deg = run_ocr_once(reader, chip_upright_0deg)
    text_180deg, score_180deg = run_ocr_once(reader, chip_upright_180deg)

    # --------------------------- #
    # 6. Compare OCR text to known parts
    # --------------------------- #
    best_part_0, best_ratio_0 = best_part_match(text_0deg, KNOWN_PARTS)
    best_part_180, best_ratio_180 = best_part_match(text_180deg, KNOWN_PARTS)

    # Decide which orientation is best by match ratio
    if best_ratio_180 > best_ratio_0:
        chosen_orientation = "180°"
        final_text = text_180deg
        final_part = best_part_180
        final_ratio = best_ratio_180
    else:
        chosen_orientation = "0°"
        final_text = text_0deg
        final_part = best_part_0
        final_ratio = best_ratio_0

    # Print results
    print(f"\n✅ Orientation chosen: {chosen_orientation}")
    print(f"✅ Raw OCR Text: {final_text}")
    if final_part:
        print(f"✅ Closest known part: {final_part} (Match ratio: {final_ratio:.2f})")
    else:
        print("❌ No close match found among known parts.")

    # --------------------------- #
    # 7. Save final correctly oriented chip
    # --------------------------- #
    if chosen_orientation == "180°":
        correct_image = chip_upright_180deg
    else:
        correct_image = chip_upright_0deg

    cv2.imwrite(save_path, correct_image)
    print(f"✅ Saved correctly oriented chip as {save_path}")

if __name__ == "__main__":
    main()