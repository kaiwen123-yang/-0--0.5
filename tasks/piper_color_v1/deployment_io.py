"""Hardware-independent boundary for camera/robot integration and replay.

Nothing in this module connects to a camera, CAN bus, enables a motor, or sends
motion. SDK commands returned here are proposals for the local robot controller.
State units match pyAgxArm's public radian/metre interface, not legacy raw CAN units.
"""
import time
import numpy as np


def observation(*, joints_rad, opening_m, external_rgb, wrist_rgb, prompt,
                state_time, external_time, wrist_time, now=None):
    now = time.monotonic() if now is None else now
    stamps = np.asarray([state_time, external_time, wrist_time], dtype=float)
    if not np.isfinite(stamps).all() or (now-stamps).min() < 0 or (now-stamps).max() > .15:
        raise ValueError("Missing, stale or future observation timestamps")
    if abs(external_time-wrist_time) > .05:
        raise ValueError("RGB observations differ by more than 50 ms")
    state = np.r_[np.asarray(joints_rad, dtype=np.float32), opening_m]
    if state.shape != (7,) or not np.isfinite(state).all() or not 0 <= state[6] <= .101:
        raise ValueError("Expected 6 joint radians and measured gripper opening metres")
    for name, image in (("external", external_rgb), ("wrist", wrist_rgb)):
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(f"{name} image must be uint8 HWC RGB; convert BGR before calling")
    return dict(state=state.astype(np.float32), external_rgb=external_rgb, wrist_rgb=wrist_rgb, prompt=prompt)


def sdk_command_proposal(action):
    action = np.asarray(action, dtype=float)
    if action.shape != (7,) or not np.isfinite(action).all() or not -1e-6 <= action[6] <= .100001:
        raise ValueError("Invalid absolute joint / gripper action")
    return {"arm": {"method":"move_j", "joints_rad":action[:6].tolist()},
            "gripper": {"method":"move_gripper_m", "width_m":float(np.clip(action[6], 0, .1))},
            "sent":False,
            "note":"Local controller must enforce measured limits, motion rate and feedback freshness; simulation controller response is not hardware calibration."}
