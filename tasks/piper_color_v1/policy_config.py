"""OpenPI config for a single Piper H: 6 joint targets [rad] + opening [m]."""
import dataclasses as dc
import os
from pathlib import Path

import numpy as np
from flax import nnx
from openpi import transforms as T
from openpi.models.pi0_config import Pi0Config
from openpi.training import config as C, optimizer, weight_loaders

HERE = Path(__file__).resolve().parent
RUN = Path(os.environ.get("PIPER_COLOR_RUN", HERE / "run"))
DATA = Path(os.environ.get("PIPER_COLOR_DATA", RUN / "dataset"))
ASSET_ID = "piper_h_color_v1"
DELTA_MASK = (True, True, True, True, True, True, False)


@dc.dataclass(frozen=True)
class PiperInputs(T.DataTransformFn):
    def __call__(self, data):
        state = np.asarray(data["state"], dtype=np.float32)
        if state.shape != (7,) or not np.isfinite(state).all():
            raise ValueError("Piper observation requires 6 measured joint radians + measured opening metres")
        images = {}
        for key in ("external_rgb", "wrist_rgb"):
            image = np.asarray(data[key])
            if image.dtype != np.uint8 or image.ndim != 3 or image.shape[-1] != 3:
                raise ValueError(f"{key} requires uint8 RGB HWC, got {image.shape} {image.dtype}")
            images[key] = image
        result = dict(state=state.copy(),
                      image={"base_0_rgb": images["external_rgb"], "left_wrist_0_rgb": images["wrist_rgb"],
                             "right_wrist_0_rgb": np.zeros_like(images["external_rgb"])},
                      image_mask={"base_0_rgb": np.True_, "left_wrist_0_rgb": np.True_, "right_wrist_0_rgb": np.False_},
                      prompt=str(data["prompt"]))
        if "actions" in data:
            result["actions"] = np.asarray(data["actions"], dtype=np.float32).copy()
        return result


@dc.dataclass(frozen=True)
class PiperOutputs(T.DataTransformFn):
    def __call__(self, data):
        return {"actions": np.asarray(data["actions"][..., :7], dtype=np.float32)}


@dc.dataclass(frozen=True)
class PiperData(C.DataConfigFactory):
    repo_id: str = ASSET_ID

    def create(self, assets_dirs, model_config):
        return dc.replace(self.create_base_config(assets_dirs, model_config),
                          data_transforms=T.Group(inputs=[PiperInputs(), T.DeltaActions(DELTA_MASK)],
                                                  outputs=[T.AbsoluteActions(DELTA_MASK), PiperOutputs()]),
                          model_transforms=C.ModelTransformFactory()(model_config))


def make_config(mode="lora", steps=1500, batch=8, resume=False):
    if mode not in ("lora", "full", "base"):
        raise ValueError(mode)
    lora = mode == "lora"
    model = Pi0Config(pi05=True, action_horizon=10, discrete_state_input=True,
                      paligemma_variant="gemma_2b_lora" if lora else "gemma_2b",
                      action_expert_variant="gemma_300m_lora" if lora else "gemma_300m")
    base = os.environ.get("PIPER_BASE_PARAMS", "/root/autodl-fs/pi05/models/openpi-assets/checkpoints/pi05_base/params")
    return C.TrainConfig(name=f"pi05_piper_color_{mode}", exp_name="v1",
                         model=model, freeze_filter=model.get_freeze_filter() if lora else nnx.Nothing,
                         ema_decay=None, data=PiperData(assets=C.AssetsConfig(assets_dir=str(RUN / "assets"), asset_id=ASSET_ID)),
                         weight_loader=weight_loaders.CheckpointWeightLoader(base),
                         assets_base_dir=str(RUN / "assets"), checkpoint_base_dir=str(RUN / "checkpoints"),
                         batch_size=batch, num_workers=2, num_train_steps=steps, log_interval=10,
                         save_interval=500, keep_period=None, resume=resume, wandb_enabled=False,
                         lr_schedule=optimizer.CosineDecaySchedule(warmup_steps=100, peak_lr=3e-5,
                                                                  decay_steps=steps, decay_lr=3e-6),
                         policy_metadata={"robot":"Piper H", "action_units":"6 joint rad + opening m",
                                          "training_domain":"simulation", "hardware_validated":False,
                                          "cameras":"external RGB + wrist RGB; virtual uncalibrated geometry"})


def make_pi0_config(steps=2010, batch=4, resume=False):
    """Pi0 LoRA: continuous state and upstream PI0 mean/std normalization."""
    model = Pi0Config(pi05=False, discrete_state_input=False, action_horizon=10,
                      paligemma_variant="gemma_2b_lora", action_expert_variant="gemma_300m_lora")
    base = Path(os.environ["PIPER_BASE_PARAMS"]).resolve(strict=True)
    if base.parent.name != "pi0_base":
        raise ValueError(f"Pi0 six-demo training requires pi0_base/params, got {base}")
    return C.TrainConfig(
        name="pi0_piper_color_lora", exp_name="six_demo_v1", model=model,
        freeze_filter=model.get_freeze_filter(), ema_decay=None,
        data=PiperData(assets=C.AssetsConfig(assets_dir=str(RUN / "assets"), asset_id=ASSET_ID)),
        weight_loader=weight_loaders.CheckpointWeightLoader(str(base)),
        assets_base_dir=str(RUN / "assets"), checkpoint_base_dir=str(RUN / "checkpoints"),
        batch_size=batch, num_workers=2, num_train_steps=steps, seed=42,
        log_interval=10, save_interval=500, keep_period=1, resume=resume, wandb_enabled=False,
        lr_schedule=optimizer.CosineDecaySchedule(warmup_steps=100, peak_lr=3e-5,
                                                  decay_steps=steps, decay_lr=3e-6),
        policy_metadata={"model_family": "pi0", "robot": "Piper H",
                         "action_units": "6 joint rad + opening m", "training_domain": "simulation",
                         "state_input": "continuous", "normalization": "mean_std",
                         "training_layouts": [100, 101], "hardware_validated": False,
                         "cameras": "external RGB + wrist RGB; virtual uncalibrated geometry"})
