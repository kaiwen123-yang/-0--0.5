"""Aggregate complete paired evidence while retaining seed/layout identities."""
import json
from pathlib import Path
import statistics
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"


def main():
    trajectories = json.loads((OUT / "trajectory_metrics.json").read_text())
    summary = {"fixed": [], "prefix": [], "closed_loop_validation": [], "task_test_used": False}
    for label in ("old2010", "new2010", "new4020", "new8040"):
        folder = OUT / "fixed" / label
        observations = json.loads((folder / "observations.json").read_text())
        prompt = json.loads((folder / "prompt_swap.json").read_text())
        assert len(observations) == 588 and len(prompt) == 14
        vv = [r for r in prompt if r["layout"] >= 1000]
        matched, endpoint_errors, same_choice = 0, [], 0
        per_layout = []
        for r in vv:
            pred, truth = np.asarray(r["endpoints"])[:, :2], np.asarray(r["teacher_endpoints"])[:, :2]
            choices = np.linalg.norm(pred[:, None, :] - truth[None, :, :], axis=-1).argmin(axis=1)
            matched += int((choices == np.arange(3)).sum())
            same_choice += int(len(set(choices.tolist())) == 1)
            endpoint_errors.extend((np.linalg.norm(pred - truth, axis=1) * 1000).tolist())
            per_layout.append({"layout": r["layout"], "seed": r["base_seed"],
                "spread_mm": r["prompt_endpoint_xy_spread_mm"], "teacher_spread_mm": r["teacher_endpoint_xy_spread_mm"],
                "choices_as_color_indices": choices.tolist(), "correct_of_3": int((choices == np.arange(3)).sum())})
        stages = []
        for stage in ("approach", "descend", "grasp", "lift", "transfer", "lower", "release", "retreat", "settle"):
            rr = [r for r in observations if r["split"] == "validation" and r["stage"] == stage]
            if rr:
                stages.append({"stage": stage, "queries": len(rr),
                    **{key + "_median": statistics.median(r[key] for r in rr)
                       for key in ("fk_xy_error_mm", "fk_z_error_mm", "joint_mae_rad", "width_mae_mm")}})
        frames = [{"frame": n, "fk_xy_error_mm_median": statistics.median(r["fk_xy_error_mm"] for r in observations
                    if r["split"] == "validation" and r["frame"] == n)} for n in sorted({r["frame"] for r in observations})]
        summary["fixed"].append({"model": label, "teacher_observation_queries": len(observations),
            "validation_prompt_groups": 10, "prompt_matched_teacher_endpoint": matched,
            "prompt_predictions": 30, "all_three_prompts_choose_same_endpoint_groups": same_choice,
            "validation_prompt_spread_median_mm": statistics.median(r["prompt_endpoint_xy_spread_mm"] for r in vv),
            "teacher_prompt_spread_median_mm": statistics.median(r["teacher_endpoint_xy_spread_mm"] for r in vv),
            "prompt_endpoint_error_median_mm": statistics.median(endpoint_errors),
            "prompt_pairs": per_layout, "validation_stages": stages, "validation_frames": frames})
    for file in sorted((OUT / "prefix").glob("*/summary.json")):
        data = json.loads(file.read_text())
        for prefix in sorted({r["prefix"] for r in data["episodes"]}):
            rows = [r for r in data["episodes"] if r["prefix"] == prefix]
            summary["prefix"].append({"model": file.parent.name, "prefix": prefix, "n": len(rows),
                "complete": len(rows) == 10, "successes": sum(r["success"] for r in rows),
                "target_lifted_5cm": sum(r["max_lift_cm"] > 5 for r in rows),
                "episodes": [{k: r[k] for k in ("layout", "target", "base_seed", "success", "max_lift_cm", "handoff_state_max_error")} for r in rows]})
    for prefix in ("baseline", "update_2010", "update_4020", "update_8040"):
        rows = [r for r in trajectories if r["split"] == "validation" and r["evaluation"].startswith(prefix)]
        summary["closed_loop_validation"].append({"model": prefix, "n": len(rows),
            "successes": sum(r["success"] for r in rows), "close_nearest_target": sum(r["close_nearest_is_target"] for r in rows),
            "target_lifted": sum(r["target_lifted_5cm"] for r in rows), "wrong_lifted": sum(r["non_target_lifted_5cm"] for r in rows),
            "close_target_xy_median_mm": statistics.median(r["close_target_xy_mm"] for r in rows),
            "close_nearest_xy_median_mm": statistics.median(r["close_nearest_xy_mm"] for r in rows),
            "orientation_median_deg": statistics.median(r["close_orientation_error_deg"] for r in rows),
            "tracking_mae_median_rad": statistics.median(r["joint_command_to_feedback_mae_rad"] for r in rows)})
    summary["unit_note"] = "5 validation layouts, 3 instructions, 2 base seeds; correlated grouped observations, descriptive counts only"
    (OUT / "evidence_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({"closed_loop_validation": summary["closed_loop_validation"],
        "fixed": [{k: r[k] for k in ("model", "validation_prompt_spread_median_mm", "prompt_matched_teacher_endpoint", "all_three_prompts_choose_same_endpoint_groups")} for r in summary["fixed"]],
        "prefix": [{k: r[k] for k in ("model", "prefix", "n", "successes", "complete")} for r in summary["prefix"]]}, indent=2))


if __name__ == "__main__": main()
