"""Sequential frozen-model probes in detached tmux; no training entry point."""
import datetime
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "outputs/pi0-120-demo-v2-20261101"
OUT = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"
ENTRY = ROOT / "scripts/run_pi0_120_d57.sh"
SIM = ROOT / "runtime/d57-color-sim/bin/python"
PROBE = ROOT / "tasks/piper_color_v1/probe_pi0_120_regression.py"
ENV = dict(os.environ, PIPER_COLOR_RUN=str(RUN), MUJOCO_GL="egl", PYOPENGL_PLATFORM="egl",
           OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2", PYTHONNOUSERSITE="1")
ENV.pop("PYTHONPATH", None); ENV.pop("PYTHONHOME", None); ENV.pop("LD_LIBRARY_PATH", None)


def save_status(**kwargs):
    status.update(updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), **kwargs)
    temp = OUT / "probe_status.json.tmp"
    temp.write_text(json.dumps(status, indent=2)); temp.replace(OUT / "probe_status.json")


def execute(stage, *args, label):
    save_status(stage=label)
    with (OUT / "logs" / f"{label}.log").open("x") as stream:
        subprocess.run(["taskset", "-c", "0-3", "nice", "-n", "10", str(SIM), "-u", str(PROBE), stage, *args],
                       env=ENV, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=5400)


def stop(p):
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGTERM)
        try: p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=10)


if __name__ == "__main__":
    (OUT / "logs").mkdir(exist_ok=True)
    status = {"pid": os.getpid(), "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "optimizer_updates": 0, "test_layouts_used": False, "completed": False}
    save_status(stage="preparing")
    with socket.socket() as probe: probe.bind(("127.0.0.1", 18767))
    try:
        execute("prepare", label="teacher_reference")
        for label, checkpoint in [
            ("old2010", ROOT / "outputs/pi0-six-demo-20261031/checkpoints/pi0_piper_color_lora/six_demo_v1/2010"),
            *[(f"new{n}", RUN / "checkpoints/pi0_piper_color_lora/120_demo_contact_v2" / str(n)) for n in (2010, 4020, 8040)]]:
            old = label == "old2010"
            norm = checkpoint / "assets" / ("piper_h_color_v1" if old else "piper_h_color_contact_v2_120")
            log = OUT / "logs" / f"serve_{label}.log"
            with log.open("x") as stream:
                service = subprocess.Popen(["bash", str(ENTRY), "serve", "--checkpoint", str(checkpoint),
                           "--norm-stats", str(norm), "--config-scope", "six" if old else "120"],
                           env=ENV, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    save_status(stage=f"loading_{label}", service_pid=service.pid)
                    deadline = time.monotonic() + 900
                    while "MODEL_LOADED " not in log.read_text(errors="replace"):
                        if service.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError(f"Service did not load: {label}")
                        time.sleep(1)
                    time.sleep(1)
                    args = ["--label", label, "--checkpoint", str(checkpoint)]
                    execute("fixed", *args, label=f"fixed_{label}")
                    if label in ("old2010", "new8040"):
                        lengths = ["85"] if old else ["30", "60", "85"]
                        execute("prefix", *args, "--prefix-lengths", *lengths, label=f"prefix_{label}")
                finally:
                    stop(service)
                    status.pop("service_pid", None)
        save_status(stage="completed", completed=True, finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException as exc:
        save_status(stage="failed", error=repr(exc))
        raise
