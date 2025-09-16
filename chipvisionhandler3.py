#!/usr/bin/env python3
import os
import subprocess
import sys
import time

# --- Configuration ---
HAILO_ENV_SCRIPT = "/home/scalepi/hailo-rpi5-examples/setup_env.sh"
HAILO_VENV_PATH = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi5_examples/bin/activate"
# Update the detection script path as needed; here we use detection_mod3_Cam.py
#DETECTION_SCRIPT = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/beltchipvision.py"
DETECTION_SCRIPT = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/chipvision3.py"
# Command-line arguments for the detection script
#DETECTION_ARGS = "--hef-path /home/scalepi/hailo-rpi5-examples/resources/chip.hef --input rpi --labels-json resources/chip.json"
DETECTION_ARGS = "--hef-path /home/scalepi/hailo-rpi5-examples/resources/NewFinal.hef --input rpi --labels-json resources/Final.json"
# (If your detection script uses relative paths, consider setting cwd accordingly.)

# --- Environment Activation ---
def activate_hailo_env():
    """Activates the Hailo environment and updates os.environ."""
    if os.getenv("HAILO_ENV_ACTIVATED") == "1":
        print("✅ Hailo environment is already active.")
        return

    print("🔧 Activating Hailo Environment...")
    # Run a bash command that sources the environment scripts then prints out the env.
    # Notice the 'env' at the end which dumps all environment variables.
    command = (
        f"bash -c 'source {HAILO_ENV_SCRIPT} && "
        f"source {HAILO_VENV_PATH} && "
        f"export HAILO_ENV_ACTIVATED=1 && env'"
    )
    result = subprocess.run(
        command, shell=True, executable="/bin/bash", capture_output=True, text=True
    )

    if result.returncode != 0:
        print("❌ Error activating environment:", result.stderr)
        sys.exit(1)

    # Parse the environment variables from the output and update os.environ
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        os.environ[key] = value

    # Make sure TAPPAS_POST_PROC_DIR is set (if it isn’t already)
    if "TAPPAS_POST_PROC_DIR" not in os.environ:
        os.environ["TAPPAS_POST_PROC_DIR"] = "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes"

    print("✅ Hailo environment activated successfully.")

# --- Run Detection Pipeline ---
def run_detection():
    """Runs the detection pipeline with the proper environment."""
    print("🚀 Running detection pipeline...")

    # Inherit our updated environment
    env = os.environ.copy()

    # Build the full command to run the detection script with its arguments.
    command = f"python3 {DETECTION_SCRIPT} {DETECTION_ARGS}"
    print(f"Running command: {command}")

    # (Optionally, if your detection script expects a particular working directory, set cwd.)
    process = subprocess.Popen(
        command, shell=True, executable="/bin/bash", env=env
    )

    try:
        process.wait()  # Wait until the detection pipeline finishes.
    except KeyboardInterrupt:
        print("🛑 AI detection interrupted.")
        process.terminate()
        sys.exit(1)

    print("✅ AI Detection completed.")

# --- Cleanup ---
def cleanup():
    """Stops any running GStreamer pipelines and detection scripts."""
    print("🧹 Cleaning up resources...")
    subprocess.run("pkill -f gst-launch-1.0", shell=True)
    subprocess.run("pkill -f detection_mod3_Cam.py", shell=True)
    print("✅ Cleanup done.")

# --- Main Execution ---
if __name__ == "__main__":
    try:
        activate_hailo_env()
        time.sleep(1)  # Give the environment a moment to settle.
        run_detection()
    except Exception as e:
        print(f"❌ Error occurred: {e}")
    finally:
        cleanup()