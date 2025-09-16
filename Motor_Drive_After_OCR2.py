#!/usr/bin/env python3
import gpiod
import time
import argparse
import sys

GPIOCHIP = "gpiochip4"   # matches your original code
LINE     = 24            # motor / belt line

def run_belt(seconds: float):
    chip = gpiod.Chip(GPIOCHIP)
    line = chip.get_line(LINE)
    line.request(consumer="belt_after_ocr", type=gpiod.LINE_REQ_DIR_OUT)
    try:
        line.set_value(1)
        print(f"ON ({seconds:.2f}s)")
        time.sleep(seconds)
        line.set_value(0)
        print("OFF")
        # small settle time is fine but optional
        time.sleep(1.0)
    finally:
        try:
            line.set_value(0)
        except Exception:
            pass
        line.release()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=9.25,
                    help="Seconds to run belt (default 9.25)")
    args = ap.parse_args()
    if args.seconds <= 0:
        print("seconds must be > 0", file=sys.stderr)
        sys.exit(2)
    run_belt(args.seconds)

if __name__ == "__main__":
    main()
