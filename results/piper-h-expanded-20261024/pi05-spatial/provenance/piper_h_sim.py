"""Workspace-local Piper H / AgileX gripper registration for LIBERO + robosuite."""
from pathlib import Path
import json
import numpy as np
from robosuite.models.robots.manipulators.manipulator_model import ManipulatorModel
from robosuite.models.grippers.gripper_model import GripperModel
from robosuite.models.grippers import GRIPPER_MAPPING
from robosuite.robots import ROBOT_CLASS_MAPPING
from robosuite.robots.single_arm import SingleArm
from piper_adapter import configuration
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT / "models/piper_h"


class AgileXGripper(GripperModel):
    def __init__(self, idn=0):
        super().__init__(str(ASSETS / "gripper.xml"), idn=idn)
        self.current_action=np.array([1.0,-1.0])
        self.command_speed=configuration().get('gripper_command_speed',0.1)

    def format_action(self, action):
        assert len(action)==1
        self.current_action=np.clip(self.current_action+np.array([-1.0,1.0])*self.command_speed*np.sign(action),-1,1)
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
        offset=configuration()['tool_frame_z_rad']
        if offset:
            # The recording camera is unchanged. This virtual wrist mount follows
            # the policy's equivalent tool frame, not a calibrated physical mount.
            transform=Rotation.from_euler('z',offset)
            for camera in self.worldbody.iter('camera'):
                if camera.get('name','').endswith('eye_in_hand'):
                    pos=transform.apply(np.fromstring(camera.get('pos'),sep=' '))
                    quat=np.fromstring(camera.get('quat'),sep=' ')
                    quat=(transform*Rotation.from_quat(quat[[1,2,3,0]])).as_quat()[[3,0,1,2]]
                    camera.set('pos',' '.join(map(str,pos)))
                    camera.set('quat',' '.join(map(str,quat)))

    @property
    def default_mount(self): return None

    @property
    def default_gripper(self): return "AgileXGripper"

    @property
    def default_controller_config(self): return "default_panda"

    @property
    def init_qpos(self):
        return np.asarray(configuration()['home_qpos'])

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
