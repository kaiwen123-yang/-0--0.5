"""Run both model servers and all LIBERO suites sequentially, with durable logs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PYTHON = "/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python"


def stop(process):
    if process is not None and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    manifest = json.loads((run / "manifest.json").read_text())
    logs = run / "logs"
    logs.mkdir(exist_ok=True)
    for name in ("run_libero_comparison.py", "run_libero_trials.py", "serve_eval_policy.py",
                 "summarize_libero_comparison.py", "libero_bootstrap.py", "run.sh", "isolated_python.py"):
        destination = run / "provenance/scripts" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(ROOT / "scripts" / name, destination)
        elif destination.read_bytes() != (ROOT / "scripts" / name).read_bytes():
            raise RuntimeError(f"Script changed after run began: {name}; review before resuming")

    def status(state, **extra):
        value = {"state": state, "updated_at": datetime.now(timezone.utc).isoformat(), **extra}
        temporary = run / "orchestrator-status.json.tmp"
        temporary.write_text(json.dumps(value, indent=2) + "\n")
        temporary.replace(run / "orchestrator-status.json")
        print(json.dumps(value), flush=True)

    def completed(model, suite):
        path = run / "episodes.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
        selected = [r for r in rows if r["model"] == model and r["suite"] == suite]
        task_ids = manifest.get("task_ids", list(range(10)))
        if isinstance(task_ids, dict):
            task_ids = task_ids[suite]
        expected = {(task, trial) for task in task_ids for trial in range(manifest["trials_per_task"])}
        return { (r["task_id"],r["trial_index"]) for r in selected if r["status"] != "error" } == expected

    def summarize():
        subprocess.run([PYTHON, "-S", str(ROOT / "scripts/summarize_libero_comparison.py"),
                        "--run-dir", str(run)], cwd=ROOT, check=True)

    server = client = None
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Received signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        for model in manifest["models"]:
            suites = [s for s in manifest["suites"] if not completed(model, s)]
            if not suites:
                continue
            active = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], text=True).strip()
            if active:
                raise RuntimeError("Another GPU compute process is active; this runner will not interrupt it")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, CUDA_VISIBLE_DEVICES="0", JAX_PLATFORMS="cuda", PYTHONUNBUFFERED="1")
            status("starting_server", model=model, port=port)
            with (logs / f"server-{model}.log").open("a") as server_log:
                server = subprocess.Popen([str(ROOT / "scripts/run.sh"), "openpi", str(ROOT / "scripts/serve_eval_policy.py"),
                                           "--model", model, "--run-dir", str(run), "--port", str(port)],
                                          cwd=ROOT, env=env, stdout=server_log, stderr=server_log, start_new_session=True)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                deadline = time.monotonic() + 240
                while True:
                    if server.poll() is not None:
                        raise RuntimeError(f"Model server exited with code {server.returncode}")
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                            if response.read() == b"OK\n":
                                break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Model server startup exceeded 240 seconds")
                        time.sleep(1)
                for suite in suites:
                    status("evaluating", model=model, suite=suite, server_pid=server.pid)
                    command = [str(ROOT / "scripts/run.sh"), "libero", str(ROOT / "scripts/run_libero_trials.py"),
                               "--run-dir", str(run), "--model", model, "--suite", suite,
                               "--port", str(port), "--trials", str(manifest["trials_per_task"]),
                               "--seed", str(manifest["seed"]), "--render-backend", "gpu",
                               "--egl-device", str(manifest["egl_device"])]
                    ids = manifest.get("task_ids")
                    if ids is not None:
                        command += ["--task-ids", *map(str, ids[suite] if isinstance(ids, dict) else ids)]
                    with (logs / f"{model}-{suite}.log").open("a") as client_log:
                        client = subprocess.Popen(command, cwd=ROOT, env=env, stdout=client_log,
                                                  stderr=client_log, start_new_session=True)
                        code = client.wait()
                    summarize()
                    if code != 0:
                        raise RuntimeError(f"Evaluator {model}/{suite} exited with {code}; inspect its log")
                stop(server)
                server = None
        summarize()
        summary = json.loads((run / "summary.json").read_text())
        if summary["status"] != "complete":
            raise RuntimeError(f"Evaluation did not finish cleanly: {summary['status']}")
        status("complete", episodes=summary["recorded_episodes"])
    except BaseException as error:
        status("stopped", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        stop(client)
        stop(server)


if __name__ == "__main__":
    main()
