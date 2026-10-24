"""Check both backend model definitions without allocating the large weights."""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["JAX_PLATFORMS"] = "cpu"

import dataclasses
import json
from pathlib import Path

from flax import nnx
import jax
import torch
from openpi.models_pytorch.pi0_pytorch import PI0Pytorch
from openpi.training import config

results = {}
for name in ("pi0_libero", "pi05_libero"):
    cfg = config.get_config(name)
    abstract = nnx.eval_shape(cfg.model.create, jax.random.key(0))
    shapes = jax.tree.leaves(nnx.state(abstract, nnx.Param))
    with torch.device("meta"):
        model = PI0Pytorch(dataclasses.replace(cfg.model, pytorch_compile_mode=None))
    assert all(p.is_meta for p in model.parameters())
    assert model.pi05 == (name == "pi05_libero")
    results[name] = {
        "jax_definition_traced": True,
        "jax_parameter_arrays": len(shapes),
        "pytorch_meta_constructed": True,
        "pytorch_parameters": sum(p.numel() for p in model.parameters()),
        "weights_allocated": False,
        "full_inference_tested": False,
    }
assert not torch.cuda.is_initialized()
path = Path(__file__).resolve().parents[1] / "results/model-definitions.json"
path.write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results, indent=2))
