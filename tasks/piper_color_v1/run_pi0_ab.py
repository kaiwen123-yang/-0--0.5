"""Detached, bounded A then B execution with full evaluations between segments."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
import shutil

from publish_pi0_ab import publish, BRANCH

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "scripts/run_pi0_ab_d57.sh"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2))
    tmp.replace(path)


def capture(*command):
    return subprocess.check_output(command, text=True, timeout=20).strip()


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def main(campaign):
    campaign = campaign.resolve(strict=True)
    if (campaign / "run.json").exists():
        raise FileExistsError("Supervisor record already exists; inspect instead of launching twice")
    if capture("git", "-C", str(ROOT), "branch", "--show-current") != BRANCH:
        raise ValueError("Wrong source branch")
    contract = json.loads((campaign / "contract.json").read_text())
    status = {"started_at": now(), "pid": os.getpid(), "stage": "initializing", "completed": False,
        "order": ["A", "B"], "base_optimizer_updates": 2010, "new_updates_per_group": 2010,
        "source_commit": capture("git", "-C", str(ROOT), "rev-parse", "HEAD"),
        "upstream_commit": capture("git", "-C", str(ROOT.parent / "pi0/openpi"), "rev-parse", "HEAD"),
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in [ENTRY, *sorted((ROOT / "tasks/piper_color_v1").glob("*.py"))]},
        "groups": {g: {"state": "queued", "completed_local_updates": 0} for g in ("A", "B")},
        "evaluation_nodes_local": [500, 1000, 2010], "hardware_execution": False, "test_split_used": False}
    save(campaign / "run.json", status)
    stopping = threading.Event()

    def event(kind, **values):
        with (campaign / "execution_events.jsonl").open("a") as stream:
            stream.write(json.dumps({"at_utc": now(), "event": kind, **values}) + "\n")

    def monitor():
        while not stopping.is_set():
            try:
                row = {"at_utc": now(), "stage": status["stage"], "supervisor_pid": os.getpid(),
                    "disk_free_bytes": shutil.disk_usage(campaign).free,
                    "gpu": capture("nvidia-smi", "--query-gpu=memory.used,utilization.gpu,temperature.gpu,power.draw", "--format=csv,noheader"),
                    "gpu_processes": capture("nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader")}
                with (campaign / "resources.jsonl").open("a") as stream:
                    stream.write(json.dumps(row) + "\n")
            except Exception as exc:
                event("resource_monitor_error", error=repr(exc))
            stopping.wait(30)

    def check_resources():
        free = int(capture("nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits").splitlines()[0])
        if free < 45000 or shutil.disk_usage(campaign).free < 20 * 1024**3:
            raise RuntimeError(f"Shared resources insufficient: GPU free={free} MiB")

    def execute(run, stage, *args, label, timeout=7200):
        status.update(stage=f"{run.name}/{label}", updated_at=now())
        save(campaign / "run.json", status)
        command = ["bash", str(ENTRY), stage, *map(str, args)]
        event("process_start", group=run.name, label=label, command=command)
        t0 = time.monotonic()
        with (run / "logs" / f"{label}.log").open("x") as stream:
            proc = subprocess.Popen(command, env=dict(os.environ, PIPER_COLOR_RUN=str(run)),
                                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            status["child_pid"] = proc.pid
            save(campaign / "run.json", status)
            try:
                rc = proc.wait(timeout=timeout)
                event("process_end", group=run.name, label=label, returncode=rc, seconds=time.monotonic() - t0)
                if rc:
                    raise RuntimeError(f"{run.name}/{label} exited {rc}; see its raw process log")
            finally:
                stop(proc)
                status.pop("child_pid", None)
                save(campaign / "run.json", status)

    def evaluate(run, local):
        check_resources()
        checkpoint = run / "checkpoints/pi0_piper_color_lora/ab_old2010" / str(local)
        norm = checkpoint / "assets/piper_h_color_v1"
        for item in ("params", "train_state", "resume.json"):
            if not (checkpoint / item).exists():
                raise FileNotFoundError(checkpoint / item)
        command = ["bash", str(ENTRY), "serve", "--checkpoint", str(checkpoint), "--norm-stats", str(norm)]
        label = f"update_{local}"
        log = run / "logs" / f"serve_{label}.log"
        status.update(stage=f"{run.name}/loading_{label}", updated_at=now())
        with log.open("x") as stream:
            service = subprocess.Popen(command, env=dict(os.environ, PIPER_COLOR_RUN=str(run)),
                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            status["service_pid"] = service.pid
            save(campaign / "run.json", status)
            event("service_start", group=run.name, local_update=local, pid=service.pid, command=command)
            try:
                deadline = time.monotonic() + 900
                while "MODEL_LOADED " not in log.read_text(errors="replace"):
                    if service.poll() is not None:
                        raise RuntimeError(f"Policy service exited {service.returncode}: {log}")
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Policy service loading exceeded 900 seconds: {log}")
                    time.sleep(1)
                # The marker precedes websocket bind. Wait for the actual listener.
                while True:
                    try:
                        with socket.create_connection(("127.0.0.1", 18768), timeout=1):
                            break
                    except OSError:
                        if service.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError("Policy server did not bind")
                        time.sleep(1)
                for split in ("train", "validation"):
                    for seed in (42, 43):
                        name = f"{label}_{split}_seed{seed}"
                        args = ["--split", split, "--seed", seed, "--checkpoint", checkpoint,
                                "--norm-stats", norm, "--output", run / "evaluations" / name]
                        if split == "train":
                            args += ["--layout-seeds", 100, 101]
                        execute(run, "evaluate", *args, label=name, timeout=5400)
                        result = json.loads((run / "evaluations" / name / "summary.json").read_text())
                        if not result["complete"] or result["errors"] or result["total"] != (6 if split == "train" else 15):
                            raise RuntimeError(f"Incomplete/error evaluation: {name}")
                        publish(campaign, f"{run.name}-{name}")
                execute(run, "probe", "--local-update", local, "--checkpoint", checkpoint,
                        label=f"probe_{local}", timeout=1800)
                publish(campaign, f"{run.name}-node-{local}-complete")
            finally:
                stop(service)
                status.pop("service_pid", None)
                event("service_stopped", group=run.name, local_update=local, returncode=service.returncode)
                save(campaign / "run.json", status)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        with (ROOT / "runtime/pi0-ab.lock").open("a") as lock, (ROOT / "runtime/pi0-120-demo.lock").open("a") as old_lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(old_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 18768))
            publish(campaign, "supervisor-started")
            for group in ("A", "B"):
                run = campaign / group
                status["groups"][group]["state"] = "running"
                matches = [contract["baseline_fixed"]["prompt_matched_teacher_endpoint"]]
                for local in (500, 1000, 2010):
                    check_resources()
                    execute(run, "train", "--until", local, *(["--resume"] if local > 500 else []), label=f"train_to_{local}")
                    status["groups"][group]["completed_local_updates"] = local
                    save(campaign / "run.json", status)
                    evaluate(run, local)
                    node = json.loads((run / f"node_{local}.json").read_text())
                    matches.append(node["prompt_matches"])
                    if local == 1000 and matches[0] > matches[1] > matches[2]:
                        status["groups"][group].update(state="stopped_by_predeclared_decline_rule", prompt_matches=matches)
                        save(run / "early_stop.json", {"reason": "two consecutive prompt-match decreases", "matches": matches,
                            "local_updates": local, "remaining_budget_not_consumed": 2010 - local})
                        event("group_early_stop", group=group, matches=matches)
                        break
                else:
                    status["groups"][group]["state"] = "complete"
                save(campaign / "run.json", status)
                publish(campaign, f"{group}-finished")
            summary = {"groups": status["groups"], "nodes": [], "selected_candidates": {},
                       "test_split_used": False, "hardware_execution": False, "additional_training_authorized": False}
            for group in ("A", "B"):
                summary["nodes"] += [json.loads(p.read_text()) for p in sorted((campaign / group).glob("node_*.json"))]
                summary["selected_candidates"][group] = json.loads((campaign / group / "selected_candidate.json").read_text())
            save(campaign / "comparison.json", summary)
            complete_budget = all(r["completed_local_updates"] == 2010 for r in status["groups"].values())
            status.update(stage="finished_review_required", completed=True, all_requested_updates_completed=complete_budget,
                          finished_at=now(), next_action="Review A/B full validation and targeting evidence; no automatic extension or test")
            save(campaign / "run.json", status)
            publish(campaign, "comparison-complete-review-required")
            for attempt in range(3):
                if json.loads((campaign / "publication_delivery.json").read_text()).get("status") == "pushed":
                    break
                time.sleep(30)
                publish(campaign, f"final-delivery-retry-{attempt + 1}")
    except BaseException as exc:
        status.update(stage="failed", error=repr(exc), finished_at=now())
        save(campaign / "run.json", status)
        event("supervisor_failure", error=repr(exc))
        publish(campaign, "failed")
        raise
    finally:
        stopping.set()
        thread.join(timeout=25)
        save(campaign / "run.json", status)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--campaign", type=Path, required=True)
    main(p.parse_args().campaign)
