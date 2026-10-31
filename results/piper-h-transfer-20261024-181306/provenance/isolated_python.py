"""Run with kaiwen-learn's interpreter and only a project's isolated dependencies."""
import os
from pathlib import Path
import runpy
import site
import sys

root = Path(__file__).resolve().parents[1]
env_name, *args = sys.argv[1:]
env = root / "envs" / env_name
packages = env / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if not packages.is_dir():
    raise SystemExit(f"Environment not installed: {packages}")
# Invoked with -S: no base-environment .pth files or ROS PYTHONPATH are loaded.
sys.path = [p for p in sys.path if p and "site-packages" not in p and "dist-packages" not in p]
sys.prefix = sys.exec_prefix = str(env)
site.ENABLE_USER_SITE = False
site.addsitedir(str(packages))
sys.path.insert(0, os.getcwd())
if not args:
    raise SystemExit("Usage: scripts/run.sh {openpi|libero|piper} SCRIPT.py [args] | -m MODULE [args] | -c CODE")
if args[0] == "-m":
    sys.argv = args[1:]
    runpy.run_module(args[1], run_name="__main__", alter_sys=True)
elif args[0] == "-c":
    sys.argv = ["-c", *args[2:]]
    exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})
else:
    sys.argv = args
    sys.path.insert(0, str(Path(args[0]).resolve().parent))
    runpy.run_path(args[0], run_name="__main__")
