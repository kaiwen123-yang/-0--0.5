"""Count independent blue/red layout pairs and check the frozen 20/5 split."""
import argparse
import json
from pathlib import Path

import numpy as np

if __package__:
    from .color_task import BLUE_RED, recorded_task
    from .dataset import GRIP_SOURCES, formal_entries
else:
    from color_task import BLUE_RED, recorded_task
    from dataset import GRIP_SOURCES, formal_entries


REQUIRED_PAIRS = {"train": 20, "validation": 5}


def _read(path):
    return json.loads(path.read_text())


def _report(episodes, *, frozen=False):
    layouts = {split: {} for split in REQUIRED_PAIRS}
    session_splits, placements, source_tasks, run_ids = {}, {}, {}, {}
    episode_counts = {split: dict.fromkeys(BLUE_RED, 0) for split in layouts}
    for split, session, placement, source, run_id, color, scene in episodes:
        if not all((session, placement, source, run_id)) or split not in layouts:
            raise ValueError(f"Missing collection identity in {run_id}")
        if session_splits.setdefault(session, split) != split:
            raise ValueError(f"Session {session} appears in both splits")
        if placements.setdefault(placement, (session, tuple(scene))) != (session, tuple(scene)):
            raise ValueError(f"Conflicting session or scene for {placement}")
        identity = (split, session, placement, color)
        seen_source = source in source_tasks
        if (source_tasks.setdefault(source, identity) != identity
                or run_ids.setdefault(run_id, (source, identity)) != (source, identity)):
            raise ValueError(f"Reused source or run with different identity: {run_id}")
        if seen_source:
            if frozen:
                raise ValueError(f"Frozen view contains repeated source: {source}")
            continue
        episode_counts[split][color] += 1
        layouts[split].setdefault(placement, set()).add(color)
    counts = {s: {c: sum(c in colors for colors in groups.values()) for c in BLUE_RED}
              for s, groups in layouts.items()}
    pairs = {s: sum(set(BLUE_RED) == colors for colors in groups.values())
             for s, groups in layouts.items()}
    missing = {s: {c: max(0, n-counts[s][c]) for c in BLUE_RED} for s,n in REQUIRED_PAIRS.items()}
    missing_pairs = {s: max(0, n-pairs[s]) for s,n in REQUIRED_PAIRS.items()}
    ready = not any(missing_pairs.values())
    # A raw collection may have spare successes. The trainable frozen view must
    # contain precisely the authorized episodes, including one per layout/target.
    if frozen:
        ready = ready and all(episode_counts[s][c] == n for s,n in REQUIRED_PAIRS.items() for c in BLUE_RED)
    return dict(ready=ready, counts=counts, episode_counts=episode_counts, paired_layouts=pairs,
                missing=missing, missing_paired_layouts=missing_pairs,
                layouts={s: {p:[c for c in BLUE_RED if c in colors] for p,colors in groups.items()}
                         for s,groups in layouts.items()})


def assess_sessions(train_sessions, validation_sessions):
    """Count sealed, approved direct demonstrations. Skip active/failed attempts."""
    episodes = []
    for split, paths in (("train", train_sessions), ("validation", validation_sessions)):
        for session in sorted({Path(path).resolve() for path in paths}):
            allocation = _read(session/"session.json")
            if allocation["split"] != split or Path(allocation["session_directory"]).resolve() != session:
                raise ValueError(f"Session allocation mismatch: {session}")
            for directory in sorted(session.glob("*_teach")):
                review_path, run_path = directory/"review.json", directory/"run.json"
                if not review_path.is_file() or not run_path.is_file():
                    continue
                review, run = _read(review_path), _read(run_path)
                if not review.get("approved_teach"):
                    continue
                task = recorded_task(run)
                if task != recorded_task(review):
                    raise ValueError(f"Reviewed instruction differs: {directory}")
                color = task["target_color"]
                if color not in BLUE_RED:
                    continue
                if (not run.get("complete") or run.get("kind") != "teach" or run.get("use") != "formal"
                        or run.get("collection_mode") not in GRIP_SOURCES
                        or run.get("stop") != "demonstration_finished"
                        or run.get("split") != split or run.get("session_id") != allocation["session_id"]
                        or run.get("source_trajectory_id") != run.get("run_id")
                        or review.get("outcome") != "success" or review.get("intervention") != "no"
                        or review.get("actual_grasped_color") != color
                        or any(review.get(k) != run.get(k)
                               for k in ("run_id", "source_trajectory_id", "session_id", "placement"))):
                    raise ValueError(f"Approved review conflicts with its sealed source: {directory}")
                episodes.append((split, run["session_id"], run["placement"], run["source_trajectory_id"],
                                 run["run_id"], color, task["scene_colors"]))
    return _report(episodes)


def assess_frozen(dataset_root):
    """Require actual eligible training windows and the requested frozen Stage A split."""
    root = Path(dataset_root).resolve()
    metadata = _read(root/"dataset.json")
    if metadata.get("collection_view") != "blue_red" or metadata.get("target_colors") != list(BLUE_RED):
        raise ValueError("Frozen budget check requires a Stage A blue/red view")
    align = _read(root/metadata["timestamp_alignment_source"])
    by_id = {a["directory"]:a for a in align["episodes"]}
    episodes = []
    for entry in formal_entries(root, "wrist", 20):
        directory = entry["directory"]
        a = by_id[directory]
        if (entry.get("collection_mode") not in GRIP_SOURCES or entry["target_color"] not in BLUE_RED
                or entry.get("valid_action_starts") != "valid_action_starts.npy"
                or entry.get("action_horizon") != 10):
            raise ValueError(f"Expected direct 10-step blue/red episode: {directory}")
        starts = np.load(root/directory/entry["valid_action_starts"], mmap_mode="r", allow_pickle=False)
        if (starts.ndim != 1 or not np.issubdtype(starts.dtype, np.integer)
                or len(starts) != entry.get("usable_starts") or not len(starts)
                or starts[0] < 0 or starts[-1] >= entry["frames"] or np.any(starts[1:] <= starts[:-1])):
            raise ValueError(f"Invalid usable action windows: {directory}")
        episodes.append((entry["split"], a["session_id"], a["placement_id"], a["source_trajectory_id"],
                         entry["run_id"], entry["target_color"], entry["scene_colors"]))
    return _report(episodes, frozen=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--train", nargs="+", type=Path)
    cli.add_argument("--validation", nargs="+", type=Path)
    cli.add_argument("--frozen", type=Path)
    cli.add_argument("--require-ready", action="store_true")
    args = cli.parse_args()
    if args.frozen is not None:
        if args.train or args.validation:
            cli.error("--frozen takes a Stage A view; omit session arguments")
        result = assess_frozen(args.frozen)
    else:
        if not args.train or not args.validation:
            cli.error("supply both --train and --validation, or use --frozen")
        result = assess_sessions(args.train, args.validation)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(args.require_ready and not result["ready"])


if __name__ == "__main__":
    raise SystemExit(main())
