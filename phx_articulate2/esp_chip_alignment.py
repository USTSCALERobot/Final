"""Retrieve chip displacement wirelessly from the ESP32-CAM.

The Pi broadcasts the ``SCALE-ARM`` hotspot, and the ESP joins it at the fixed
address ``http://10.42.0.20``. This module uses only Python's standard library;
pyserial is not needed.

Before moving real hardware, measure PIXELS_PER_CM and confirm
IMAGE_DOWN_TO_ARM_SIGN for the way the camera is mounted.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Callable, Iterable, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Camera calibration. Replace this with a measured value:
# move a target a known distance and divide the pixel change by that distance.
PIXELS_PER_CM = 36.5 # chip is ~2cm tall and is about 73 pixels tall in the ESP image.

# +1 means "down" in the ESP image requires increasing the selected arm axis.
# Change to -1 if a down-image correction moves the arm the wrong direction.
IMAGE_DOWN_TO_ARM_SIGN = 1
ESP_TAG = "\033[1;36m[ESP]\033[0m"

class ChipShiftWiFi:
    """HTTP client for the ESP32-CAM access point."""

    def __init__(self, base_url: str = "http://10.42.0.20"):
        self.base_url = base_url.rstrip("/")

    def __enter__(self) -> "ChipShiftWiFi":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        pass

    def _request(self, path: str, timeout: float, method: str = "GET") -> dict:
        request = Request(self.base_url + path, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ESP returned HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise ConnectionError(
                f"Cannot reach ESP at {self.base_url}; "
                "make sure the SCALE-ARM hotspot is active and the ESP joined it"
            ) from error

    def read_shift(self, timeout: float = 5.0) -> float:
        """Return one signed pixel shift (image down is positive)."""
        payload = self._request("/shift", timeout)
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", "invalid ESP response"))
        print(
            f"{ESP_TAG} center={float(payload['center_px']):.1f} px, "
            f"reference={float(payload['reference_px']):.1f} px, "
            f"shift={float(payload['shift_px']):+.1f} px, "
            f"confidence={float(payload['confidence']):.3f}"
        )
        return float(payload["shift_px"])

    def calibrate_reference(self, timeout: float = 5.0) -> None:
        self._request("/calibrate", timeout, method="POST")

    def restore_standard_reference(self, timeout: float = 5.0) -> None:
        self._request("/reset-reference", timeout, method="POST")

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
            readings.append(self.read_shift(remaining))
            if len(readings) < samples:
                time.sleep(0.55)
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
    esp: ChipShiftWiFi,
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
    parser.add_argument("--url", default="http://10.42.0.20")
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
    with ChipShiftWiFi(args.url) as esp:
        if args.calibrate:
            esp.calibrate_reference()
            print("ESP saved the currently visible chip as its reference.")
            return 0
        shift = esp.median_shift(samples=args.samples, timeout=args.timeout)
        delta = correction_cm(shift)
        print(f"Chip shift: {shift:+.1f} px")
        print(f"Arm-axis correction: {delta:+.3f} cm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
