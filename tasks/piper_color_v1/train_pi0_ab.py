"""Real LoRA adaptation: restore old complete state, count local updates separately."""
import argparse
import dataclasses
import functools
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
from openpi.training import checkpoints, data_loader as D, optimizer, sharding
from dataset import PiperDataset
from policy_config import RUN, DATA, make_pi0_config
from prepare_pi0_ab import ASSET, BASE, BATCH, BUDGET, OLD, sha, save
from train_pi0_120 import OrderedDataset


def config(resume=False):
    cfg = make_pi0_config(steps=BASE + BUDGET, batch=BATCH, resume=resume)
    return dataclasses.replace(cfg, exp_name="ab_old2010", keep_period=1,
        lr_schedule=optimizer.CosineDecaySchedule(warmup_steps=0, peak_lr=3e-6,
                                                  decay_steps=BASE + BUDGET, decay_lr=3e-6),
        policy_metadata={**cfg.policy_metadata, "training_layouts": list(range(100, 140)),
                         "environment_version": "piper_h_color_contact_v2_impratio10", "adaptation_group": RUN.name})


def publish(stage):
    from publish_pi0_ab import publish as deliver
    deliver(RUN.parent, f"{RUN.name}-{stage}")


def train(until, resume=False):
    from scripts import train as upstream
    logging.basicConfig(level=logging.INFO)
    started = time.monotonic()
    cfg = config(resume)
    contract = json.loads((RUN.parent / "contract.json").read_text())
    sampling = json.loads((RUN / "sampler.json").read_text())
    for p, digest in [(RUN / "sample_order.npy", sampling["sample_order_sha256"]),
            (DATA / "manifest.json", contract["dataset_manifest_sha256"]),
            (DATA / "index.json", contract["dataset_index_sha256"]),
            (RUN / f"assets/{ASSET}/norm_stats.json", contract["normalization_sha256"]),
            (RUN / "scene/scene.xml", contract["scene_sha256"])]:
        if sha(p) != digest:
            raise ValueError(f"Frozen input changed: {p}")
    config_path = RUN / "train_config.txt"
    canonical = repr(dataclasses.replace(cfg, resume=False))
    if resume:
        if config_path.read_text() != canonical:
            raise ValueError("Adaptation config changed between segments")
    else:
        config_path.write_text(canonical)
        for entry in contract["old_checkpoint_files"]:
            if sha(OLD / entry["path"]) != entry["sha256"]:
                raise ValueError("Original checkpoint changed")
    dc = cfg.data.create(cfg.assets_dirs, cfg.model)
    if cfg.model.pi05 or dc.use_quantile_norm or dc.norm_stats is None:
        raise ValueError("Pi0 mean/std contract violated")
    order = np.load(RUN / "sample_order.npy", allow_pickle=False)
    if len(order) != BATCH * BUDGET:
        raise ValueError("Sampler budget differs")
    train_rng, init_rng = jax.random.split(jax.random.key(cfg.seed))
    if jax.random.key_data(train_rng).tolist() != contract["old_resume"]["train_rng_key_data"]:
        raise ValueError("RNG differs from old complete checkpoint")
    mesh = sharding.make_mesh(cfg.fsdp_devices)
    data_sharding = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec(sharding.DATA_AXIS))
    replicated = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec())
    manager, resuming = checkpoints.initialize_checkpoint_dir(cfg.checkpoint_dir, keep_period=1,
                                                               overwrite=False, resume=resume)
    start = int(manager.latest_step()) if resuming else 0
    if resume != resuming or not start < until <= BUDGET:
        raise ValueError(f"Invalid local segment or resume: {start} -> {until}")
    if resuming:
        previous = json.loads((cfg.checkpoint_dir / str(start) / "resume.json").read_text())
        if (previous["local_updates"] != start or previous["optimizer_updates"] != BASE + start or
                previous["sample_offset"] != start * BATCH or previous["config_sha256"] != sha(config_path) or
                previous["sample_order_sha256"] != sampling["sample_order_sha256"]):
            raise ValueError("Saved local/global step or sampler mismatch")
    metrics = RUN / "lora_metrics.jsonl"
    lines = metrics.read_text().splitlines() if metrics.exists() else []
    if [json.loads(line)["local_update"] for line in lines[:start]] != list(range(1, start + 1)):
        raise ValueError("Missing preceding real-update metrics")
    if len(lines) > start:
        history = RUN / "history"
        history.mkdir(exist_ok=True)
        shutil.copyfile(metrics, history / f"interrupted_metrics_{time.time_ns()}.jsonl")
        metrics.write_text("".join(line + "\n" for line in lines[:start]))
    dataset = D.transform_dataset(OrderedDataset(PiperDataset(DATA, "train", 10), order[start * BATCH:until * BATCH]), dc)
    loader = D.DataLoaderImpl(dc, D.TorchDataLoader(dataset, BATCH, sharding=data_sharding,
        shuffle=False, num_workers=cfg.num_workers, seed=cfg.seed, num_batches=until - start))
    state, state_sharding = upstream.init_train_state(cfg, init_rng, mesh, resume=True)
    if resuming:
        state = checkpoints.restore_state(manager, state, loader, step=start)
    else:
        source_manager, found = checkpoints.initialize_checkpoint_dir(OLD.parent, keep_period=1,
                                                                     overwrite=False, resume=True)
        try:
            if not found:
                raise ValueError("Old full checkpoint unavailable")
            state = checkpoints.restore_state(source_manager, state, loader, step=BASE)
        finally:
            source_manager.close()
    jax.block_until_ready(state)
    counters = [int(x) for x in jax.tree.leaves(state.opt_state)
                if x.ndim == 0 and np.issubdtype(x.dtype, np.integer)]
    if int(state.step) != BASE + start or not counters or any(c != BASE + start for c in counters):
        raise ValueError(f"Restored optimizer counters differ: {state.step}, {counters}")
    lr = cfg.lr_schedule.create()
    if not all(np.isclose(float(lr(i)), 3e-6, rtol=1e-6) for i in (0, BASE, BASE + BUDGET - 1)):
        raise ValueError("Learning rate is not the fixed adaptation rate")
    verification = {"group": RUN.name, "local_updates": start, "optimizer_updates": int(state.step),
        "optimizer_scalar_counters": counters, "optimizer_array_leaves": len(jax.tree.leaves(state.opt_state)),
        "source_checkpoint": str(cfg.checkpoint_dir / str(start)) if resuming else str(OLD),
        "sample_offset": start * BATCH, "next_samples": order[start * BATCH:(start + 1) * BATCH].tolist(),
        "train_rng_key_data": jax.random.key_data(train_rng).tolist(), "config_sha256": sha(config_path),
        "learning_rate": float(lr(BASE + start)), "full_optimizer_restored": True}
    save(RUN / f"resume_verification_{start}.json", verification)
    report = {**verification, "segment_end_local": until, "segment_complete": False,
        "trainable_parameters": sum(x.size for x in jax.tree.leaves(state.params.filter(cfg.trainable_filter))),
        "total_parameters": sum(x.size for x in jax.tree.leaves(state.params.filter(nnx.Param))),
        "initialization_seconds": time.monotonic() - started}
    save(RUN / "lora_training.json", report)
    print("TRAIN_INITIALIZED " + json.dumps(report), flush=True)
    step_fn = jax.jit(functools.partial(upstream.train_step, cfg),
        in_shardings=(replicated, state_sharding, data_sharding),
        out_shardings=(state_sharding, replicated), donate_argnums=(1,))
    previous_end = time.monotonic()
    try:
        for local, batch in enumerate(loader, start=start + 1):
            t0 = time.monotonic()
            with sharding.set_mesh(mesh):
                state, info = step_fn(train_rng, state, batch)
            values = {k: float(v) for k, v in jax.device_get(info).items()}
            if not np.isfinite(list(values.values())).all():
                raise RuntimeError(f"Nonfinite real-update metrics: {local}: {values}")
            samples = order[(local - 1) * BATCH:local * BATCH]
            row = {"group": RUN.name, "local_update": local, "optimizer_update": BASE + local,
                **values, "wall_time": time.time(), "compute_seconds": time.monotonic() - t0,
                "data_wait_seconds": t0 - previous_end, "learning_rate": float(lr(BASE + local - 1)),
                "sample_offset_before": (local - 1) * BATCH, "sample_indices": samples.tolist(),
                "sample_frames": (samples % 268).tolist(), "sample_episode_indices": (samples // 268).tolist(),
                "rng_fold_in_step": BASE + local - 1}
            with metrics.open("a") as stream:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
            report.update(local_updates=local, optimizer_updates=BASE + local)
            if local == start + 1 or local % 10 == 0:
                save(RUN / "training_progress.json", {**row, "segment_end_local": until})
                print("UPDATE " + json.dumps(row), flush=True)
            if local % 500 == 0 or local == until:
                if int(state.step) != BASE + local:
                    raise ValueError("Actual optimizer update differs")
                selected_path = RUN / "selected_candidate.json"
                selected = json.loads(selected_path.read_text())["local_update"] if selected_path.exists() else None
                existing = sorted(manager.all_steps())
                # Keep a valid latest restore point and the selected candidate during the save.
                retain_before = set(existing[-1:]) | ({selected} if selected is not None else set())
                deleted = []
                for old in existing:
                    if old not in retain_before:
                        manager.delete(old)
                        deleted.append(old)
                if shutil.disk_usage(RUN).free < 20 * 1024**3:
                    raise RuntimeError("Less than 20 GiB free before full checkpoint")
                used = sum(p.stat().st_size for p in RUN.parent.glob("*/checkpoints/**/*") if p.is_file())
                source_size = sum(x["bytes"] for x in contract["old_checkpoint_files"])
                if used + source_size > 60 * 1024**3:
                    raise RuntimeError("Saving would exceed 60 GiB new-checkpoint budget")
                checkpoints.save_state(manager, state, loader, local)
                manager.wait_until_finished()
                checkpoint = cfg.checkpoint_dir / str(local)
                save(checkpoint / "resume.json", {"local_updates": local, "optimizer_updates": BASE + local,
                    "sample_offset": local * BATCH, "sample_order_sha256": sampling["sample_order_sha256"],
                    "config_sha256": sha(config_path), "train_rng_key_data": jax.random.key_data(train_rng).tolist(),
                    "rng_rule": contract["rng_rule"], "old_checkpoint": str(OLD), "group": RUN.name})
                report.update(checkpoint=str(checkpoint), retained_checkpoints=sorted(manager.all_steps()),
                              segment_complete=local == until)
                save(RUN / "lora_training.json", report)
                with (RUN / "checkpoint_history.jsonl").open("a") as stream:
                    stream.write(json.dumps({"saved_local": local, "optimizer_updates": BASE + local,
                        "deleted_local": deleted, "retained_local": report["retained_checkpoints"],
                        "selected_candidate": selected, "wall_time": time.time()}) + "\n")
                print(f"CHECKPOINT_COMPLETE group={RUN.name} local={local} optimizer={BASE + local}", flush=True)
                publish(f"train-update-{local}")
            previous_end = time.monotonic()
        if int(state.step) != BASE + until:
            raise RuntimeError("Data loader ended before requested budget")
    except BaseException as exc:
        report["error"] = repr(exc)
        raise
    finally:
        manager.wait_until_finished()
        report["wall_seconds"] = time.monotonic() - started
        save(RUN / "lora_training.json", report)
        manager.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--until", type=int, choices=[500, 1000, 2010], required=True)
    p.add_argument("--resume", action="store_true")
    a = p.parse_args()
    train(a.until, a.resume)
