"""Run small real CUDA operations in a single selected backend; no large model."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("torch", "jax"))
    args = parser.parse_args()
    result = {"backend": args.backend, "model_weights_loaded": False, "training": False}
    if args.backend == "torch":
        import torch
        with torch.inference_mode():
            x = torch.ones((64, 64), device="cuda", dtype=torch.bfloat16)
            y = x @ x
            assert torch.all(y == 64).item()
            layer = torch.nn.Conv2d(3, 8, 3).to(device="cuda", dtype=torch.bfloat16)
            output = layer(torch.ones((1, 3, 32, 32), device="cuda", dtype=torch.bfloat16))
            assert torch.isfinite(output).all().item()
            torch.cuda.synchronize()
        result.update(version=torch.__version__, cuda_build=torch.version.cuda,
                      device=torch.cuda.get_device_name(), cudnn=torch.backends.cudnn.version(),
                      allocated_peak_bytes=torch.cuda.max_memory_allocated(),
                      checks=["bfloat16_matmul", "bfloat16_cudnn_convolution"])
    else:
        import jax
        import jax.numpy as jnp
        device = jax.devices("gpu")[0]
        x = jax.device_put(jnp.ones((64, 64), dtype=jnp.bfloat16), device)
        y = jax.jit(lambda a: a @ a)(x).block_until_ready()
        assert bool(jnp.all(y == 64))
        assert y.device.platform == "gpu"
        result.update(version=jax.__version__, device=str(device),
                      device_kind=device.device_kind, memory_stats=device.memory_stats(),
                      checks=["bfloat16_jit_matmul"])
    result["status"] = "passed"
    root = Path(__file__).resolve().parents[1]
    (root / f"results/gpu-{args.backend}-check.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
