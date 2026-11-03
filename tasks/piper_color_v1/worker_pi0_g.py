"""Run the fixed full-task roster and record task/phase outcomes."""
import argparse, sys
from pathlib import Path
import numpy as np
import evaluate_pi0_ef as evaluator
from g_common import *
from run_pi0_ef import partition

def metrics(task, stem):
    result = read(stem.with_suffix(".json"))
    with np.load(stem.with_suffix(".npz")) as trace:
        objects = trace["object_positions"]
        tcp, command = trace["tcp"], trace["executed_command"]
        ci = COLORS.index(task["target"])
        position = objects[0, ci]
        slot = "back" if position[1] > -.09 else ("front_left" if position[0] < -.18 else "front_right")
        closing = np.flatnonzero(command[:, 6] < .06)
        close = int(closing[0]) if len(closing) else None
        lifted = (objects[:, :, 2] - objects[0, :, 2]).max(axis=0) > .05
        wrong_lift = any(lifted[i] for i in range(3) if i != ci)
        diag = result["diagnostics"]
        if result["success"]: stage = "success"
        elif close is None: stage = "approach_no_closure"
        elif wrong_lift: stage = "wrong_target"
        elif not lifted[ci]: stage = "approach_or_grasp"
        elif not diag["over_box_frames"]: stage = "lift_or_transfer"
        elif not result["correct_in_box"]: stage = "lower_or_release"
        elif not result["gripper_open"]: stage = "release"
        else: stage = "stability_or_distractor"
        return dict(**task, success=result["success"], error=result["error"], slot=slot, failure_stage=stage,
            frames=result["steps"], first_close_frame=close, close_time_s=None if close is None else close/20,
            close_target_xy_mm=None if close is None else float(np.linalg.norm(tcp[close,:2]-objects[close,ci,:2])*1000),
            target_lifted_5cm=bool(lifted[ci]), non_target_lifted_5cm=bool(wrong_lift),
            correct_in_box=result["correct_in_box"], gripper_open=result["gripper_open"],
            over_box_frames=diag["over_box_frames"], result_json=str(stem.with_suffix(".json")),
            trajectory=str(stem.with_suffix(".npz")), video=str(stem.with_suffix(".mp4")))

def evaluate(label, roster_path, checkpoint):
    rows = []
    tasks = read(roster_path)
    for task in tasks:
        unit = CAMPAIGN / "evaluations" / label / trial_id(task)
        done = unit / "completed.json"
        if done.exists():
            rows.append(read(done))
            continue
        output = unit / ("attempt000_seed" + str(task["base_seed"]))
        stem = output / ("layout_%05d_%s" % (task["layout"], task["target"]))
        if not stem.with_suffix(".json").exists():
            sys.argv = ["evaluate_pi0_ef.py", "--mode", "lora", "--model-family", "pi0",
                "--split", task["split"], "--steps", "420", "--replan-steps", "5",
                "--seed", str(task["base_seed"]), "--seed-scope", "episode",
                "--layout-seeds", str(task["layout"]), "--targets", task["target"],
                "--data", str(CAMPAIGN / "evaluation_layouts"), "--output", str(output),
                "--checkpoint", str(checkpoint), "--norm-stats", str(NORM),
                "--policy-host", "127.0.0.1", "--policy-port", str(PORT)]
            evaluator.main()
            protocol = read(output / "protocol.json")
            protocol["source_revision"] = read(CAMPAIGN / "contract.json")["implementation_commit"]
            save(output / "protocol.json", protocol)
        row = metrics(task, stem)
        if row["error"]:
            raise RuntimeError("Full task execution error: " + str(stem))
        save(done, row)
        rows.append(row)
        save(CAMPAIGN / "evaluation_progress.json",
             dict(label=label, completed=len(rows), expected=len(tasks), last=task, at_utc=now()))
    save(CAMPAIGN / ("node_" + label + ".json"), dict(label=label, summary=partition(rows), episodes=rows))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.label, args.roster, args.checkpoint)
