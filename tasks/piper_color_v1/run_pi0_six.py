"""Run only the authorized 2010-update development budget and its evaluations."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "scripts/run_pi0_six_d57.sh"
UPDATES = (500, 1000, 1500, 2000, 2010)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def capture(*command):
    return subprocess.check_output(command, text=True).strip()


def main(run):
    run = run.resolve()
    run.mkdir(parents=True, exist_ok=False)
    (run / "logs").mkdir()
    env = dict(os.environ, PIPER_COLOR_RUN=str(run))
    status = {"started_at": now(), "pid": os.getpid(), "stage": "preparing", "completed": False,
              "authorized_scope": "pi0 LoRA 6 demos, 2010 updates, 5 checkpoint evaluations and final seed-43 repeat",
              "source_commit": capture("git", "-C", str(ROOT), "rev-parse", "HEAD"),
              "upstream_commit": capture("git", "-C", str(ROOT.parent / "pi0/openpi"), "rev-parse", "HEAD"),
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [ENTRY, *sorted((ROOT / "tasks/piper_color_v1").glob("*.py"))]},
              "gpu_before": capture("nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv"),
              "gpu_processes_before": capture("nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv"),
              "evaluation_base_seeds": [42, 43], "checkpoint_update_counts": list(UPDATES),
              "hardware_execution": False}
    save(run / "run.json", status)

    def execute(stage, *args, label=None, timeout=14400):
        status.update(stage=label or stage, updated_at=now())
        save(run / "run.json", status)
        log = run / "logs" / f"{label or stage}.log"
        with log.open("w") as stream:
            subprocess.run(["bash", str(ENTRY), stage, *map(str, args)], env=env,
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=timeout)

    try:
        with (ROOT / "runtime/pi0-six-demo.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock.write(str(os.getpid()))
            lock.flush()
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 18766))
            execute("prepare", timeout=900)
            execute("train")
            for updates in UPDATES:
                checkpoint = run / "checkpoints/pi0_piper_color_lora/six_demo_v1" / str(updates)
                norm = checkpoint / "assets/piper_h_color_v1"
                if not all((checkpoint / item).exists() for item in ("params", "train_state", "resume.json")):
                    raise RuntimeError(f"Incomplete checkpoint: {checkpoint}")
                log_path = run / "logs" / f"serve_{updates}.log"
                with log_path.open("w") as stream:
                    service = subprocess.Popen(["bash", str(ENTRY), "serve", "--checkpoint", str(checkpoint),
                                                "--norm-stats", str(norm)], env=env,
                                               stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        status.update(stage=f"loading_checkpoint_{updates}", service_pid=service.pid, updated_at=now())
                        save(run / "run.json", status)
                        deadline = time.monotonic() + 600
                        while "MODEL_LOADED " not in log_path.read_text(errors="replace"):
                            if service.poll() is not None:
                                raise RuntimeError(f"Pi0 service exited with {service.returncode}; see {log_path}")
                            if time.monotonic() > deadline:
                                raise TimeoutError(f"Checkpoint load exceeded 600 seconds: {checkpoint}")
                            time.sleep(1)
                        # The loaded marker immediately precedes WebSocket bind.
                        time.sleep(1)
                        for seed in ((42, 43) if updates == 2010 else (42,)):
                            label = f"eval_{updates}_seed{seed}"
                            execute("evaluate", "--checkpoint", checkpoint, "--norm-stats", norm,
                                    "--seed", seed, "--output", run / "evaluations" / label,
                                    label=label, timeout=2400)
                            result = json.loads((run / "evaluations" / label / "summary.json").read_text())
                            if not result["complete"] or result["total"] != 6 or result["errors"]:
                                raise RuntimeError(f"Evaluation execution was incomplete: {label}")
                    finally:
                        if service.poll() is None:
                            service.terminate()
                            try:
                                service.wait(timeout=30)
                            except subprocess.TimeoutExpired:
                                service.kill()
                                service.wait(timeout=10)
                        status.pop("service_pid", None)
            execute("summarize", timeout=120)
            status.update(stage="completed", completed=True, finished_at=now(),
                          report=str(run / "summary.json"),
                          gpu_after=capture("nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv"))
            save(run / "run.json", status)
            subprocess.run(["/root/miniconda3/bin/python", str(Path(__file__).with_name("publish_pi0_six.py")),
                            str(run), "--stage", "evaluation-complete"], check=True)
    except BaseException as exc:
        status.update(stage="failed", error=repr(exc), finished_at=now())
        save(run / "run.json", status)
        # One bounded publication attempt records failures as failures.
        try:
            subprocess.run(["/root/miniconda3/bin/python", str(Path(__file__).with_name("publish_pi0_six.py")),
                            str(run), "--stage", "failed"], check=True, timeout=180)
        except Exception as publication_error:
            status["failure_publication_error"] = repr(publication_error)
        raise
    finally:
        save(run / "run.json", status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    main(parser.parse_args().run)
