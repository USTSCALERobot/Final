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

## Software requirements

- Raspberry Pi OS and Python 3
- HailoRT 4.23 with matching firmware and Python bindings
- Hailo Raspberry Pi examples and GStreamer plugins
- Custom YOLOv8 HEF and labels JSON
- OpenCV, NumPy, EasyOCR, and `gpiod`
- Tkinter and the audio packages imported by `UIChipRequest2.py`
- Dynamixel dependencies used by `phx_articulate2`

Verify Hailo:

```bash
hailortcli fw-control identify
hailortcli --version
/usr/bin/python3 -c "import hailo_platform; print(hailo_platform.__file__)"
```

The Python package, native HailoRT library, device firmware, and driver must use compatible versions.

## Deployment layout

The scripts currently expect the project at:

```text
/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final
```

Detector resources:

```text
/home/scalepi/hailo-rpi5-examples/resources/NewFinal.hef
/home/scalepi/hailo-rpi5-examples/resources/Final.json
```

Runtime data:

```text
/home/scalepi/Desktop/savephototest
```

Update the constants near the top of each script if the deployment uses different paths.

## Runtime files

| File | Purpose |
| --- | --- |
| `chip_request_input.txt` | Requested circuit or part numbers |
| `latest_detection.txt` | Shared vision, OCR, timing, and mapping results |
| `Circuits.txt` | Circuit definitions and drop-off mappings |
| `Parts.txt` | Reference data reserved for matching extensions |
| `chip.png` / `chip2.png` | Full detection frames |
| `chip_cropped_*.png` | Individual chip crops |
| `masked_blob.png` | Background-masked OCR input |
| `rotated_blob.png` | First orientation candidate |
| `rotated_blob_180.png` | Alternate orientation candidate |
| `final_oriented_chip.png` | Orientation selected by OCR matching |

`latest_detection.txt` is the interface between perception, conveyor, and robotic-control stages. Changing its fields or separators requires corresponding downstream parser changes.

## Running the system

Create the runtime directory and add the required circuit mapping:

```bash
mkdir -p /home/scalepi/Desktop/savephototest
```

Run the pipeline:

```bash
cd /home/scalepi/hailo-rpi5-examples/basic_pipelines/Final
/usr/bin/python3 master2.py
```

The process collects a request, detects and classifies chips, moves the conveyor, and sorts the components. Stop it with `Ctrl+C`.

### Conveyor timing

`EXTRA_RUN_SEC` controls the between-frame conveyor nudge shared by the vision and arm stages:

```bash
export EXTRA_RUN_SEC=1.0
/usr/bin/python3 master2.py
```

## Running individual stages

Use individual stages for calibration and diagnosis only when their expected inputs exist:

```bash
/usr/bin/python3 UIChipRequest2.py

/usr/bin/python3 chipvision3.py \
  --hef-path /home/scalepi/hailo-rpi5-examples/resources/NewFinal.hef \
  --labels-json /home/scalepi/hailo-rpi5-examples/resources/Final.json

/usr/bin/python3 ocrhandler2.py
/usr/bin/python3 Motor_Drive_After_OCR2.py
/usr/bin/python3 phx_articulate2/Pick_coord_from_crop_txt3.py
```

The final two commands move hardware and should only run when the conveyor and arm are ready.

## Calibration

System performance depends on both perception and mechanical calibration:

- Keep the camera position fixed after calibration.
- Use even lighting to preserve package-text contrast.
- Confirm that the conveyor speed model matches the physical belt.
- Verify image-to-arm coordinate conversion before enabling pickup.
- Adjust gripper height and angle offsets for the packages being handled.
- Validate every coordinate in `Circuits.txt` before automatic placement.

## Troubleshooting

### Hailo works from the CLI but not Python

A stale package under `~/.local` can shadow the system binding:

```bash
PYTHONNOUSERSITE=1 /usr/bin/python3 -c \
  "import hailo_platform; print(hailo_platform.__file__)"
```

### No chips are detected

- Confirm that the HEF and labels JSON exist.
- Confirm that the camera is available.
- Inspect `chip.png`, the crop images, and `latest_detection.txt`.
- Check for missing GStreamer or post-processing components.

### OCR fails

- Inspect `masked_blob.png` and both rotated candidates.
- Improve focus and lighting around the marking.
- Confirm that the crop contains the complete identifier.
- Add the identifier to `KNOWN_PARTS` or the applicable circuit mapping.

### OCR succeeds but the part is not selected

Inspect these fields in `latest_detection.txt`:

```text
Raw OCR Text:
Closest known part:
Match ratio:
Requested Part(s):
Match parts for mapping:
```

The matched name must agree with the manual request or requested circuit.

### The arm misses a chip

- Recheck camera-to-arm calibration.
- Confirm the conveyor offset.
- Verify pickup height, gripper angle, and belt position.
- Test slowly with a clear workspace before restoring normal speed.

## Development and validation

Validate Python changes before deployment:

```bash
/usr/bin/python3 -m py_compile \
  master2.py chipvision3.py ocrhandler2.py beltocr2.py \
  Motor_Drive_After_OCR2.py
```

Recommended validation order:

1. Test camera acquisition and detection without the arm.
2. Check saved crops and OCR results.
3. Validate coordinate conversion with the arm above the conveyor.
4. Test conveyor timing at reduced speed.
5. Enable pickup and placement only after the preceding stages pass.

Generated images, logs, and `__pycache__` directories should not be committed.

## Research results

The reported experimental classification accuracy is **97.9%**. The results demonstrate the feasibility of combining embedded inference, OCR, and robotic manipulation for flexible semiconductor sorting without structured component feeding.

## Authors

- Daniel Walczak — Department of Electrical and Computer Engineering, University of St. Thomas
- Lucas Linnemann — Department of Electrical and Computer Engineering, University of St. Thomas
- Cheol-Hong Min — Department of Electrical and Computer Engineering, University of St. Thomas
- Hassan Salamy — Department of Electrical and Computer Engineering, University of St. Thomas

## Publication

This repository accompanies *Selective Object Detection and OCR-Based Sorting in Semiconductor Pick-and-Place Robotics* (IEEE, 2025).
