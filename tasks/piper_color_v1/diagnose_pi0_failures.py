"""Replay real Pi0 trajectories and teacher actions; diagnostics never train."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import time

import mujoco
import numpy as np
from sim import BOX, COLORS, HALF, ColorEnv

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs/pi0-six-demo-20261031"
DATA = ROOT / "results/piper-color-v1/dataset-v1"
STATE_SPEC = mujoco.mjtState.mjSTATE_INTEGRATION


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sample(env):
    target = env.positions()[env.target]
    tcp = env.data.site_xpos[env.site].copy()
    rotation = env.data.site_xmat[env.site].reshape(3, 3).copy()
    target_geom = env.model.geom(f"geom_{env.target}").id
    finger_geoms = [env.model.geom(f"gripper_link{i}_collision").id for i in (1, 2)]
    normal, tangent, counts = np.zeros(2), np.zeros(2), np.zeros(2, dtype=int)
    for k in range(env.data.ncon):
        contact = env.data.contact[k]
        pair = (int(contact.geom1), int(contact.geom2))
        if target_geom not in pair:
            continue
        for i, finger in enumerate(finger_geoms):
            if finger in pair:
                wrench = np.empty(6)
                mujoco.mj_contactForce(env.model, env.data, k, wrench)
                normal[i] += max(0.0, wrench[0])
                tangent[i] += float(np.linalg.norm(wrench[1:3]))
                counts[i] += 1
    integration = np.empty(mujoco.mj_stateSize(env.model, STATE_SPEC))
    mujoco.mj_getState(env.model, env.data, integration, STATE_SPEC)
    return dict(state=env.state(), qpos=env.data.qpos.copy(), qvel=env.data.qvel.copy(),
                tcp=tcp, target_position=target, tcp_rotation=rotation,
                object_in_tcp=rotation.T @ (target - tcp),
                normal_force=normal, tangential_force=tangent, contact_count=counts,
                orientation_error_deg=np.degrees(np.arccos(np.clip((np.trace(env.rotation.T @ rotation) - 1) / 2, -1, 1))),
                command_before=env.command.copy(), physics_state=integration)


def arrays(samples):
    return {key: np.asarray([row[key] for row in samples]) for key in samples[0]}


def describe(trace, result, raw, commands):
    pos, tcp = trace["target_position"], trace["tcp"]
    lift = pos[:, 2] - HALF
    high = np.flatnonzero(lift > .05)
    bilateral = (trace["normal_force"] > .05).all(axis=1)
    held = np.flatnonzero((lift > .05) & bilateral)
    above = (abs(pos[:, 0] - BOX[0]) < .072 - HALF) & (abs(pos[:, 1] - BOX[1]) < .064 - HALF)
    peak = int(lift.argmax())
    floor = np.flatnonzero((np.arange(len(lift)) > peak) & (lift < .01)) if len(high) else np.array([], dtype=int)
    drop = int(floor[0]) if len(floor) and not above.any() else None
    closest = int(np.argmin(np.linalg.norm(tcp[:, :2] - pos[:, :2], axis=1) + 2 * np.maximum(tcp[:, 2] - .06, 0)))
    relevant = held[:1].tolist() if len(held) else [closest]
    approach = relevant[0]
    tail = slice(drop, None) if drop is not None else slice(0, 0)
    reapproach = ((np.linalg.norm(tcp[tail, :2] - pos[tail, :2], axis=1) < .04) &
                  (tcp[tail, 2] < .06) & (trace["state"][tail, 6] > .06))
    return dict(success=result["success"], max_lift_cm=float(lift.max() * 100),
                first_lifted_frame=int(high[0]) if len(high) else None,
                first_bilateral_lift_frame=int(held[0]) if len(held) else None,
                over_box_frames=int(above.sum()), drop_frame=drop,
                bilateral_contact_frames=int(bilateral.sum()),
                approach_reference_frame=approach,
                approach_xy_offset_mm=float(np.linalg.norm(tcp[approach, :2] - pos[approach, :2]) * 1000),
                approach_object_in_tcp_mm=(trace["object_in_tcp"][approach] * 1000).tolist(),
                approach_orientation_error_deg=float(trace["orientation_error_deg"][approach]),
                normal_force_at_reference_N=trace["normal_force"][approach].tolist(),
                gripper_width_at_reference_m=float(trace["state"][approach, 6]),
                raw_to_executed_joint_mae_rad=float(np.mean(abs(raw[:, :6] - commands[:, :6]))),
                command_tracking_joint_mae_rad=float(np.mean(abs(commands[:, :6] - trace["state"][:, :6]))),
                gripper_open_command_frames_before_drop=int(np.sum(commands[approach:drop, 6] > .04)) if drop else None,
                open_low_reapproach_frames_after_drop=int(reapproach.sum()) if drop is not None else None,
                terminal=result)


def replay(out):
    out.mkdir(parents=True, exist_ok=False)
    env = ColorEnv(render=False)
    rows = []
    try:
        for source_type in ("teacher", "policy42", "policy43"):
            for layout in (100, 101):
                for color in COLORS:
                    env.reset(layout, color)
                    name = f"{source_type}_{layout}_{color}"
                    if source_type == "teacher":
                        source = DATA / "train" / f"layout_{layout:05d}_{color}.npz"
                        with np.load(source, allow_pickle=False) as x:
                            commands = np.concatenate([x["action"], np.repeat(x["action"][-1:], 40, axis=0)])
                            raw = commands.copy()
                            reference = x["state"].copy()
                        original = None
                    else:
                        folder = SOURCE / "evaluations" / f"eval_2010_seed{source_type[-2:]}"
                        source = folder / f"layout_{layout:05d}_{color}.npz"
                        original = json.loads(source.with_suffix(".json").read_text())
                        with np.load(source, allow_pickle=False) as x:
                            commands, raw, reference = x["executed_command"].copy(), x["raw_action"].copy(), x["qpos"].copy()
                    samples, differences = [], []
                    stable_count, ever_stable = 0, False
                    for step, command in enumerate(commands):
                        samples.append(sample(env))
                        if step < len(reference):
                            current = env.state() if source_type == "teacher" else env.data.qpos
                            differences.append(float(np.max(abs(current - reference[step]))))
                        env.step(command)
                        stable_count = stable_count + 1 if env.result()["success"] else 0
                        ever_stable = ever_stable or stable_count >= 40
                    trace = arrays(samples)
                    result = {**env.result(), "success": bool(ever_stable)}
                    row = {"name": name, "source_type": source_type, "layout": layout, "target": color,
                           "source": str(source), "source_sha256": fingerprint(source),
                           "max_replay_state_difference": max(differences),
                           "original_success": original["success"] if original else True,
                           **describe(trace, result, raw, commands)}
                    # Teacher labels were saved as float32 from float64 IK commands;
                    # contact-sensitive trajectories need not be bitwise identical.
                    # Retain their numeric differences and judge physical feasibility.
                    # Policy commands were saved in full precision and must replay closely.
                    row["replay_state_match_required"] = source_type != "teacher"
                    row["reproduced"] = row["success"] == row["original_success"] and (
                        source_type == "teacher" or max(differences) < 1e-5)
                    np.savez_compressed(out / f"{name}.npz", **trace, raw_action=raw, executed_command=commands)
                    save(out / f"{name}.json", row)
                    rows.append(row)
                    save(out / "summary.json", {"episodes": rows, "all_reproduced": all(r["reproduced"] for r in rows),
                                               "teacher_successes": sum(r["success"] for r in rows if r["source_type"] == "teacher")})
                    print("REPLAY", name, "success", row["success"], "reproduced", row["reproduced"],
                          "offset_mm", round(row["approach_xy_offset_mm"], 2), "drop", row["drop_frame"], flush=True)
                    if not row["reproduced"]:
                        raise RuntimeError(f"Replay differs from the stored trajectory: {name}")
    finally:
        env.close()


def physics_probes(replay_dir, out):
    """Keep the exact acquired grasp; change subsequent motion or contact friction."""
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    for source_row in json.loads((replay_dir / "summary.json").read_text())["episodes"]:
        start = source_row["first_bilateral_lift_frame"]
        if start is None:
            continue
        with np.load(replay_dir / f"{source_row['name']}.npz", allow_pickle=False) as x:
            commands = x["executed_command"].copy()
        for mode in ("recorded_motion", "hold_pose_3s", "double_friction"):
            env = ColorEnv(render=False)
            try:
                env.reset(source_row["layout"], source_row["target"])
                for command in commands[:start]:
                    env.step(command)
                if mode == "double_friction":
                    for name in (f"geom_{env.target}", "gripper_link1_collision", "gripper_link2_collision"):
                        env.model.geom_friction[env.model.geom(name).id, 0] *= 2
                hold = np.r_[env.state()[:6], 0.0]
                sequence = np.repeat(hold[None], 60, axis=0) if mode == "hold_pose_3s" else commands[start:]
                samples = []
                stable_count, stable = 0, False
                for command in sequence:
                    samples.append(sample(env))
                    env.step(command)
                    stable_count = stable_count + 1 if env.result()["success"] else 0
                    stable = stable or stable_count >= 40
                trace = arrays(samples)
                row = {"source": source_row["name"], "mode": mode, "start_frame": start,
                       "diagnostic_intervention": mode != "recorded_motion", "autonomous_success_eligible": False,
                       "target_height_at_end_m": float(env.positions()[env.target][2] - HALF),
                       "held_5cm_at_end": bool(env.positions()[env.target][2] - HALF > .05),
                       "full_task_conditions_observed": stable,
                       "bilateral_contact_fraction": float(np.mean((trace["normal_force"] > .05).all(axis=1))),
                       "object_in_tcp_start_mm": (trace["object_in_tcp"][0] * 1000).tolist(),
                       "object_in_tcp_end_mm": (trace["object_in_tcp"][-1] * 1000).tolist()}
                rows.append(row)
                save(out / "summary.json", {"probes": rows})
                print("PHYSICS_PROBE", source_row["name"], mode, row["held_5cm_at_end"],
                      "full_conditions", stable, flush=True)
            finally:
                env.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["replay", "physics"])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--replay", type=Path)
    a = p.parse_args()
    if a.stage == "replay":
        replay(a.output)
    else:
        physics_probes(a.replay, a.output)
