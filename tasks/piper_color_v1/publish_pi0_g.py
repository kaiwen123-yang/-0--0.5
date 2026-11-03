"""Publish the G source, compact records, and delivery indexes."""
import os, shutil, subprocess
from g_common import *

def publish(stage):
    RESULTS.mkdir(parents=True, exist_ok=True)
    for current, dirs, files in os.walk(CAMPAIGN):
        dirs[:] = [d for d in dirs if d not in ("checkpoints", "assets", "scene")]
        for name in files:
            source = __import__("pathlib").Path(current) / name
            if source.suffix not in (".json", ".jsonl", ".txt", ".md", ".log", ".exit"):
                continue
            destination = RESULTS / source.relative_to(CAMPAIGN)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    paths = ["AGENTS.md", "docs/PI0_REPRO_REVIEW_NEXT_PLAN_20261103.md", "docs/PI0_NEXT_STAGE_PROMPT_20261103.md",
             str(RESULTS.relative_to(ROOT))]
    paths += [str(p.relative_to(ROOT)) for p in (ROOT / "tasks/piper_color_v1").glob("*pi0_g.py")]
    paths += ["tasks/piper_color_v1/g_common.py", "scripts/run_pi0_g_d57.sh"]
    ledger = ROOT / "publication" / TASK
    if ledger.exists():
        paths.append(str(ledger.relative_to(ROOT)))
    git("add", "--", *paths)
    if git("diff", "--cached", "--name-only"):
        git("commit", "-m", "Record pi0 G fixed-vision contrast: " + stage)
    commit = git("rev-parse", "HEAD")
    try:
        env = gh_env()
        proc = subprocess.run(["git", "-C", str(ROOT), "-c", "http.proxy=" + env["https_proxy"],
            "-c", "http.version=HTTP/1.1", "push", "origin", "HEAD:refs/heads/" + BRANCH],
            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        receipt = dict(stage=stage, commit=commit, at_utc=now(), status="pushed" if proc.returncode == 0 else "pending",
                       output=proc.stdout[-1500:], transport="autodl_academic_only")
    except Exception as exc:
        receipt = dict(stage=stage, commit=commit, at_utc=now(), status="pending", error=str(exc),
                       transport="autodl_academic_only")
    save(CAMPAIGN / "publication_delivery.json", receipt)
    print("GIT_PUBLICATION", receipt["status"], commit, stage, flush=True)
    return receipt["status"] == "pushed"

if __name__ == "__main__":
    import sys
    publish(sys.argv[1])
