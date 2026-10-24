"""CPU-only environment/config/transform checks; never loads the large model."""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["JAX_PLATFORMS"] = "cpu"

import importlib.metadata as metadata
import json
from pathlib import Path
import sys

import jax
import numpy as np
import torch
import transformers
from openpi.models import tokenizer
from openpi.policies import libero_policy
from openpi.training import config

root = Path(__file__).resolve().parents[1]
result = {
    "python_executable": sys.executable,
    "prefix": sys.prefix,
    "versions": {p: metadata.version(p) for p in (
        "openpi", "torch", "torchvision", "transformers", "jax", "jaxlib", "flax", "lerobot", "numpy"
    )},
    "torch_path": torch.__file__,
    "transformers_path": transformers.__file__,
    "cuda_build": torch.version.cuda,
    "compiled_cuda_arches": torch._C._cuda_getArchFlags(),
    "jax_devices": [str(device) for device in jax.devices()],
    "cuda_initialized": torch.cuda.is_initialized(),
    "configs": {},
}
assert result["cuda_build"] == "12.8"
assert "sm_120" in result["compiled_cuda_arches"]
assert not result["cuda_initialized"]
for name in ("pi0_libero", "pi05_libero", "pi0_libero_low_mem_finetune"):
    cfg = config.get_config(name)
    obs, actions = cfg.model.inputs_spec()
    example = libero_policy.make_libero_example()
    inp = libero_policy.LiberoInputs(cfg.model.model_type)(example)
    out = libero_policy.LiberoOutputs()({"actions": np.zeros((cfg.model.action_horizon, 32))})
    assert out["actions"].shape == (cfg.model.action_horizon, 7)
    assert inp["image"]["base_0_rgb"].shape == (224, 224, 3)
    tok = tokenizer.PaligemmaTokenizer(cfg.model.max_token_len)
    tokens, mask = tok.tokenize("pick up the black bowl", np.zeros(32) if cfg.model.discrete_state_input else None)
    assert tokens.shape == mask.shape == (cfg.model.max_token_len,)
    result["configs"][name] = {
        "type": str(cfg.model.model_type), "action_spec": list(actions.shape),
        "max_token_len": cfg.model.max_token_len, "discrete_state_input": cfg.model.discrete_state_input,
        "default_batch_size": cfg.batch_size, "tokenizer_checked": True,
    }
result["status"] = "passed_cpu_only"
(root / "results/environment-check.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
