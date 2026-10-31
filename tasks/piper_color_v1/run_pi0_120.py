"""Detached D57 pipeline: v2 data -> old-model baseline -> first training cycle."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "scripts/run_pi0_120_d57.sh"
BRANCH = "codex/pi0-120-demo-v2-20261101"
ASSET = "piper_h_color_contact_v2_120"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def capture(*command):
    return subprocess.check_output(command, text=True, timeout=20).strip()


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def main(run):
    run = run.resolve(strict=True)
    if (run / "run.json").exists():
        raise FileExistsError("Run already has a supervisor record; inspect before any restart")
    if capture("git", "-C", str(ROOT), "branch", "--show-current") != BRANCH:
        raise ValueError("Unexpected source branch")
    env = dict(os.environ, PIPER_COLOR_RUN=str(run))
    status = {"started_at": now(), "pid": os.getpid(), "stage": "waiting_for_dataset", "completed": False,
              "scope": "pi0 v2 120-demo first cycle to 8040; pause for closed-loop review before longer stages",
              "schedule_budget": 24120, "automatic_training_end": 8040,
              "source_commit": capture("git", "-C", str(ROOT), "rev-parse", "HEAD"),
              "upstream_commit": capture("git", "-C", str(ROOT.parent / "pi0/openpi"), "rev-parse", "HEAD"),
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [ENTRY, *sorted((ROOT / "tasks/piper_color_v1").glob("*.py"))]},
              "evaluation_nodes": [2010, 4020, 8040], "evaluation_base_seeds": [42, 43],
              "baseline": "old six-demo pi0 checkpoint 2010, original normalization, frozen v2 validation 15x2",
              "hardware_execution": False}
    save(run / "run.json", status)
    stopping = threading.Event()

    def event(kind, **kwargs):
        with (run / "execution_events.jsonl").open("a") as stream:
            stream.write(json.dumps({"at_utc": now(), "event": kind, **kwargs}) + "\n")

    def monitor():
        while not stopping.is_set():
            try:
                row = {"at_utc": now(), "stage": status["stage"], "supervisor_pid": os.getpid(),
                       "disk_free_bytes": shutil.disk_usage(run).free,
                       "gpu": capture("nvidia-smi", "--query-gpu=memory.used,utilization.gpu,temperature.gpu,power.draw", "--format=csv,noheader"),
                       "gpu_processes": capture("nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader")}
                with (run / "resources.jsonl").open("a") as stream:
                    stream.write(json.dumps(row) + "\n")
            except Exception as exc:
                event("resource_monitor_error", error=repr(exc))
            stopping.wait(30)

    def publish(stage):
        try:
            result = subprocess.run(["/root/miniconda3/bin/python", str(ROOT / "tasks/piper_color_v1/publish_pi0_120.py"),
                                     str(run), "--stage", stage], timeout=150)
            if result.returncode:
                event("publication_error", stage=stage, returncode=result.returncode)
        except Exception as exc:
            event("publication_error", stage=stage, error=repr(exc))

    def execute(stage, *args, label=None, timeout=14400):
        label = label or stage
        status.update(stage=label, updated_at=now())
        save(run / "run.json", status)
        command = ["bash", str(ENTRY), stage, *map(str, args)]
        event("process_start", label=label, command=command)
        t0 = time.monotonic()
        with (run / "logs" / f"{label}.log").open("x") as stream:
            process = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            status["child_pid"] = process.pid
            save(run / "run.json", status)
            try:
                rc = process.wait(timeout=timeout)
                event("process_end", label=label, returncode=rc, elapsed_seconds=time.monotonic() - t0)
                if rc:
                    raise RuntimeError(f"{label} exited {rc}; see logs/{label}.log")
            finally:
                stop(process)
                status.pop("child_pid", None)

    def evaluate(checkpoint, name, baseline=False):
        norm = checkpoint / "assets" / ("piper_h_color_v1" if baseline else ASSET)
        for item in ("params", "train_state", "resume.json"):
            if not (checkpoint / item).exists():
                raise FileNotFoundError(checkpoint / item)
        log = run / "logs" / f"serve_{name}.log"
        command = ["bash", str(ENTRY), "serve", "--checkpoint", str(checkpoint), "--norm-stats", str(norm),
                   "--config-scope", "six" if baseline else "120"]
        status.update(stage=f"loading_{name}", updated_at=now())
        save(run / "run.json", status)
        with log.open("x") as stream:
            service = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            status["service_pid"] = service.pid
            save(run / "run.json", status)
            event("service_start", name=name, pid=service.pid, command=command)
            try:
                deadline = time.monotonic() + 900
                while "MODEL_LOADED " not in log.read_text(errors="replace"):
                    if service.poll() is not None:
                        raise RuntimeError(f"Policy service exited {service.returncode}: {log}")
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Model loading timeout: {name}")
                    time.sleep(1)
                time.sleep(1)
                for split in (("validation",) if baseline else ("train", "validation")):
                    for seed in (42, 43):
                        label = f"{name}_{split}_seed{seed}"
                        args = ["--split", split, "--seed", seed, "--checkpoint", checkpoint, "--norm-stats", norm,
                                "--output", run / "evaluations" / label]
                        if split == "train":
                            args += ["--layout-seeds", 100, 101]
                        execute("evaluate", *args, label=label, timeout=5400)
                        result = json.loads((run / "evaluations" / label / "summary.json").read_text())
                        if not result["complete"] or result["errors"] or result["total"] != (6 if split == "train" else 15):
                            raise RuntimeError(f"Incomplete evaluation: {label}")
                        summarize()
                        publish(label)
            finally:
                stop(service)
                event("service_stopped", name=name, returncode=service.returncode)
                status.pop("service_pid", None)

    def summarize():
        rows = []
        for path in sorted((run / "evaluations").glob("*/summary.json")):
            result = json.loads(path.read_text())
            episodes = result["episodes"]
            rows.append({"evaluation": path.parent.name, "split": result["split"],
                         "successes": result["successes"], "total": result["total"], "errors": result["errors"],
                         "complete": result["complete"],
                         "lifted_5cm": sum(e.get("diagnostics", {}).get("max_lift_cm", 0) > 5 for e in episodes),
                         "bilateral_lift": sum(e.get("diagnostics", {}).get("first_bilateral_lift_frame") is not None for e in episodes),
                         "over_box": sum(e.get("diagnostics", {}).get("over_box_frames", 0) > 0 for e in episodes),
                         "observed_drops": sum(e.get("diagnostics", {}).get("drop_frame") is not None for e in episodes)})
        save(run / "evaluation_summary.json", {"evaluations": rows, "test_used": False,
             "decision": "Review both seeds and grouped layouts at 8040 before authorizing the next segment"})

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    try:
        with (ROOT / "runtime/pi0-120-demo.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 18767))
            deadline = time.monotonic() + 3600
            while not (run / "generate.exit").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("Dataset preparation exceeded 1 hour")
                time.sleep(2)
            if (run / "generate.exit").read_text().strip() != "0" or not (run / "data_complete.json").exists():
                raise RuntimeError("Data generation failed; see logs/generate.log")
            controls = json.loads((run / "teacher_controls.json").read_text())
            if not controls["complete"] or not controls["all_passed"]:
                raise ValueError("Teacher controls failed")
            if shutil.disk_usage(run).free < 85 * 1024**3:
                raise RuntimeError("Insufficient disk for 120-demo checkpoints and evaluations")
            execute("prepare", timeout=1800)
            publish("data-and-normalization-frozen")
            old = ROOT / "outputs/pi0-six-demo-20261031/checkpoints/pi0_piper_color_lora/six_demo_v1/2010"
            evaluate(old, "baseline_old2010_v2", baseline=True)
            for updates in (2010, 4020, 8040):
                args = ["--until", updates] + (["--resume"] if updates > 2010 else [])
                execute("train", *args, label=f"train_to_{updates}")
                checkpoint = run / "checkpoints/pi0_piper_color_lora/120_demo_contact_v2" / str(updates)
                evaluate(checkpoint, f"update_{updates}")
            summarize()
            status.update(stage="decision_required_at_8040", first_cycle_complete=True,
                          completed=True, full_24120_budget_complete=False, finished_at=now(),
                          next_action="Review complete success and failure trajectories across both seeds before 16080/24120")
            save(run / "run.json", status)
            publish("first-cycle-complete-review-required")
            # Only a bounded retry window; failed uploads never consume GPU work again.
            for attempt in range(3):
                delivery = json.loads((run / "publication_delivery.json").read_text()) if (run / "publication_delivery.json").exists() else {}
                if delivery.get("status") == "pushed":
                    break
                time.sleep(30)
                publish(f"final-delivery-retry-{attempt + 1}")
    except BaseException as exc:
        status.update(stage="failed", error=repr(exc), finished_at=now())
        save(run / "run.json", status)
        event("supervisor_failure", error=repr(exc))
        publish("failed")
        raise
    finally:
        stopping.set()
        monitor_thread.join(timeout=25)
        save(run / "run.json", status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    main(parser.parse_args().run)
