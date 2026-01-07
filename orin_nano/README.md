# Jetson Orin Nano Developer Kit Documentation

## Packaging

The [non-official board](https://category.yahboom.net/products/jetson-orin-nano?variant=52589661618492) used in this project comes from Yahboom Robotics, so it's preflashed already and no set up is required. Simply power it up to use for the first time.

## IMX 477

The [IMX 477](https://www.uctronics.com/imx477-12mp-high-quality-camera-motorized-focus-autofocus.html) module used in this project comes from Arducam. All relevant documentation can be found on the linked site for the module.

In case those docs don't work, set up the board for the module by running `cd /opt/nvidia/jetson-io` and `sudo python jetson-io.py`, then go to the CSI config menu and select `IMX477 Dual 4-lane`. Save and reboot following the menu instructions. Verify connection with `ls /dev/video`; it should output `/dev/video0`. Once you verify the connection, see supported resolutions and frames per second using `v4l2-ctl --list-formats-ext`.

## Known Issues

This section is to document issues the team ran across while working with the Jetson and their solutions, if any.

### Chromium unable to run

- Issue is related to changes in the `snap` package, usually due to a system update
- Fix with `sudo snap revert snapd` to rollback the breaking changes
