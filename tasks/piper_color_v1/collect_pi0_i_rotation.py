"""Three authorized recovery suffixes with smooth takeover rotation during lift.

Original collector/data are preserved. No autonomous policy or controller change.
"""
import collections
import time
from scipy.spatial.transform import Rotation, Slerp
import os
from pathlib import Path
import imageio.v2 as imageio
import numpy as np
from bct_common import ROOT, read, save, now
from diagnose_pi0_failures import sample, arrays
from sim import BOX, HALF, HZ
from sim_v2 import ColorEnvV2

TASK = "pi0-held-rotation-20261104"
RUN = ROOT / "outputs" / TASK
DATA = RUN / "dataset"

def compact_state(trace):
    return dict(tcp=trace["tcp"].tolist(), target_position=trace["target_position"].tolist(),
                target_lift_m=float(trace["target_position"][2]-HALF),
                normal_force_N=trace["normal_force"].tolist(),
                contact_count=trace["contact_count"].tolist(),
                measured_width_m=float(trace["state"][6]),
                commanded_width_m=float(trace["command_before"][6]),
                object_in_tcp_m=trace["object_in_tcp"].tolist())

def collect():
    started = time.monotonic()
    roster = read(RUN / "case_roster.json")
    DATA.mkdir(exist_ok=True)
    manifest = dict(started_at=now(), maximum_attempts=3, teacher_change="SO(3) interpolation from measured takeover rotation to original reset target over existing 30 lift frames using position smoothstep", attempts=[], accepted=[],
                    train_only=True, teacher_supervision_only=True, max_steps=420,
                    consecutive_success_required=40, hz=HZ, autonomous_episodes_added=0,
                    training_updates_added=0, complete=False)
    if (RUN / "manifest.json").exists():
        manifest = read(RUN / "manifest.json")
    save(RUN / "manifest.json", manifest)
    entries = read(DATA/"index.json") if (DATA/"index.json").exists() else []
    env = ColorEnvV2(render=True)
    try:
        for case in roster:
            name = f"recovery_{case['layout']:05d}_{case['target']}_seed{case['base_seed']}"
            stem = DATA / name
            if any(x["name"] == name for x in manifest["attempts"]):
                continue
            if stem.with_suffix(".json").exists():
                raise RuntimeError("Existing recovery attempt must not be rerun: " + name)
            frame = case["intervention_frame"]
            row = dict(case, name=name, attempted_at=now(), success=False, accepted=False,
                       teacher_intervention=True, autonomous_success_eligible=False,
                       trajectory=str(stem.with_suffix(".npz")), video=str(stem.with_suffix(".mp4")),
                       remaining_budget=420-frame, teacher_plan=[])
            manifest["active_attempt"] = name
            save(RUN / "manifest.json", manifest)
            env.reset(case["layout"], case["target"])
            observations, commands, timestamps, stages, traces, rotation_targets = [], [], [], [], [], []
            consecutive = 0
            full = False
            writer = imageio.get_writer(str(stem.with_suffix(".mp4")), fps=HZ, codec="libx264",
                quality=7, macro_block_size=1, output_params=["-threads", "2"])
            def record(command, stage, rotation_target=None):
                nonlocal consecutive, full
                if env.steps >= 420:
                    return False
                observations.append(env.observe())
                timestamps.append(float(env.data.time))
                traces.append(sample(env))
                rotation_targets.append(env.rotation.copy() if rotation_target is None else rotation_target.copy())
                writer.append_data(env.panorama())
                commands.append(env.step(command))
                stages.append(stage)
                consecutive = consecutive+1 if env.result()["success"] else 0
                full = consecutive >= 40
                return not full and env.steps < 420
            def move(stage, endpoint, width, n):
                start = env.data.site_xpos[env.site].copy()
                start_width = float(env.command[6])
                previous = env.state()[:6].copy()
                reset_rotation = env.rotation.copy()
                measured_rotation = env.data.site_xmat[env.site].reshape(3, 3).copy()
                rotation_path = Slerp([0., 1.], Rotation.from_matrix(np.stack([measured_rotation, reset_rotation]))) if stage == "lift" else None
                if rotation_path is not None:
                    row["rotation_transition"] = dict(stage=stage, frames=n, interpolation="shortest-path SLERP with t*t*(3-2*t)",
                        measured_start=measured_rotation.tolist(), reset_target=reset_rotation.tolist())
                row["teacher_plan"].append(dict(stage=stage, start_frame=env.steps,
                    endpoint=endpoint.tolist(), width=width, planned_frames=n))
                for j in range(n):
                    t = (j+1)/n
                    blend = t*t*(3-2*t)
                    rotation_target = rotation_path(blend).as_matrix() if rotation_path is not None else reset_rotation
                    env.rotation = rotation_target
                    try:
                        previous = env.ik(start+blend*(endpoint-start), previous)
                    finally:
                        env.rotation = reset_rotation
                    if not record(np.r_[previous,start_width+blend*(width-start_width)],stage,rotation_target):
                        return False
                return True
            try:
                with np.load(case["trajectory"], allow_pickle=False) as source:
                    for command in source["executed_command"][:frame]:
                        record(command, "policy_prefix")
                    # Record provenance of the actual takeover inside this attempt.
                    row["prefix_qpos_max_difference"] = float(abs(env.data.qpos-source["qpos"][frame]).max())
                    row["prefix_qvel_max_difference"] = float(abs(env.data.qvel-source["qvel"][frame]).max())
                    row["prefix_command_max_difference"] = float(abs(env.command-source["diagnostic_command_before"][frame]).max())
                takeover = sample(env)
                row["takeover"] = compact_state(takeover)
                row["takeover_clock_seconds"] = float(env.data.time)
                row["takeover_steps"] = env.steps
                row["held_at_takeover"] = bool((takeover["normal_force"]>.05).all() and
                    takeover["target_position"][2]-HALF>.05)
                row["bilateral_at_takeover"] = bool((takeover["normal_force"]>.05).all())
                # No reset, teleport, regrasp, force, or learned-policy rescue is used.
                if not row["bilateral_at_takeover"]:
                    raise ValueError("Selected actual takeover does not retain bilateral target contact")
                tcp = env.data.site_xpos[env.site].copy()
                running = True
                if tcp[2] < .16:
                    running = move("lift", np.r_[tcp[:2], .17], 0., 30)
                if running:
                    offset = env.positions()[env.target]-env.data.site_xpos[env.site]
                    endpoint = np.r_[BOX[:2]-offset[:2], .17]
                    running = move("transfer", endpoint, 0., 40)
                if running:
                    offset = env.positions()[env.target]-env.data.site_xpos[env.site]
                    endpoint = np.r_[BOX[:2]-offset[:2], .08]
                    running = move("lower", endpoint, 0., 26)
                if running:
                    endpoint = env.data.site_xpos[env.site].copy()
                    running = move("release", endpoint, .10, 20)
                if running:
                    endpoint = np.r_[env.data.site_xpos[env.site][:2], .17]
                    running = move("retreat", endpoint, .10, 30)
                while not full and env.steps < 420:
                    if not record(env.command.copy(), "settle"):
                        break
                row.update(success=bool(full), terminal=env.result(), steps=env.steps,
                           continuous_success_steps=consecutive)
                if full:
                    row["outcome_reason"] = "Teacher suffix completed original task conditions for 40 consecutive steps within total 420"
                else:
                    terminal = env.result()
                    causes = [k for k,v in [("target_not_in_box",not terminal["correct_in_box"]),
                        ("wrong_object_in_box",terminal["wrong_in_box"]),("gripper_not_open",not terminal["gripper_open"]),
                        ("distractor_displacement",max(terminal["distractor_displacement_m"].values())>=.025),
                        ("joint_limit_violation",terminal["max_joint_violation_rad"]>=.01)] if v]
                    row["outcome_reason"] = "Original 420-step budget exhausted: "+", ".join(causes or ["fewer_than_40_consecutive_success_steps"])
            except ValueError as exc:
                row.update(error=str(exc), outcome_reason=str(exc), terminal=env.result(),
                           steps=env.steps, continuous_success_steps=consecutive)
            finally:
                writer.close()
            row["teacher_frames"] = max(0, len(commands)-frame)
            row["stage_frames"] = dict(collections.Counter(stages[frame:]))
            row["accepted"] = row["success"]
            trace = arrays(traces)
            full_arrays = dict(state=np.stack([o["state"] for o in observations]),
                executed_command=np.asarray(commands), timestamp=np.asarray(timestamps), stage=np.asarray(stages),
                external_rgb=np.stack([o["external_rgb"] for o in observations]),
                wrist_rgb=np.stack([o["wrist_rgb"] for o in observations]),
                teacher_mask=np.arange(len(commands))>=frame, prompt=observations[0]["prompt"],
                teacher_rotation_target=np.stack(rotation_targets),
                final_qpos=env.data.qpos.copy(), final_qvel=env.data.qvel.copy(),
                final_physics_state=sample(env)["physics_state"])
            np.savez_compressed(stem.with_suffix(".npz"), **full_arrays,
                **{"diagnostic_"+k:v for k,v in trace.items()})
            if row["success"]:
                stem.mkdir()
                for field,source_field in [("state","state"),("action","executed_command"),
                        ("external_rgb","external_rgb"),("wrist_rgb","wrist_rgb"),("stage","stage"),
                        ("timestamp","timestamp")]:
                    values = full_arrays[source_field][frame:]
                    if field == "action":
                        values = values.astype(np.float32)
                    np.save(stem/(field+".npy"), values, allow_pickle=False)
                entries.append(dict(directory=name,frames=row["teacher_frames"],split="train",
                    layout_seed=case["layout"],target=case["target"],slot=case["slot"],
                    prompt=observations[0]["prompt"],source_trial=case["trajectory"],
                    intervention_frame=frame,stage_frames=row["stage_frames"],
                    supervision="teacher_suffix_only"))
                manifest["accepted"].append(name)
            save(stem.with_suffix(".json"),row)
            manifest["attempts"].append(row)
            manifest["accepted_count"]=len(entries)
            save(DATA/"index.json",entries)
            save(RUN/"manifest.json",manifest)
            print("RECOVERY", name, "takeover", frame, "success", row["success"],
                  "suffix",row["teacher_frames"],"steps",env.steps,flush=True)
    finally:
        env.close()
    manifest.update(complete=len(manifest["attempts"])==3, wall_seconds=time.monotonic()-started,finished_at=now(),active_attempt=None,
        attempted=len(manifest["attempts"]),accepted_count=len(entries),
        expert_frames=sum(x["frames"] for x in entries),
        stage_frames=dict(sum((collections.Counter(x["stage_frames"]) for x in entries),collections.Counter())))
    save(RUN/"manifest.json",manifest)
    print("RECOVERY_BATCH_FINISHED",manifest["attempted"],len(entries),manifest["expert_frames"],"complete",manifest["complete"],flush=True)

if __name__ == "__main__":
    collect()
