"""Explicit future full-finetuning entry; no GPU work when real prerequisites are absent.

Run from the repository root with its existing OpenPI Python environment:
  python -m tasks.piper_real_single_v1.train --spec <actual.json> --stage prepare-stats
  python -m tasks.piper_real_single_v1.train --spec <actual.json> --stage train

The first command computes statistics only from actual labeled training
episodes. The second never creates statistics automatically. This module
does not schedule a second model, change allocator settings or switch to LoRA.
"""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from .dataset import SingleCameraDataset, read_policy_timestamps, training_data_requirements


def prepare_stats(spec):
    from openpi.shared import normalize

    from .policy_config import DELTA_MASK, asset_id, run_directory

    root = Path(spec["dataset_root"]).expanduser()
    dataset_metadata = json.loads((root / "dataset.json").read_text())
    horizon = int(spec["action_horizon"])
    entries = [entry for entry in json.loads((root / "index.json").read_text()) if entry["split"] == "train"]
    stats = {key: normalize.RunningStats() for key in ("state", "actions")}
    frames = 0
    for entry in entries:
        directory = root / entry["directory"]
        read_policy_timestamps(directory, entry["frames"])
        state = np.load(directory / "state.npy", mmap_mode="r", allow_pickle=False)
        actions = np.load(directory / "actions.npy", mmap_mode="r", allow_pickle=False)
        indices = np.minimum(np.arange(len(state))[:, None] + np.arange(horizon)[None, :], len(state) - 1)
        chunks = actions[indices].copy()
        chunks[:, :, :6] -= state[:, None, :6]
        stats["state"].update(state)
        stats["actions"].update(chunks.reshape(-1, 7))
        frames += len(state)
    run = run_directory(spec)
    run.mkdir(parents=True, exist_ok=True)
    destination = run / "assets" / asset_id(spec)
    normalize.save(destination, {key: value.get_statistics() for key, value in stats.items()})
    report = {
        "status": "PREPARED_FROM_REAL_TRAINING_EPISODES",
        "model_family": spec["model_family"],
        "camera_mount": spec["camera_mount"],
        "dataset_root": str(root),
        "timestamp_alignment_source": str(root / dataset_metadata["timestamp_alignment_source"]),
        "split": "train",
        "frames": frames,
        "action_horizon": horizon,
        "policy_hz": spec["policy_hz"],
        "policy_hz_semantics": "nominal aligned dataset/action grid; not measured runtime frequency",
        "action_delta_mask": DELTA_MASK,
        "heldout_used": False,
        "norm_directory": str(destination),
        "training_started": False,
    }
    (run / "normalization.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def train(spec):
    import jax
    from flax import nnx
    from openpi.training import data_loader as D
    from scripts import train as upstream

    from .policy_config import asset_id, make_full_config, run_directory

    cfg = make_full_config(spec)

    def create_loader(config, *, sharding=None, shuffle=True, **kwargs):
        data_config = config.data.create(config.assets_dirs, config.model)
        dataset = SingleCameraDataset(spec["dataset_root"], "train", config.model.action_horizon, spec["policy_hz"])
        transformed = D.transform_dataset(dataset, data_config)
        loader = D.TorchDataLoader(
            transformed, config.batch_size, sharding=sharding, shuffle=shuffle,
            num_workers=config.num_workers, seed=config.seed,
        )
        return D.DataLoaderImpl(data_config, loader)

    # The existing project uses this process-local data-loader injection;
    # no file inside the shared OpenPI checkout is modified.
    upstream._data_loader.create_data_loader = create_loader
    original_init = upstream.init_train_state
    run = run_directory(spec)
    run.mkdir(parents=True, exist_ok=True)
    recorded_spec = {
        **spec,
        "resolved_paths": {
            "run_directory": str(run),
            "checkpoint_directory": str(cfg.checkpoint_dir),
            "norm_directory": str(run / "assets" / asset_id(spec)),
        },
    }
    (run / "run_spec.json").write_text(json.dumps(recorded_spec, indent=2) + "\n")

    def record_parameter_counts(*args, **kwargs):
        state, sharding = original_init(*args, **kwargs)
        total = sum(value.size for value in jax.tree.leaves(state.params.filter(nnx.Param)))
        trainable = sum(value.size for value in jax.tree.leaves(state.params.filter(cfg.trainable_filter)))
        report = {
            "model_family": spec["model_family"],
            "total_parameters": total,
            "trainable_parameters": trainable,
            "all_parameters_trainable": trainable == total,
            "measurement": (
                "parameter shapes before checkpoint restoration"
                if kwargs.get("resume") else "actual initialized training state"
            ),
        }
        (run / "parameter_counts.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)
        return state, sharding

    upstream.init_train_state = record_parameter_counts
    upstream.main(cfg)
    print(json.dumps({"status": "COMPLETED", "model_family": spec["model_family"],
                      "run_directory": str(run), "checkpoint_directory": str(cfg.checkpoint_dir)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--stage", required=True, choices=("prepare-stats", "train"))
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text())
    required = ("model_family", "camera_mount", "run_root", "experiment_name", "dataset_root",
                "openpi_root", "action_horizon", "policy_hz")
    missing = [f"spec.{key}" for key in required if spec.get(key) is None or spec.get(key) == ""]
    if spec.get("model_family") not in ("pi0", "pi05"):
        missing.append("spec.model_family must be pi0 or pi05")
    if spec.get("camera_mount") not in ("external_fixed", "wrist"):
        missing.append("spec.camera_mount must be external_fixed or wrist")
    if spec.get("policy_hz") != 20:
        missing.append("spec.policy_hz must be 20 for this dataset/action contract")
    if args.stage == "train":
        if not spec.get("base_params"):
            missing.append("spec.base_params")
        settings = spec.get("training") or {}
        required_training = ("ema_enabled", "batch_size", "num_workers", "num_train_steps", "seed",
                             "log_interval", "save_interval", "resume", "warmup_steps", "peak_lr",
                             "decay_steps", "decay_lr")
        missing += [f"spec.training.{key}" for key in required_training if settings.get(key) is None]
        if settings.get("ema_enabled") and settings.get("ema_decay") is None:
            missing.append("spec.training.ema_decay when ema_enabled=true")
        if "keep_period" not in settings:
            missing.append("spec.training.keep_period (null is allowed)")
    if missing:
        print(json.dumps({"status": "NOT_RUN", "stage": args.stage, "missing": missing,
                          "training_started": False}, indent=2))
        return 2
    family = spec["model_family"]
    mount = spec["camera_mount"]
    run = Path(spec["run_root"]).expanduser() / family / spec["experiment_name"]
    aid = f"piper_h_{mount}_{family}_single_v1"
    missing = training_data_requirements(spec["dataset_root"], mount, spec["policy_hz"])
    if args.stage == "train":
        norm = run / "assets" / aid / "norm_stats.json"
        if not norm.is_file():
            missing.append(str(norm))
        if not Path(spec["base_params"]).expanduser().is_dir():
            missing.append(str(spec["base_params"]))
    if missing:
        print(json.dumps({"status": "NOT_RUN", "stage": args.stage, "missing": missing, "training_started": False}, indent=2))
        return 2
    openpi_root = Path(spec["openpi_root"]).expanduser()
    sys.path.insert(0, str(openpi_root))
    sys.path.insert(0, str(openpi_root / "src"))
    if args.stage == "prepare-stats":
        prepare_stats(spec)
    else:
        train(spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
