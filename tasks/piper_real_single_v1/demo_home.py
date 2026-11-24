"""Piper H direct MOVE_J return to six-axis zero, independent of task actions."""
import math
import os
import subprocess
import time

from demo_io import HERE, gap, h0, healthy, read, save, snapshot


ZERO = [0.] * 6


def released_pose(dev, rx, grip):
    row = snapshot(dev, rx, grip)
    st = row["arm"]
    stopped = st["teach_status"] == 2 or (st["ctrl_mode"] == 1 and st["teach_status"] == 0)
    flags = row["gripper"]["foc_status"]
    if (not stopped or st["ctrl_mode"] not in (0, 1, 2) or st["arm_status"] or st["motion_status"]
            or h0.calibration_driver_issues(dev, st, require_can=False)
            or row["gripper"]["mode"] != "width"
            or any(v for k,v in flags.items() if k not in ("driver_enable_status","homing_status"))
            or not all(math.isfinite(v) for v in row["q_rad"]) or not 0 <= row["width_m"] <= .1):
        raise ValueError(f"回零需要停止示教、静止及六轴健康使能：{st}")
    return row


def first_home_target(q, bounds):
    first = list(q)
    for i, (v, (lo, hi)) in enumerate(zip(q, bounds, strict=True)):
        if not lo <= 0 <= hi:
            raise ValueError(f"零目标不在 J{i+1} 当前限位内")
        if not lo <= v <= hi:
            # This is the measured zero-end recovery used on the real H. Every
            # transmitted target remains legal. It never changes a taught sample.
            near_j2 = i == 1 and lo == 0 and -math.radians(1) <= v < 0
            near_j3 = i == 2 and hi == 0 and 0 < v <= math.radians(1)
            if not (near_j2 or near_j3):
                raise ValueError(f"实测 J{i+1} 不在已验证回零起始范围内")
            first[i] = 0.
    return first


def home_waypoints(start, first, held, bounds, ctrl_mode, taught_start):
    """Choose the same ordered references for the geometry checker and the sender."""
    if start != first:
        return None  # Keep both sweeps for an initially out-of-bounds measurement.
    points = [first]
    if ctrl_mode != 1 and held != ZERO:
        if (taught_start is None or gap(held, taught_start) > .35 or gap(held, ZERO) > 5.
                or not all(lo <= v <= hi for v, (lo, hi) in zip(held, bounds, strict=True))):
            return None  # A different previous target still needs an independent sweep.
        if held != first:
            points.append(held)
    if points[-1] != ZERO:
        points.append(ZERO)
    return points


def clear_profile(heights, returning_home):
    threshold = .020
    if not isinstance(heights, list) or not heights or any(
            type(z) not in (float, int) or not math.isfinite(z) for z in heights):
        raise ValueError("缺少有效的离抓取位高度采样")
    if min(heights) > threshold:
        return True
    if not returning_home or not 0 < heights[0] < threshold or heights[-1] < threshold:
        return False
    for previous, current in zip(heights, heights[1:]):
        if previous < threshold:
            if current <= previous:
                return False
        elif current < threshold:
            return False
    return True


def check_sweep(run, request):
    save(run/"home_request.json", request)
    subprocess.run(["/usr/bin/python3", "-sB", str(HERE/"home_geometry.py"), str(run)],
                   env=dict(os.environ, OPENBLAS_NUM_THREADS="1"), check=True)
    route = read(run/"route_check.json")
    profiles = route["clearance_profiles_m"]
    expected = {"commanded"} if request["ctrl_mode"] == 1 or "home_waypoints_rad" in request else {"commanded", "previous_target"}
    returning_home = request.get("goal_q_rad", ZERO) == ZERO
    if (set(profiles) != expected or type(route["mesh_pairs"]) is not int or route["mesh_pairs"] <= 0
            or route["intersections"] != [] or not 0 <= route["max_fk_difference"] < 1e-4
            or not all(clear_profile(p, returning_home) for p in profiles.values())
            or any(p[0] != profiles["commanded"][0] for p in profiles.values())
            or min(min(p) for p in profiles.values()) != route["clearance_above_pick_m"]):
        raise ValueError(f"直达零位的实测起姿几何检查未通过，见 {run/'route_check.json'}")
    return route


def handoff_at_measured_pose(dev, rx, grip, sender, initial, start, first_target, report):
    """Use fresh mode acknowledgements; replace the prior arm target on CAN entry."""
    prior = int(initial["ctrl_mode"])
    for mode in {2: (0, 1), 0: (1,), 1: ()}[prior]:
        msg = dev.robot._MSG_ModeCtrl(ctrl_mode=mode, move_mode=1, move_spd_rate_ctrl=1)
        sender.call("handoff_mode", mode, lambda: dev.robot._send_msg(msg))
        sent = time.time()
        deadline = time.monotonic() + 2.
        stable_since = None
        anchored = False
        while time.monotonic() < deadline:
            row = snapshot(dev, rx, grip)
            status = row["arm"]
            issues = h0.calibration_driver_issues(dev, status, require_can=False)
            if issues or gap(row["q_rad"], start) > .5 or int(status["ctrl_mode"]) not in (prior, mode):
                raise RuntimeError(f"Unexpected state in control handoff: {status}, {issues}")
            fresh = dev.robot.get_arm_status().timestamp > sent and all(
                dev.robot.get_driver_states(j).timestamp > sent for j in range(1, 7))
            if fresh and int(status["ctrl_mode"]) == mode:
                if mode == 1 and not anchored:
                    sender.arm(first_target, "fresh_start_on_CAN_ack")
                    anchored = True
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= .3:
                    report.setdefault("mode_acknowledgements", []).append(mode)
                    break
            else:
                stable_since = None
            time.sleep(.01)
        else:
            raise RuntimeError(f"No sustained acknowledgement of controller mode {mode}")
        prior = mode


def ramp_joints(dev, rx, grip, sender, first, goal, width, speed, stop_requested, source):
    # Same smoothstep and 50 ms update used by the supervised SDK return.
    distance = gap(first, goal)
    seconds = max(1.5 * distance / speed, math.sqrt(6 * distance / 8))
    steps = max(1, math.ceil(seconds / .05))
    previous = first
    last = time.monotonic()
    for i in range(steps + 1):
        tick = time.monotonic()
        if tick - last > .15:
            raise RuntimeError("回零参考调度中断")
        last = tick
        row = healthy(dev, rx, grip, allow_disabled_gripper=True)
        if gap(row["q_rad"], previous) > 1. or abs(row["width_m"] - width) > .002:
            raise RuntimeError("回零跟踪或夹爪反馈异常")
        if stop_requested():
            # The first reference may not yet have been sent when we enter in CAN.
            sender.arm(previous, "operator_requested_reposition_hold")
            return previous, False
        u = i / steps
        weight = 1 - u*u*(3 - 2*u)
        target = [end + (v-end)*weight for v,end in zip(first,goal,strict=True)] if i < steps else goal
        sender.arm(target, source)
        previous = target
        time.sleep(max(0., .05 - (time.monotonic() - tick)))
    return previous, True
