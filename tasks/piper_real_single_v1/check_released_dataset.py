"""Independently check the 2026-11-24 blue/red release using Python and NumPy."""
import argparse
from collections import Counter
import json
from pathlib import Path
from uuid import UUID

import numpy as np


PERIOD_NS = 50_000_000
HORIZON = 10
SOURCES = {
    "arm_action_source": "future_measured_joint_positions",
    "gripper_action_source": "future_measured_sdk_width",
    "future_offset_ns": PERIOD_NS,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def array(path):
    return np.load(path, allow_pickle=False, mmap_mode="r")


def check_episode(root, entry, aligned):
    episode_id = entry["directory"]
    require(str(UUID(episode_id)) == episode_id, "invalid episode directory")
    p = root / episode_id
    n = entry["frames"]
    require(n > 0 and aligned["directory"] == episode_id and entry["run_id"] == episode_id
            and aligned["source_trajectory_id"] == episode_id, "episode/source mismatch")
    for key in ("split", "target_color", "scene_colors", "prompt", "outcome", "actual_grasped_color",
                "run_id", "intervention", "destination_id", "training_eligible", "valid_action_starts",
                "usable_starts", "excluded_rows", "action_horizon", "collection_mode", *SOURCES):
        require(aligned[key] == entry[key], f"index and alignment disagree on {key}")
    color = entry["target_color"]
    scene = entry["scene_colors"]
    require(color in ("blue", "red") and len(set(scene)) == len(scene)
            and set(scene) in ({"blue", "red"}, {"blue", "red", "white", "green"}), "invalid scene")
    require(entry["prompt"] == f"Pick up the {color} block, place it in the shallow tray, release it, and retreat."
            and entry["actual_grasped_color"] == color and entry["outcome"] == "success"
            and entry["intervention"] == "no" and entry["training_eligible"] is True
            and entry["destination_id"] == "fixed_shallow_tray", "task or review mismatch")
    require(entry["collection_mode"] == "kinesthetic_manual_gripper_v1"
            and all(entry[key] == val for key, val in SOURCES.items()), "unsupported action provenance")
    require(entry["valid_action_starts"] == "valid_action_starts.npy"
            and entry["action_horizon"] == HORIZON
            and aligned["sources"] == f"{episode_id}/row_sources.jsonl", "source file or horizon mismatch")

    state, action = array(p / "state.npy"), array(p / "actions.npy")
    t = array(p / "policy_timestamps_ns.npy")
    starts = array(p / "valid_action_starts.npy")
    require(t.shape == (n,) and t.dtype == np.int64 and np.all(np.diff(t) == PERIOD_NS), "invalid 20 Hz grid")
    require(state.shape == action.shape == (n, 7) and state.dtype == action.dtype == np.float32,
            "state or action shape/dtype mismatch")
    require(np.array_equal(state[1:], action[:-1], equal_nan=True), "next-row measured targets disagree")
    sources = [json.loads(line) for line in (p / "row_sources.jsonl").read_text(encoding="utf-8").splitlines()]
    require(len(sources) == n, "row provenance count mismatch")
    valid = np.empty(n, dtype=bool)
    for i, row in enumerate(sources):
        tick = int(t[i])
        anchor = tick + PERIOD_NS
        require(row["t"] == tick and row["action_at_ns"] == anchor
                and all(row[key] == val for key, val in SOURCES.items()), f"grid/source mismatch at {i}")
        require(max(row["image_ns"], row["q_ns"], row["grip_ns"]) <= tick
                and max(row["future_joint_ns"], row["future_grip_ns"]) <= anchor, f"noncausal source at {i}")
        require(type(row["training_row_valid"]) is bool and isinstance(row["excluded_reasons"], list)
                and row["training_row_valid"] == (not row["excluded_reasons"]), f"validity mismatch at {i}")
        valid[i] = row["training_row_valid"]
        if valid[i]:
            require(min(row["future_joint_ns"], row["future_grip_ns"]) > tick
                    and tick-min(row["image_ns"], row["q_ns"], row["grip_ns"]) <= 100_000_000,
                    f"stale usable source at {i}")
        if i:
            prev = sources[i-1]
            require((prev["future_joint_ns"], prev["future_grip_ns"], prev["future_joint_id"], prev["future_grip_id"])
                    == (row["q_ns"], row["grip_ns"], row["q"], row["grip"]), f"source discontinuity at row {i}")
    for a in (state[valid], action[valid]):
        require(np.isfinite(a).all() and np.all((0 <= a[:, 6]) & (a[:, 6] <= .10)),
                "nonfinite or out-of-range width in rows marked usable")
    # The recorded policy repeats the last row to pad a chunk crossing the episode end.
    padded_valid = np.pad(valid, (0, HORIZON-1), mode="edge")
    expected = np.flatnonzero(np.lib.stride_tricks.sliding_window_view(padded_valid, HORIZON).all(axis=1))
    require(starts.dtype == np.int64 and np.array_equal(expected, starts) and len(starts) > 0,
            "stored starts differ from recomputation")
    q = read_json(p / "quality.json")
    excluded = n - int(valid.sum())
    require(entry["usable_starts"] == q["usable_starts"] == len(starts)
            and entry["excluded_rows"] == q["excluded_rows"] == excluded and q["grid_rows"] == n,
            "index or quality totals differ")
    require(q["host_frames"] == q["queue_drops"] == 0, "unexpected host TX or RGB queue drops")
    marks = q["events"]
    require([m["event"] for m in marks] == ["start", "close", "open", "end"]
            and np.all(np.diff([m["mono_ns"] for m in marks]) > 0) and marks[0]["mono_ns"] == t[0]
            and t[-1]+PERIOD_NS <= marks[-1]["mono_ns"] < t[-1]+2*PERIOD_NS
            and aligned["task_end"] == marks[-1] and marks[-1]["operator_task_success"] is True,
            "incomplete or inconsistent task markers")
    mark_coverage = {}
    full = starts[starts + HORIZON <= n]
    for mark in marks[1:3]:
        ns = mark["mono_ns"]
        mark_coverage[mark["event"]] = int(np.count_nonzero((t[full] <= ns) & (ns < t[full] + HORIZON*PERIOD_NS)))
    rgb_path = p / "camera_rgb.npy"
    if rgb_path.exists():
        rgb = array(rgb_path)
        require(rgb.shape == (n, 480, 640, 3) and rgb.dtype == np.uint8, "unexpected RGB shape/dtype")
    return Counter(episodes=1, grid_rows=n, valid_rows=int(valid.sum()), valid_starts=len(starts),
                   full_unpadded_starts=len(full), rgb_arrays=int(rgb_path.exists())), mark_coverage


def check(root):
    md = read_json(root / "dataset.json")
    index = read_json(root / "index.json")
    alignment = read_json(root / "alignment_manifest.json")
    require(md["policy_hz"] == 20 and md["collection_view"] == "blue_red"
            and md["target_colors"] == ["blue", "red"] and md["camera_mount"] == "wrist"
            and md["camera_id"] == "CC16762023M" and md["gripper_basis"] == "piper_h_sdk_width_m_v1"
            and md["training_eligible"] is True
            and md["timestamp_alignment_source"] == "alignment_manifest.json"
            and alignment["period_ns"] == PERIOD_NS, "wrong dataset contract")
    align = {a["directory"]: a for a in alignment["episodes"]}
    ids = [e["directory"] for e in index]
    require(len(index) == len(set(ids)) == len(alignment["episodes"]) == 50 and set(ids) == set(align),
            "missing, duplicate or extra episode identifiers")
    totals = {"train": Counter(), "validation": Counter()}
    colors = {s: Counter() for s in totals}
    pairs, sessions = {}, {}
    sparse_events = []
    for e in index:
        a = align[e["directory"]]
        try:
            counts, mark_cov = check_episode(root, e, a)
        except (KeyError, OSError, ValueError) as err:
            raise ValueError(f"{e['directory']}: {err}") from err
        split, color = e["split"], e["target_color"]
        require(split in totals and a["session_id"] and a["placement_id"], "invalid split or layout identity")
        require(sessions.setdefault(a["session_id"], split) == split, "cross-split session")
        session, scene, targets = pairs.setdefault(a["placement_id"], (a["session_id"], set(e["scene_colors"]), []))
        require(session == a["session_id"] and scene == set(e["scene_colors"]), "layout identity reused")
        targets.append(color)
        colors[split][color] += 1
        totals[split].update(counts)
        if min(mark_cov.values()) < HORIZON:
            sparse_events.append(dict(placement=a["placement_id"],target=color, coverage=mark_cov))
    require(all(sorted(v[2]) == ["blue", "red"] for v in pairs.values()), "missing or extra paired target")
    require(colors["train"] == {"blue": 20, "red": 20} and colors["validation"] == {"blue": 5, "red": 5},
            "50-example quota differs")
    rgb = sum(x["rgb_arrays"] for x in totals.values())
    require(rgb in (0, 50), "incomplete RGB set: use all 50 RGB arrays or the numeric-only companion")
    return dict(validation="passed", mode="full_array_headers" if rgb else "numeric_only", by_split=totals,
                colors=colors, layouts=len(pairs), partial_mark_coverage=sparse_events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Directory containing dataset.json and index.json")
    parser.add_argument("--require-rgb", action="store_true", help="Require the full release with all 50 RGB arrays")
    args = parser.parse_args()
    summary = check(args.dataset)
    if args.require_rgb:
        require(summary["mode"] == "full_array_headers", "RGB arrays absent from a requested full release check")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
