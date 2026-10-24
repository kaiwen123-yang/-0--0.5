"""Render one LIBERO observation with Mesa llvmpipe, without NVIDIA or policies."""
import json
import time
from libero_bootstrap import ROOT, configure, configure_software_rendering, allow_trusted_initial_states

configure()
mesa_vendor, device_index = configure_software_rendering()

import mujoco
from OpenGL import GL
# Verify the renderer before constructing the benchmark environment.
context = mujoco.GLContext(256, 256)
context.make_current()
renderer = GL.glGetString(GL.GL_RENDERER).decode()
assert "llvmpipe" in renderer.lower() or "softpipe" in renderer.lower(), renderer
context.free()

import numpy as np
from PIL import Image
from libero.libero import benchmark
from libero.libero.envs import OffScreenRenderEnv
allow_trusted_initial_states()

started = time.monotonic()
suite = benchmark.get_benchmark_dict()["libero_spatial"]()
env = OffScreenRenderEnv(
    bddl_file_name=suite.get_task_bddl_file_path(0),
    camera_heights=256,
    camera_widths=256,
    hard_reset=False,
)
try:
    env.seed(7)
    obs = env.reset()
    obs = env.set_init_state(suite.get_task_init_states(0)[0])
    obs, reward, done, info = env.step([0.0] * 6 + [-1.0])
    frames = {k: v for k, v in obs.items() if k.endswith("_image")}
    assert len(frames) == 2
    for name, frame in frames.items():
        assert frame.shape == (256, 256, 3)
        assert frame.dtype == np.uint8 and frame.std() > 0
        Image.fromarray(frame[::-1, ::-1]).save(ROOT / f"results/libero_{name}.png")
    result = {
        "status": "passed",
        "renderer": renderer,
        "EGL_vendor_file": str(mesa_vendor),
        "EGL_software_device_index": device_index,
        "CUDA_VISIBLE_DEVICES": "",
        "render_resolution": [256, 256],
        "task": suite.get_task(0).name,
        "images": list(frames),
        "physics_steps": 1,
        "model_inference": False,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "scope": "CPU software rendering; GPU EGL and policy evaluation not tested",
    }
    (ROOT / "results/libero_render_smoke.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
finally:
    env.close()
