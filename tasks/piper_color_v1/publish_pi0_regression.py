"""Publish compact diagnostic evidence; raw arrays use a separately verified release."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"
DEST = ROOT / "results/piper-color-v1/pi0-120-regression-diagnosis-20261101"
BRANCH = "codex/pi0-120-demo-v2-20261101"


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, timeout=90).strip()


def publish(stage):
    if git("branch", "--show-current") != BRANCH:
        raise RuntimeError("Branch changed")
    if git("diff", "--cached", "--name-only"):
        raise RuntimeError("Commit source changes separately before publishing results")
    selected = set()
    for pattern in ("*.json", "*.csv", "*.md", "logs/*.log", "fixed/*/*.json", "prefix/*/*.json",
                    "teacher_reference/*.json", "history/**/*.json", "history/**/*.log", "figures/*"):
        selected.update(OUT.glob(pattern))
    files = []
    for source in sorted(selected):
        if source.is_file():
            relative = source.relative_to(OUT)
            target = DEST / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            files.append({"file": str(relative), "bytes": target.stat().st_size,
                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (DEST / "publication_index.json").write_text(json.dumps({
        "stage": stage, "at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_commit_before_snapshot": git("rev-parse", "HEAD"), "files": files,
        "server_output": str(OUT), "optimizer_updates": 0,
        "raw_binary_status": "See raw_artifact_release.json when available; large arrays are not stored in Git"}, indent=2))
    git("add", "--", str(DEST.relative_to(ROOT)))
    git("commit", "-m", f"Record pi0 regression diagnosis: {stage}")
    git("push", "origin", f"HEAD:refs/heads/{BRANCH}")
    head = git("rev-parse", "HEAD")
    remote = git("ls-remote", "--heads", "origin", f"refs/heads/{BRANCH}").split()[0]
    if remote != head: raise ValueError("Remote does not match published commit")
    print(json.dumps({"stage": stage, "verified_remote_commit": head}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--stage", required=True)
    publish(p.parse_args().stage)
