# Jetson Orin Nano Developer Kit Documentation

**If something is not on this doc, then it hasn't been done yet in this project.**

## Packaging

The [non-official board](https://category.yahboom.net/products/jetson-orin-nano?variant=52589661618492) used in this project comes from Yahboom Robotics, so it's preflashed already and no set up is required. Simply power it up to use for the first time.

## IMX 477 (old camera)

The [IMX 477](https://www.uctronics.com/imx477-12mp-high-quality-camera-motorized-focus-autofocus.html) module used in this project comes from Arducam. All relevant documentation can be found on the linked site for the module. **NO LONGER IN USE. (see IMX 219)**

In case those docs don't work, set up the board for the module by running `cd /opt/nvidia/jetson-io` and `sudo python jetson-io.py`, then go to the CSI config menu and select `IMX477 Dual 4-lane`. Save and reboot following the menu instructions. Verify connection with `ls /dev/video`; it should output `/dev/video0`. Once you verify the connection, see supported resolutions and frames per second using `v4l2-ctl --list-formats-ext`.

## IMX 219 (current camera)

The [IMX 219](https://www.uctronics.com/arducam-8-mp-sony-visible-light-ir-fixed-focus-camera-module-for-nvidia-jetson-nano.html) module used in this project comes from Arducam. This camera replaced the initial IMX477 because it offered better built-in support from the NVIDIA Jetson Orin Nano Super firmware.

The setup process is the same as the steps outlined in the IMX477 section, but this time you have to set up the pins for this camera module instead.

## SSH

This section documents how to control the Jetson Orin Nano Super from another machine (e.g. a Mac) over SSH, while still displaying the camera GUI on the Jetson’s own monitor. **SSH client must be on the 'eduroam' network to connect.**

- **Initial SSH setup**
  - Ensure the Jetson is powered on, connected to the same network (Ethernet or Wi‑Fi), and reachable (for example `ping <jetson-ip>`).
  - SSH into the Jetson from your machine:
    - `ssh <jetson-username>@<jetson-ip>` (replace `<jetson-username>` and `<jetson-ip>` as appropriate).
    - `whoami` to find username and `ip addr show` to find IP address (can check Wi-Fi settings too)
  - SSH sessions can be closed in 3 ways:
    - `exit`
    - `Ctrl + D`
    - `press Enter, then type ~.`
  - If SSH is not available, install and enable the SSH server on the Jetson:
    - `sudo apt update && sudo apt install openssh-server`
    - `sudo systemctl enable ssh && sudo systemctl start ssh`

- **Running GUI apps (camera or app) from SSH while displaying on the Jetson monitor**
  - From the SSH session, explicitly target the Jetson’s local X display:
    - `export DISPLAY=:0`
    - `export XAUTHORITY=/home/jetson/.Xauthority` (adjust path/username if different).
  - Make sure the same user is logged into the Jetson’s desktop on the attached monitor.
  - Restart the Argus camera daemon once to clear stale state (The Argus camera stack can get stuck after crashes or improper shutdowns. Restarting nvargus-daemon resolves most camera initialization issues):
    - `sudo systemctl restart nvargus-daemon`
  - Run any script from the project directory:
    - `cd ~/SCALE_Robot/Final/orin_nano`
    - `python <filename>`
  - Result: CLI activity is visible in the SSH terminal on your machine, while the OpenCV window and camera feed appear on the Jetson’s physical display.

- **What went wrong**
  - **Using X11 forwarding (`ssh -X` / `ssh -Y`) with `nvarguscamerasrc`**:
    - This set `DISPLAY` to something like `localhost:10.0` (your Mac’s X server).
    - The Jetson Argus stack then failed to create an EGL stream for the camera, producing errors such as:
      - `Error BadParameter ... Failed to create FrameConsumer`
      - `gstnvarguscamerasrc.cpp, waitRunning: Invalid thread state 3`
    - Fix: do **not** use X forwarding with the Argus camera pipeline; instead, SSH without `-X/-Y` and point `DISPLAY` to `:0`.
  - **Running OpenCV GUI code over SSH without a usable display**:
    - When no display was available (or GTK was pointed at the wrong display), `cv2.namedWindow` failed with:
      - `cv2.error: Can't initialize GTK backend in function 'cvInitSystem'`
    - Fix: either run the script with a valid `DISPLAY` pointing to the Jetson’s own X server (`:0`), or add a headless mode that skips `cv2.namedWindow` / `cv2.imshow` when running without GUI (not implemented).

## Known Issues

This section is to document issues the team ran across while working with the Jetson and their solutions, if any.

### Chromium unable to run

- Issue is related to changes in the `snap` package, usually due to a system update
- Fix with `sudo snap revert snapd` to rollback the breaking changes
