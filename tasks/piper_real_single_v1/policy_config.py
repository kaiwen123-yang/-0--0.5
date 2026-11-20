"""One real RGB camera and two independent, fully trainable OpenPI families.

Reference OpenPI: 215abfb217dbac7d5f1273282331b9b1866c0479.
Raw state/actions are six joint radians and total gripper opening in metres.
The model retains its pretrained 32-dimensional state/action projections.
"""

import dataclasses as dc
from pathlib import Path

import numpy as np
from flax import nnx
from openpi import transforms as T
from openpi.models.pi0_config import Pi0Config
from openpi.training import config as C, optimizer, weight_loaders


CAMERA_SLOTS = {"external_fixed": "base_0_rgb", "wrist": "left_wrist_0_rgb"}
IMAGE_SLOTS = ("base_0_rgb", "left_wrist_0_rgb", "right_wrist_0_rgb")
DELTA_MASK = (True, True, True, True, True, True, False)


def asset_id(spec):
    return f"piper_h_{spec['camera_mount']}_{spec['model_family']}_single_v1"


def run_directory(spec):
    return Path(spec["run_root"]).expanduser() / spec["model_family"] / spec["experiment_name"]


@dc.dataclass(frozen=True)
class SingleCameraInputs(T.DataTransformFn):
    camera_mount: str

    def __call__(self, data):
        rgb = np.asarray(data["camera_rgb"])
        active_slot = CAMERA_SLOTS[self.camera_mount]
        result = {
            "state": np.asarray(data["state"], dtype=np.float32).copy(),
            "image": {name: rgb if name == active_slot else np.zeros_like(rgb) for name in IMAGE_SLOTS},
            "image_mask": {name: np.bool_(name == active_slot) for name in IMAGE_SLOTS},
            "prompt": str(data["prompt"]),
        }
        if "actions" in data:
            result["actions"] = np.asarray(data["actions"], dtype=np.float32).copy()
        return result


@dc.dataclass(frozen=True)
class SingleCameraOutputs(T.DataTransformFn):
    def __call__(self, data):
        return {"actions": np.asarray(data["actions"][..., :7], dtype=np.float32)}


@dc.dataclass(frozen=True, kw_only=True)
class SingleCameraData(C.DataConfigFactory):
    camera_mount: str

    def create(self, assets_dirs, model_config):
        return dc.replace(
            self.create_base_config(assets_dirs, model_config),
            data_transforms=T.Group(
                inputs=[SingleCameraInputs(self.camera_mount), T.DeltaActions(DELTA_MASK)],
                outputs=[T.AbsoluteActions(DELTA_MASK), SingleCameraOutputs()],
            ),
            model_transforms=C.ModelTransformFactory()(model_config),
        )


def model_config(spec):
    pi05 = {"pi0": False, "pi05": True}[spec["model_family"]]
    return Pi0Config(
        pi05=pi05,
        discrete_state_input=pi05,
        action_dim=32,
        action_horizon=int(spec["action_horizon"]),
        paligemma_variant="gemma_2b",
        action_expert_variant="gemma_300m",
    )


def policy_metadata(spec):
    pi05 = spec["model_family"] == "pi05"
    return {
        "model_family": spec["model_family"],
        "finetuning": "full",
        "robot": "Piper H",
        "camera_mount": spec["camera_mount"],
        "active_image_slot": CAMERA_SLOTS[spec["camera_mount"]],
        "real_camera_count": 1,
        "state_units": "6 measured joint rad + measured total opening m",
        "action_units": "6 absolute joint target rad + absolute total opening m",
        "state_input": "discrete" if pi05 else "continuous",
        "normalization": "quantile" if pi05 else "mean_std",
        "policy_hz": 20,
        "policy_hz_semantics": "nominal dataset/action grid; not measured inference or robot frequency",
        "training_domain": "real_demonstrations",
        "hardware_validated": False,
    }


def make_full_config(spec):
    """Build configuration only; this does not load weights or start training.

    Hyperparameters and paths come from an explicit per-experiment JSON spec.
    No B assets, LoRA variants, fictitious dataset or generated statistics are
    substituted. The separate train entry point requires real labeled data.
    """
    family = spec["model_family"]
    settings = spec["training"]
    root = run_directory(spec)
    aid = asset_id(spec)
    return C.TrainConfig(
        name=f"{family}_piper_real_single_full",
        exp_name=spec["experiment_name"],
        model=model_config(spec),
        freeze_filter=nnx.Nothing,
        ema_decay=settings["ema_decay"] if settings["ema_enabled"] else None,
        data=SingleCameraData(
            repo_id=aid,
            camera_mount=spec["camera_mount"],
            assets=C.AssetsConfig(assets_dir=str(root / "assets"), asset_id=aid),
        ),
        weight_loader=weight_loaders.CheckpointWeightLoader(str(Path(spec["base_params"]).expanduser())),
        assets_base_dir=str(root / "assets"),
        checkpoint_base_dir=str(root / "checkpoints"),
        batch_size=int(settings["batch_size"]),
        num_workers=int(settings["num_workers"]),
        num_train_steps=int(settings["num_train_steps"]),
        seed=int(settings["seed"]),
        log_interval=int(settings["log_interval"]),
        save_interval=int(settings["save_interval"]),
        keep_period=settings["keep_period"],
        resume=bool(settings["resume"]),
        wandb_enabled=False,
        lr_schedule=optimizer.CosineDecaySchedule(
            warmup_steps=int(settings["warmup_steps"]),
            peak_lr=float(settings["peak_lr"]),
            decay_steps=int(settings["decay_steps"]),
            decay_lr=float(settings["decay_lr"]),
        ),
        policy_metadata=policy_metadata(spec),
    )


def make_inference_config(spec, checkpoint):
    """Only model/input fields are needed to load a completed checkpoint."""
    aid = asset_id(spec)
    return C.TrainConfig(
        name=f"{spec['model_family']}_piper_real_single_full",
        model=model_config(spec),
        data=SingleCameraData(
            repo_id=aid,
            camera_mount=spec["camera_mount"],
            assets=C.AssetsConfig(assets_dir=str(Path(checkpoint) / "assets"), asset_id=aid),
        ),
        policy_metadata=policy_metadata(spec),
    )
