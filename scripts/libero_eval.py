"""Run the upstream LIBERO client; CPU software rendering is the default."""
import os
import runpy
from libero_bootstrap import ROOT, configure, configure_software_rendering, allow_trusted_initial_states

configure()
backend = os.environ.get("LIBERO_RENDER_BACKEND", "cpu")
if backend == "cpu":
    configure_software_rendering()
elif backend == "gpu":
    # Explicit opt-in: this path was not exercised while the shared GPU was busy.
    for key in ("__EGL_VENDOR_LIBRARY_FILENAMES", "LIBGL_ALWAYS_SOFTWARE", "MESA_LOADER_DRIVER_OVERRIDE", "GALLIUM_DRIVER"):
        os.environ.pop(key, None)
    os.environ["MUJOCO_GL"] = "egl"
    os.environ["PYOPENGL_PLATFORM"] = "egl"
else:
    raise SystemExit("LIBERO_RENDER_BACKEND must be cpu (default) or gpu")
allow_trusted_initial_states()
runpy.run_path(str(ROOT / "repos/openpi/examples/libero/main.py"), run_name="__main__")
