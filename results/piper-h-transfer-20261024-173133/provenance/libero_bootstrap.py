"""Workspace-local LIBERO paths and Python 3.11 compatibility helpers."""
import ctypes
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "repos/openpi/third_party/libero"
BENCHMARK_ROOT = SOURCE / "libero/libero"


def configure(cpu_only=False):
    config_dir = ROOT / "envs/libero/config"
    dataset_dir = ROOT / "envs/libero/datasets"
    config_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "benchmark_root": str(BENCHMARK_ROOT),
        "bddl_files": str(BENCHMARK_ROOT / "bddl_files"),
        "init_states": str(BENCHMARK_ROOT / "init_files"),
        "datasets": str(dataset_dir),
        "assets": str(BENCHMARK_ROOT / "assets"),
    }
    # JSON is valid YAML; writing before the LIBERO import avoids its interactive
    # first-run prompt and keeps the user's ~/.libero untouched.
    (config_dir / "config.yaml").write_text(json.dumps(paths, indent=2) + "\n")
    os.environ["LIBERO_CONFIG_PATH"] = str(config_dir)
    os.environ.setdefault("NUMBA_CACHE_DIR", str(ROOT / "envs/libero/numba_cache"))
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "envs/libero/matplotlib"))
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    if cpu_only:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        # GLFW is imported but no GL context is created when renderers are disabled.
        os.environ["MUJOCO_GL"] = "glx"
    sys.path.insert(0, str(SOURCE))
    return paths


def allow_trusted_initial_states():
    """Allow only NumPy data types in the upstream initial-state tensor files.

    PyTorch >=2.6 uses weights_only=True by default, unlike the upstream 1.11
    version. Keep that restricted loader instead of disabling it globally.
    """
    import numpy as np
    import torch
    torch.serialization.add_safe_globals([
        np.core.multiarray._reconstruct,
        np.ndarray,
        np.dtype,
        np.dtypes.Float64DType,
        np.dtypes.Float32DType,
    ])


def configure_software_rendering():
    """Select Mesa's software EGL device without initializing hardware displays."""
    mesa_vendor = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")
    if not mesa_vendor.is_file():
        raise SystemExit("Mesa EGL vendor file unavailable; CPU rendering was not attempted.")
    os.environ.update({
        "CUDA_VISIBLE_DEVICES": "",
        "MUJOCO_GL": "egl",
        "PYOPENGL_PLATFORM": "egl",
        "__EGL_VENDOR_LIBRARY_FILENAMES": str(mesa_vendor),
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "MESA_LOADER_DRIVER_OVERRIDE": "swrast",
        "GALLIUM_DRIVER": "llvmpipe",
        "LP_NUM_THREADS": "2",
    })

    # Mesa advertises hardware devices too. Select only its explicit software device,
    # before MuJoCo initializes any EGL display; never assume that index zero is CPU.
    egl = ctypes.CDLL("libEGL.so.1")
    egl.eglGetProcAddress.restype = ctypes.c_void_p
    query_devices = ctypes.CFUNCTYPE(
        ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)
    )(egl.eglGetProcAddress(b"eglQueryDevicesEXT"))
    query_string = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int)(
        egl.eglGetProcAddress(b"eglQueryDeviceStringEXT")
    )
    devices = (ctypes.c_void_p * 32)()
    count = ctypes.c_int()
    assert query_devices(32, devices, ctypes.byref(count))
    for device_index in range(count.value):
        extensions = query_string(devices[device_index], 0x3055) or b""
        if b"EGL_MESA_device_software" in extensions:
            os.environ["MUJOCO_EGL_DEVICE_ID"] = str(device_index)
            break
    else:
        raise SystemExit("No Mesa software EGL device; rendering was not attempted.")
    return str(mesa_vendor), device_index
