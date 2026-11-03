"""Reuse the single Release queue, then clean only published inactive members."""
import collections, fcntl, math, os, shutil, subprocess
from pathlib import Path
from g_common import *
from publish_pi0_g import publish
import upload_pi_progressive as upload
TRANSFER = ROOT / "runtime/pi-progressive-upload-20261101"
LEDGER = ROOT / "publication" / TASK
G_PART = 256 * 1024**2

def register(mapping):
    if mapping.get("g500_registered"):
        return
    groups = collections.defaultdict(list)
    for path in sorted(CAMPAIGN.rglob("*")):
        if not path.is_file():
            continue
        if "checkpoints" in path.parts:
            group = "g500-checkpoint"
        elif "evaluations" in path.parts and path.suffix in (".npz", ".mp4"):
            group = "g500-evaluation-" + path.relative_to(CAMPAIGN).parts[1]
        elif path.suffix == ".npy":
            group = "g500-sampler"
        else:
            continue
        stat = path.stat()
        groups[group].append(dict(source=str(path),archive_path=str(path.relative_to(ROOT.parent)),
                                  bytes=stat.st_size,mtime_ns=stat.st_mtime_ns))
    jobs = []
    for group, members in groups.items():
        small=[]; size=0; serial=0
        def bundle():
            nonlocal small,size,serial
            if small:
                jobs.append(dict(name=group+f"-records-{serial:04d}.tar",group=group,kind="small_records_bundle",
                    members=small,source_bytes=size,status="queued",attempts=0))
                small=[];size=0;serial+=1
        for member in members:
            n=member["bytes"]
            if n<=8*1024**2:
                if size+n>64*1024**2: bundle()
                small.append(member);size+=n
            else:
                parts=math.ceil(n/G_PART)
                for part in range(parts):
                    offset=part*G_PART if parts>1 else 0
                    length=min(G_PART,n-offset) if parts>1 else n
                    jobs.append(dict(name=group+f"-file-{serial:04d}-part-{part:03d}",group=group,kind="raw_file_range",
                        members=[member],source_bytes=length,bytes=length,offset=offset,part=part,parts=parts,
                        status="queued",attempts=0))
                serial+=1
        bundle()
    mapping["jobs"]=jobs+mapping["jobs"]
    mapping["g500_registered"]=True
    upload.write_status(mapping,"g500_registered")

def sync_index(mapping):
    LEDGER.mkdir(parents=True,exist_ok=True)
    g_jobs=[j for j in mapping["jobs"] if j["group"].startswith("g500-")]
    save(LEDGER/"asset_index.json",dict(release_tag=upload.TAG,groups="G500 checkpoint, evaluations, sampler",jobs=g_jobs))
    missing=[dict(group=j["group"],name=j["name"],status=j["status"],bytes=j.get("bytes",j["source_bytes"]),
                  source_paths=[m["source"] for m in j["members"]],error=j.get("error"))
             for j in mapping["jobs"] if j["status"]!="uploaded"]
    save(LEDGER/"pending.json",dict(at_utc=now(),assets=missing))
    receipts=[read(p) for p in LEDGER.glob("cleanup-*.json")]
    save(LEDGER/"delivery_status.json",dict(at_utc=now(),experiment_complete=read(CAMPAIGN/"run.json").get("completed",False),experiment_stage=read(CAMPAIGN/"run.json").get("stage"),transport="autodl_academic_only",
        g_assets=dict(total=len(g_jobs),uploaded=sum(j["status"]=="uploaded" for j in g_jobs)),
        historical_assets=dict(total=len(mapping["jobs"])-len(g_jobs),
            uploaded=sum(j["status"]=="uploaded" and not j["group"].startswith("g500-") for j in mapping["jobs"])),
        retention_policy="retention_policy.json",automatic_research_product_deletion=False,
        cleanup_scope="inactive temporary transfer copies only; all training/resumption/reproduction products retained",
        prior_deletions_recorded_before_current_policy=True,
        retained_groups=[p.stem.removeprefix("retained-") for p in LEDGER.glob("retained-*.json")],
        pending_assets=len(missing),pending_manifest=str((LEDGER/"pending.json").relative_to(ROOT)),
        deleted_groups=[dict(group=r["group"],files=len(r["deleted_paths"]),bytes=r["freed_bytes"]) for r in receipts if r["status"]=="deleted"],
        freed_bytes=sum(r["freed_bytes"] for r in receipts if r["status"]=="deleted")))

def cleanup_group(group,jobs,assets,mapping):
    # Latest user instruction retains all research products needed for training/continuation.
    if not all(j["status"]=="uploaded" for j in jobs):
        return
    prior=LEDGER/("cleanup-"+group+".json")
    if prior.exists() and read(prior).get("status")=="deleted":
        return
    members={m["source"]:m for j in jobs for m in j["members"]}
    retained=[m for name,m in members.items() if Path(name).is_file()]
    if not retained:
        return
    save(LEDGER/("retained-"+group+".json"),dict(group=group,status="retained_for_training_and_resumption",
        at_utc=now(),release_tag=upload.TAG,members=retained,
        assets=[dict(name=j["name"],bytes=j["bytes"],status=j["status"]) for j in jobs],
        policy="retention_policy.json",deleted_paths=[],freed_bytes=0))
    sync_index(mapping)
    publish(group+"-published-retained")
    print("GROUP_RETAINED",group,len(retained),flush=True)

def cleanup_restored(mapping):
    save(LEDGER/"retained-restored-inputs.json",dict(at_utc=now(),
        status="retained_for_training_and_resumption",policy="retention_policy.json",
        source_member_index=str((CAMPAIGN/"input_restore.json").relative_to(ROOT)),
        protected_paths=[str(OLD),str(ROOT/"outputs/pi0-120-demo-v2-20261101/dataset"),
                         str(NORM),str(CHECKPOINT)],
        deleted_paths=[],freed_bytes=0))
    sync_index(mapping)

def deliver(history_only=False):
    LEDGER.mkdir(parents=True,exist_ok=True)
    lock=(TRANSFER/"queue.lock").open("a")
    fcntl.flock(lock,fcntl.LOCK_EX)
    os.nice(19)
    subprocess.run(["ionice","-c","3","-p",str(os.getpid())],check=True)
    mapping=read(TRANSFER/"mapping.json")
    if not history_only:
        register(mapping)
    sync_index(mapping)
    publish("historical-upload-started" if history_only else "release-queued")
    if not history_only:
        cleanup_restored(mapping)
    try:
        release_id,assets=upload.release(upload.TAG)
    except Exception as exc:
        save(LEDGER/"transport_pending.json",dict(at_utc=now(),status="pending",error=str(exc),transport="autodl_academic_only"))
        sync_index(mapping);publish("release-metadata-pending");return
    upload.reconcile_remote_receipts(mapping,assets)
    groups=collections.defaultdict(list)
    for job in mapping["jobs"]:
        groups[job["group"]].append(job)
    new_groups=[(group,jobs) for group,jobs in groups.items() if group.startswith("g500-")]
    new_groups.sort(key=lambda item:item[0]=="g500-checkpoint")
    previous_groups=[(group,jobs) for group,jobs in groups.items() if not group.startswith("g500-")]
    for group,jobs in new_groups+previous_groups:
        for job in jobs:
            if history_only and read(CAMPAIGN/"run.json").get("completed"):
                sync_index(mapping)
                publish("historical-upload-yield-to-G")
                return
            if job["status"]=="uploaded":
                continue
            path=None;temporary=False
            try:
                path,offset,size,temporary=upload.materialize(job)
                old=assets.get(job["name"])
                if old:
                    if old["size"]==size and old["state"]=="uploaded":
                        job.update(status="uploaded",receipt=old)
                    else:
                        raise RuntimeError("Existing remote asset has different size/state")
                else:
                    job.update(status="uploading",attempts=job.get("attempts",0)+1)
                    upload.write_status(mapping,"running",job["name"])
                    receipt=upload.stream_upload(release_id,job,path,offset,size)
                    job.update(status="uploaded",receipt=receipt,uploaded_at=now())
                    assets[job["name"]]=receipt
                    with (TRANSFER/"receipts.jsonl").open("a") as stream:
                        stream.write(__import__("json").dumps(dict(at_utc=now(),name=job["name"],receipt=receipt))+"\n")
                upload.write_status(mapping,"running")
                print("ASSET_UPLOADED",job["name"],flush=True)
            except Exception as exc:
                job.update(status="pending",error=str(exc))
                upload.write_status(mapping,"paused_academic_transfer_failed",job["name"])
                sync_index(mapping);publish("release-transfer-pending")
                return
            finally:
                if temporary and path is not None and path.exists():
                    path.unlink()
        cleanup_group(group,jobs,assets,mapping)
    sync_index(mapping)
    upload.write_status(mapping,"complete" if not any(j["status"]!="uploaded" for j in mapping["jobs"]) else "finished_with_pending")
    publish("delivery-final")

if __name__=="__main__":
    import sys
    deliver(history_only="--history-only" in sys.argv)
