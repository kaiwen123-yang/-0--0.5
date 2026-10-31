"""Summarize autonomous full-task results; stage observations are diagnostics."""
import json
from pathlib import Path
import sys

import numpy as np
from sim import BOX, COLORS, HALF


def summarize(run):
    evaluations = []
    for directory in sorted((run / "evaluations").iterdir()):
        summary = json.loads((directory / "summary.json").read_text())
        protocol = json.loads((directory / "protocol.json").read_text())
        episodes = []
        for e in summary["episodes"]:
            stem = f"layout_{e['layout_seed']:05d}_{e['target']}"
            with np.load(directory / f"{stem}.npz", allow_pickle=False) as trace:
                target = trace["object_positions"][:, COLORS.index(e["target"])]
                above = (np.abs(target[:, 0] - BOX[0]) < .072 - HALF) & (np.abs(target[:, 1] - BOX[1]) < .064 - HALF)
            lifted = e["max_lift_m"][e["target"]] > .05
            if e["success"]:
                failure = None
            elif e["error"]:
                failure = "execution_error"
            elif not lifted:
                failure = "target_not_lifted_5cm"
            elif not above.any():
                failure = "lifted_but_not_over_box"
            else:
                failure = "reached_box_but_failed_placement_release_or_hold"
            episodes.append({"layout_seed": e["layout_seed"], "target": e["target"],
                             "episode_seed": e["episode_seed"], "success": e["success"],
                             "target_lifted_5cm": lifted, "target_ever_over_box": bool(above.any()),
                             "correct_in_box_final": e["correct_in_box"], "wrong_in_box_final": e["wrong_in_box"],
                             "gripper_open_final": e["gripper_open"], "stable_2s": e["stable_2s"],
                             "distractor_displacement_m": e["distractor_displacement_m"],
                             "max_joint_violation_rad": e["max_joint_violation_rad"],
                             "failure_observation": failure, "video": str(directory / f"{stem}.mp4"),
                             "trajectory": str(directory / f"{stem}.npz")})
        evaluations.append({"name": directory.name, "checkpoint": protocol["policy"]["checkpoint"],
                            "base_seed": protocol["seed"], "successes": summary["successes"],
                            "total": summary["total"], "complete": summary["complete"],
                            "wall_seconds": summary["wall_seconds"], "episodes": episodes})
    final = [e for e in evaluations if Path(e["checkpoint"]).name == "2010"]
    report = {"model_family": "pi0", "training": json.loads((run / "lora_training.json").read_text()),
              "evaluations": evaluations,
              "development_gate_passed": len(final) == 2 and all(e["successes"] == e["total"] == 6 for e in final),
              "scope": "Training-layout learning check; no held-out generalization or hardware evaluation",
              "success_definition": "correct color in box, wrong colors excluded, gripper open, distractors and joints within original limits, all conditions held continuously for 2 seconds",
              "physics_clock": "paused during inference", "next_training_started": False}
    (run / "summary.json").write_text(json.dumps(report, indent=2))
    lines = ["# Pi0 six-demo development run", "", "| Updates | Base seed | Full-task success |", "|---:|---:|---:|"]
    for e in evaluations:
        lines.append(f"| {Path(e['checkpoint']).name} | {e['base_seed']} | {e['successes']}/{e['total']} |")
    lines += ["", f"Final two-seed development gate: {report['development_gate_passed']}", "", report["scope"]]
    (run / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"development_gate_passed": report["development_gate_passed"],
                      "evaluations": [{k: e[k] for k in ("name", "successes", "total")} for e in evaluations]}), flush=True)


if __name__ == "__main__":
    summarize(Path(sys.argv[1]))
