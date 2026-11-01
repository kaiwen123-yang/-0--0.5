"""Read existing closed-loop records; quantify targeting, approach and grasp."""
import csv
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "outputs/pi0-120-demo-v2-20261101"
OUT = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"
COLORS = ("red", "green", "blue")


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False))


def first(mask):
    ids = np.flatnonzero(mask)
    return int(ids[0]) if len(ids) else None


def analyze(path):
    result = json.loads(path.with_suffix(".json").read_text())
    with np.load(path, allow_pickle=False) as x:
        d = {k: x[k] for k in x.files}
    color = result["target"]
    ci = COLORS.index(color)
    n = len(d["state"])
    tcp, obj, command = d["tcp"], d["object_positions"], d["executed_command"]
    xy = np.linalg.norm(tcp[:, None, :2] - obj[:, :, :2], axis=2)
    initial_xy = np.linalg.norm(tcp[:, None, :2] - obj[0, :, :2], axis=2)
    low = tcp[:, 2] < .06
    closing = command[:, 6] < .06
    close = first(closing)
    low_index = first(low)
    ref = close if close is not None else int(np.argmin(tcp[:, 2]))
    # Report geometry to every object; nearest identity is not itself a grasp.
    nearest = int(xy[ref].argmin())
    heights = obj[:, :, 2] - obj[0, :, 2]
    lifted = heights.max(axis=0) > .05
    bilat = (d["diagnostic_normal_force"] > .05).all(axis=1)
    target_lift = heights[:, ci] > .05
    target_xy = xy[:, ci]
    before = slice(0, min(ref + 1, n))
    low_ids = np.flatnonzero(low)
    low_best = int(low_ids[np.argmin(target_xy[low_ids])]) if len(low_ids) else None
    # First close, descent and fixed 1.5s location use separate fields.
    row = dict(evaluation=path.parent.name, split=result["split"], layout=result["layout_seed"], target=color,
        base_seed=int(path.parent.name[-2:]), success=result["success"], error=result["error"], frames=n,
        source=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        first_close_frame=close, first_low_frame=low_index,
        close_time_s=close / 20 if close is not None else None,
        close_tcp_height_mm=float(tcp[ref, 2] * 1000),
        close_target_xy_mm=float(target_xy[ref] * 1000), close_nearest_color=COLORS[nearest],
        close_nearest_xy_mm=float(xy[ref, nearest] * 1000),
        close_nearest_is_target=nearest == ci, close_width_command_m=float(command[ref, 6]),
        close_object_local_mm=(d["diagnostic_object_in_tcp"][ref] * 1000).tolist(),
        close_orientation_error_deg=float(d["diagnostic_orientation_error_deg"][ref]),
        close_xy_by_color_mm=(xy[ref] * 1000).tolist(),
        low_target_xy_mm=float(target_xy[low_index] * 1000) if low_index is not None else None,
        low_nearest_color=COLORS[int(xy[low_index].argmin())] if low_index is not None else None,
        best_low_target_xy_mm=float(target_xy[low_best] * 1000) if low_best is not None else None,
        approach30_target_xy_mm=float(initial_xy[min(30, n - 1), ci] * 1000),
        approach30_nearest_color=COLORS[int(initial_xy[min(30, n - 1)].argmin())],
        approach30_tcp=tcp[min(30, n - 1)].tolist(),
        target_lifted_5cm=bool(lifted[ci]),
        non_target_lifted_5cm=bool(any(lifted[i] for i in range(3) if i != ci)),
        lifted_colors=[COLORS[i] for i in range(3) if lifted[i]],
        target_first_contact_frame=first(d["diagnostic_contact_count"].sum(axis=1) > 0),
        target_first_bilateral_frame=first(bilat), target_bilateral_frames=int(bilat.sum()),
        target_first_bilateral_lift_frame=first(bilat & target_lift),
        target_peak_height_mm=float(heights[:, ci].max() * 1000),
        joint_raw_to_executed_mae_rad=float(np.mean(abs(d["raw_action"][:, :6] - command[:, :6]))),
        joint_command_to_feedback_mae_rad=float(np.mean(abs(command[:, :6] - d["state_after"][:, :6]))),
        initial_object_positions=obj[0].tolist(),
        distractor_max_xy_displacement_mm=float(max(np.max(np.linalg.norm(obj[:, i, :2] - obj[0, i, :2], axis=1))
                                                   for i in range(3) if i != ci) * 1000))
    if row["success"]:
        row["failure_class"] = "success"
    elif row["non_target_lifted_5cm"]:
        row["failure_class"] = "wrong_object_lifted"
    elif not row["close_nearest_is_target"] and row["close_nearest_xy_mm"] < 40:
        row["failure_class"] = "closed_near_wrong_object_without_lift"
    elif not row["target_lifted_5cm"]:
        row["failure_class"] = "target_grasp_or_approach_failure"
    else:
        row["failure_class"] = "failure_after_target_lift"
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [analyze(path) for path in sorted((RUN / "evaluations").glob("*/layout_*.npz"))]
    save(OUT / "trajectory_metrics.json", rows)
    flat = [{k: v for k, v in r.items() if not isinstance(v, (list, dict))} for r in rows]
    with (OUT / "trajectory_metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
        writer.writeheader(); writer.writerows(flat)
    grouped = []
    for group in sorted({r["evaluation"] for r in rows}):
        rr = [r for r in rows if r["evaluation"] == group]
        classes = {kind: sum(r["failure_class"] == kind for r in rr) for kind in sorted({r["failure_class"] for r in rr})}
        grouped.append(dict(evaluation=group, n=len(rr), successes=sum(r["success"] for r in rr),
            close_nearest_is_target=sum(r["close_nearest_is_target"] for r in rr),
            target_lifted=sum(r["target_lifted_5cm"] for r in rr),
            wrong_object_lifted=sum(r["non_target_lifted_5cm"] for r in rr),
            median_approach30_target_xy_mm=statistics.median(r["approach30_target_xy_mm"] for r in rr),
            median_close_target_xy_mm=statistics.median(r["close_target_xy_mm"] for r in rr),
            median_close_nearest_xy_mm=statistics.median(r["close_nearest_xy_mm"] for r in rr),
            median_close_orientation_deg=statistics.median(r["close_orientation_error_deg"] for r in rr),
            median_joint_tracking_mae_rad=statistics.median(r["joint_command_to_feedback_mae_rad"] for r in rr),
            failure_classes=classes))
    pairs = []
    for old in [r for r in rows if r["evaluation"].startswith("baseline")]:
        new = next(r for r in rows if r["evaluation"].startswith("update_8040_validation") and
                   all(r[k] == old[k] for k in ("layout", "target", "base_seed")))
        assert np.allclose(old["initial_object_positions"], new["initial_object_positions"], atol=1e-10, rtol=0)
        pairs.append({"layout": old["layout"], "target": old["target"], "base_seed": old["base_seed"],
                      "old_success": old["success"], "new_success": new["success"],
                      "old_close_target_mm": old["close_target_xy_mm"], "new_close_target_mm": new["close_target_xy_mm"],
                      "new_failure_class": new["failure_class"], "new_nearest_color": new["close_nearest_color"]})
    save(OUT / "paired_validation.json", pairs)
    save(OUT / "lost_success_cases.json", [p for p in pairs if p["old_success"] and not p["new_success"]])
    # Same layout's three prompts: approach positions compared to distinct targets.
    prompt_rows = []
    for group in sorted({r["evaluation"] for r in rows}):
        for layout in sorted({r["layout"] for r in rows if r["evaluation"] == group}):
            rr = [r for r in rows if r["evaluation"] == group and r["layout"] == layout]
            pos = np.array([r["approach30_tcp"][:2] for r in rr])
            prompt_rows.append({"evaluation": group, "layout": layout,
                "mean_between_prompt_xy_mm_at_1p5s": float(np.mean([np.linalg.norm(pos[i] - pos[j]) * 1000
                    for i in range(3) for j in range(i + 1, 3)])),
                "selected_nearest_colors": [r["approach30_nearest_color"] for r in rr],
                "all_prompts_nearest_same_object": len({r["approach30_nearest_color"] for r in rr}) == 1})
    save(OUT / "prompt_conditioned_approach.json", prompt_rows)
    profiles = {k: {"type": type(flat[0][k]).__name__, "missing": sum(r[k] is None for r in flat),
                        "unique": len({str(r[k]) for r in flat})} for k in flat[0]}
    save(OUT / "data_profile.json", {"rows": len(rows), "groups": len(grouped), "columns": profiles,
         "unit": "episode; colors and seeds within a layout are correlated; no significance tests",
         "figures": "paired case traces, per-case targeting errors and explicit count tables"})
    save(OUT / "trajectory_summary.json", {"groups": grouped, "validation_pairs": len(pairs),
        "old_success_new_failure": sum(p["old_success"] and not p["new_success"] for p in pairs),
        "old_failure_new_success": sum(not p["old_success"] and p["new_success"] for p in pairs),
        "same_initial_layout_verified": True,
        "definitions": {"close": "first executed opening command <0.06m", "low": "first TCP z <0.06m",
                        "wrong_object_lift": "any non-target rises >0.05m above its initial center",
                        "bilateral_contact": "target normal force >0.05N on both fingers",
                        "failure_priority": "success, non-target lift, wrong-object closure, pre-lift failure, post-lift failure"}})
    print(json.dumps({"groups": grouped, "lost_pairs": [p for p in pairs if p["old_success"] and not p["new_success"]]}, indent=2))


if __name__ == "__main__":
    main()
