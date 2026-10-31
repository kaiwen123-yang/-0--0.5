"""Fixed-checkpoint teacher-prefix and teacher-observation diagnostic probes."""
import argparse
import json
from pathlib import Path

import mujoco
import numpy as np
from diagnose_pi0_failures import DATA, SOURCE, arrays, describe, sample, save
from policy_client import PolicyClient
from sim import COLORS, ColorEnv

FAILURES = ((100, "red"), (100, "blue"), (101, "green"), (101, "blue"))


def demonstration(layout, color):
    source = DATA / "train" / f"layout_{layout:05d}_{color}.npz"
    with np.load(source, allow_pickle=False) as x:
        return {k: x[k].copy() for k in x.files}


def prefixes(policy, out, prefix_lengths=(85, 115), include_controls=True):
    out.mkdir(parents=True, exist_ok=False)
    env = ColorEnv(render=True)
    rows = []
    try:
        cases = [(layout, color, seed) for layout, color in FAILURES for seed in (42, 43)]
        if include_controls:
            cases += [(100, "green", 42), (101, "red", 42)]
        for prefix in prefix_lengths:
            for layout, color, base_seed in cases:
                d = demonstration(layout, color)
                env.reset(layout, color)
                for action in d["action"][:prefix]:
                    env.step(action)
                handoff = sample(env)
                episode_seed = base_seed + layout * 3 + COLORS.index(color)
                policy.reset_seed(episode_seed)
                observation = env.observe()
                # Match the original policy's sampling-key index at this control step.
                # These outputs are discarded; teacher actions remain the sole prefix.
                for _ in range(prefix // 5):
                    policy.infer(observation)
                samples, raw, commands = [], [], []
                stable_count, stable, error = 0, False, None
                try:
                    for step in range(prefix, 420, 5):
                        predicted = np.asarray(policy.infer(env.observe())["actions"])
                        if predicted.shape != (10, 7) or not np.isfinite(predicted).all():
                            raise ValueError("Invalid policy action")
                        for action in predicted[:min(5, 420 - step)]:
                            samples.append(sample(env)); raw.append(action.copy())
                            commands.append(env.step(action))
                            stable_count = stable_count + 1 if env.result()["success"] else 0
                            if stable_count >= 40:
                                stable = True
                                break
                            if env.max_joint_violation > .02:
                                raise RuntimeError("Measured joint-limit overshoot")
                        if stable:
                            break
                except Exception as exc:
                    error = repr(exc)
                trace = arrays(samples)
                result = {**env.result(), "success": bool(stable and error is None)}
                name = f"prefix{prefix}_{layout}_{color}_seed{base_seed}"
                row = {"name": name, "prefix": prefix, "layout": layout, "target": color,
                       "base_seed": base_seed, "episode_seed": episode_seed,
                       "teacher_prefix": True, "policy_success_rate_eligible": False,
                       "rng_advance_calls": prefix // 5, "error": error,
                       "handoff_state_max_difference": float(np.max(abs(handoff["state"] - d["state"][prefix]))),
                       "handoff_xy_offset_mm": float(np.linalg.norm(handoff["target_position"][:2] - handoff["tcp"][:2]) * 1000),
                       "handoff_normal_force_N": handoff["normal_force"].tolist(),
                       **describe(trace, result, np.asarray(raw), np.asarray(commands))}
                rows.append(row)
                save(out / f"{name}.json", row)
                np.savez_compressed(out / f"{name}.npz", **trace, raw_action=np.asarray(raw), executed_command=np.asarray(commands))
                save(out / "summary.json", {"episodes": rows, "intervention_only": True})
                print("PREFIX", name, "success", stable, "error", error, flush=True)
                if error:
                    raise RuntimeError(error)
    finally:
        env.close()


def fixed_observations(policy, out):
    out.mkdir(parents=True, exist_ok=False)
    env = ColorEnv(render=False)
    fk = mujoco.MjData(env.model)
    rows, predictions = [], {}
    try:
        for layout in (100, 101):
            for color in COLORS:
                d = demonstration(layout, color)
                env.reset(layout, color)
                for frame in (30, 50, 60, 70, 80, 95, 110, 130, 150, 165, 185, 210):
                    obs = {k: d[k][frame] for k in ("state", "external_rgb", "wrist_rgb")}
                    obs["prompt"] = str(d["prompt"])
                    truth = d["action"][np.minimum(np.arange(frame, frame + 10), len(d["action"]) - 1)]
                    for seed in (42, 43):
                        policy.reset_seed(seed + layout * 3 + COLORS.index(color))
                        pred = np.asarray(policy.infer(obs)["actions"])
                        targets = []
                        for sequence in (pred[:5], truth[:5]):
                            positions = []
                            for action in sequence:
                                fk.qpos[:] = env.data.qpos
                                fk.qpos[env.qadr] = action[:6]
                                mujoco.mj_forward(env.model, fk)
                                positions.append(fk.site_xpos[env.site].copy())
                            targets.append(np.asarray(positions))
                        row = {"layout": layout, "target": color, "frame": frame, "stage": str(d["stage"][frame]),
                               "base_seed": seed, "noise_reset_per_observation": True,
                               "first5_joint_mae_rad": float(np.mean(abs(pred[:5, :6] - truth[:5, :6]))),
                               "first5_width_mae_m": float(np.mean(abs(pred[:5, 6] - truth[:5, 6]))),
                               "pred_width_mean_m": float(pred[:5, 6].mean()), "teacher_width_mean_m": float(truth[:5, 6].mean()),
                               "target_fk_error_mean_mm": float(np.mean(np.linalg.norm(targets[0] - targets[1], axis=1)) * 1000),
                               "target_fk_xy_error_mean_mm": float(np.mean(np.linalg.norm((targets[0] - targets[1])[:, :2], axis=1)) * 1000)}
                        rows.append(row)
                        predictions[f"{layout}_{color}_{frame}_{seed}"] = pred
                save(out / "summary.json", {"observations": rows, "evaluation": "prediction on exact recorded teacher input; not a task success rate"})
                print("FIXED_OBSERVATIONS", layout, color, "observations", len(rows), flush=True)
        np.savez_compressed(out / "predictions.npz", **predictions)
    finally:
        env.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["prefix", "fixed"])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--port", type=int, default=18767)
    p.add_argument("--prefix-lengths", nargs="+", type=int, choices=[30, 60, 85, 115], default=[85, 115])
    p.add_argument("--failed-only", action="store_true")
    a = p.parse_args()
    policy = PolicyClient("127.0.0.1", a.port)
    expected = SOURCE / "checkpoints/pi0_piper_color_lora/six_demo_v1/2010"
    if Path(policy.metadata["checkpoint"]).resolve() != expected.resolve() or policy.metadata.get("model_family") != "pi0":
        raise ValueError("Unexpected model service")
    try:
        prefixes(policy, a.output, a.prefix_lengths, not a.failed_only) if a.stage == "prefix" else fixed_observations(policy, a.output)
    finally:
        policy.close()
