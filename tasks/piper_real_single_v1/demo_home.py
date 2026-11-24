"""Piper H direct MOVE_J return to six-axis zero, independent of task actions."""
import math
import time

from demo_io import gap, h0, healthy, snapshot


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
    for i, (v, (lo, hi)) in enumerate(zip(q, bounds, strict=True)):
        if not lo <= 0 <= hi:
            raise ValueError(f"零目标不在 J{i+1} 控制器回读范围内")
        if not lo <= v <= hi:
            raise ValueError(f"实测 J{i+1} 在控制器回读范围外；保留原值")
    return list(q)


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


def ramp_joints(dev, rx, grip, sender, first, goal, width, speed, stop_requested, source,
                *, profile="smoothstep"):
    # One joint-space segment, sampled every 50 ms; speed is degrees/second.
    distance = gap(first, goal)
    if profile == "trapezoid":
        acceleration = 8.
        acceleration_time = min(speed / acceleration, math.sqrt(distance / acceleration))
        peak_speed = acceleration * acceleration_time
        cruise_time = max(0., distance / speed - speed / acceleration)
        seconds = 2 * acceleration_time + cruise_time
    else:
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
        if profile == "trapezoid":
            elapsed = seconds * u
            if elapsed <= acceleration_time:
                travelled = .5 * acceleration * elapsed * elapsed
            elif elapsed >= seconds - acceleration_time:
                travelled = distance - .5 * acceleration * (seconds - elapsed)**2
            else:
                travelled = .5 * acceleration * acceleration_time**2 + peak_speed * (elapsed - acceleration_time)
            weight = 1 - travelled / distance if distance else 0.
        else:
            weight = 1 - u*u*(3 - 2*u)
        target = [end + (v-end)*weight for v,end in zip(first,goal,strict=True)] if i < steps else goal
        sender.arm(target, source)
        previous = target
        time.sleep(max(0., .05 - (time.monotonic() - tick)))
    return previous, True

