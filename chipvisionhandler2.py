#!/usr/bin/env python3
import os
import subprocess
import sys
import time

# --- Configuration ---
HAILO_VENV_PATH    = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi_examples/bin/activate"
HAILO_VENV_PYTHON  = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi_examples/bin/python3"
HAILO_PROJECT_ROOT = "/home/scalepi/hailo-rpi5-examples"

DETECTION_SCRIPT = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/chipvision3.py"
DETECTION_ARGS   = "--hef-path /home/scalepi/hailo-rpi5-examples/resources/NewFinal.hef --input rpi --labels-json resources/Final.json"


# --- Environment Activation ---
def activate_hailo_env():
    """
    Activates the Hailo venv and loads its environment variables into os.environ.
    - Skips setup_env.sh entirely (it requires interactive sourcing).
    - Injects /usr/lib/python3/dist-packages into PYTHONPATH so that
      system-only packages (gi / GStreamer bindings) are visible to the venv Python.
    """
    if os.getenv("HAILO_ENV_ACTIVATED") == "1":
        print("✅ Hailo environment is already active.")
        return

    print("🔧 Activating Hailo Environment...")

    if not os.path.exists(HAILO_VENV_PATH):
        print(f"❌ Venv not found: {HAILO_VENV_PATH}")
        sys.exit(1)

    command = (
        f"bash -c '"
        f"source {HAILO_VENV_PATH} && "
        f"export HAILO_ENV_ACTIVATED=1 && "
        # Project root first so local modules are found
        f"export PYTHONPATH={HAILO_PROJECT_ROOT}:$PYTHONPATH && "
        # System dist-packages needed for gi (GStreamer Python bindings)
        f"export PYTHONPATH=/usr/lib/python3/dist-packages:$PYTHONPATH && "
        f"export TAPPAS_POST_PROC_DIR=/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes && "
        f"env'"
    )

    result = subprocess.run(
        command, shell=True, executable="/bin/bash",
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"❌ Error activating environment (exit code {result.returncode})")
        print(f"   STDERR: {result.stderr.strip() or '(empty)'}")
        print(f"   STDOUT tail:")
        for line in result.stdout.strip().splitlines()[-15:]:
            print(f"     {line}")
        sys.exit(1)

    # Apply captured env vars to this process
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key and key.isidentifier():
            os.environ[key] = value

    print("✅ Hailo environment activated successfully.")


# --- Run Detection Pipeline ---
def run_detection():
    """
    Runs the detection pipeline using the venv's own Python binary.
    Using the venv Python directly gives access to venv packages (setproctitle,
    hailo, numpy, etc.) while the PYTHONPATH set above provides gi/GStreamer.
    """
    print("🚀 Running detection pipeline...")

    env = os.environ.copy()

    # Use the venv Python, NOT /usr/bin/python3 or the system default.
    command = f"{HAILO_VENV_PYTHON} {DETECTION_SCRIPT} {DETECTION_ARGS}"
    print(f"Running command: {command}")

    process = subprocess.Popen(
        command, shell=True, executable="/bin/bash", env=env
    )

    try:
        process.wait()
    except KeyboardInterrupt:
        print("🛑 AI detection interrupted.")
        process.terminate()
        sys.exit(1)

    print("✅ AI Detection completed.")


# --- Cleanup ---
def cleanup():
    """Stops any stray GStreamer pipelines."""
    print("🧹 Cleaning up resources...")
    subprocess.run("pkill -f gst-launch-1.0", shell=True)
    subprocess.run("pkill -f chipvision3.py", shell=True)
    print("✅ Cleanup done.")


# --- Main Execution ---
if __name__ == "__main__":
    try:
        activate_hailo_env()
        time.sleep(1)   # let the environment settle
        run_detection()
    except Exception as e:
        print(f"❌ Error occurred: {e}")
    finally:
        cleanup()