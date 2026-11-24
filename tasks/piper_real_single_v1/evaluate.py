"""Evaluate retained full-training checkpoints on the frozen V01 demonstrations.

Run after training, in the same family's existing OpenPI environment:
  python -m tasks.piper_real_single_v1.evaluate --spec actual.json

This is open-loop imitation evaluation, not a robot success rate. No CAN sender,
norm fitting, optimizer update, or training-data gradient is involved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from .dataset import SingleCameraDataset
from .width_contract import model_asset_id


# Descriptive evaluation strata, not collection limits or data exclusion rules.
MOVING_JOINT_DEG = 0.5
MOVING_GRIPPER_MM = 1.0


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def errors_summary(error, scale):
    joints = np.rad2deg(error[..., :6])
    gripper = error[..., 6] * 1000
    return {
        "joint_mae_deg": float(np.abs(joints).mean()),
        "joint_rmse_deg": float(np.sqrt(np.square(joints).mean())),
        "per_joint_mae_deg": np.abs(joints).mean(axis=(0, 1)).tolist(),
        "gripper_mae_mm": float(np.abs(gripper).mean()),
        "gripper_rmse_mm": float(np.sqrt(np.square(gripper).mean())),
        "first_step_joint_mae_deg": float(np.abs(joints[:, 0]).mean()),
        "first_step_gripper_mae_mm": float(np.abs(gripper[:, 0]).mean()),
        "last_step_joint_mae_deg": float(np.abs(joints[:, -1]).mean()),
        "last_step_gripper_mae_mm": float(np.abs(gripper[:, -1]).mean()),
        "normalized_mse7": float(np.square(error * scale).mean()),
    }


def episode_metrics(predicted, target, state, moving, scale):
    groups = {}
    for group, mask in (("all", np.ones(len(moving), dtype=bool)),
                        ("moving", moving), ("low_motion", ~moving)):
        groups[group] = None if not mask.any() else {
            "sampled_windows": int(mask.sum()),
            "model": errors_summary((predicted - target)[mask], scale),
            "hold_current_state_baseline": errors_summary((state[:, None] - target)[mask], scale),
        }
    return groups


def macro_average(episodes):
    result = {}
    for group in ("all", "moving", "low_motion"):
        rows = [e["metrics"][group] for e in episodes if e["metrics"][group] is not None]
        if not rows:
            result[group] = None
            continue
        item = {
            "contributing_episodes": len(rows),
            "sampled_windows": sum(r["sampled_windows"] for r in rows),
        }
        for method in ("model", "hold_current_state_baseline"):
            item[method] = {
                key: np.asarray([r[method][key] for r in rows]).mean(axis=0).tolist()
                for key in rows[0][method]
            }
        result[group] = item
    return result


def evaluate_checkpoint(spec, checkpoint, output, sample_count, seed):
    from .infer import create_policy
    from .train import split_digest

    dataset_root = Path(spec["dataset_root"]).expanduser()
    dataset = SingleCameraDataset(dataset_root, "validation", spec["action_horizon"], spec["policy_hz"])
    asset = checkpoint / "assets" / model_asset_id(spec)
    norm_binding = json.loads((asset / "width_contract.json").read_text())
    if norm_binding["frozen_split_sha256"] != split_digest(dataset_root):
        raise ValueError("Checkpoint and evaluation dataset refer to different frozen splits")
    action_stats = json.loads((asset / "norm_stats.json").read_text())["norm_stats"]["actions"]
    if spec["model_family"] == "pi05":
        scale = 2.0 / (np.asarray(action_stats["q99"]) - np.asarray(action_stats["q01"]) + 1e-6)
    else:
        scale = 1.0 / (np.asarray(action_stats["std"]) + 1e-6)

    policy = create_policy(spec, checkpoint)
    horizon = int(spec["action_horizon"])
    alignment = json.loads((dataset_root / "alignment_manifest.json").read_text())
    provenance = {e["directory"]: e for e in alignment["episodes"]}
    episodes, samples, predictions, targets, states, ids, frames, movements = [], [], [], [], [], [], [], []
    for episode_index, entry in enumerate(dataset.entries):
        starts = dataset.starts[episode_index]
        if starts is None:
            starts = np.arange(entry["frames"])
        selected = np.linspace(0, len(starts) - 1, min(sample_count, len(starts)), dtype=np.int64)
        selected_frames = {int(starts[i]) for i in selected}
        directory = dataset_root / entry["directory"]
        with (directory / "row_sources.jsonl").open() as source:
            source_rows = {j: json.loads(line) for j, line in enumerate(source) if j in selected_frames}
        offset = int(dataset.ends[episode_index - 1]) if episode_index else 0
        ep_predicted, ep_target, ep_state, ep_moving = [], [], [], []
        for selected_index in selected:
            frame = int(starts[int(selected_index)])
            sample = dataset[offset + int(selected_index)]
            target = sample["actions"].copy()
            state = sample["state"].copy()
            observation = {key: value for key, value in sample.items() if key != "actions"}
            noise_seed = int.from_bytes(hashlib.sha256(
                f"{seed}:{entry['directory']}:{frame}".encode()).digest()[:8], "little")
            noise = np.random.default_rng(noise_seed).standard_normal((horizon, 32), dtype=np.float32)
            predicted = np.asarray(policy.infer(observation, noise=noise)["actions"], dtype=np.float32)
            if predicted.shape != (horizon, 7) or not np.isfinite(predicted).all():
                raise ValueError(f"Invalid prediction at {entry['directory']} row {frame}")
            relative_target = target - state[None]
            moving = bool(np.max(np.abs(np.rad2deg(relative_target[:, :6]))) >= MOVING_JOINT_DEG
                          or np.max(np.abs(relative_target[:, 6] * 1000)) >= MOVING_GRIPPER_MM)
            ep_predicted.append(predicted)
            ep_target.append(target)
            ep_state.append(state)
            ep_moving.append(moving)
            samples.append({
                "episode": entry["directory"], "target_color": entry["target_color"],
                "frame_index": frame, "valid_start_index": int(selected_index),
                "policy_timestamp_ns": source_rows[frame]["t"],
                "source_file": str(directory / "row_sources.jsonl"),
                "observation_source": source_rows[frame],
                "action_row_indices": np.minimum(np.arange(frame, frame + horizon), entry["frames"] - 1).tolist(),
                "noise_seed": noise_seed, "motion_group": "moving" if moving else "low_motion",
                "tail_padded": frame + horizon > entry["frames"],
            })
        ep_predicted, ep_target, ep_state = map(np.asarray, (ep_predicted, ep_target, ep_state))
        ep_moving = np.asarray(ep_moving, dtype=bool)
        source = provenance[entry["directory"]]
        episodes.append({
            "episode": entry["directory"], "split": "validation", "target_color": entry["target_color"],
            "scene_colors": entry["scene_colors"], "prompt": entry["prompt"],
            "session_id": source["session_id"], "placement_id": source["placement_id"],
            "source_trajectory_id": source["source_trajectory_id"],
            "available_valid_starts": len(starts), "sampled_windows": len(selected),
            "metrics": episode_metrics(ep_predicted, ep_target, ep_state, ep_moving, scale),
        })
        predictions.extend(ep_predicted)
        targets.extend(ep_target)
        states.extend(ep_state)
        ids.extend([entry["directory"]] * len(selected))
        frames.extend(int(starts[i]) for i in selected)
        movements.extend(ep_moving.tolist())
        print(json.dumps({"checkpoint": checkpoint.name, "episode": entry["directory"],
                          "sampled_windows": len(selected),
                          "metrics": episodes[-1]["metrics"]}, ensure_ascii=False), flush=True)

    output.mkdir(parents=True, exist_ok=True)
    np.savez(output / "predictions.npz",
        predicted=np.asarray(predictions), target=np.asarray(targets), state=np.asarray(states),
        episode=np.asarray(ids), frame_index=np.asarray(frames, dtype=np.int64), moving=np.asarray(movements))
    with (output / "samples.jsonl").open("w") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False, allow_nan=False) + "\n")
    report = {
        "status": "COMPLETED", "evaluation": "open_loop_action_imitation",
        "not_a_robot_success_rate": True, "sent_to_hardware": False,
        "model_family": spec["model_family"], "checkpoint": str(checkpoint),
        "checkpoint_step_directory": checkpoint.name, "dataset_root": str(dataset_root),
        "frozen_split_sha256": norm_binding["frozen_split_sha256"],
        "normalization_source": str(asset), "normalization_split": "train",
        "normalization_refitted": False, "gradient_updates": 0,
        "sampling": {
            "rule": "equally spaced indices in each episode's ordered valid_action_starts",
            "maximum_windows_per_episode": sample_count, "seed": seed,
            "noise": "fixed float32 Gaussian [10,32], keyed by seed/episode/frame; same across checkpoints and model families",
            "flow_steps": 10, "sampled_episodes": len(episodes), "sampled_windows": len(samples),
            "covers_all_validation_windows": all(e["sampled_windows"] == e["available_valid_starts"] for e in episodes),
        },
        "motion_groups": {
            "moving": f"any of next {horizon} targets differs from current state by >= {MOVING_JOINT_DEG} joint degrees or >= {MOVING_GRIPPER_MM} gripper mm",
            "low_motion": "all differences below both descriptive thresholds",
            "these_are_not_motion_limits": True,
        },
        "aggregation": "equal weight per episode within each group; RMSE fields are means of per-episode RMSE",
        "normalized_mse7": "all seven real action dimensions, using this model's train normalization scale; compare checkpoints within the same model",
        "overall": macro_average(episodes),
        "by_color": {color: macro_average([e for e in episodes if e["target_color"] == color])
                     for color in ("blue", "red")},
        "episodes": episodes, "samples_file": str(output / "samples.jsonl"),
        "predictions_file": str(output / "predictions.npz"),
    }
    write_json(output / "report.json", report)
    print(json.dumps({"status": report["status"], "report": str(output / "report.json"),
                      "overall": report["overall"]}, ensure_ascii=False), flush=True)


def evaluate_retained(spec, spec_path, output, sample_count, seed):
    run = Path(spec["run_root"]).expanduser() / spec["model_family"] / spec["experiment_name"]
    run_spec = json.loads((run / "run_spec.json").read_text())
    root = Path(run_spec["resolved_paths"]["checkpoint_directory"])
    checkpoints = sorted((p for p in root.iterdir() if p.name.isdigit() and (p / "params").is_dir()),
                         key=lambda p: int(p.name))
    if not checkpoints:
        raise ValueError(f"No completed checkpoints in {root}")
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for checkpoint in checkpoints:
        destination = output / checkpoint.name
        # Each process exits before the next model is loaded; no concurrent checkpoints on the GPU.
        subprocess.run([sys.executable, "-u", "-m", "tasks.piper_real_single_v1.evaluate",
                        "--spec", str(spec_path), "--checkpoint", str(checkpoint), "--output", str(destination),
                        "--samples-per-episode", str(sample_count), "--seed", str(seed)], check=True)
        reports.append(json.loads((destination / "report.json").read_text()))
    ranked = sorted(reports, key=lambda r: r["overall"]["moving"]["model"]["normalized_mse7"])
    summary = {
        "status": "COMPLETED", "model_family": spec["model_family"],
        "evaluation": "open_loop_action_imitation", "not_a_robot_success_rate": True,
        "selection_rule": "lowest episode-macro seven-dimensional train-normalized MSE on moving validation windows",
        "validation_selected_checkpoint": ranked[0]["checkpoint"],
        "selection_scope": "retained checkpoints only; validation-selected, not an independent test result",
        "checkpoints": [{"checkpoint": r["checkpoint"], "report": str(output / Path(r["checkpoint"]).name / "report.json"),
                         "overall": r["overall"], "by_color": r["by_color"]} for r in reports],
    }
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples-per-episode", type=int, default=64)
    parser.add_argument("--seed", type=int, default=20261124)
    args = parser.parse_args()
    if args.samples_per_episode < 1:
        parser.error("--samples-per-episode must be positive")
    spec_path = Path(args.spec).expanduser().resolve()
    spec = json.loads(spec_path.read_text())
    run = Path(spec["run_root"]).expanduser() / spec["model_family"] / spec["experiment_name"]
    output = args.output or run / "evaluation"
    if args.checkpoint is None:
        evaluate_retained(spec, spec_path, output, args.samples_per_episode, args.seed)
    else:
        openpi = Path(spec["openpi_root"]).expanduser()
        sys.path.insert(0, str(openpi))
        sys.path.insert(0, str(openpi / "src"))
        evaluate_checkpoint(spec, args.checkpoint.expanduser(), output, args.samples_per_episode, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
