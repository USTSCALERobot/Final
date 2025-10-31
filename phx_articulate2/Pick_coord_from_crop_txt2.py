import kinematics as kin
import numpy as np
import phx
import time
import math
import re

# Turn on Phoenix system and initialize resting position
phx.turn_on()
phx.rest_position()


def transform_coordinates(x1, y1):
    """Transform coordinates from System 1 (0-1 scale) to System 2 (15-22 in X, -10 to 10 in Y)."""
    x2 = x1 * (22 - 15) + 15
    y2 = y1 * (-10 - (10)) + (10)
    return x2, y2


CIRCUITS_FILE = "/home/scalepi/Desktop/savephototest/Circuits.txt"
PARTS_FILE = "/home/scalepi/Desktop/savephototest/Parts.txt"  # NOTE File still needs to be fully updated/created


def load_circuits(filepath):
    """ Parse Circuits.txt into a dict:
    { 'CIRCUIT1': { 'SN74185AN': (x, y, z, map_theta), ... }, ... }
    """
    circuits = {}
    text = open(filepath, 'r').read()
    blocks = re.findall(r'(CIRCUIT\d+)\s*=\s*\[([^\]]+)\]', text, flags=re.IGNORECASE)

    for circuit_name, block in blocks:
        key = circuit_name.upper()
        circuits[key] = {}
        entries = re.findall(r'\d+\.\s*([^()]+)\(\s*([-\d.,\s]+)\s*\)', block)

        for part_name, coord_str in entries:
            part = part_name.strip()
            nums = [float(n) for n in coord_str.split(',')]
            circuits[key][part] = (nums[0], nums[1], nums[2], nums[3])

    return circuits


def get_detections_from_file(filename):
    """Parse detection blocks from the file and return list of dictionaries."""
    with open(filename, 'r') as file:
        content = file.read()

    blocks = content.strip().split('-----------------------------------')
    detections = []

    for block in blocks:
        match_point = re.search(r"Chip Middle Point: \((\d+\.\d+), (\d+\.\d+)\)", block)
        match_angle = re.search(r"Angle of error: (\d+\.\d+)", block)
        match_part = re.search(r"Closest known part: (.+)", block)

        if match_point and match_angle:
            x = float(match_point.group(1))
            y = float(match_point.group(2))
            angle = float(match_angle.group(1))
            part = match_part.group(1).strip() if match_part else None
            detections.append({"x": x, "y": y, "angle": angle, "part": part})

    return detections


def calculate_angle(x, y):
    if abs(y) > abs(x):
        angle_rad = math.atan2(x, y)
        angle_rad -= (math.pi) / 4
        angle_deg = math.degrees(angle_rad) + 45
        if angle_deg < 0:
            angle_deg += 360
    else:
        angle_rad = math.atan2(y, x)
        angle_rad -= math.pi
        angle_deg = math.degrees(angle_rad)
        if angle_deg < 0:
            angle_deg += 360
    return angle_deg


def angle_to_motor_steps(angle_deg):
    motor_position = (angle_deg / 180) * 512
    return round(motor_position)


def adjust_gripper_angle(current_angle, additional_angle):
    adjusted_angle = current_angle + additional_angle
    print(f"Gripper adjusted by {additional_angle} degrees. New angle: {adjusted_angle:.2f}")
    return adjusted_angle


def readjusted_gripper_angle(current_angle, additional_angle):
    adjusted_angle = current_angle - additional_angle
    print(f"Gripper adjusted by {additional_angle} degrees. New angle: {adjusted_angle:.2f}")
    return adjusted_angle


def go_to_pos(pickup_pos, theta0_4):
    try:
        joint_angles = kin.ik3(pickup_pos)
        theta4 = kin.calculate_theta_4(joint_angles, theta0_4)
        phx.set_wrist(theta4)
        phx.set_wse(joint_angles)
        phx.wait_for_completion()
    except ValueError as e:
        print(f"Error: Unable to reach position {pickup_pos}.")
        print(f"Details: {e}")
        return False
    return True


def move_to_position_with_z_adjustment(pickup_pos, theta0_4, z_adjustment=15):
    intermediate_pos = pickup_pos.copy()
    intermediate_pos[2] += z_adjustment
    # print(f"Moving to intermediate position (Z first): {intermediate_pos}")
    go_to_pos(intermediate_pos, theta0_4)
    print(f"Moving to final position: {pickup_pos}")
    go_to_pos(pickup_pos, theta0_4)


def set_gripper(position):
    phx.set_gripper(position)


def pick_up(x, y, additional_angle=0):
    pickup_pos = [x, y, 21]
    theta0_4 = -90
    print(f"Picking up from position: {pickup_pos}, with theta4: {theta0_4}")

    angle = calculate_angle(x, y)
    print(f"The gripper is adjusted to angle: {angle:.2f} degrees")
    adjusted_angle = adjust_gripper_angle(angle, additional_angle)
    gripper_position = angle_to_motor_steps(adjusted_angle)
    set_gripper(gripper_position)

    # print(f"Moving to the position (X, Y, 25) with theta_4 set.")
    intermediate_pos = [x, y, 25]
    go_to_pos(intermediate_pos, theta0_4)

    # print(f"Moving down to pick up position (X, Y, 20).")
    go_to_pos(pickup_pos, theta0_4)
    phx.close_gripper2()
    # print("Gripper closed at the pick up location.")
    time.sleep(3.5)

    # print(f"Moving up to clear the area: (X, Y, 25).")
    intermediate_pos[2] = 25
    go_to_pos(intermediate_pos, theta0_4)
    fixed_position = [10, 0, 25]
    go_to_pos(fixed_position, 0)


def calculate_drop_bearing(x, y):
    """Compute the raw bearing angle for drop-off, based purely on the (x, y) offset from the base.
    Uses absolute values so that drop quadrants always yield a positive bearing between 0-90°.
    """
    return math.degrees(math.atan2(abs(y), abs(x)))


# --- Updated drop_off() with raw-based adjustment ---
def drop_off(x, y, z, desired_angle):
    """ Drop at (x, y, z):
    1) raw = calculate_drop_bearing(x, y)
    2) zero_offset = raw - 90
    3) delta = zero_offset + desired_angle
    4) if x >= 0: new_angle = raw - delta
       else: new_angle = raw + delta
    5) normalize, convert to steps, set_gripper
    6) move, open, and return home
    """
    drop_off_pos = [x, y, z]
    theta0_4 = -95

    # Step 1: raw bearing
    raw = calculate_drop_bearing(x, y)
    print(f"Raw drop bearing: {raw:.2f}°")

    # Step 2: baseline offset
    zero_offset = raw - 90

    # Step 3: compute delta
    delta = zero_offset + desired_angle
    print(f"Computed delta: zero_offset({zero_offset:.2f}) + desired({desired_angle:.2f}) = {delta:.2f}°")

    # Step 4: apply conditional sign
    if x <= 0:
        new_angle = delta + raw
        print(f"x>=0: new_angle = raw({raw:.2f}) - delta({delta:.2f}) = {new_angle:.2f}°")
    else:
        new_angle = raw - delta
        print(f"x<0: new_angle = raw({raw:.2f}) + delta({delta:.2f}) = {new_angle:.2f}°")

    # Step 5: normalize and set
    new_angle %= 360
    motor_pos = angle_to_motor_steps(new_angle)
    print(f"Setting gripper to {new_angle:.2f}° (motor pos {motor_pos})")
    set_gripper(motor_pos)

    # Step 6: perform motion
    print(f"Dropping off at {drop_off_pos}, base θ₀₋₄ = {theta0_4}")
    move_to_position_with_z_adjustment(drop_off_pos, theta0_4)
    phx.open_gripper2()
    print("Gripper opened at drop-off location.")
    time.sleep(2.5)

    print("Moving to fixed position (10, 0, 25)...")
    go_to_pos([10, 0, 25], 0)

    print("Returning to rest position...")
    phx.rest_position()


# --- Main Loop ---
def main():
    filename = "/home/scalepi/Desktop/savephototest/latest_detection.txt"
    circuits = load_circuits(CIRCUITS_FILE)

    try:
        with open(filename, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print("Detection file not found.")
        return

    for block in content.strip().split('-----------------------------------'):
        mp = re.search(r"Chip Middle Point: \(([\d.]+), ([\d.]+)\)", block)
        ma = re.search(r"Angle of error: ([\d.]+)", block)
        rc = re.search(r"Requested Part\(s\):\s*(CIRCUIT\d+)", block) #TODO: Fix bug that causes no part requests to be skipped and part names always come in as "None"
        mm = re.search(r"Match parts for mapping:\s*(.+)", block)

        if not (mp and ma and rc and mm):
            print(f"MP: '{mp}'")
            print(f"MA: '{ma}'")
            print(f"RC: '{rc}'")
            print(f"MM: '{mm}'")
            print("Insufficient chip information; skipping pickup")
            continue

        x_raw, y_raw = map(float, mp.groups())
        part_circuit = rc.group(1).upper()
        part_name = mm.group(1).strip()

        # === Pickup Phase ===
        tx, ty = transform_coordinates(x_raw, y_raw)
        angle = float(ma.group(1))

        if abs(angle) < 1.0:
            pickup_offset = 0
        elif angle > 90:
            pickup_offset = angle - 180
        else:
            pickup_offset = angle

        print(f"Picking up '{part_name}' at ({tx:.2f},{ty:.2f}) with {pickup_offset:.2f}° offset")
        pick_up(tx, ty, pickup_offset)
        phx.rest_position_closed()

        # === Drop-off Phase ===
        if part_name == "None":
            dx, dy, dz, desired_angle = -10, -15, 12, 0
        else:
            dx, dy, dz, desired_angle = circuits[part_circuit][part_name]

        print(f"Dropping off '{part_name}' at ({dx:.2f},{dy:.2f},{dz:.2f}), CIRCUITS θ = {desired_angle:.2f}°")
        drop_off(dx, dy, dz, desired_angle)

        print("All operations complete. Resting.")
        phx.rest_position()


if __name__ == "__main__":
    phx.turn_on()
    phx.rest_position()
    main()
