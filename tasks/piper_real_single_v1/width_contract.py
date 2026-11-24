"""Native Piper H SDK width, independent of pad clearance measurements."""
WIDTH = "piper_h_sdk_width_m_v1"
REPRESENTATION = "absolute_joint_targets_rad_and_sdk_width_m"
RETREAT = "post_release_retreat"
TERMINAL_VERSION = 1
CAMERA = "CC16762023M"


def require_width(record):
    if record.get("gripper_basis") != WIDTH:
        raise ValueError(f"Expected explicit gripper_basis={WIDTH}")


def require_setup(cfg):
    require_width(cfg)
    if (cfg.get("commissioning_only") is not False or cfg.get("split") not in ("train", "validation")
            or cfg.get("terminal_kind") != RETREAT or cfg.get("terminal_version") != TERMINAL_VERSION
            or not cfg.get("installation") or not cfg.get("pad_measurements")
            or (cfg.get("open_m"), cfg.get("close_m"), cfg.get("force_N")) != (.040, .015, 1.0)):
        raise ValueError("Missing verified Piper H setup, split, terminal or pad installation evidence")


def model_asset_id(spec):
    require_width(spec)
    if spec.get("camera_mount") != "wrist" or spec.get("action_horizon") != 10:
        raise ValueError("This contract uses the single wrist DC1 and ten-step chunks")
    return f"piper_h_wrist_{spec['model_family']}_{WIDTH}"
