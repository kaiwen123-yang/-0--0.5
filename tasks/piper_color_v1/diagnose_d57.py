"""Task-level diagnoses for the fixed color checkpoint; never trains a policy.

Teacher replay and teacher-prefix interventions are explicitly separate from
policy evaluation. All probes use training/validation layouts, never test data.
"""
import argparse
import json
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from policy_client import PolicyClient
from sim import COLORS, ColorEnv, HZ


def episode(data, split, seed, color):
    stem = data / split / f"layout_{seed:05d}_{color}"
    with np.load(stem.with_suffix(".npz"), allow_pickle=False) as d:
        extra = {k: d[k].copy() for k in ("stage", "prompt")}
    return {**extra, **{k: np.load(stem / f"{k}.npy", mmap_mode="r")
                        for k in ("state", "action", "external_rgb", "wrist_rgb")}}


def replay(data, out):
    env = ColorEnv(render=True)
    rows = []
    try:
        for split, seed in (("train", 100), ("validation", 1000)):
            for color in COLORS:
                d = episode(data, split, seed, color)
                env.reset(seed, color)
                errors, pixels = [], []
                for frame, action in enumerate(d["action"]):
                    errors.append(env.state()-d["state"][frame])
                    if frame in (0, 95, 185, 245):
                        obs = env.observe()
                        pixels.append({"frame": frame, **{
                            key: float(np.mean(abs(obs[key].astype(float)-d[key][frame].astype(float))))
                            for key in ("external_rgb", "wrist_rgb")}})
                    env.step(action)
                stable = []
                for _ in range(40):
                    env.step(env.command)
                    stable.append(env.result()["success"])
                row = dict(split=split, seed=seed, color=color, teacher_replay=True,
                           success=bool(all(stable)), state_max_abs=float(abs(np.asarray(errors)).max()),
                           state_mean_abs=float(abs(np.asarray(errors)).mean()), pixel_mae_255=pixels,
                           result=env.result())
                rows.append(row)
                (out / "teacher_replay.json").write_text(json.dumps(rows, indent=2))
                print("TEACHER_REPLAY", split, color, row["success"], row["state_max_abs"], flush=True)
    finally:
        env.close()


def frozen_observations(data, recovery, out, policy):
    frames = [15, 45, 70, 95, 125, 160, 185, 210, 245]
    old = np.load(recovery / "offline-diagnostic/predictions.npz")
    policy.reset_seed(0)  # Original offline script uses the upstream default key(0).
    rows, arrays = [], {}
    for split, seed in (("train", 100), ("validation", 1000)):
        for color in COLORS:
            d = episode(data, split, seed, color)
            for frame in frames:
                obs = {k: d[k][frame].copy() for k in ("state", "external_rgb", "wrist_rgb")}
                obs["prompt"] = str(d["prompt"])
                pred = np.asarray(policy.infer(obs)["actions"])
                truth = d["action"][np.minimum(np.arange(frame, frame+10), len(d["action"])-1)]
                key = f"{split}_{seed}_{color}_{frame}"
                prior = old[key+"_pred"]
                row = dict(split=split, seed=seed, color=color, frame=frame, stage=str(d["stage"][frame]),
                           joint_mae_rad=float(abs(pred[:, :6]-truth[:, :6]).mean()),
                           width_mae_m=float(abs(pred[:, 6]-truth[:, 6]).mean()),
                           width_pred_mean_m=float(pred[:, 6].mean()), width_truth_mean_m=float(truth[:, 6].mean()),
                           old_prediction_joint_mae_rad=float(abs(pred[:, :6]-prior[:, :6]).mean()),
                           old_prediction_width_mae_m=float(abs(pred[:, 6]-prior[:, 6]).mean()),
                           old_prediction_max_abs=float(abs(pred-prior).max()))
                rows.append(row); arrays[key+"_pred"] = pred
    (out / "frozen_observations.json").write_text(json.dumps(rows, indent=2))
    np.savez_compressed(out / "frozen_predictions.npz", **arrays)
    old.close()
    print("FROZEN_OBSERVATIONS", len(rows), "old max diff", max(x["old_prediction_max_abs"] for x in rows), flush=True)


def prefix_interventions(data, out, policy):
    env = ColorEnv(render=True)
    rows = []
    try:
        for prefix in (112, 178):
            for color in COLORS:
                seed = 1000
                d = episode(data, "validation", seed, color)
                env.reset(seed, color)
                stem = out / f"teacher_prefix_{prefix}_{color}"
                writer = imageio.get_writer(str(stem.with_suffix(".mp4")), fps=HZ,
                    codec="libx264", quality=7, macro_block_size=1, output_params=["-threads", "2"])
                for action in d["action"][:prefix]:
                    writer.append_data(env.panorama()); env.step(action)
                prefix_state_error = float(abs(env.state()-d["state"][prefix]).max())
                policy.reset_seed(42)
                consecutive, stable, error = 0, False, None
                states, commands, raw, poses = [], [], [], []
                try:
                    for step in range(prefix, 420, 5):
                        actions = np.asarray(policy.infer(env.observe())["actions"])
                        if actions.shape != (10, 7) or not np.isfinite(actions).all():
                            raise ValueError("Invalid policy output")
                        for action in actions[:min(5, 420-step)]:
                            writer.append_data(env.panorama())
                            states.append(env.state()); raw.append(action.copy())
                            commands.append(env.step(action)); poses.append(env.data.site_xpos[env.site].copy())
                            consecutive = consecutive+1 if env.result()["success"] else 0
                            if consecutive >= 40:
                                stable = True; break
                            if env.max_joint_violation > .02:
                                raise RuntimeError("Joint limit overshoot > 0.02 rad")
                        if stable: break
                except Exception as exc:
                    error = repr(exc)
                finally:
                    writer.close()
                row = dict(prefix_steps=prefix, seed=seed, color=color, success=bool(stable and error is None),
                           error=error, prefix_state_max_abs=prefix_state_error, result=env.result(),
                           teacher_prefix=True, policy_success_rate_eligible=False,
                           note="Video begins with recorded teacher commands; intervention, not unassisted policy evaluation")
                rows.append(row)
                stem.with_suffix(".json").write_text(json.dumps(row, indent=2))
                np.savez_compressed(stem.with_suffix(".npz"), state=np.asarray(states),
                                    command=np.asarray(commands), raw_action=np.asarray(raw), tcp=np.asarray(poses))
                (out / "prefix_interventions.json").write_text(json.dumps(rows, indent=2))
                print("TEACHER_PREFIX", prefix, color, row["success"], error, flush=True)
                if error: raise RuntimeError(error)
    finally:
        env.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--recovery", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--port", type=int, default=18765)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    replay(a.data, a.output)
    policy = PolicyClient("127.0.0.1", a.port)
    try:
        (a.output / "policy.json").write_text(json.dumps(policy.metadata, indent=2))
        frozen_observations(a.data, a.recovery, a.output, policy)
        prefix_interventions(a.data, a.output, policy)
    finally:
        policy.close()
