# """Keep all arm joints stationary while moving the gripper a specified
# distance (degrees) at a constant speed (degrees/sec).

# Usage (from shell):
#   python hold_arm.py --delta 30 --rate 10

# This will open the gripper by +30 degrees at 10 deg/sec. Use a negative
# `--delta` to close.
# """

# import time
# import argparse
# import phx


# def move_gripper_by(delta_deg, rate_deg_per_sec, step_ms=500, use_gripper2=False):
# 	"""Move the gripper by `delta_deg` degrees at `rate_deg_per_sec`.

# 	Only the gripper motor is commanded; all other joints remain untouched
# 	so they hold their current positions.
# 	- `delta_deg` may be positive (open more) or negative (close).
# 	- `rate_deg_per_sec` must be > 0.
# 	- `step_ms` controls update frequency; smaller -> smoother.
# 	"""
# 	if rate_deg_per_sec <= 0:
# 		raise ValueError('rate_deg_per_sec must be > 0')

# 	motor = phx.gripper2 if use_gripper2 else phx.gripper

# 	# Read current angle robustly from the motor's present position.
# 	# Prefer using the motor's mapping attributes set by `phx.config_motor_angles()`.
# 	try:
# 		raw_pos = motor.get_position()
# 	except Exception as e:
# 		raise RuntimeError('Unable to read motor present position') from e

# 	# motor mapping attributes have slightly different names in parts of
# 	# the codebase (`min_map_deg`/`max_map_deg` vs `min_angle`/`max_angle`).
# 	min_map = getattr(motor, 'min_map_deg', None) or getattr(motor, 'min_angle', None)
# 	max_map = getattr(motor, 'max_map_deg', None) or getattr(motor, 'max_angle', None)
# 	if min_map is None or max_map is None:
# 		raise AttributeError('Motor mapping attributes missing; call phx.turn_on() first')

# 	current_deg = phx.map_val(raw_pos, motor.MIN_POS_VAL, motor.MAX_POS_VAL, min_map, max_map)

# 	target_deg = current_deg + delta_deg
# 	target_deg = phx.check_limit(motor, target_deg)

# 	total_deg = target_deg - current_deg
# 	if abs(total_deg) < 1e-6:
# 		return

# 	step_sec = step_ms / 1000.0
# 	step_deg = rate_deg_per_sec * step_sec
# 	if step_deg <= 0:
# 		raise ValueError('Computed step_deg must be > 0')

# 	steps = max(1, int(abs(total_deg) / step_deg))
# 	sign = 1 if total_deg > 0 else -1

# 	# set a conservative moving speed for gripper (affects internal motor profile)
# 	try:
# 		motor.set_moving_speed(phx.half_speed)
# 	except Exception:
# 		pass

# 	moved = 0.0
# 	prev_deg = current_deg
# 	for _ in range(steps):
# 		remaining = abs(total_deg) - moved
# 		step = min(remaining, step_deg)
# 		next_deg = current_deg + sign * step
# 		next_deg = phx.check_limit(motor, next_deg)
# 		next_pos = int(phx.deg_to_pos(motor, next_deg))
# 		if use_gripper2:
# 			phx.set_gripper2(next_pos)
# 		else:
# 			phx.set_gripper(next_pos)
# 		time.sleep(step_sec)
# 		moved += abs(next_deg - prev_deg)
# 		prev_deg = next_deg
# 		current_deg = next_deg

# 	# ensure final exact position
# 	final_pos = int(phx.deg_to_pos(motor, target_deg))
# 	if use_gripper2:
# 		phx.set_gripper2(final_pos)
# 	else:
# 		phx.set_gripper(final_pos)
# 	phx.wait_for_completion()


# def main(argv=None):
# 	parser = argparse.ArgumentParser(description='Hold arm joints and move gripper')
# 	parser.add_argument('--delta', type=float, required=True,
# 						help='Degrees to move gripper (positive opens, negative closes)')
# 	parser.add_argument('--rate', type=float, required=True,
# 						help='Rate in degrees per second (positive)')
# 	parser.add_argument('--gripper2', action='store_true', help='Operate gripper2 instead')
# 	parser.add_argument('--step_ms', type=int, default=50, help='Update interval in milliseconds')
# 	args = parser.parse_args(argv)

# 	try:
# 		phx.turn_on()
# 	except Exception as e:
# 		print('Warning: failed to call phx.turn_on():', e)

# 	try:
# 		move_gripper_by(args.delta, args.rate, step_ms=args.step_ms, use_gripper2=args.gripper2)
# 		print(f'Moved gripper by {args.delta} deg at {args.rate} deg/s')
# 	except Exception as e:
# 		print('Error during gripper move:', e)
# 	finally:
# 		try:
# 			phx.wait_for_completion()
# 		except Exception:
# 			pass
# 		try:
# 			phx.turn_off()
# 		except Exception:
# 			pass


# if __name__ == '__main__':
# 	main()

import phx
import Pick_coord_from_crop_txt3 as pc

phx.set_gripper2(1)
