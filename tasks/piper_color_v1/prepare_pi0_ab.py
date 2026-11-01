"""Freeze the authorized A/B adaptation contract without copying large inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / "outputs/pi0-ab-old2010-20261101"
OLD_RUN = ROOT / "outputs/pi0-six-demo-20261031"
OLD = OLD_RUN / "checkpoints/pi0_piper_color_lora/six_demo_v1/2010"
V2 = ROOT / "outputs/pi0-120-demo-v2-20261101"
DIAG = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"
BRANCH = "codex/pi0-ab-old2010-20261101"
ASSET = "piper_h_color_v1"
BUDGET, BATCH, BASE = 2010, 4, 2010


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False))
    temp.replace(path)


def main():
    if CAMPAIGN.exists():
        raise FileExistsError(f"Inspect existing campaign before restart: {CAMPAIGN}")
    if shutil.disk_usage(ROOT).free < 75 * 1024**3:
        raise RuntimeError("Need 75 GiB free for bounded new checkpoints and trajectories")
    for item in ("params", "train_state", "resume.json", f"assets/{ASSET}/norm_stats.json"):
        if not (OLD / item).exists():
            raise FileNotFoundError(OLD / item)
    source_resume = json.loads((OLD / "resume.json").read_text())
    if source_resume["completed_updates"] != BASE:
        raise ValueError("Wrong fork state")
    entries = json.loads((V2 / "dataset/index.json").read_text())
    expected = {(s, c) for s in range(100, 140) for c in ("red", "green", "blue")}
    if (len(entries) != 120 or {(e["layout_seed"], e["target"]) for e in entries} != expected
            or any(e["split"] != "train" or e["frames"] != 268 for e in entries)):
        raise ValueError("Expected frozen 120 x 268 train starts")
    frozen = json.loads((V2 / "normalization.json").read_text())
    checked = []
    for e in frozen["selected_episodes"]:
        for key, digest in e["array_sha256"].items():
            p = V2 / "dataset" / e["directory"] / f"{key}.npy"
            if sha(p) != digest:
                raise ValueError(f"Frozen training array changed: {p}")
            checked.append({"path": str(p), "bytes": p.stat().st_size, "sha256": digest})
    if len(checked) != 480:
        raise ValueError("Incomplete training-array provenance")
    manifest_sha = sha(V2 / "dataset/manifest.json")
    if manifest_sha != frozen["source_manifest_sha256"]:
        raise ValueError("Dataset manifest changed")
    checkpoint_files = [{"path": str(p.relative_to(OLD)), "bytes": p.stat().st_size, "sha256": sha(p)}
                        for p in sorted(OLD.rglob("*")) if p.is_file()]
    baseline = json.loads((DIAG / "evidence_summary.json").read_text())
    baseline_fixed = next(r for r in baseline["fixed"] if r["model"] == "old2010")
    contract = {"branch": BRANCH, "order": ["A", "B"], "base_updates": BASE,
        "new_updates_per_group": BUDGET, "batch": BATCH, "horizon": 10, "executed_actions": 5,
        "learning_rate": 3e-6, "new_warmup_steps": 0, "seed": 42,
        "old_checkpoint": str(OLD), "old_resume": source_resume,
        "old_checkpoint_files": checkpoint_files, "old_train_config_sha256": sha(OLD_RUN / "train_config.txt"),
        "dataset": str(V2 / "dataset"), "dataset_manifest_sha256": manifest_sha,
        "dataset_index_sha256": sha(V2 / "dataset/index.json"),
        "scene_sha256": sha(V2 / "scene/scene.xml"),
        "normalization_sha256": sha(OLD / f"assets/{ASSET}/norm_stats.json"),
        "evaluation_nodes_local": [500, 1000, 2010], "publish_nodes_local": [500, 1000, 1500, 2000, 2010],
        "evaluation": {"training_layouts": [100, 101], "validation_layouts": list(range(1000, 1005)),
                       "base_seeds": [42, 43], "max_steps": 420, "stable_success_steps": 40},
        "baseline_fixed": baseline_fixed,
        "baseline_validation_successes": [5, 6],
        "baseline_sources": {str(p): sha(p) for p in [DIAG / "evidence_summary.json",
            DIAG / "fixed/old2010/prompt_swap.json", V2 / "evaluations/baseline_old2010_v2_validation_seed42/summary.json",
            V2 / "evaluations/baseline_old2010_v2_validation_seed43/summary.json"]},
        "candidate_rule": "validation only: all engineering gates, minimum seed successes, total successes, prompt matches; earlier node breaks ties",
        "early_stop": "stop that group if baseline > node500 > node1000 prompt-match counts; B still starts independently from old2010",
        "checkpoint_retention": "latest two plus validation-selected candidate per group; prune superseded non-candidates before saving; new checkpoint total <=60GiB",
        "test_split_used": False, "hardware_execution": False,
        "changed_from_old_training": ["120 frozen v2 training demonstrations", "constant 3e-6 learning rate without new warmup",
                                      "fresh local sampler offset 0", "A uniform versus B weighted starts"],
        "rng_rule": "same old train_rng; upstream folds with cumulative train_state.step (2010 + local step before update)"}
    CAMPAIGN.mkdir()
    (CAMPAIGN / "logs").mkdir()
    save(CAMPAIGN / "contract.json", contract)
    save(CAMPAIGN / "verified_training_arrays.json", checked)
    save(CAMPAIGN / "teacher_reference_files.json", [
        {"path": str(p), "sha256": sha(p), "bytes": p.stat().st_size}
        for p in sorted((DIAG / "teacher_reference").glob("layout_*.npz"))])
    # Common random numbers couple color/layout choices; only inverse-CDF frame distribution differs.
    streams = np.random.SeedSequence(42).spawn(3)
    n = BUDGET * BATCH
    color_ids = np.random.default_rng(streams[0]).integers(0, 3, n)
    layout_ids = np.random.default_rng(streams[1]).integers(100, 140, n)
    u = np.random.default_rng(streams[2]).random(n)
    lookup = {(e["layout_seed"], e["target"]): i for i, e in enumerate(entries)}
    colors = ("red", "green", "blue")
    episode_ids = np.array([lookup[(int(s), colors[int(c)])] for s, c in zip(layout_ids, color_ids)])
    for group in ("A", "B"):
        run = CAMPAIGN / group
        run.mkdir()
        (run / "logs").mkdir()
        (run / "dataset").symlink_to(V2 / "dataset", target_is_directory=True)
        shutil.copytree(V2 / "scene", run / "scene")
        shutil.copytree(OLD / "assets", run / "assets")
        (run / "probes").mkdir()
        (run / "probes/teacher_reference").symlink_to(DIAG / "teacher_reference", target_is_directory=True)
        if group == "A":
            frames = np.floor(u * 268).astype(np.int64)
        else:
            frames = np.where(u < .4, np.floor(u / .4 * 10),
                      np.where(u < .7, 10 + np.floor((u - .4) / .3 * 52),
                               62 + np.floor((u - .7) / .3 * 206))).astype(np.int64)
        order = episode_ids * 268 + frames
        np.save(run / "sample_order.npy", order, allow_pickle=False)
        # Text equivalent is committed, so the exact sample schedule is available from Git.
        save(run / "sample_order.json", order.tolist())
        sample_contract = {"group": group, "samples": n, "seed": 42,
            "implementation": "NumPy PCG64, SeedSequence(42).spawn(3): color, layout, inverse-CDF frame",
            "color_probabilities": [1/3] * 3, "layout_probabilities": "1/40 conditional on color",
            "frame_probabilities": "uniform 0..267" if group == "A" else "0.4/10 for 0..9; 0.3/52 for 10..61; 0.3/206 for 62..267",
            "realized_color_counts": {c: int((color_ids == i).sum()) for i, c in enumerate(colors)},
            "realized_phase_counts": [int((frames < 10).sum()), int(((frames >= 10) & (frames < 62)).sum()), int((frames >= 62).sum())],
            "sample_order_sha256": sha(run / "sample_order.npy"), "new_sample_offset": 0,
            "data_index_sha256": contract["dataset_index_sha256"], "normalization_sha256": contract["normalization_sha256"],
            "sampler_with_replacement": True, "new_demonstrations": 0}
        save(run / "sampler.json", sample_contract)
    print("PREPARED " + json.dumps({"campaign": str(CAMPAIGN), "verified_arrays": len(checked),
         "source_checkpoint_bytes": sum(r["bytes"] for r in checkpoint_files)}), flush=True)


if __name__ == "__main__":
    main()
