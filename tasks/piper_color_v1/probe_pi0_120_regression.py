"""Frozen-model action and teacher-prefix probes; no optimizer or test layouts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import mujoco
import numpy as np
from diagnose_pi0_failures import arrays, sample, describe
from policy_client import PolicyClient
from sim import COLORS, teacher
from sim_v2 import ColorEnvV2

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "outputs/pi0-120-demo-v2-20261101"
OUT = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"
FRAMES = (0, 10, 20, 30, 45, 55, 65, 75, 90, 105, 130, 165, 190, 230)
LAYOUTS = (100, 101, 1000, 1001, 1002, 1003, 1004)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def path_for(layout, color):
    if layout < 1000:
        return RUN / "dataset/train" / f"layout_{layout:05d}_{color}.npz"
    return OUT / "teacher_reference" / f"layout_{layout:05d}_{color}.npz"


def load_demo(layout, color):
    with np.load(path_for(layout, color), allow_pickle=False) as x:
        return {k: x[k].copy() for k in x.files}


def prepare():
    directory = OUT / "teacher_reference"
    directory.mkdir(exist_ok=False)
    env = ColorEnvV2(render=True)
    rows = []
    try:
        for layout in LAYOUTS:
            for color in COLORS:
                env.reset(layout, color)
                source = path_for(layout, color)
                if layout >= 1000:
                    result = teacher(env, source)
                    if not result["success"]:
                        raise RuntimeError(f"V2 validation teacher failed: {layout}/{color}")
                d = load_demo(layout, color)
                env.reset(layout, color)
                samples, errors = [], []
                for i, command in enumerate(d["executed_command"]):
                    samples.append(sample(env))
                    errors.append(float(np.max(abs(env.state() - d["state"][i]))))
                    env.step(command)
                stable = []
                for _ in range(40):
                    env.step(env.command)
                    stable.append(env.result()["success"])
                row = {"layout": layout, "target": color, "success": all(stable),
                       "max_replay_state_error": max(errors), "source": str(source),
                       "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "training_data_modified": False, "used_for_normalization": False}
                rows.append(row)
                if not row["success"] or max(errors) > 1e-6:
                    raise RuntimeError(f"Teacher replay mismatch: {row}")
                np.savez_compressed(directory / f"trace_{layout}_{color}.npz", **arrays(samples),
                                    executed_command=d["executed_command"], stage=d["stage"])
                save(directory / "summary.json", {"episodes": rows, "diagnostic_reference_only": True})
                print("TEACHER_REFERENCE", layout, color, row["success"], max(errors), flush=True)
    finally:
        env.close()


def fk_positions(env, fk, actions):
    positions = []
    for action in actions:
        fk.qpos[:] = env.data.qpos
        fk.qpos[env.qadr] = action[:6]
        mujoco.mj_forward(env.model, fk)
        positions.append(fk.site_xpos[env.site].copy())
    return np.asarray(positions)


def fixed(policy, label):
    out = OUT / "fixed" / label
    out.mkdir(parents=True, exist_ok=False)
    rows, prediction_arrays, prompt_rows = [], {}, []
    env = ColorEnvV2(render=False)
    fk = mujoco.MjData(env.model)
    try:
        for layout in LAYOUTS:
            demos = {color: load_demo(layout, color) for color in COLORS}
            for color, d in demos.items():
                env.reset(layout, color)
                for frame in FRAMES:
                    obs = {k: d[k][frame].copy() for k in ("state", "external_rgb", "wrist_rgb")}
                    obs["prompt"] = str(d["prompt"])
                    truth = d["action"][np.minimum(np.arange(frame, frame + 10), len(d["action"]) - 1)]
                    truth_fk = fk_positions(env, fk, truth[:5])
                    for seed in (42, 43):
                        policy.reset_seed(seed + layout * 3 + COLORS.index(color))
                        pred = np.asarray(policy.infer(obs)["actions"])
                        if pred.shape != (10, 7) or not np.isfinite(pred).all():
                            raise ValueError("Invalid prediction")
                        pred_fk = fk_positions(env, fk, pred[:5])
                        row = {"model": label, "layout": layout, "target": color, "frame": frame,
                               "stage": str(d["stage"][frame]), "base_seed": seed,
                               "split": "train" if layout < 1000 else "validation",
                               "joint_mae_rad": float(abs(pred[:5, :6] - truth[:5, :6]).mean()),
                               "width_mae_mm": float(abs(pred[:5, 6] - truth[:5, 6]).mean() * 1000),
                               "fk_xy_error_mm": float(np.linalg.norm((pred_fk - truth_fk)[:, :2], axis=1).mean() * 1000),
                               "fk_z_error_mm": float(abs(pred_fk[:, 2] - truth_fk[:, 2]).mean() * 1000),
                               "pred_width_mm": float(pred[:5, 6].mean() * 1000),
                               "teacher_width_mm": float(truth[:5, 6].mean() * 1000)}
                        rows.append(row)
                        prediction_arrays[f"{layout}_{color}_{frame}_{seed}"] = pred
                save(out / "observations.json", rows)
                print("FIXED", label, layout, color, len(rows), flush=True)
            # Exactly common RGB/state and RNG; only prompt changes.
            for key in ("state", "external_rgb", "wrist_rgb"):
                assert all(np.array_equal(demos["red"][key][0], demos[c][key][0]) for c in COLORS)
            env.reset(layout, "red")
            common = {k: demos["red"][k][0].copy() for k in ("state", "external_rgb", "wrist_rgb")}
            for seed in (42, 43):
                endpoints, targets = [], []
                for color in COLORS:
                    policy.reset_seed(seed + layout * 3)
                    pred = np.asarray(policy.infer({**common, "prompt": str(demos[color]["prompt"])})["actions"])
                    endpoints.append(fk_positions(env, fk, pred)[-1])
                    targets.append(fk_positions(env, fk, demos[color]["action"][:10])[-1])
                    prediction_arrays[f"prompt_swap_{layout}_{color}_{seed}"] = pred
                endpoints, targets = np.asarray(endpoints), np.asarray(targets)
                spread = lambda x: float(np.mean([np.linalg.norm(x[i, :2] - x[j, :2]) * 1000
                                         for i in range(3) for j in range(i + 1, 3)]))
                prompt_rows.append({"model": label, "layout": layout, "base_seed": seed,
                    "common_noise_seed": seed + layout * 3, "prompt_endpoint_xy_spread_mm": spread(endpoints),
                    "teacher_endpoint_xy_spread_mm": spread(targets), "endpoints": endpoints.tolist(),
                    "teacher_endpoints": targets.tolist(), "only_changed_input": "prompt"})
            save(out / "prompt_swap.json", prompt_rows)
        np.savez_compressed(out / "predictions.npz", **prediction_arrays)
        save(out / "protocol.json", {"policy": policy.metadata, "frames": FRAMES,
              "teacher_conditioned_only": True, "task_success_rate_eligible": False,
              "observation_count": len(rows), "common_prompt_swap_groups": len(prompt_rows)})
    finally:
        env.close()


def prefixes(policy, label, lengths):
    out = OUT / "prefix" / label
    out.mkdir(parents=True, exist_ok=False)
    cases = json.loads((OUT / "lost_success_cases.json").read_text())
    rows = []
    env = ColorEnvV2(render=True)
    try:
        for prefix in lengths:
            for case in cases:
                layout, color, seed = case["layout"], case["target"], case["base_seed"]
                d = load_demo(layout, color)
                env.reset(layout, color)
                for command in d["executed_command"][:prefix]:
                    env.step(command)
                handoff = sample(env)
                state_error = float(np.max(abs(handoff["state"] - d["state"][prefix])))
                if state_error > 1e-6:
                    raise RuntimeError("Prefix physical replay mismatch")
                policy.reset_seed(seed + layout * 3 + COLORS.index(color))
                obs = env.observe()
                for _ in range(prefix // 5):
                    policy.infer(obs)
                samples, commands, raw, object_positions = [], [], [], []
                consecutive, stable = 0, False
                for step in range(prefix, 420, 5):
                    pred = np.asarray(policy.infer(env.observe())["actions"])
                    if pred.shape != (10, 7) or not np.isfinite(pred).all():
                        raise RuntimeError("Invalid policy action")
                    for action in pred[:min(5, 420 - step)]:
                        samples.append(sample(env)); raw.append(action.copy())
                        object_positions.append(np.stack([env.positions()[c] for c in COLORS]))
                        commands.append(env.step(action))
                        consecutive = consecutive + 1 if env.result()["success"] else 0
                        if consecutive >= 40:
                            stable = True
                            break
                        if env.max_joint_violation > .02:
                            raise RuntimeError("Joint overshoot")
                    if stable:
                        break
                trace = arrays(samples)
                result = {**env.result(), "success": bool(stable)}
                row = {"model": label, "prefix": prefix, "layout": layout, "target": color, "base_seed": seed,
                    "teacher_intervention": True, "autonomous_success_rate_eligible": False,
                    "rng_advance_calls": prefix // 5, "handoff_state_max_error": state_error,
                    "handoff_xy_mm": float(np.linalg.norm(handoff["target_position"][:2] - handoff["tcp"][:2]) * 1000),
                    "handoff_normal_forces_N": handoff["normal_force"].tolist(),
                    **describe(trace, result, np.asarray(raw), np.asarray(commands))}
                rows.append(row)
                name = f"prefix{prefix}_{layout}_{color}_seed{seed}"
                save(out / f"{name}.json", row)
                np.savez_compressed(out / f"{name}.npz", **trace, raw_action=raw, executed_command=commands,
                                    object_positions=object_positions)
                save(out / "summary.json", {"episodes": rows, "expected": len(cases) * len(lengths),
                    "selection": "all 10 old-success/new-8040-failure paired validation trials", "intervention_only": True})
                print("PREFIX", label, prefix, layout, color, seed, stable, flush=True)
    finally:
        env.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["prepare", "fixed", "prefix"])
    p.add_argument("--label")
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--prefix-lengths", type=int, nargs="+", default=[30, 60, 85])
    a = p.parse_args()
    if a.stage == "prepare":
        prepare()
    else:
        policy = PolicyClient("127.0.0.1", 18767)
        if Path(policy.metadata["checkpoint"]).resolve() != a.checkpoint.resolve() or policy.metadata["model_family"] != "pi0":
            raise ValueError("Wrong checkpoint service")
        try:
            fixed(policy, a.label) if a.stage == "fixed" else prefixes(policy, a.label, a.prefix_lengths)
        finally:
            policy.close()
