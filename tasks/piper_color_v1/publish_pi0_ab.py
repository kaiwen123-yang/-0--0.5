"""Commit scoped text snapshots and deliver with bounded Git retries."""
import argparse
import datetime
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "codex/pi0-ab-old2010-20261101"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2))
    tmp.replace(path)


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, timeout=40).strip()


def publish(campaign, stage):
    campaign = Path(campaign).resolve(strict=True)
    try:
        with (campaign / "publication.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if git("branch", "--show-current") != BRANCH:
                raise RuntimeError("Publication branch changed")
            destination = ROOT / "results/piper-color-v1" / campaign.name
            destination.mkdir(parents=True, exist_ok=True)
            relative = str(destination.relative_to(ROOT))
            if any(not p.startswith(relative + "/") for p in git("diff", "--cached", "--name-only").splitlines()):
                raise RuntimeError("Unrelated staged files")
            files = set(campaign.glob("*.json")) | set(campaign.glob("*.jsonl")) | set(campaign.glob("*.exit"))
            files.update(campaign.glob("logs/*.log"))
            for group in ("A", "B"):
                run = campaign / group
                for pattern in ("*.json", "*.jsonl", "*.txt", "assets/**/*.json", "scene/*", "logs/*.log",
                                "evaluations/**/*.json", "probes/fixed/**/*.json", "history/*.jsonl"):
                    files.update(run.glob(pattern))
            for src in sorted(files):
                if src.is_file():
                    dst = destination / src.relative_to(campaign)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
            inventory = []
            for resume in sorted(campaign.glob("*/checkpoints/*/*/*/resume.json")):
                ckpt = resume.parent
                members = [p for p in ckpt.rglob("*") if p.is_file()]
                inventory.append({"server_path": str(ckpt), "bytes": sum(p.stat().st_size for p in members),
                                  "files": len(members), "resume": json.loads(resume.read_text()), "uploaded": False})
            save(destination / "publication_status.json", {"stage": stage, "snapshot_at_utc": now(),
                "branch": BRANCH, "campaign_directory": str(campaign), "text_files": len(files),
                "full_checkpoints": inventory,
                "scope": "source/config, exact text sampling tables, every update metric, raw process logs and evaluation/probe JSON",
                "large_artifacts": "full checkpoints, videos and raw arrays remain on D57; not uploaded by Git publisher"})
            git("add", "--", relative)
            if git("diff", "--cached", "--name-only"):
                git("commit", "-m", f"Record pi0 old2010 A/B: {stage}")
            commit = git("rev-parse", "HEAD")
            for attempt in range(1, 4):
                result = subprocess.run(["timeout", "--kill-after=3s", "25s", "git", "-C", str(ROOT),
                    "-c", "http.version=HTTP/1.1", "push", "origin", f"HEAD:refs/heads/{BRANCH}"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=32)
                row = {"stage": stage, "commit": commit, "attempt": attempt, "at_utc": now(),
                       "returncode": result.returncode, "output": result.stdout[-4000:]}
                with (campaign / "publication_attempts.jsonl").open("a") as stream:
                    stream.write(json.dumps(row) + "\n")
                if result.returncode == 0:
                    receipt = {"stage": stage, "commit": commit, "pushed_at_utc": row["at_utc"]}
                    with (campaign / "publication_receipts.jsonl").open("a") as stream:
                        stream.write(json.dumps(receipt) + "\n")
                    save(campaign / "publication_delivery.json", {"status": "pushed", **receipt, "pending_commits": False})
                    print("GITHUB_PUSHED " + json.dumps(receipt), flush=True)
                    return True
                if attempt < 3:
                    time.sleep(2 * attempt)
            save(campaign / "publication_delivery.json", {"status": "pending", "stage": stage,
                 "commit": commit, "pending_commits": True, "next_attempt": "next update boundary/evaluation/final retry"})
            print("GITHUB_PENDING " + commit, flush=True)
            return False
    except Exception as exc:
        with (campaign / "publication_errors.jsonl").open("a") as stream:
            stream.write(json.dumps({"stage": stage, "at_utc": now(), "error": repr(exc)}) + "\n")
        save(campaign / "publication_delivery.json", {"status": "error_pending", "stage": stage,
             "error": repr(exc), "pending_commits": True})
        print("PUBLICATION_ERROR " + repr(exc), flush=True)
        return False


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("campaign", type=Path)
    p.add_argument("--stage", required=True)
    a = p.parse_args()
    raise SystemExit(0 if publish(a.campaign, a.stage) else 1)
