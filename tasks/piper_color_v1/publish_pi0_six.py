"""Publish compact real-run logs at each 500-update boundary; no model upload."""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "codex/pi0-six-demo-20261031"


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, timeout=120).strip()


def publish(run, stage):
    if git("branch", "--show-current") != BRANCH:
        raise RuntimeError("Publication branch changed; refusing to commit onto another task")
    destination = ROOT / "results/piper-color-v1" / run.name
    destination.mkdir(parents=True, exist_ok=True)
    selected = []
    for pattern in ("*.json", "*.jsonl", "*.txt", "REPORT.md", "assets/**/*.json", "dataset/*.json",
                    "logs/*.log", "evaluations/**/*.json"):
        selected.extend(run.glob(pattern))
    files = []
    for source in sorted(set(selected)):
        if source.is_file():
            relative = source.relative_to(run)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            files.append(str(relative))
    checkpoints = []
    checkpoint_root = run / "checkpoints/pi0_piper_color_lora/six_demo_v1"
    if checkpoint_root.exists():
        for checkpoint in sorted(checkpoint_root.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else -1):
            if (checkpoint / "resume.json").exists():
                content = [p for p in checkpoint.rglob("*") if p.is_file()]
                checkpoints.append({"updates": int(checkpoint.name), "server_path": str(checkpoint),
                                    "file_count": len(content), "bytes": sum(p.stat().st_size for p in content),
                                    "resume": json.loads((checkpoint / "resume.json").read_text()),
                                    "uploaded": False})
    record = {"updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "stage": stage, "run_directory": str(run), "branch": BRANCH,
              "tracked_files": files, "local_checkpoints": checkpoints,
              "publication_scope": "source/config and all per-update logs; model parameters, optimizer, videos and NPZ remain on D57",
              "success_claim": "Only complete closed-loop evaluation determines task success"}
    (destination / "publication_status.json").write_text(json.dumps(record, indent=2))
    git("add", "--", str(destination.relative_to(ROOT)))
    git("commit", "-m", f"Record pi0 six-demo {stage} with per-update logs")
    git("push", "origin", f"HEAD:refs/heads/{BRANCH}")
    receipt = {"stage": stage, "commit": git("rev-parse", "HEAD"),
               "pushed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with (run / "publication_receipts.jsonl").open("a") as stream:
        stream.write(json.dumps(receipt) + "\n")
    print("GITHUB_PUSHED " + json.dumps(receipt), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    publish(args.run.resolve(strict=True), args.stage)
