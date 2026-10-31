"""Explicit virtual tool / camera adapter; never imports a hardware driver."""
import json
import os
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]


def configuration():
    path = os.environ.get('PIPER_SIM_CONFIG')
    if path:
        return json.loads(Path(path).read_text())
    return {'version': 'v2_quaternion_hemisphere_and_home_yaw', 'tool_frame_z_rad': 0.0,
            'home_qpos': json.loads((ROOT/'models/piper_h/home.json').read_text())['qpos'],
            'replan_steps': 5, 'gripper_state_scale': .8}


def policy_state(obs, converter, config):
    rotation = Rotation.from_quat(obs['robot0_eef_quat'])
    offset = config['tool_frame_z_rad']
    if offset:
        rotation = rotation * Rotation.from_euler('z', offset)
    quat = rotation.as_quat()
    if quat[0] < 0:
        quat = -quat
    return np.r_[obs['robot0_eef_pos'], converter(quat),
                 obs['robot0_gripper_qpos'] * config['gripper_state_scale']]
