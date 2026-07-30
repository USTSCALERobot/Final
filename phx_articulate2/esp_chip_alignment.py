"""Align the Phoenix arm to a chip using the ESP32-CAM chip_shift sketch.

The ESP prints lines such as:
    center=91.0 px, confidence=97%, threshold=84, shift=6.5 px down

This module reads those lines, converts the image shift to centimetres, and
updates one coordinate of an arm pose.  It can be imported by the pickup
script or run by itself.

Install the serial dependency on the arm computer with:
    python3 -m pip install pyserial

Before moving real hardware, measure PIXELS_PER_CM and confirm
IMAGE_DOWN_TO_ARM_SIGN for the way the camera is mounted.
"""

from __future__ import annotations

import argparse
import re
import statistics
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # Keep parsing/tests usable without pyserial installed.
    serial = None
    list_ports = None


BAUD_RATE = 115200

# Camera calibration. Replace this with a measured value:
# move a target a known distance and divide the pixel change by that distance.
PIXELS_PER_CM = 36.5 # chip is ~2cm tall and is about 73 pixels tall in the ESP image.

# +1 means "down" in the ESP image requires increasing the selected arm axis.
# Change to -1 if a down-image correction moves the arm the wrong direction.
IMAGE_DOWN_TO_ARM_SIGN = 1

SHIFT_PATTERN = re.compile(
    r"shift=(?P<pixels>\d+(?:\.\d+)?)\s*px\s*"
    r"(?P<direction>up|down|centered)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ShiftReading:
    """One signed shift measurement from the ESP."""

    pixels: float  # down is positive; up is negative
    raw_line: str


def parse_shift(line: str) -> Optional[ShiftReading]:
    """Parse one ESP status line, returning None if it has no shift."""
    match = SHIFT_PATTERN.search(line)
    if not match:
        return None

    magnitude = float(match.group("pixels"))
    direction = match.group("direction").lower()
    if direction == "up":
        magnitude = -magnitude
    elif direction == "centered":
        magnitude = 0.0
    return ShiftReading(magnitude, line.rstrip())


def available_ports() -> list[str]:
    """Return currently visible serial device names."""
    if list_ports is None:
        return []
    return [port.device for port in list_ports.comports()]


class ChipShiftESP:
    """Small client for the serial protocol in ESP32/chip_shift.ino."""

    def __init__(self, port: str, timeout: float = 1.0):
        if serial is None:
            raise RuntimeError("pyserial is required: python3 -m pip install pyserial")
        self.connection = serial.Serial(port, BAUD_RATE, timeout=timeout)
        # Opening an ESP32 serial port may reset it.
        time.sleep(2.0)
        self.connection.reset_input_buffer()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ChipShiftESP":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def calibrate_reference(self) -> None:
        """Tell the ESP to save the currently detected chip as its reference."""
        self.connection.write(b"c\n")
        self.connection.flush()

    def erase_reference(self) -> None:
        """Discard live calibration and restore the standard-image reference."""
        self.connection.write(b"r\n")
        self.connection.flush()

    def read_shift(self, timeout: float = 5.0) -> ShiftReading:
        """Wait for the next valid shift measurement."""
        deadline = time.monotonic() + timeout
        last_line = ""
        while time.monotonic() < deadline:
            line = self.connection.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            last_line = line
            reading = parse_shift(line)
            if reading is not None:
                return reading
        detail = f" Last ESP message: {last_line!r}" if last_line else ""
        raise TimeoutError(f"No shift measurement received in {timeout:.1f}s.{detail}")

    def median_shift(self, samples: int = 3, timeout: float = 8.0) -> float:
        """Return the median signed pixel shift, rejecting an occasional outlier."""
        if samples < 1:
            raise ValueError("samples must be at least 1")
        deadline = time.monotonic() + timeout
        readings = []
        while len(readings) < samples:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Received only {len(readings)} of {samples} shift samples"
                )
            readings.append(self.read_shift(remaining).pixels)
        return float(statistics.median(readings))


def correction_cm(
    shift_pixels: float,
    pixels_per_cm: float = PIXELS_PER_CM,
    image_down_to_arm_sign: int = IMAGE_DOWN_TO_ARM_SIGN,
    max_step_cm: float = 1.0,
) -> float:
    """Convert signed image error to a bounded arm-axis correction."""
    if pixels_per_cm <= 0:
        raise ValueError("pixels_per_cm must be positive")
    if image_down_to_arm_sign not in (-1, 1):
        raise ValueError("image_down_to_arm_sign must be -1 or +1")
    correction = image_down_to_arm_sign * shift_pixels / pixels_per_cm
    return max(-max_step_cm, min(max_step_cm, correction))


def align_pose(
    esp: ChipShiftESP,
    pose: Sequence[float],
    move_to: Callable[[list[float]], object],
    *,
    axis: int = 1,
    pixels_per_cm: float = PIXELS_PER_CM,
    image_down_to_arm_sign: int = IMAGE_DOWN_TO_ARM_SIGN,
    tolerance_pixels: float = 2.0,
    max_step_cm: float = 1.0,
    max_iterations: int = 5,
    samples: int = 3,
    settle_seconds: float = 0.75,
) -> list[float]:
    """Iteratively correct an arm pose and return the final commanded pose.

    ``move_to`` receives a mutable ``[x, y, z]`` pose. In the existing pickup
    code it can be ``lambda p: go_to_pos(p, theta0_4)``.
    """
    if axis not in (0, 1, 2):
        raise ValueError("axis must be 0 (x), 1 (y), or 2 (z)")

    adjusted = list(map(float, pose))
    for attempt in range(1, max_iterations + 1):
        shift = esp.median_shift(samples=samples)
        print(f"ESP alignment {attempt}: signed shift {shift:+.1f} px")
        if abs(shift) <= tolerance_pixels:
            print("ESP alignment is within tolerance.")
            return adjusted

        delta = correction_cm(
            shift, pixels_per_cm, image_down_to_arm_sign, max_step_cm
        )
        adjusted[axis] += delta
        print(
            f"Moving arm axis {'xyz'[axis]} by {delta:+.3f} cm "
            f"to {adjusted[axis]:.3f} cm"
        )
        result = move_to(adjusted.copy())
        if result is False:
            raise RuntimeError(f"Arm rejected alignment pose {adjusted}")
        time.sleep(settle_seconds)

    raise RuntimeError(
        f"Chip did not align within {tolerance_pixels:.1f} px after "
        f"{max_iterations} corrections"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="ESP serial port, e.g. /dev/ttyUSB0 or COM4")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="save the currently visible chip as the ESP reference",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    port = args.port
    if not port:
        ports = available_ports()
        if len(ports) != 1:
            print("Specify --port. Visible ports:", ", ".join(ports) or "none")
            return 2
        port = ports[0]

    with ChipShiftESP(port) as esp:
        if args.calibrate:
            esp.calibrate_reference()
            print("Calibration command sent; verify the ESP says reference saved.")
            time.sleep(1.0)
            return 0
        shift = esp.median_shift(samples=args.samples, timeout=args.timeout)
        delta = correction_cm(shift)
        print(f"Chip shift: {shift:+.1f} px")
        print(f"Arm-axis correction: {delta:+.3f} cm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
