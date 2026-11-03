"""Publish only this recovery task's source and compact records using the existing Git lock."""
import fcntl, shutil, subprocess
from pathlib import Path
from bct_common import ROOT, read, save, now, gh_env, git
TASK="pi0-held-recovery-20261103"
RUN=ROOT/"outputs"/TASK
RESULTS=ROOT/"results/piper-color-v1"/TASK
LEDGER=ROOT/"publication"/TASK
BRANCH="codex/pi0-g-fixed-vision-20261103"

def publish(stage):
    with (ROOT/"runtime/pi-bct-publication.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        RESULTS.mkdir(parents=True,exist_ok=True)
        for p in RUN.rglob("*"):
            if p.is_file() and p.suffix in (".json",".md",".log",".exit"):
                dst=RESULTS/p.relative_to(RUN);dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(p,dst)
        paths=[str(RESULTS.relative_to(ROOT))]
        paths += [str(p.relative_to(ROOT)) for p in (ROOT/"tasks/piper_color_v1").glob("*pi0_held_recovery.py")]
        paths += ["docs/PI0_G_COMPLETED_NEXT_REVIEW_20261103.md"]
        if LEDGER.exists():paths.append(str(LEDGER.relative_to(ROOT)))
        git("add","--",*paths)
        if git("diff","--cached","--name-only"):
            git("commit","-m","Record eight-case pi0 held-state recovery: "+stage)
        commit=git("rev-parse","HEAD")
        env=gh_env()
        proc=subprocess.run(["git","-C",str(ROOT),"-c","http.proxy="+env["https_proxy"],
            "-c","http.version=HTTP/1.1","push","origin","HEAD:refs/heads/"+BRANCH],
            env=env,capture_output=True,text=True,timeout=90)
        receipt=dict(stage=stage,commit=commit,at_utc=now(),
            status="pushed" if proc.returncode==0 else "pending",transport="autodl_academic_only")
        save(RUN/"publication_delivery.json",receipt)
        print("RECOVERY_GIT",receipt["status"],commit,stage,flush=True)
        return receipt

if __name__=="__main__":
    import sys
    publish(sys.argv[1])
