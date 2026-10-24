"""Compare checkpoint global tensor metadata with the selected model; CPU only."""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["JAX_PLATFORMS"] = "cpu"

import json
from pathlib import Path
from flax import nnx, traverse_util
import jax
import orbax.checkpoint as ocp
from openpi.models.pi0_config import Pi0Config
from openpi.training import config

root = Path(__file__).resolve().parents[1]
results = {}
for name in ("pi0_libero", "pi05_libero", "pi0_base", "pi05_base"):
    path = root / "checkpoints" / name / "params"
    with ocp.PyTreeCheckpointer() as checkpointer:
        metadata = checkpointer.metadata(path)["params"]
    actual = traverse_util.flatten_dict(metadata)
    if all(key[-1] == "value" for key in actual):
        actual = {key[:-1]: value for key, value in actual.items()}
    # Base checkpoints have no task-specific TrainConfig. Their model definitions
    # are the upstream defaults; LIBERO uses its own documented task config.
    model_config = (Pi0Config(pi05=(name == "pi05_base"))
                    if name.endswith("_base") else config.get_config(name).model)
    abstract = nnx.eval_shape(model_config.create, jax.random.key(0))
    expected = traverse_util.flatten_dict(nnx.state(abstract, nnx.Param).to_pure_dict())
    missing = sorted("/".join(key) for key in expected.keys() - actual.keys())
    extra = sorted("/".join(key) for key in actual.keys() - expected.keys())
    mismatches = {
        "/".join(key): {"checkpoint": list(actual[key].shape), "model": list(expected[key].shape)}
        for key in expected.keys() & actual.keys() if actual[key].shape != expected[key].shape
    }
    result = {"parameter_arrays": len(actual), "missing": missing, "extra": extra,
              "shape_mismatches": mismatches, "tensor_data_restored": False,
              "status": "passed" if not (missing or extra or mismatches) else "failed"}
    results[name] = result
path = root / "results/checkpoint-shapes.json"
path.write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results, indent=2))
if any(value["status"] != "passed" for value in results.values()):
    raise SystemExit(1)
