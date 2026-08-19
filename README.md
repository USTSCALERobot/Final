# Selective Object Detection and OCR-Based Sorting in Semiconductor Pick-and-Place Robotics

This repository contains an automated semiconductor sorting system developed at the University of St. Thomas. It combines embedded object detection, optical character recognition (OCR), conveyor control, and robotic inverse kinematics to recognize, classify, pick, and sort integrated circuits.

`master2.py` is the active entry point.

## Project overview

Traditional pick-and-place systems commonly rely on structured feeders and pre-aligned components. This project instead detects semiconductor chips placed at arbitrary positions and orientations on a conveyor. A camera observes the workspace, a custom YOLOv8 model locates each chip, OCR reads its package markings, and a Phoenix robotic arm moves the selected component to its assigned destination.

The system uses low-cost embedded hardware:

- A Raspberry Pi manages the application pipeline and hardware control.
- A Hailo AI accelerator executes the custom object-detection model.
- EasyOCR performs package-label recognition and classification in the current implementation.
- OpenCV handles preprocessing, crop extraction, orientation, and coordinates.
- A conveyor moves components between the camera and pickup stations.
- A Phoenix arm uses inverse kinematics to pick and place detected components.

Experimental testing reported **97.9% classification accuracy** across chips with varying package sizes, pin counts, labels, positions, and orientations.

## Research objective

The project evaluates whether semiconductor sorting can be performed accurately in real time with embedded hardware and a custom AI pipeline. Its goals are to:

- Detect semiconductor packages without requiring pre-alignment.
- Read package text despite arbitrary chip orientation.
- Match recognized markings to requested parts or circuit definitions.
- Transform image-space coordinates into physical pickup coordinates.
- Compensate for conveyor movement between detection and pickup.
- Place recognized and unrecognized components into appropriate destinations.

## System pipeline

```text
Part or circuit request
          ↓
Camera acquisition
          ↓
YOLOv8 detection on Hailo
          ↓
Bounding-box and crop extraction
          ↓
Masking and orientation correction
          ↓
OCR and part-number matching
          ↓
Conveyor distance compensation
          ↓
Image-to-robot coordinate transformation
          ↓
Inverse kinematics, pickup, and placement
```

### 1. User request

`UIChipRequest2.py` records a requested circuit or list of components. The request is written to `chip_request_input.txt` for the matching stage.

### 2. Selective object detection

`chipvision3.py` runs a custom YOLOv8 model through the Hailo pipeline. It records bounding boxes, saves chip crops, and tracks conveyor timing across one or two frames.

### 3. OCR and classification

`ocrhandler2.py` invokes `beltocr2.py`, which:

- Parses the detected frames and crop locations.
- Removes unnecessary background.
- Estimates chip orientation.
- Tests upright and 180-degree orientations.
- Reads package markings with EasyOCR.
- Compares OCR output against known part numbers.
- Writes the selected part, orientation, coordinates, and confidence to `latest_detection.txt`.

### 4. Conveyor compensation

`Motor_Drive_After_OCR2.py` uses vision timing to estimate how far components have traveled and how long the conveyor must run to reach the pickup station.

### 5. Robotic sorting

`phx_articulate2/Pick_coord_from_crop_txt3.py` converts normalized image coordinates into the arm coordinate system. Inverse-kinematics routines calculate the joint positions needed to approach, rotate, grasp, lift, and place each chip.

Recognized parts can be placed using mappings from `Circuits.txt`. Unrecognized parts can be routed to a separate location.

## Active implementation

| File | Responsibility |
| --- | --- |
| `master2.py` | Runs the complete pipeline |
| `UIChipRequest2.py` | Collects requested circuits or part numbers |
| `vosk_voice_detection.py` | Supports voice input |
| `chipvision3.py` | Runs Hailo detection and saves crop metadata |
| `ocrhandler2.py` | Starts OCR processing |
| `beltocr2.py` | Preprocesses images, performs OCR, and matches parts |
| `Motor_Drive_After_OCR2.py` | Controls post-OCR conveyor movement |
| `phx_articulate2/Pick_coord_from_crop_txt3.py` | Selects pickups and controls arm motion |
| `phx_articulate2/kinematics.py` | Calculates robotic kinematics |
| `phx_articulate2/phx.py` | Controls the Phoenix arm and gripper |

## Hardware

- Raspberry Pi 5
- Hailo-8L AI accelerator
- Raspberry Pi-compatible camera
- GPIO-controlled conveyor motor
- Phoenix robotic arm
- Dynamixel actuators and interface hardware

The full pipeline moves physical hardware. Keep the workspace clear, verify limits and drop-off coordinates, and maintain access to an emergency stop or power disconnect.

## Contributors

- Ryan Bercich — University of St. Thomas
- Lucas Linnemann — University of St. Thomas
- Louis Stevenson — University of St. Thomas
- Theodore Thorpe — University of St. Thomas
- Daniel Walczak — University of St. Thomas
