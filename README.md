# SCALE Automated Vision System

SCALE is a Raspberry Pi 5–based system that detects integrated circuits on a conveyor, reads their markings, matches them to requested parts, and uses a Phoenix robotic arm to sort them. `master2.py` is the active entry point.

## Pipeline

```text
UI request
   ↓
Hailo chip detection and image cropping
   ↓
OCR, orientation selection, and part matching
   ↓
Conveyor movement compensation
   ↓
Phoenix arm pickup and drop-off
```

The active stages are:

1. `UIChipRequest2.py` records the requested circuit or part.
2. `chipvision3.py` runs Hailo object detection and saves chip crops and coordinates.
3. `ocrhandler2.py` launches `beltocr2.py` to orient crops, read markings, and match known parts.
4. `Motor_Drive_After_OCR2.py` moves the conveyor to the arm station.
5. `phx_articulate2/Pick_coord_from_crop_txt3.py` transforms the detected coordinates and controls the arm.

## Hardware

- Raspberry Pi 5
- Hailo-8L accelerator
- Camera supported by the Hailo Raspberry Pi pipeline
- GPIO-controlled conveyor motor
- Phoenix robotic arm with Dynamixel servos

The code assumes the Hailo device, GPIO lines, camera, conveyor, and arm are connected and configured. Running the full pipeline can move physical hardware.

## Software requirements

- Raspberry Pi OS with Python 3
- HailoRT 4.23 and compatible Python bindings
- Hailo Raspberry Pi examples and GStreamer plugins
- OpenCV and NumPy
- EasyOCR for the current `beltocr2.py` implementation
- `gpiod`
- Tkinter and the audio/speech packages imported by `UIChipRequest2.py`
- Dynamixel dependencies used by `phx_articulate2`

Verify the Hailo installation:

```bash
hailortcli fw-control identify
hailortcli --version
/usr/bin/python3 -c "import hailo_platform; print(hailo_platform.__file__)"
```

The expected target is a Hailo-8L with matching 4.23 runtime, firmware, and Python bindings.

## Deployment layout

The active scripts currently use absolute Raspberry Pi paths and expect the repository at:

```text
/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final
```

Runtime images and text files are written to:

```text
/home/scalepi/Desktop/savephototest
```

Required Hailo detection resources are referenced by `master2.py`:

```text
/home/scalepi/hailo-rpi5-examples/resources/NewFinal.hef
/home/scalepi/hailo-rpi5-examples/resources/Final.json
```

Update the constants near the top of the scripts if your deployment uses different locations.

## Runtime data

Important files in `savephototest` include:

| File | Purpose |
| --- | --- |
| `chip_request_input.txt` | Requested circuit or individual parts |
| `latest_detection.txt` | Coordinates, OCR output, timing offsets, and selected part matches |
| `Circuits.txt` | Circuit-to-part and arm drop-off mappings |
| `chip_cropped_*.png` | Crops produced by the vision stage |
| `masked_blob.png` | Background-masked OCR image |
| `rotated_blob.png` | First OCR orientation |
| `rotated_blob_180.png` | Alternate OCR orientation |
| `final_oriented_chip.png` | Orientation selected for OCR and debugging |

`latest_detection.txt` is the interface between vision/OCR, conveyor timing, and arm control. Changes to its field names or separators must be coordinated across those stages.

## Running the system

Create the runtime directory and ensure `Circuits.txt` is present:

```bash
mkdir -p /home/scalepi/Desktop/savephototest
```

Start the complete pipeline from the project directory:

```bash
cd /home/scalepi/hailo-rpi5-examples/basic_pipelines/Final
/usr/bin/python3 master2.py
```

Stop it with `Ctrl+C`. Before running, keep the conveyor and arm workspace clear and make sure an emergency stop or power disconnect is accessible.

### Configuration

`master2.py` recognizes:

```bash
export EXTRA_RUN_SEC=1.0
```

`EXTRA_RUN_SEC` controls the between-frame conveyor nudge shared by the vision and arm stages.

## Running individual stages

Use individual stages for diagnosis only when the required input files already exist:

```bash
/usr/bin/python3 UIChipRequest2.py
/usr/bin/python3 chipvision3.py --hef-path /home/scalepi/hailo-rpi5-examples/resources/NewFinal.hef --labels-json /home/scalepi/hailo-rpi5-examples/resources/Final.json
/usr/bin/python3 ocrhandler2.py
/usr/bin/python3 Motor_Drive_After_OCR2.py
/usr/bin/python3 phx_articulate2/Pick_coord_from_crop_txt3.py
```

The motor and arm commands move hardware. Do not run them casually during software-only testing.

## Troubleshooting

### Hailo Python import fails

Check that the Python binding and native library have the same version. A user-installed package under `~/.local` can shadow the system binding:

```bash
PYTHONNOUSERSITE=1 /usr/bin/python3 -c "import hailo_platform; print(hailo_platform.__file__)"
```

### No detections

- Confirm that the HEF and labels JSON exist.
- Confirm that the camera is available.
- Inspect `latest_detection.txt` and the generated `chip*.png` images.
- Check the Hailo/GStreamer console output for missing plugins or post-processing libraries.

### OCR does not recognize a chip

- Inspect `masked_blob.png`, both rotated images, and `final_oriented_chip.png`.
- Make sure the chip marking is focused, sufficiently large, and evenly illuminated.
- Confirm that the desired identifier appears in `KNOWN_PARTS` or the circuit mapping used by `beltocr2.py`.

### Arm does not use a recognized part

Inspect the corresponding block in `latest_detection.txt`, especially:

```text
Closest known part:
Requested Part(s):
Match parts for mapping:
```

The recognized name must agree with the requested part or the entries loaded from `Circuits.txt`.

## Development notes

- Keep hardware-dependent paths and GPIO assignments explicit when deploying to a new Pi.
- Do not commit generated images, logs, or `__pycache__` directories.
- Validate Python changes before deploying:

```bash
/usr/bin/python3 -m py_compile master2.py chipvision3.py ocrhandler2.py beltocr2.py Motor_Drive_After_OCR2.py
```

- Test vision and OCR before enabling the conveyor and arm.

## Project contributors

Dan Walczak, Bennett Nelson, Erik Perez, Louis Stevenson, Ryan Bercich, and Theodore Thorpe — University of St. Thomas.
