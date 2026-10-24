"""Diagnose stage-specific prediction errors on fixed teacher observations.

No fitting, policy updates, robot commands or success-rate relabeling. This is
teacher-forced prediction accuracy, not a closed-loop success evaluation.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from openpi.policies import policy_config as upstream
from policy_config import make_config


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(exist_ok=True, parents=True)
    policy = upstream.create_trained_policy(make_config("lora"), a.checkpoint,
                                            sample_kwargs={"num_steps":10})
    results = []
    arrays = {}
    frames = [15, 45, 70, 95, 125, 160, 185, 210, 245]
    for split, seed in [("train", 100), ("validation", 1000)]:
        for color in ("red", "green", "blue"):
            with np.load(a.data / split / f"layout_{seed:05d}_{color}.npz", allow_pickle=False) as d:
                for frame in frames:
                    obs = dict(state=d["state"][frame].copy(), external_rgb=d["external_rgb"][frame].copy(),
                               wrist_rgb=d["wrist_rgb"][frame].copy(), prompt=str(d["prompt"]))
                    started = time.monotonic()
                    pred = np.asarray(policy.infer(obs)["actions"])
                    elapsed = time.monotonic()-started
                    ids = np.minimum(np.arange(frame, frame+10), len(d["action"])-1)
                    truth = d["action"][ids]
                    if pred.shape != (10,7) or not np.isfinite(pred).all():
                        raise ValueError("Invalid model prediction")
                    item = dict(split=split, layout_seed=seed, target=color, frame=frame, stage=str(d["stage"][frame]),
                                joint_mae_rad=float(np.mean(np.abs(pred[:,:6]-truth[:,:6]))),
                                width_mae_m=float(np.mean(np.abs(pred[:,6]-truth[:,6]))),
                                joint1_pred_delta=float(np.mean(pred[:,0]-obs["state"][0])),
                                joint1_true_delta=float(np.mean(truth[:,0]-obs["state"][0])),
                                width_pred_mean_m=float(np.mean(pred[:,6])),
                                width_true_mean_m=float(np.mean(truth[:,6])), inference_seconds=elapsed)
                    results.append(item)
                    key = f"{split}_{seed}_{color}_{frame}"
                    arrays[f"{key}_pred"] = pred
                    arrays[f"{key}_truth"] = truth
                    arrays[f"{key}_state"] = obs["state"]
                    (a.output / "observations.json").write_text(json.dumps(results, indent=2))
                    print(json.dumps(item), flush=True)
    groups = []
    for split in ("train", "validation"):
        for stage in dict.fromkeys(r["stage"] for r in results):
            subset = [r for r in results if r["split"]==split and r["stage"]==stage]
            groups.append(dict(split=split, stage=stage, observations=len(subset),
                               joint_mae_rad=float(np.mean([r["joint_mae_rad"] for r in subset])),
                               width_mae_m=float(np.mean([r["width_mae_m"] for r in subset])),
                               joint1_pred_delta=float(np.mean([r["joint1_pred_delta"] for r in subset])),
                               joint1_true_delta=float(np.mean([r["joint1_true_delta"] for r in subset]))))
    report = dict(checkpoint=str(a.checkpoint), observations=len(results), groups=groups,
                  evaluation="teacher-forced action prediction only, not success rate",
                  purpose="Local diagnostic before spending more rented GPU time", hardware_execution=False,
                  model_updated=False, independent_test_set_used=False)
    (a.output / "summary.json").write_text(json.dumps(report, indent=2))
    np.savez_compressed(a.output / "predictions.npz", **arrays)
    print("DIAGNOSTIC_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
