"""Actual data and sampler audit for the two completed runs."""
import collections
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from sim import COLORS
from sim_v2 import ColorEnvV2

ROOT = Path(__file__).resolve().parents[2]
NEW = ROOT / "outputs/pi0-120-demo-v2-20261101"
OLD = ROOT / "outputs/pi0-six-demo-20261031"
OUT = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    entries = json.loads((NEW / "dataset/index.json").read_text())
    manifest = json.loads((NEW / "dataset/manifest.json").read_text())
    issues, rows, stage_counts = [], [], collections.Counter()
    env = ColorEnvV2(render=False)
    slots = np.array([[-.235, -.15], [-.13, -.15], [-.205, -.035]])
    slot_counts = {c: collections.Counter() for c in COLORS}
    precontact_differences = []
    for e in entries:
        file = NEW / "dataset" / (e["directory"] + ".npz")
        archived = next(x for x in manifest["episodes"] if x["layout_seed"] == e["layout_seed"] and x["target"] == e["target"])
        if sha(file) != archived["sha256"]:
            issues.append(f"hash:{file}")
        with np.load(file, allow_pickle=False) as x:
            if str(x["prompt"]) != e["prompt"] or e["prompt"] != f"pick up the {e['target']} block and place it in the box":
                issues.append(f"prompt:{file}")
            if str(x["target"]) != e["target"] or int(x["layout_seed"]) != e["layout_seed"]:
                issues.append(f"identity:{file}")
            if not np.allclose(np.diff(x["timestamp"]), .05, atol=1e-8):
                issues.append(f"time:{file}")
            for k in ("state", "action"):
                expanded = np.load(NEW / "dataset" / e["directory"] / f"{k}.npy")
                if not np.array_equal(expanded, x[k]): issues.append(f"expanded:{file}:{k}")
            if not np.array_equal(x["action"], x["executed_command"].astype(np.float32)):
                issues.append(f"actual_command:{file}")
            stage_counts.update(x["stage"].tolist())
            if e["layout_seed"] in (100, 101):
                old_path = ROOT / "results/piper-color-v1/dataset-v1" / archived["file"]
                with np.load(old_path, allow_pickle=False) as old:
                    for phase in ("approach", "descend", "grasp", "lift"):
                        mask = x["stage"] == phase
                        precontact_differences.append({"layout": e["layout_seed"], "target": e["target"], "stage": phase,
                            "joint_command_mae_rad": float(abs(x["action"][mask, :6] - old["action"][mask, :6]).mean()),
                            "opening_command_mae_m": float(abs(x["action"][mask, 6] - old["action"][mask, 6]).mean()),
                            "state_joint_mae_rad": float(abs(x["state"][mask, :6] - old["state"][mask, :6]).mean())})
        env.reset(e["layout_seed"], e["target"])
        p = env.positions()[e["target"]][:2]
        slot = int(np.linalg.norm(slots - p, axis=1).argmin())
        slot_counts[e["target"]][slot] += 1
        rows.append({"layout": e["layout_seed"], "target": e["target"], "slot": slot})
    env.close()
    equal_initial = []
    initial_differences = []
    for layout in range(100, 140):
        eps = [e for e in entries if e["layout_seed"] == layout]
        for key in ("state", "external_rgb", "wrist_rgb"):
            arrays = [np.load(NEW / "dataset" / e["directory"] / f"{key}.npy", mmap_mode="r")[0] for e in eps]
            equal_initial.append(all(np.array_equal(arrays[0], a) for a in arrays[1:]))
            initial_differences.append({"layout": layout, "key": key,
                "max_abs_difference": max(float(abs(arrays[0].astype(float) - a.astype(float)).max()) for a in arrays[1:]),
                "max_mean_abs_difference": max(float(abs(arrays[0].astype(float) - a.astype(float)).mean()) for a in arrays[1:])})
    order = np.load(NEW / "sample_order.npy")
    old_order = np.load(OLD / "sample_order.npy")
    new_metrics = [json.loads(s) for s in (NEW / "lora_metrics.jsonl").read_text().splitlines()]
    sample_match = all(r["sample_indices"] == order[(r["step"] - 1) * 4:r["step"] * 4].tolist() for r in new_metrics)
    norms = {}
    for label, run, asset in (("old", OLD, "piper_h_color_v1"), ("new", NEW, "piper_h_color_contact_v2_120")):
        norms[label] = json.loads((run / "assets" / asset / "norm_stats.json").read_text())["norm_stats"]
    ratios = {key: (np.array(norms["new"][key]["std"]) / np.array(norms["old"][key]["std"])).tolist()
              for key in ("state", "actions")}
    old_final_lr = 3e-6 + .5 * (3e-5 - 3e-6) * (1 + math.cos(math.pi * (2009 - 100) / (2010 - 100)))
    report = {"episodes_checked": len(entries), "data_issues": issues, "all_120_teacher_successes": all(e["success"] for e in manifest["episodes"]),
        "all_same_layout_initial_rgb_and_state_equal_across_prompts": all(equal_initial),
        "initial_observation_differences": initial_differences,
        "color_counts": dict(collections.Counter(e["target"] for e in entries)),
        "target_slot_counts_by_color": slot_counts, "stage_frame_counts": dict(stage_counts),
        "approach_fraction": stage_counts["approach"] / 32160,
        "sampler": {"new_seen_starts": 8040 * 4, "new_unique_starts": int(len(np.unique(order[:32160]))),
                    "new_each_start_seen_once": bool(np.array_equal(np.sort(order[:32160]), np.arange(32160))),
                    "all_logged_indices_match_saved_order": sample_match,
                    "old_each_start_seen_five_times": bool(np.all(np.bincount(old_order, minlength=1608) == 5)),
                    "old_epochs": 5, "new_epochs": 1},
        "new_to_old_norm_std_ratio": ratios, "norms": norms,
        "old_new_teacher_command_comparison": precontact_differences,
        "learning_rate": {"old_decay_steps": 2010, "new_decay_steps": 24120,
                          "old_final_schedule_lr": old_final_lr, "new_final_recorded_lr": new_metrics[-1]["learning_rate"],
                          "new_old_final_ratio": new_metrics[-1]["learning_rate"] / old_final_lr},
        "loss_definition": "flow-matching velocity MSE averaged across all 32 action dimensions and the action horizon; seven physical output dimensions",
        "loss_definition_source": "../pi0/openpi/src/openpi/models/pi0.py:189-214 and transforms.PadStatesAndActions",
        "attribution": "data count, contact version, normalization and training schedule changed jointly; not a single-variable data-size experiment"}
    (OUT / "training_data_audit.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ("norms", "old_new_teacher_command_comparison")}, indent=2))


if __name__ == "__main__": main()
