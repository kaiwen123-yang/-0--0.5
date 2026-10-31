"""Fixed six-demo Pi0 run using OpenPI's real optimizer and checkpoint code."""
import argparse
import functools
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import subprocess
import time

OPENPI = Path(os.environ["PIPER_OPENPI"])
sys.path.insert(0, str(OPENPI))

import jax
import numpy as np
from flax import nnx
from openpi.shared import normalize
from openpi.training import checkpoints, data_loader as D, sharding
from dataset import PiperDataset
from policy_config import ASSET_ID, DATA, DELTA_MASK, RUN, make_pi0_config

UPDATES = (500, 1000, 1500, 2000, 2010)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def prepare():
    source = Path(os.environ["PIPER_SOURCE_DATA"]).resolve(strict=True)
    index = json.loads((source / "index.json").read_text())
    manifest = json.loads((source / "manifest.json").read_text())
    selected = [e for e in index if e["split"] == "train" and e["layout_seed"] in (100, 101)]
    expected = {(s, c) for s in (100, 101) for c in ("red", "green", "blue")}
    if len(selected) != 6 or {(e["layout_seed"], e["target"]) for e in selected} != expected:
        raise ValueError("Expected exactly two training layouts and all three colors")
    if sum(e["frames"] for e in selected) != 1608:
        raise ValueError("The fixed six-demo budget requires 1608 starts")
    DATA.mkdir(parents=True, exist_ok=False)
    stats = {k: normalize.RunningStats() for k in ("state", "actions")}
    provenance = []
    episodes = []
    for entry in selected:
        episode = next(e for e in manifest["episodes"]
                       if e["layout_seed"] == entry["layout_seed"] and e["target"] == entry["target"])
        source_npz = source / episode["file"]
        if not episode["success"] or episode["split"] != "train" or sha(source_npz) != episode["sha256"]:
            raise ValueError(f"Invalid teacher episode {source_npz}")
        directory = source / entry["directory"]
        hashes = {}
        with np.load(source_npz, allow_pickle=False) as archived:
            for key in ("state", "action", "external_rgb", "wrist_rgb"):
                array = np.load(directory / f"{key}.npy", mmap_mode="r")
                if not np.array_equal(array, archived[key]):
                    raise ValueError(f"Expanded data differs from teacher archive: {directory}/{key}")
                hashes[key] = sha(directory / f"{key}.npy")
        state, action = (np.load(directory / f"{key}.npy") for key in ("state", "action"))
        if state.shape != (entry["frames"], 7) or action.shape != state.shape:
            raise ValueError("Invalid actual demonstration state/action data")
        if not np.isfinite(state).all() or not np.isfinite(action).all():
            raise ValueError("Non-finite demonstration data")
        ids = np.minimum(np.arange(len(state))[:, None] + np.arange(10)[None, :], len(state) - 1)
        chunks = action[ids].copy()
        chunks[:, :, :6] -= state[:, None, :6]
        stats["state"].update(state)
        stats["actions"].update(chunks.reshape(-1, 7))
        link = DATA / entry["directory"]
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(directory, target_is_directory=True)
        npz_link = DATA / episode["file"]
        npz_link.parent.mkdir(parents=True, exist_ok=True)
        npz_link.symlink_to(source_npz)
        provenance.append({**entry, "npz_sha256": episode["sha256"], "array_sha256": hashes})
        episodes.append(episode)
    write_json(DATA / "index.json", selected)
    write_json(DATA / "manifest.json", {**manifest, "split_seeds": {"train": [100, 101], "validation": [], "test": []},
                                        "episodes": episodes, "source_manifest_sha256": sha(source / "manifest.json")})
    normalize.save(RUN / "assets" / ASSET_ID, {k: v.get_statistics() for k, v in stats.items()})
    order = np.concatenate([np.random.default_rng(42 + epoch).permutation(1608) for epoch in range(5)])
    np.save(RUN / "sample_order.npy", order, allow_pickle=False)
    write_json(RUN / "normalization.json", {
        "model_family": "pi0", "normalization": "mean_std", "state_input": "continuous",
        "split": "train", "frames": 1608, "episodes": 6, "horizon": 10,
        "action_delta_mask": DELTA_MASK, "heldout_used": False,
        "sample_order_sha256": sha(RUN / "sample_order.npy"),
        "sampling": "five complete permutations; numpy PCG64 seeds 42..46; saved order defines resume offset",
        "source_manifest_sha256": sha(source / "manifest.json"), "selected_episodes": provenance})
    print("PREPARED 6 demonstrations / 1608 starts / PI0 mean_std", flush=True)


class OrderedDataset:
    def __init__(self, dataset, order):
        self.dataset, self.order = dataset, order

    def __len__(self):
        return len(self.order)

    def __getitem__(self, index):
        return self.dataset[int(self.order[index])]


def train(resume=False):
    from scripts import train as upstream
    logging.basicConfig(level=logging.INFO)
    started = time.monotonic()
    cfg = make_pi0_config(resume=resume)
    dc = cfg.data.create(cfg.assets_dirs, cfg.model)
    if cfg.model.pi05 or cfg.model.discrete_state_input or dc.use_quantile_norm or dc.norm_stats is None:
        raise ValueError("Pi0 continuous state / mean-std normalization contract is not satisfied")
    config_text = repr(cfg)
    config_path = RUN / "train_config.txt"
    if resume and config_path.read_text() != config_text.replace("resume=True", "resume=False"):
        raise ValueError("Resume configuration differs from the saved configuration")
    if not resume:
        config_path.write_text(config_text)
    train_rng, init_rng = jax.random.split(jax.random.key(cfg.seed))
    mesh = sharding.make_mesh(cfg.fsdp_devices)
    data_sharding = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec(sharding.DATA_AXIS))
    replicated = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec())
    manager, resuming = checkpoints.initialize_checkpoint_dir(
        cfg.checkpoint_dir, keep_period=1, overwrite=False, resume=resume)
    start = int(manager.latest_step()) if resuming else 0
    if start >= cfg.num_train_steps:
        raise ValueError("Run already reached the fixed update budget")
    order = np.load(RUN / "sample_order.npy", allow_pickle=False)
    normalization = json.loads((RUN / "normalization.json").read_text())
    if sha(RUN / "sample_order.npy") != normalization["sample_order_sha256"] or len(order) != 8040:
        raise ValueError("Saved sampling order changed")
    if resuming:
        saved = json.loads((cfg.checkpoint_dir / str(start) / "resume.json").read_text())
        if saved["completed_updates"] != start or saved["sample_offset"] != start * cfg.batch_size:
            raise ValueError("Checkpoint state and sampler offset disagree")
        if saved["train_rng_key_data"] != jax.random.key_data(train_rng).tolist():
            raise ValueError("Resume RNG differs from saved RNG")
    dataset = OrderedDataset(PiperDataset(DATA, "train", 10), order[start * cfg.batch_size:])
    dataset = D.transform_dataset(dataset, dc)
    loader = D.DataLoaderImpl(dc, D.TorchDataLoader(
        dataset, cfg.batch_size, sharding=data_sharding, shuffle=False,
        num_workers=cfg.num_workers, seed=cfg.seed, num_batches=cfg.num_train_steps - start))
    state, state_sharding = upstream.init_train_state(cfg, init_rng, mesh, resume=resuming)
    if resuming:
        state = checkpoints.restore_state(manager, state, loader, step=start)
    jax.block_until_ready(state)
    report = {"model_family": "pi0", "mode": "lora", "requested_steps": 2010, "batch_size": 4,
              "seed": cfg.seed, "trainable_parameters": sum(x.size for x in jax.tree.leaves(state.params.filter(cfg.trainable_filter))),
              "total_parameters": sum(x.size for x in jax.tree.leaves(state.params.filter(nnx.Param))),
              "training_domain": "synthetic_piper_h", "hardware_execution": False,
              "completed": False, "completed_updates": start, "checkpoints": [],
              "initialization_seconds": time.monotonic() - started}
    write_json(RUN / "lora_training.json", report)
    print("TRAIN_INITIALIZED " + json.dumps(report), flush=True)
    step_fn = jax.jit(functools.partial(upstream.train_step, cfg),
                      in_shardings=(replicated, state_sharding, data_sharding),
                      out_shardings=(state_sharding, replicated), donate_argnums=(1,))
    durations = []
    try:
        for completed, batch in enumerate(loader, start=start + 1):
            step_start = time.monotonic()
            with sharding.set_mesh(mesh):
                state, info = step_fn(train_rng, state, batch)
            info = jax.device_get(info)
            values = {k: float(v) for k, v in info.items()}
            if not np.isfinite(list(values.values())).all():
                raise RuntimeError(f"Non-finite metrics at update {completed}: {values}")
            elapsed = time.monotonic() - step_start
            durations.append(elapsed)
            row = {"step": completed, **values, "wall_time": time.time(), "compute_seconds": elapsed}
            row.update(sample_starts_seen=completed * cfg.batch_size,
                       equivalent_start_epochs=completed * cfg.batch_size / 1608)
            with (RUN / "lora_metrics.jsonl").open("a") as f:
                f.write(json.dumps(row) + "\n")
            report["completed_updates"] = completed
            if completed == start + 1 or completed % 10 == 0:
                write_json(RUN / "training_progress.json", {**row, "requested_steps": 2010})
                print("UPDATE " + json.dumps(row), flush=True)
            if completed % 100 == 0:
                recent = durations[max(10, len(durations) - 90):]
                if recent:
                    write_json(RUN / "training_eta.json", {
                        "completed_updates": completed, "mean_compute_seconds": float(np.mean(recent)),
                        "median_compute_seconds": float(np.median(recent)),
                        "remaining_compute_seconds": float(np.mean(recent) * (2010 - completed)),
                        "excludes": "checkpoint IO, evaluation, and future contention changes"})
            if completed in UPDATES:
                if int(state.step) != completed:
                    raise ValueError("Checkpoint update counter differs from train state")
                checkpoints.save_state(manager, state, loader, completed)
                manager.wait_until_finished()
                checkpoint = cfg.checkpoint_dir / str(completed)
                write_json(checkpoint / "resume.json", {
                    "completed_updates": completed, "sample_offset": completed * cfg.batch_size,
                    "sample_order_sha256": normalization["sample_order_sha256"],
                    "train_rng_key_data": jax.random.key_data(train_rng).tolist(),
                    "rng_rule": "OpenPI folds train_rng with restored train_state.step",
                    "config_sha256": sha(config_path), "optimizer_saved_by": "OpenPI train_state item"})
                report["checkpoints"].append(str(checkpoint))
                report["wall_seconds"] = time.monotonic() - started
                if completed == 2010:
                    report.update(completed=True, checkpoint=str(checkpoint))
                write_json(RUN / "lora_training.json", report)
                print(f"CHECKPOINT_COMPLETE updates={completed} path={checkpoint}", flush=True)
                subprocess.run(["/root/miniconda3/bin/python", str(Path(__file__).with_name("publish_pi0_six.py")),
                                str(RUN), "--stage", f"train-update-{completed}"], check=True)
        if int(state.step) != 2010:
            raise RuntimeError("Training ended before the authorized 2010 updates")
        report.update(completed=True, checkpoint=str(cfg.checkpoint_dir / "2010"))
    except BaseException as exc:
        report["error"] = repr(exc)
        raise
    finally:
        manager.wait_until_finished()
        report["wall_seconds"] = time.monotonic() - started
        report["jax_memory_stats"] = {k: int(v) for k, v in (jax.devices()[0].memory_stats() or {}).items()}
        write_json(RUN / "lora_training.json", report)
        manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "train"])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    prepare() if args.stage == "prepare" else train(args.resume)
