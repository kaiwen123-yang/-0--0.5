"""Validate completed evaluation records, action arrays, and every saved video."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess

from summarize_libero_comparison import build_summary, read_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    # Validate the current authoritative records instead of trusting a summary
    # that could predate the last episode append or a later manifest change.
    manifest, rows, task_ids, missing = read_run(run)
    summary = build_summary(manifest, rows, task_ids, missing)
    if summary["status"] != "complete" or summary["error_episodes"]:
        raise SystemExit("The run is incomplete or has errors; cannot validate it as complete")
    planned_keys = {
        (model, suite, task, trial)
        for model in manifest["models"]
        for suite in manifest["suites"]
        for task in task_ids[suite]
        for trial in range(manifest["trials_per_task"])
    }
    assert len(rows) == len(planned_keys) == manifest["expected_episodes"]
    keys = {(r["model"], r["suite"], r["task_id"], r["trial_index"]) for r in rows}
    assert len(keys) == len(rows)
    assert keys == planned_keys, "Recorded episode keys differ from the planned evaluation grid"
    assert summary["paired_comparison"]["overall"]["complete"]
    assert not summary["paired_comparison"]["overall"]["mismatched_pairs"]

    import numpy as np

    def check(row):
        video = (run / row["video_path"]).resolve()
        actions_file = (run / row["actions_path"]).resolve()
        assert video.is_relative_to(run) and actions_file.is_relative_to(run)
        assert video.stat().st_size > 0
        actions = np.load(actions_file, allow_pickle=False)
        assert actions.shape == (row["steps"], 7), actions_file
        assert np.isfinite(actions).all(), actions_file
        assert 0 < row["steps"] <= row["max_action_steps"]
        if row["status"] == "failure":
            assert row["steps"] == row["max_action_steps"]
        assert row["video_frames"] == row["steps"] + 1
        assert row["inference_calls"] == (row["steps"] + row["replan_steps"] - 1) // row["replan_steps"]
        assert row["server_metadata"]["model"] == row["model"]
        assert row["server_metadata"]["run_id"] == run.name
        info = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,codec_name,avg_frame_rate,nb_frames,duration", "-of", "json", str(video)
        ], text=True, timeout=15))["streams"][0]
        assert (info["width"], info["height"]) == (448, 224), video
        assert info["codec_name"] == "h264", video
        assert Fraction(info["avg_frame_rate"]) == row["video_fps"] == 20, video
        assert int(info["nb_frames"]) == row["video_frames"], video
        assert abs(float(info["duration"]) - row["video_frames"] / 20) < 0.002, video
        return {"model": row["model"], "suite": row["suite"], "task_id": row["task_id"],
                "trial_index": row["trial_index"], "video_path": row["video_path"],
                "video_bytes": video.stat().st_size,
                "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "video_frames": int(info["nb_frames"]), "actions_shape": list(actions.shape),
                "actions_sha256": hashlib.sha256(actions_file.read_bytes()).hexdigest()}

    with ThreadPoolExecutor(max_workers=4) as executor:
        artifacts = list(executor.map(check, rows))
    assert len({r["video_path"] for r in rows}) == len(rows)
    partial = list((run / "videos").rglob("*.partial.mp4"))
    assert not partial, partial
    report = {"status": "passed", "checked_at": datetime.now(timezone.utc).isoformat(),
              "episodes": len(rows), "videos": len(artifacts), "action_arrays": len(artifacts),
              "total_video_bytes": sum(a["video_bytes"] for a in artifacts),
              "paired_initial_conditions": "all state hashes, state indices, environment and policy seeds match",
              "video_validation": "ffprobe headers/frame count/duration plus file SHA256; not full decode of every frame",
              "artifacts": artifacts}
    (run / "artifact-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "artifacts"}, indent=2))


if __name__ == "__main__":
    main()
