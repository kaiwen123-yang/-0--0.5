"""Reuse the frozen-input protocol and summarize all autonomous validation cases."""
import argparse
import json
import os
from pathlib import Path
import statistics

import numpy as np
import probe_pi0_120_regression as original
from analyze_pi0_120_regression import analyze
from policy_client import PolicyClient
from prepare_pi0_ab import save, sha

RUN = Path(os.environ["PIPER_COLOR_RUN"])


def summarize(local):
    label = f"update_{local}"
    prompt = json.loads((RUN / "probes/fixed" / label / "prompt_swap.json").read_text())
    observations = json.loads((RUN / "probes/fixed" / label / "observations.json").read_text())
    if len(prompt) != 14 or len(observations) != 588:
        raise ValueError("Frozen-input evaluation incomplete")
    pairs = []
    for r in prompt:
        if r["layout"] < 1000:
            continue
        pred, truth = np.asarray(r["endpoints"])[:, :2], np.asarray(r["teacher_endpoints"])[:, :2]
        choices = np.linalg.norm(pred[:, None] - truth[None], axis=-1).argmin(axis=1)
        pairs.append({"layout": r["layout"], "base_seed": r["base_seed"], "choices": choices.tolist(),
            "matched_of_3": int((choices == np.arange(3)).sum()), "all_same_choice": len(set(choices.tolist())) == 1,
            "prompt_spread_mm": r["prompt_endpoint_xy_spread_mm"],
            "teacher_spread_mm": r["teacher_endpoint_xy_spread_mm"]})
    trajectories = []
    by_seed, train_by_seed = [], []
    for split in ("train", "validation"):
        for seed in (42, 43):
            path = RUN / "evaluations" / f"{label}_{split}_seed{seed}"
            summary = json.loads((path / "summary.json").read_text())
            expected = 6 if split == "train" else 15
            if not summary["complete"] or summary["errors"] or summary["total"] != expected:
                raise ValueError(f"Incomplete autonomous evaluation: {path}")
            (train_by_seed if split == "train" else by_seed).append(summary["successes"])
            trajectories += [analyze(p) for p in sorted(path.glob("layout_*.npz"))]
    validation = [r for r in trajectories if r["split"] == "validation"]
    if len(validation) != 30:
        raise ValueError("Need all 30 validation cases")
    matched = sum(r["matched_of_3"] for r in pairs)
    closed_correct = sum(r["first_close_frame"] is not None and r["close_nearest_is_target"] for r in validation)
    wrong_lift = sum(r["non_target_lifted_5cm"] for r in validation)
    stages = []
    for stage in sorted({r["stage"] for r in observations}):
        rows = [r for r in observations if r["split"] == "validation" and r["stage"] == stage]
        if rows:
            stages.append({"stage": stage, "queries": len(rows), **{k: statistics.median(r[k] for r in rows)
                for k in ("joint_mae_rad", "width_mae_mm", "fk_xy_error_mm", "fk_z_error_mm")}})
    grouped = []
    for layout in range(1000, 1005):
        rows = [r for r in validation if r["layout"] == layout]
        pp = [r for r in pairs if r["layout"] == layout]
        grouped.append({"layout": layout, "trials": len(rows), "successes": sum(r["success"] for r in rows),
            "prompt_matches": sum(r["matched_of_3"] for r in pp),
            "closed_correct": sum(r["first_close_frame"] is not None and r["close_nearest_is_target"] for r in rows),
            "wrong_lifts": sum(r["non_target_lifted_5cm"] for r in rows),
            "close_target_xy_median_mm": statistics.median(r["close_target_xy_mm"] for r in rows)})
    gates = {"prompt_match_at_least_24_of_30": matched >= 24, "correct_close_at_least_24_of_30": closed_correct >= 24,
             "wrong_lift_at_most_2_of_30": wrong_lift <= 2,
             "validation_total_at_least_11_and_each_seed_at_least_5": sum(by_seed) >= 11 and min(by_seed) >= 5,
             "all_evaluations_complete_without_errors": True}
    result = {"group": RUN.name, "local_update": local, "optimizer_update": 2010 + local,
        "validation_successes_by_seed": by_seed, "validation_total": 30, "training_diagnostic_successes_by_seed": train_by_seed,
        "prompt_matches": matched, "prompt_total": 30, "prompt_pairs": pairs,
        "all_three_prompts_same_endpoint_groups": sum(r["all_same_choice"] for r in pairs),
        "correct_close": closed_correct, "non_target_lifts": wrong_lift,
        "close_target_xy_median_mm": statistics.median(r["close_target_xy_mm"] for r in validation),
        "by_layout": grouped, "fixed_observation_stage_medians": stages, "engineering_gates": gates,
        "all_engineering_gates_pass": all(gates.values()), "test_split_used": False,
        "statistics": "descriptive counts from 5 validation layouts x 3 instructions x 2 seeds",
        "candidate_score": [int(all(gates.values())), min(by_seed), sum(by_seed), matched]}
    save(RUN / f"node_{local}.json", result)
    save(RUN / f"trajectory_metrics_{local}.json", trajectories)
    candidate_path = RUN / "selected_candidate.json"
    previous = json.loads(candidate_path.read_text()) if candidate_path.exists() else None
    if previous is None or result["candidate_score"] > previous["candidate_score"]:
        save(candidate_path, {"local_update": local, "candidate_score": result["candidate_score"],
                              "selection_uses": "validation only; no independent test"})
    print("NODE_SUMMARY " + json.dumps(result), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--local-update", type=int, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    a = p.parse_args()
    original.OUT = RUN / "probes"
    # No teacher intervention is run. These archived observations are diagnostics only.
    for record in json.loads((RUN.parent / "teacher_reference_files.json").read_text()):
        if sha(record["path"]) != record["sha256"]:
            raise ValueError("Frozen teacher reference changed")
    policy = PolicyClient("127.0.0.1", 18768)
    try:
        if Path(policy.metadata["checkpoint"]).resolve() != a.checkpoint.resolve():
            raise ValueError("Wrong checkpoint loaded for frozen-input probes")
        original.fixed(policy, f"update_{a.local_update}")
    finally:
        policy.close()
    summarize(a.local_update)
