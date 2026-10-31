"""Workspace-local Piper H / AgileX gripper registration for LIBERO + robosuite."""
from pathlib import Path
import json
import numpy as np
from robosuite.models.robots.manipulators.manipulator_model import ManipulatorModel
from robosuite.models.grippers.gripper_model import GripperModel
from robosuite.models.grippers import GRIPPER_MAPPING
from robosuite.robots import ROBOT_CLASS_MAPPING
from robosuite.robots.single_arm import SingleArm

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT / "models/piper_h"


class AgileXGripper(GripperModel):
    def __init__(self, idn=0):
        super().__init__(str(ASSETS / "gripper.xml"), idn=idn)
        self.current_action=np.array([1.0,-1.0])

    def format_action(self, action):
        assert len(action)==1
        self.current_action=np.clip(self.current_action+np.array([-1.0,1.0])*0.1*np.sign(action),-1,1)
        return self.current_action

    @property
    def dof(self): return 1

    @property
    def init_qpos(self): return np.array([0.05,-0.05])

    @property
    def _important_geoms(self):
        return {"left_finger":["gripper_link1_collision"], "right_finger":["gripper_link2_collision"],
                "left_fingerpad":["gripper_link1_collision"],"right_fingerpad":["gripper_link2_collision"]}


class MountedPiperH(ManipulatorModel):
    def __init__(self, idn=0):
        super().__init__(str(ASSETS / "robot.xml"),idn=idn)

    @property
    def default_mount(self): return None

    @property
    def default_gripper(self): return "AgileXGripper"

    @property
    def default_controller_config(self): return "default_panda"

    @property
    def init_qpos(self):
        home=ASSETS / "home.json"
        if home.exists(): return np.array(json.loads(home.read_text())["qpos"])
        return np.array([0,1.0,-1.0,0,1.0,0])

    @property
    def base_xpos_offset(self):
        return {"table":lambda table_length:(-table_length/2+0.04,0,0.90),
                "kitchen_table":lambda table_length:(-table_length/2+0.04,0,0.90),
                "empty":(-0.46,0,0.90)}

    @property
    def top_offset(self): return np.array([0,0,0.8])

    @property
    def _horizontal_radius(self): return 0.7

    @property
    def arm_type(self): return "single"


GRIPPER_MAPPING["AgileXGripper"]=AgileXGripper
ROBOT_CLASS_MAPPING["MountedPiperH"]=SingleArm
