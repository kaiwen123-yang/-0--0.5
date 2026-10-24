"""Use official OpenPI optimizer, train step, checkpoint format and inference."""
import argparse
import functools
import json
import os
from pathlib import Path
import sys
import time

# The upstream checkout is deliberately not edited by this task.
OPENPI = Path(os.environ.get("PIPER_OPENPI", "/root/autodl-tmp/pi05/openpi"))
sys.path.insert(0, str(OPENPI))

import jax
import numpy as np
from flax import nnx, traverse_util
from openpi import transforms as T
from openpi.shared import normalize
from openpi.training import data_loader as D
from dataset import PiperDataset
from policy_config import ASSET_ID, DATA, RUN, DELTA_MASK, make_config


def prepare_stats():
    index = json.loads((DATA / "index.json").read_text())
    stats = {k: normalize.RunningStats() for k in ("state", "actions")}
    n = 0
    for e in index:
        if e["split"] != "train":
            continue
        directory = DATA / e["directory"]
        state = np.load(directory / "state.npy")
        action = np.load(directory / "action.npy")
        # Match the training distribution of entire action chunks, including end padding.
        ids = np.minimum(np.arange(len(state))[:,None]+np.arange(10)[None,:], len(state)-1)
        chunks = action[ids].copy()
        chunks[:,:,:6] -= state[:,None,:6]
        stats["state"].update(state)
        stats["actions"].update(chunks.reshape(-1,7))
        n += len(state)
    normalize.save(RUN / "assets" / ASSET_ID, {k:v.get_statistics() for k,v in stats.items()})
    (RUN / "normalization.json").write_text(json.dumps(dict(split="train", frames=n, horizon=10,
                                                               action_delta_mask=DELTA_MASK, heldout_used=False), indent=2))
    print("TRAIN_ONLY_NORMALIZATION", n, flush=True)


def create_loader(cfg, *, sharding=None, shuffle=True, **kwargs):
    dc = cfg.data.create(cfg.assets_dirs, cfg.model)
    dataset = PiperDataset(DATA, "train", cfg.model.action_horizon)
    dataset = D.transform_dataset(dataset, dc)
    loader = D.TorchDataLoader(dataset, cfg.batch_size, sharding=sharding, shuffle=shuffle,
                               num_workers=cfg.num_workers, seed=cfg.seed)
    return D.DataLoaderImpl(dc, loader)


def train(mode, steps, batch, resume=False):
    from scripts import train as upstream
    cfg = make_config(mode, steps, batch, resume)
    # Narrow process-local injection; training/optimizer/checkpoint code is upstream.
    upstream._data_loader.create_data_loader = create_loader
    real_init, real_step = upstream.init_train_state, upstream.train_step
    report = dict(mode=mode, requested_steps=steps, batch_size=batch, seed=42,
                  training_domain="synthetic_piper_h", hardware_execution=False, completed=False)
    metrics_path = RUN / f"{mode}_metrics.jsonl"
    def tracked_init(*args, **kwargs):
        state, sharding = real_init(*args, **kwargs)
        report["trainable_parameters"] = sum(x.size for x in jax.tree.leaves(state.params.filter(cfg.trainable_filter)))
        report["total_parameters"] = sum(x.size for x in jax.tree.leaves(state.params.filter(nnx.Param)))
        print("PARAMETERS", json.dumps(report), flush=True)
        return state, sharding
    def record_metrics(step, loss, grad):
        row = dict(step=int(step), loss=float(loss), grad_norm=float(grad), wall_time=time.time())
        if not np.isfinite([row["loss"], row["grad_norm"]]).all():
            raise RuntimeError("Non-finite training metrics")
        with metrics_path.open("a") as f:
            f.write(json.dumps(row)+"\n")
    def tracked_step(config, rng, state, batch):
        state, info = real_step(config, rng, state, batch)
        jax.debug.callback(record_metrics, state.step, info["loss"], info["grad_norm"], ordered=True)
        return state, info
    upstream.init_train_state, upstream.train_step = tracked_init, tracked_step
    started = time.monotonic()
    try:
        upstream.main(cfg)
        report.update(completed=True, checkpoint=str(cfg.checkpoint_dir / str(steps-1)))
    finally:
        report["wall_seconds"] = time.monotonic()-started
        report["jax_memory_stats"] = {k:int(v) for k,v in (jax.devices()[0].memory_stats() or {}).items()}
        (RUN / f"{mode}_training.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["prepare", "lora", "full"])
    p.add_argument("--steps", type=int, default=1500)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--resume", action="store_true")
    a = p.parse_args()
    RUN.mkdir(exist_ok=True, parents=True)
    if a.stage == "prepare":
        prepare_stats()
    else:
        train(a.stage, a.steps, a.batch, a.resume)
