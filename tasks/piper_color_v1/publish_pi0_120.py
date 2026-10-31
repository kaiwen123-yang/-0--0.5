"""Snapshot every real update log; bounded delivery and explicit pending state."""
import argparse
import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "codex/pi0-120-demo-v2-20261101"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, timeout=35).strip()


def save(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def publish(run, stage):
    with (run / "publication.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if git("branch", "--show-current") != BRANCH:
            raise RuntimeError("Publication branch changed")
        destination = ROOT / "results/piper-color-v1" / run.name
        destination.mkdir(parents=True, exist_ok=True)
        relative_root = str(destination.relative_to(ROOT))
        staged = git("diff", "--cached", "--name-only").splitlines()
        if any(not p.startswith(relative_root + "/") for p in staged):
            raise RuntimeError("Unrelated staged changes; refusing to commit them")
        selected = set()
        for pattern in ("*.json", "*.jsonl", "*.txt", "*.exit", "assets/**/*.json", "dataset/*.json",
                        "scene/*.xml", "scene/*.json", "logs/*.log", "evaluations/**/*.json", "history/*"):
            selected.update(run.glob(pattern))
        for source in sorted(selected):
            if source.is_file():
                target = destination / source.relative_to(run)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        checkpoints = []
        for resume in sorted((run / "checkpoints").glob("*/*/*/resume.json")):
            checkpoint = resume.parent
            paths = [p for p in checkpoint.rglob("*") if p.is_file()]
            checkpoints.append({"updates": int(checkpoint.name), "server_path": str(checkpoint),
                 "file_count": len(paths), "bytes": sum(p.stat().st_size for p in paths),
                 "resume": json.loads(resume.read_text()), "uploaded": False})
        save(destination / "publication_status.json", {"stage": stage, "snapshot_at_utc": now(),
             "run_directory": str(run), "branch": BRANCH,
             "tracked_files": [str(p.relative_to(run)) for p in sorted(selected) if p.is_file()],
             "local_checkpoints": checkpoints,
             "publication_scope": "source, config, all per-update logs, teacher and evaluation JSON, scene and checksums",
             "binary_location": "D57: regenerated RGB data, full checkpoints, videos and raw trajectories retained locally",
             "success_criterion": "Complete closed-loop task under the frozen v2 environment"})
        git("add", "--", relative_root)
        if git("diff", "--cached", "--name-only"):
            git("commit", "-m", f"Record pi0 120-demo v2 {stage}")
        commit = git("rev-parse", "HEAD")
        attempts = []
        for attempt in range(1, 4):
            result = subprocess.run(["timeout", "--kill-after=3s", "25s", "git", "-C", str(ROOT),
                       "-c", "http.version=HTTP/1.1", "push", "origin", f"HEAD:refs/heads/{BRANCH}"],
                       text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            row = {"stage": stage, "commit": commit, "attempt": attempt, "at_utc": now(),
                   "returncode": result.returncode, "output": result.stdout[-4000:]}
            attempts.append(row)
            with (run / "publication_attempts.jsonl").open("a") as stream:
                stream.write(json.dumps(row) + "\n")
            if result.returncode == 0:
                receipt = {"stage": stage, "commit": commit, "pushed_at_utc": row["at_utc"]}
                with (run / "publication_receipts.jsonl").open("a") as stream:
                    stream.write(json.dumps(receipt) + "\n")
                save(run / "publication_delivery.json", {"status": "pushed", **receipt, "pending_commits": False})
                print("GITHUB_PUSHED " + json.dumps(receipt), flush=True)
                return
            if attempt < 3:
                time.sleep(2 * attempt)
        save(run / "publication_delivery.json", {"status": "pending", "stage": stage,
             "commit": commit, "attempts": attempts, "pending_commits": True,
             "next_action": "next 500-update boundary, evaluation, completion or bounded final retries"})
        print("GITHUB_PENDING " + commit, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    publish(args.run.resolve(strict=True), args.stage)
