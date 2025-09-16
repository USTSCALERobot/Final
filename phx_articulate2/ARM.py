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
PARTS_FILE    = "/home/scalepi/Desktop/savephototest/Parts.txt" #NOTE File still needs to be fully updated/created

def load_circuits(filepath):
    """
    Parse Circuits.txt into a dict:
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
    #print(f"Moving to intermediate position (Z first): {intermediate_pos}")
    go_to_pos(intermediate_pos, theta0_4)
    print(f"Moving to final position: {pickup_pos}")
    go_to_pos(pickup_pos, theta0_4)

def set_gripper(position):
    phx.set_gripper(position)

def pick_up(x, y, additional_angle=0):
    pickup_pos = [x, y, 20]
    theta0_4 = -95

    print(f"Picking up from position: {pickup_pos}, with theta4: {theta0_4}")

    angle = calculate_angle(x, y)
    print(f"The gripper is adjusted to angle: {angle:.2f} degrees")
    adjusted_angle = adjust_gripper_angle(angle, additional_angle)
    gripper_position = angle_to_motor_steps(adjusted_angle)
    set_gripper(gripper_position)

    #print(f"Moving to the position (X, Y, 25) with theta_4 set.")
    intermediate_pos = [x, y, 25]
    go_to_pos(intermediate_pos, theta0_4)

    #print(f"Moving down to pick up position (X, Y, 20).")
    go_to_pos(pickup_pos, theta0_4)

    phx.close_gripper2()
    #print("Gripper closed at the pick up location.")
    time.sleep(3.5)

    #print(f"Moving up to clear the area: (X, Y, 25).")
    intermediate_pos[2] = 25
    go_to_pos(intermediate_pos, theta0_4)

    fixed_position = [10, 0, 25]
    go_to_pos(fixed_position, 0)

FRAME_ROTATION_OFFSET = -90.0


def drop_off(x, y, z, additional_angle):
    """
    Move to (x, y, z), rotate gripper to the absolute desired_angle, open,
    and return home. Assumes gripper yaw is reset to 0° before call.
    """
    drop_off_pos = [x, y, z]
    theta0_4    = -95


    angle = calculate_angle(x, y)
    print(f"The gripper is adjusted to angle: {angle:.2f} degrees")
    adjusted_angle = adjust_gripper_angle(angle, additional_angle)
    gripper_position = angle_to_motor_steps(adjusted_angle)
    set_gripper(gripper_position)


    # Move in Z then XY, release, and return home
    print(f"Dropping off at {drop_off_pos} with base orientation θ₀₋₄ = {theta0_4}")
    move_to_position_with_z_adjustment(drop_off_pos, theta0_4)

    phx.open_gripper2()
    print("Gripper opened at the drop-off location.")
    time.sleep(2.5)

    print("Moving to fixed position (10, 0, 25)...")
    go_to_pos([10, 0, 25], 0)

    print("Returning to rest position...")
    phx.rest_position()


# --- Updated main() ---
def main():
    filename = "/home/scalepi/Desktop/savephototest/latest_detection.txt"
    circuits = load_circuits(CIRCUITS_FILE)

    try:
        with open(filename, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print("Detection file not found.")
        return

    # Process each detection block
    for block in content.strip().split('-----------------------------------'):
        mp = re.search(r"Chip Middle Point: \(([\d.]+), ([\d.]+)\)", block)
        ma = re.search(r"Angle of error: ([\d.]+)", block)
        rc = re.search(r"Requested Part\(s\):\s*(CIRCUIT\d+)", block)
        mm = re.search(r"Match parts for mapping:\s*(.+)", block)

        if not (mp and ma and rc and mm):
            continue

        x_raw, y_raw = map(float, mp.groups())
        part_circuit = rc.group(1).upper()
        part_name    = mm.group(1).strip()

        # Transform pickup, normalize pickup angle, then pick
        tx, ty = transform_coordinates(x_raw, y_raw)
        angle    = float(ma.group(1))
        if abs(angle) < 1.0:
            pickup_offset = 0
        elif angle > 90:
            pickup_offset = angle - 180
        else:
            pickup_offset = angle

        print(f"Processing part '{part_name}' on {part_circuit}")
        pick_up(tx, ty, pickup_offset)
        phx.rest_position_closed()

        # Determine drop-off coordinates & desired_angle
        if part_name == "None":
            dx, dy, dz, desired_angle = -10, -15, 12, 0
        else:
            dx, dy, dz, raw_theta = circuits[part_circuit][part_name]
            # normalize mapping angle
            if abs(raw_theta) < 1.0:
                desired_angle = 0
            elif raw_theta > 90:
                desired_angle = raw_theta - 180
            else:
                desired_angle = raw_theta

        print(f"Mapping drop-off to ({dx}, {dy}, {dz}), θ = {desired_angle:.2f}°")
        drop_off(dx, dy, dz, desired_angle)

    print("Returning to resting position after all drop-offs...")
    phx.rest_position()
    time.sleep(0.1)


if __name__ == "__main__":
    phx.turn_on()
    phx.rest_position()
    main()
