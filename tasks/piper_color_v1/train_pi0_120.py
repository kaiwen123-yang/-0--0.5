"""Fixed 24,120-step schedule, staged real LoRA updates, exact sampler resume."""
import argparse
import dataclasses
import functools
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.environ["PIPER_OPENPI"])
import jax
import numpy as np
from flax import nnx
from openpi.shared import normalize
from openpi.training import checkpoints, data_loader as D, config as C, sharding
from dataset import PiperDataset
from policy_config import RUN, DATA, DELTA_MASK, PiperData, make_pi0_config

ASSET = "piper_h_color_contact_v2_120"
BUDGET, FRAMES, BATCH = 24120, 32160, 4
NODES = (2010, 4020, 8040, 16080, 24120)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def config(resume=False):
    cfg = make_pi0_config(steps=BUDGET, batch=BATCH, resume=resume)
    return dataclasses.replace(cfg, exp_name="120_demo_contact_v2", keep_period=1,
        data=PiperData(repo_id=ASSET, assets=C.AssetsConfig(assets_dir=str(RUN / "assets"), asset_id=ASSET)),
        policy_metadata={**cfg.policy_metadata, "training_layouts": list(range(100, 140)),
                         "environment_version": "piper_h_color_contact_v2_impratio10"})


def prepare():
    if (RUN / "normalization.json").exists():
        raise FileExistsError("Normalization is already frozen")
    entries = json.loads((DATA / "index.json").read_text())
    manifest = json.loads((DATA / "manifest.json").read_text())
    expected = {(s, c) for s in range(100, 140) for c in ("red", "green", "blue")}
    if len(entries) != 120 or {(e["layout_seed"], e["target"]) for e in entries} != expected:
        raise ValueError("Expected exactly 120 train-only v2 demonstrations")
    if sum(e["frames"] for e in entries) != FRAMES or any(e["split"] != "train" for e in entries):
        raise ValueError("Frame budget or split mismatch")
    if manifest["scene_sha256"] != sha(RUN / "scene/scene.xml"):
        raise ValueError("Data scene differs from frozen scene")
    stats = {k: normalize.RunningStats() for k in ("state", "actions")}
    provenance = []
    for entry in entries:
        directory = DATA / entry["directory"]
        state = np.load(directory / "state.npy")
        action = np.load(directory / "action.npy")
        ids = np.minimum(np.arange(len(state))[:, None] + np.arange(10)[None, :], len(state) - 1)
        chunks = action[ids].copy()
        chunks[:, :, :6] -= state[:, None, :6]
        stats["state"].update(state)
        stats["actions"].update(chunks.reshape(-1, 7))
        provenance.append({**entry, "array_sha256": {k: sha(directory / f"{k}.npy")
                            for k in ("state", "action", "external_rgb", "wrist_rgb")}})
    normalize.save(RUN / "assets" / ASSET, {k: v.get_statistics() for k, v in stats.items()})
    order = np.concatenate([np.random.default_rng(42 + epoch).permutation(FRAMES) for epoch in range(3)])
    np.save(RUN / "sample_order.npy", order, allow_pickle=False)
    save(RUN / "normalization.json", {"model_family": "pi0", "normalization": "mean_std",
         "state_input": "continuous", "split": "train", "frames": FRAMES, "episodes": 120,
         "horizon": 10, "action_delta_mask": DELTA_MASK, "heldout_used": False,
         "norm_stats_sha256": sha(RUN / "assets" / ASSET / "norm_stats.json"),
         "sample_order_sha256": sha(RUN / "sample_order.npy"),
         "sampling": "three complete permutations; numpy PCG64 seeds 42,43,44; fixed saved order",
         "source_manifest_sha256": sha(DATA / "manifest.json"), "selected_episodes": provenance})
    print("PREPARED 120 demonstrations / 32160 starts / PI0 mean_std", flush=True)


class OrderedDataset:
    def __init__(self, dataset, order):
        self.dataset, self.order = dataset, order

    def __len__(self):
        return len(self.order)

    def __getitem__(self, index):
        return self.dataset[int(self.order[index])]


def publish(stage):
    # Publication failures remain visible without invalidating optimizer work.
    try:
        result = subprocess.run(["/root/miniconda3/bin/python", str(Path(__file__).with_name("publish_pi0_120.py")),
                                 str(RUN), "--stage", stage], timeout=150)
        if result.returncode:
            raise RuntimeError(f"Publisher exit {result.returncode}")
    except Exception as exc:
        with (RUN / "publication_errors.jsonl").open("a") as stream:
            stream.write(json.dumps({"stage": stage, "wall_time": time.time(), "error": repr(exc)}) + "\n")
        print("PUBLICATION_ERROR " + repr(exc), flush=True)


def train(until, resume=False):
    from scripts import train as upstream
    logging.basicConfig(level=logging.INFO)
    started = time.monotonic()
    cfg = config(resume)
    dc = cfg.data.create(cfg.assets_dirs, cfg.model)
    if cfg.model.pi05 or cfg.model.discrete_state_input or dc.use_quantile_norm or dc.norm_stats is None:
        raise ValueError("Pi0 continuous-state / mean-std contract violated")
    config_path = RUN / "train_config.txt"
    canonical = repr(dataclasses.replace(cfg, resume=False))
    if resume and config_path.read_text() != canonical:
        raise ValueError("Fixed training configuration changed")
    if not resume:
        config_path.write_text(canonical)
    frozen = json.loads((RUN / "normalization.json").read_text())
    if (sha(RUN / "sample_order.npy") != frozen["sample_order_sha256"] or
        sha(DATA / "manifest.json") != frozen["source_manifest_sha256"] or
        sha(RUN / "assets" / ASSET / "norm_stats.json") != frozen["norm_stats_sha256"]):
        raise ValueError("Sampling, dataset or normalization changed")
    order = np.load(RUN / "sample_order.npy", allow_pickle=False)
    if len(order) != BUDGET * BATCH:
        raise ValueError("Wrong saved permutation budget")
    train_rng, init_rng = jax.random.split(jax.random.key(cfg.seed))
    mesh = sharding.make_mesh(cfg.fsdp_devices)
    data_sharding = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec(sharding.DATA_AXIS))
    replicated = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec())
    manager, resuming = checkpoints.initialize_checkpoint_dir(cfg.checkpoint_dir, keep_period=1,
                                                               overwrite=False, resume=resume)
    start = int(manager.latest_step()) if resuming else 0
    if not start < until <= BUDGET:
        raise ValueError(f"Invalid segment {start} -> {until}")
    if resuming:
        saved = json.loads((cfg.checkpoint_dir / str(start) / "resume.json").read_text())
        if (saved["config_sha256"] != sha(config_path) or saved["completed_updates"] != start or
            saved["sample_offset"] != start * BATCH or saved["sample_order_sha256"] != frozen["sample_order_sha256"] or
            saved["train_rng_key_data"] != jax.random.key_data(train_rng).tolist()):
            raise ValueError("Checkpoint RNG / schedule / sampler mismatch")
    metrics = RUN / "lora_metrics.jsonl"
    if metrics.exists():
        lines = metrics.read_text().splitlines()
        if [json.loads(line)["step"] for line in lines[:start]] != list(range(1, start + 1)):
            raise ValueError("Metrics before restored checkpoint are not contiguous")
        if len(lines) > start:
            history = RUN / "history"
            history.mkdir(exist_ok=True)
            shutil.copyfile(metrics, history / f"interrupted_metrics_{time.time_ns()}.jsonl")
            metrics.write_text("".join(line + "\n" for line in lines[:start]))
    elif start:
        raise ValueError("Checkpoint exists without preceding metrics")
    dataset = OrderedDataset(PiperDataset(DATA, "train", 10), order[start * BATCH:until * BATCH])
    dataset = D.transform_dataset(dataset, dc)
    loader = D.DataLoaderImpl(dc, D.TorchDataLoader(dataset, BATCH, sharding=data_sharding,
              shuffle=False, num_workers=cfg.num_workers, seed=cfg.seed, num_batches=until - start))
    state, state_sharding = upstream.init_train_state(cfg, init_rng, mesh, resume=resuming)
    if resuming:
        state = checkpoints.restore_state(manager, state, loader, step=start)
    jax.block_until_ready(state)
    if int(state.step) != start:
        raise ValueError("Optimizer step differs from restored checkpoint")
    counters = [int(x) for x in jax.tree.leaves(state.opt_state)
                if x.ndim == 0 and np.issubdtype(x.dtype, np.integer)]
    save(RUN / f"resume_verification_{start}.json", {"restored_updates": int(state.step),
         "optimizer_scalar_counters": counters, "optimizer_array_leaves": len(jax.tree.leaves(state.opt_state)),
         "sample_offset": start * BATCH, "next_sample_indices": order[start * BATCH:(start + 1) * BATCH].tolist(),
         "config_sha256": sha(config_path), "train_rng_key_data": jax.random.key_data(train_rng).tolist(),
         "schedule_budget": BUDGET, "segment_end": until})
    report = {"model_family": "pi0", "mode": "lora", "schedule_budget": BUDGET, "segment_end": until,
              "batch_size": BATCH, "seed": cfg.seed, "completed_updates": start, "segment_complete": False,
              "trainable_parameters": sum(x.size for x in jax.tree.leaves(state.params.filter(cfg.trainable_filter))),
              "total_parameters": sum(x.size for x in jax.tree.leaves(state.params.filter(nnx.Param))),
              "resumed_from_update": start, "initialization_seconds": time.monotonic() - started,
              "hardware_execution": False}
    save(RUN / "lora_training.json", report)
    print("TRAIN_INITIALIZED " + json.dumps(report), flush=True)
    step_fn = jax.jit(functools.partial(upstream.train_step, cfg),
          in_shardings=(replicated, state_sharding, data_sharding),
          out_shardings=(state_sharding, replicated), donate_argnums=(1,))
    lr = cfg.lr_schedule.create()
    durations = []
    previous_end = time.monotonic()
    try:
        for completed, batch in enumerate(loader, start=start + 1):
            step_start = time.monotonic()
            data_wait = step_start - previous_end
            with sharding.set_mesh(mesh):
                state, info = step_fn(train_rng, state, batch)
            values = {k: float(v) for k, v in jax.device_get(info).items()}
            if not np.isfinite(list(values.values())).all():
                raise RuntimeError(f"Non-finite metrics at {completed}: {values}")
            elapsed = time.monotonic() - step_start
            durations.append(elapsed)
            row = {"step": completed, **values, "wall_time": time.time(), "compute_seconds": elapsed,
                   "data_wait_seconds": data_wait, "learning_rate": float(lr(completed - 1)),
                   "sample_indices": order[(completed - 1) * BATCH:completed * BATCH].tolist(),
                   "sample_starts_seen": completed * BATCH, "equivalent_start_epochs": completed * BATCH / FRAMES}
            with metrics.open("a") as stream:
                stream.write(json.dumps(row) + "\n")
            report["completed_updates"] = completed
            if completed == start + 1 or completed % 10 == 0:
                save(RUN / "training_progress.json", {**row, "segment_end": until, "schedule_budget": BUDGET})
                print("UPDATE " + json.dumps(row), flush=True)
            if completed % 100 == 0:
                recent = durations[max(10, len(durations) - 90):]
                if recent:
                    save(RUN / "training_eta.json", {"completed_updates": completed,
                         "mean_compute_seconds": float(np.mean(recent)), "median_compute_seconds": float(np.median(recent)),
                         "remaining_segment_compute_seconds": float(np.mean(recent) * (until - completed)),
                         "remaining_to_8040_compute_seconds": float(np.mean(recent) * max(0, 8040 - completed)),
                         "excludes": "model loading, checkpoint IO, evaluation, future resource contention"})
            if completed % 500 == 0 or completed == until:
                if int(state.step) != completed:
                    raise ValueError("Checkpoint state step mismatch")
                if shutil.disk_usage(RUN).free < 25 * 1024**3:
                    raise RuntimeError("Less than 25 GiB free before full checkpoint")
                checkpoints.save_state(manager, state, loader, completed)
                manager.wait_until_finished()
                checkpoint = cfg.checkpoint_dir / str(completed)
                save(checkpoint / "resume.json", {"completed_updates": completed, "sample_offset": completed * BATCH,
                     "sample_order_sha256": frozen["sample_order_sha256"], "config_sha256": sha(config_path),
                     "train_rng_key_data": jax.random.key_data(train_rng).tolist(),
                     "rng_rule": "OpenPI folds train_rng with restored train_state.step",
                     "optimizer_saved_by": "OpenPI train_state item", "schedule_budget": BUDGET})
                saved_steps = sorted(manager.all_steps())
                retain = set(saved_steps[-2:]) | set(NODES)
                deleted = []
                for old in saved_steps:
                    if old not in retain:
                        manager.delete(old)
                        deleted.append(old)
                report.update(checkpoint=str(checkpoint), retained_checkpoints=sorted(manager.all_steps()),
                              wall_seconds=time.monotonic() - started, segment_complete=completed == until)
                save(RUN / "lora_training.json", report)
                with (RUN / "checkpoint_history.jsonl").open("a") as stream:
                    stream.write(json.dumps({"saved": completed, "deleted": deleted,
                         "retained": report["retained_checkpoints"], "wall_time": time.time()}) + "\n")
                print(f"CHECKPOINT_COMPLETE updates={completed} path={checkpoint}", flush=True)
                publish(f"train-update-{completed}")
            previous_end = time.monotonic()
        if int(state.step) != until:
            raise RuntimeError("Segment ended before requested update")
    except BaseException as exc:
        report["error"] = repr(exc)
        raise
    finally:
        manager.wait_until_finished()
        report["wall_seconds"] = time.monotonic() - started
        report["jax_memory_stats"] = {k: int(v) for k, v in (jax.devices()[0].memory_stats() or {}).items()}
        save(RUN / "lora_training.json", report)
        manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "train"])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--until", type=int, choices=NODES, default=2010)
    args = parser.parse_args()
    prepare() if args.stage == "prepare" else train(args.until, args.resume)
