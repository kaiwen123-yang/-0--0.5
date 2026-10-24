"""Piper H color pick/place benchmark. Physics only; no hardware imports.

The scripted demonstrator uses privileged object poses. Learned policies get only
two RGB images, measured joints / gripper width, and a language instruction.
Robot geometry / inertia are copied from the pinned official URDF conversion.
Camera poses and actuator response are simulation assumptions, not calibration.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET

os.environ.setdefault("MUJOCO_GL", "egl")
import imageio.v2 as imageio
import mujoco
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
COLORS = ("red", "green", "blue")
RGBA = ((.85, .035, .035, 1), (.035, .65, .065, 1), (.035, .08, .85, 1))
HOME = np.array([0, 1.4466463733, -1.2650348504, 0, 1.4764511809, -.35])
HZ = 20
DT = 1 / HZ
HALF = .0175
BOX = np.array([-.14, .16, .0])


def vector(x):
    return " ".join(str(float(v)) for v in x)


def camera(parent, name, position, target, fovy):
    pos, target = np.asarray(position), np.asarray(target)
    z = pos - target
    z /= np.linalg.norm(z)
    x = np.cross([0., 0., 1.], z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    ET.SubElement(parent, "camera", name=name, pos=vector(pos),
                  xyaxes=vector(np.r_[x, y]), fovy=str(fovy))


def scene_xml():
    source = HERE / "assets"
    if not (source / "robot.xml").exists():
        source = PROJECT / "models/piper_h"
    root = ET.parse(source / "robot.xml").getroot()
    grip = ET.parse(source / "gripper.xml").getroot()
    root.set("model", "piper_h_color_pick_v1")
    root.find("compiler").set("meshdir", str(source))
    ET.SubElement(root, "option", timestep="0.002", integrator="implicitfast",
                  cone="elliptic", iterations="60", gravity="0 0 -9.81")
    vis = ET.SubElement(root, "visual")
    ET.SubElement(vis, "global", offwidth="1280", offheight="720")
    ET.SubElement(vis, "quality", shadowsize="2048")
    ET.SubElement(vis, "headlight", ambient=".45 .45 .45", diffuse=".7 .7 .7", specular=".1 .1 .1")
    ET.SubElement(root.find("asset"), "texture", type="skybox", builtin="gradient", rgb1=".28 .34 .42", rgb2=".1 .14 .18", width="256", height="1536")
    world = root.find("worldbody")
    for c in list(world.findall("camera")):
        world.remove(c)
    base = world.find("body")
    base.set("pos", "-0.46 0 0")
    right_hand = root.find(".//body[@name='right_hand']")
    right_hand.append(copy.deepcopy(grip.find("worldbody/body")))
    for tag in ("asset", "actuator", "contact", "sensor", "equality"):
        src = grip.find(tag)
        if src is None:
            continue
        dst = root.find(tag)
        if dst is None:
            dst = ET.SubElement(root, tag)
        dst.extend(copy.deepcopy(list(src)))
    # Nominal virtual mount. Real DC1 mount transform must be calibrated later.
    flange = root.find(".//body[@name='flange_link']")
    flange.remove(flange.find("camera"))
    camera(flange, "wrist", [-.055, 0, .028], [0, 0, .125], 70)
    camera(world, "external", [.65, -.65, .75], [-.15, .02, .02], 43)
    camera(world, "panorama", [.75, 1., .85], [-.20, 0, .22], 48)
    ET.SubElement(world, "light", name="key", pos="0 -1 2", dir="0 0 -1", diffuse=".8 .8 .8")
    ET.SubElement(world, "light", name="fill", pos="-1 1 1.5", dir="0 0 -1", diffuse=".4 .4 .4")
    ET.SubElement(world, "geom", name="floor", type="plane", size="3 3 .1", pos="0 0 -.75", rgba=".19 .22 .25 1")
    ET.SubElement(world, "geom", name="table", type="box", size=".65 .45 .025", pos="-.10 0 -.025", rgba=".58 .52 .43 1", friction=".8 .01 .001")
    # Neutral open box: bottom and four real collision walls, no success weld.
    for name, offset, size in [
        ("bottom", [0, 0, .004], [.072, .064, .004]),
        ("left", [-.076, 0, .032], [.004, .072, .032]),
        ("right", [.076, 0, .032], [.004, .072, .032]),
        ("front", [0, -.068, .032], [.072, .004, .032]),
        ("back", [0, .068, .032], [.072, .004, .032]),
    ]:
        ET.SubElement(world, "geom", name=f"box_{name}", type="box", pos=vector(BOX + offset),
                      size=vector(size), rgba=".7 .72 .74 1", friction=".8 .01 .001")
    for color, rgba in zip(COLORS, RGBA, strict=True):
        body = ET.SubElement(world, "body", name=f"block_{color}", pos=f"-.2 0 {HALF+.001}")
        ET.SubElement(body, "freejoint", name=f"free_{color}")
        ET.SubElement(body, "geom", name=f"geom_{color}", type="box", size=vector([HALF]*3),
                      rgba=vector(rgba), mass=".055", friction="1 .01 .001", condim="4", solref=".008 1")
    return ET.tostring(root, encoding="unicode")


class ColorEnv:
    def __init__(self, render=False):
        self.model = mujoco.MjModel.from_xml_string(scene_xml())
        self.data = mujoco.MjData(self.model)
        self.ik_data = mujoco.MjData(self.model)
        self.qadr = np.array([self.model.jnt_qposadr[self.model.joint(f"joint{i}").id] for i in range(1, 7)])
        self.dadr = np.array([self.model.jnt_dofadr[self.model.joint(f"joint{i}").id] for i in range(1, 7)])
        self.limits = np.array([self.model.joint(f"joint{i}").range for i in range(1, 7)])
        self.gadr = np.array([self.model.jnt_qposadr[self.model.joint(f"gripper_joint{i}").id] for i in (1, 2)])
        self.site = self.model.site("grip_site").id
        self.mass = np.zeros((self.model.nv, self.model.nv))
        self.renderer = mujoco.Renderer(self.model, height=224, width=224) if render else None
        self.pan = None
        self.reset(0, "red")

    def reset(self, layout_seed, target_color):
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[self.qadr] = HOME
        self.data.qpos[self.gadr] = [.05, -.05]
        self.command = np.r_[HOME, .1]
        self.layout_seed = int(layout_seed)
        self.target = target_color
        rng = np.random.default_rng(layout_seed)
        # Same layout is repeated with all three language targets.
        slots = np.array([[-.235, -.15], [-.13, -.15], [-.205, -.035]])
        slots += rng.uniform(-.014, .014, size=(3, 2))
        permutation = rng.permutation(3)
        for i, color in enumerate(COLORS):
            a = self.model.jnt_qposadr[self.model.joint(f"free_{color}").id]
            self.data.qpos[a:a+3] = np.r_[slots[permutation[i]], HALF+.001]
            self.data.qpos[a+3:a+7] = [1, 0, 0, 0]
        mujoco.mj_forward(self.model, self.data)
        self.rotation = self.data.site_xmat[self.site].reshape(3, 3).copy()
        for _ in range(12):
            self.step(self.command)
        self.initial_positions = self.positions()
        self.max_joint_violation = 0.
        self.max_lift = {c: 0. for c in COLORS}
        self.steps = 0
        self.data.time = 0
        return self.observe() if self.renderer else self.state()

    def state(self):
        return np.r_[self.data.qpos[self.qadr], self.data.qpos[self.gadr[0]] - self.data.qpos[self.gadr[1]]].astype(np.float32)

    def positions(self):
        return {c: self.data.body(f"block_{c}").xpos.copy() for c in COLORS}

    def observe(self):
        images = {}
        for key, cam in (("external_rgb", "external"), ("wrist_rgb", "wrist")):
            self.renderer.update_scene(self.data, camera=cam)
            images[key] = self.renderer.render().copy()
        return dict(state=self.state(), **images,
                    prompt=f"pick up the {self.target} block and place it in the box")

    def panorama(self):
        if self.pan is None:
            self.pan = mujoco.Renderer(self.model, height=720, width=1280)
        self.pan.update_scene(self.data, camera="panorama")
        return self.pan.render().copy()

    def step(self, target):
        target = np.asarray(target, dtype=np.float64)
        if target.shape != (7,) or not np.isfinite(target).all():
            raise ValueError("Expected finite 7D absolute joint targets / width")
        target = np.clip(target, np.r_[self.limits[:, 0]+.004, 0], np.r_[self.limits[:, 1]-.004, .1])
        # Same execution envelope for teacher and learned policy; saved labels are
        # these actual targets, never substituted next-state measurements.
        self.command += np.clip(target-self.command, -np.r_[[.045]*6, .01], np.r_[[.045]*6, .01])
        for _ in range(25):
            q, dq = self.data.qpos[self.qadr], self.data.qvel[self.dadr]
            mujoco.mj_fullM(self.model, self.mass, self.data.qM)
            acceleration = 180 * (self.command[:6] - q) - 28 * dq
            torque = self.mass[np.ix_(self.dadr, self.dadr)] @ acceleration + self.data.qfrc_bias[self.dadr]
            self.data.ctrl[:6] = np.clip(torque, -80, 80)
            self.data.ctrl[6:] = [self.command[6]/2, -self.command[6]/2]
            mujoco.mj_step(self.model, self.data)
        if hasattr(self, "max_lift"):
            for c, pos in self.positions().items():
                self.max_lift[c] = max(self.max_lift[c], float(pos[2]-HALF))
            q = self.data.qpos[self.qadr]
            self.max_joint_violation = max(self.max_joint_violation, float(np.max(np.maximum(self.limits[:, 0]-q, q-self.limits[:, 1]))))
            self.steps += 1
        return self.command.copy()

    def ik(self, position, previous=None):
        self.ik_data.qpos[:] = self.data.qpos
        start = self.data.qpos[self.qadr].copy() if previous is None else previous.copy()
        def residual(q):
            self.ik_data.qpos[self.qadr] = q
            mujoco.mj_forward(self.model, self.ik_data)
            pos = self.ik_data.site_xpos[self.site]
            rot = self.ik_data.site_xmat[self.site].reshape(3, 3)
            angular = Rotation.from_matrix(self.rotation @ rot.T).as_rotvec()
            return np.r_[pos-position, .12*angular]
        sol = least_squares(residual, np.clip(start, self.limits[:,0]+.006, self.limits[:,1]-.006),
                            bounds=(self.limits[:,0]+.005, self.limits[:,1]-.005), max_nfev=160,
                            ftol=1e-9, xtol=1e-9, gtol=1e-9)
        error = residual(sol.x)
        if np.linalg.norm(error[:3]) > .003 or np.linalg.norm(error[3:]) > .006:
            raise ValueError(f"Unreachable teacher waypoint {position}: residual {error}")
        return sol.x

    def result(self):
        positions = self.positions()
        def in_box(p):
            return bool(abs(p[0]-BOX[0]) < .072-HALF and abs(p[1]-BOX[1]) < .064-HALF and .012 < p[2] < .05)
        correct = in_box(positions[self.target])
        wrong = any(in_box(positions[c]) for c in COLORS if c != self.target)
        moved = {c: float(np.linalg.norm(positions[c][:2]-self.initial_positions[c][:2])) for c in COLORS if c != self.target}
        return dict(layout_seed=self.layout_seed, target=self.target, correct_in_box=correct,
                    wrong_in_box=wrong, gripper_open=bool(self.state()[6] > .08),
                    distractor_displacement_m=moved, max_lift_m=self.max_lift,
                    max_joint_violation_rad=self.max_joint_violation,
                    success=bool(correct and not wrong and self.state()[6] > .08 and max(moved.values()) < .025
                                 and self.max_joint_violation < .01),
                    final_positions={k:v.tolist() for k,v in positions.items()}, steps=self.steps)

    def close(self):
        if self.renderer:
            self.renderer.close()
        if self.pan:
            self.pan.close()


def teacher(env, output=None, video=None, trace=False):
    """Cartesian waypoint IK expert; no teleport, attachment, or object force."""
    pos = env.positions()[env.target].copy()
    rows, stages = [], []
    writer = imageio.get_writer(str(video), fps=HZ, codec="libx264", quality=7, macro_block_size=1) if video else None
    plan = [
        ("approach", np.r_[pos[:2], .17], .10, 1.5),
        ("descend", np.r_[pos[:2], .020], .10, 1.6),
        ("grasp", np.r_[pos[:2], .020], .0, 1.0),
        ("lift", np.r_[pos[:2], .17], .0, 1.5),
        ("transfer", BOX+np.array([0, 0, .17]), .0, 2.0),
        ("lower", BOX+np.array([0, 0, .08]), .0, 1.3),
        ("release", BOX+np.array([0, 0, .08]), .10, 1.0),
        ("retreat", BOX+np.array([0, 0, .17]), .10, 1.5),
        ("settle", BOX+np.array([0, 0, .17]), .10, 2.0),
    ]
    previous = env.state()[:6].copy()
    for name, endpoint, width, seconds in plan:
        start = env.data.site_xpos[env.site].copy()
        start_width = env.command[6]
        n = int(seconds*HZ)
        for j in range(n):
            t = (j+1)/n
            blend = t*t*(3-2*t)
            waypoint = start + blend*(endpoint-start)
            previous = env.ik(waypoint, previous)
            obs = env.observe() if output else None
            if writer:
                writer.append_data(env.panorama())
            timestamp = float(env.data.time)
            command = env.step(np.r_[previous, start_width+blend*(width-start_width)])
            if obs is not None:
                rows.append((obs, command, timestamp))
                stages.append(name)
        if trace:
            print(name, "tcp", env.data.site_xpos[env.site].round(4).tolist(), "objects", {c:p.round(4).tolist() for c,p in env.positions().items()}, "width", round(float(env.state()[6]),4), flush=True)
    # Success must stay true throughout a further hold, separate from training frames.
    stable = []
    for _ in range(40):
        if writer:
            writer.append_data(env.panorama())
        env.step(env.command)
        stable.append(env.result()["success"])
    result = env.result()
    result["stable_2s"] = all(stable)
    result["success"] = result["success"] and result["stable_2s"]
    result["source"] = "scripted_ik_simulation_teacher"
    result["privileged_object_poses"] = True
    result["hardware_execution"] = False
    if writer:
        writer.close()
    if output:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(output, state=np.stack([r[0]["state"] for r in rows]),
                            action=np.stack([r[1] for r in rows]).astype(np.float32),
                            external_rgb=np.stack([r[0]["external_rgb"] for r in rows]),
                            wrist_rgb=np.stack([r[0]["wrist_rgb"] for r in rows]),
                            timestamp=np.array([r[2] for r in rows]),
                            stage=np.array(stages), prompt=rows[0][0]["prompt"],
                            layout_seed=env.layout_seed, target=env.target)
        output.with_suffix(".json").write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--target", choices=COLORS, default="red")
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--record-data", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    env = ColorEnv(render=args.record_data)
    env.reset(args.seed, args.target)
    (args.output / "scene.xml").write_text(scene_xml())
    result = teacher(env, args.output / "episode.npz" if args.record_data else None,
                     args.output / "panorama.mp4" if args.video else None, trace=True)
    (args.output / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    env.close()


if __name__ == "__main__":
    main()
