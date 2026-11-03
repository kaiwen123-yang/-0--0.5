"""Reuse the single Release queue, then clean only published inactive members."""
import collections, fcntl, math, os, shutil, subprocess
from pathlib import Path
from g_common import *
from publish_pi0_g import publish
import upload_pi_progressive as upload
TRANSFER = ROOT / "runtime/pi-progressive-upload-20261101"
LEDGER = ROOT / "publication" / TASK

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
                parts=math.ceil(n/upload.CHUNK) if n>=2*1024**3 else 1
                for part in range(parts):
                    offset=part*upload.CHUNK if parts>1 else 0
                    length=min(upload.CHUNK,n-offset) if parts>1 else n
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
    save(LEDGER/"delivery_status.json",dict(at_utc=now(),experiment_complete=True,transport="autodl_academic_only",
        g_assets=dict(total=len(g_jobs),uploaded=sum(j["status"]=="uploaded" for j in g_jobs)),
        historical_assets=dict(total=len(mapping["jobs"])-len(g_jobs),
            uploaded=sum(j["status"]=="uploaded" and not j["group"].startswith("g500-") for j in mapping["jobs"])),
        pending_assets=len(missing),pending_manifest=str((LEDGER/"pending.json").relative_to(ROOT)),
        deleted_groups=[dict(group=r["group"],files=len(r["deleted_paths"]),bytes=r["freed_bytes"]) for r in receipts if r["status"]=="deleted"],
        freed_bytes=sum(r["freed_bytes"] for r in receipts if r["status"]=="deleted")))

def cleanup_group(group,jobs,assets,mapping):
    record=LEDGER/("cleanup-"+group+".json")
    if record.exists() and read(record)["status"]=="deleted":
        return
    if not all(j["status"]=="uploaded" for j in jobs):
        return
    if any(j["name"] not in assets or assets[j["name"]]["size"]!=j["bytes"] or assets[j["name"]]["state"]!="uploaded" for j in jobs):
        return
    members={m["source"]:m for j in jobs for m in j["members"]}
    paths=[Path(name) for name in members]
    if not all(p.resolve().is_relative_to(ROOT/"outputs") or p.resolve().is_relative_to(ROOT/"results") for p in paths):
        return
    existing=[p for p in paths if p.is_file()]
    if not existing:
        return
    receipt=dict(group=group,status="published_ready_to_delete",at_utc=now(),release_tag=upload.TAG,
        assets=[dict(name=j["name"],size=j["bytes"],state=assets[j["name"]]["state"]) for j in jobs],
        members=list(members.values()),deleted_paths=[],freed_bytes=0)
    save(record,receipt);sync_index(mapping)
    if not publish(group+"-indexed"):
        return
    removed=[]
    for path in existing:
        removed.append(dict(path=str(path),bytes=path.stat().st_size))
        path.unlink()
    receipt.update(status="deleted",deleted_paths=removed,freed_bytes=sum(p["bytes"] for p in removed),deleted_at=now())
    save(record,receipt);sync_index(mapping)
    publish(group+"-deleted")
    print("GROUP_DELETED",group,receipt["freed_bytes"],flush=True)

def cleanup_restored(mapping):
    restore=read(CAMPAIGN/"input_restore.json")
    restore["groups"]["g-norm-copy"] = dict(source_receipt=restore["groups"]["ab-b-checkpoint-2010"]["source_receipt"],
        members=[dict(path=str(NORM/"norm_stats.json"),bytes=(NORM/"norm_stats.json").stat().st_size)] if (NORM/"norm_stats.json").exists() else [])
    for group,entry in restore["groups"].items():
        record=LEDGER/("cleanup-restored-"+group+".json")
        if record.exists() and read(record)["status"]=="deleted":
            continue
        receipt=dict(group="restored-"+group,status="published_ready_to_delete",
            source_release=upload.TAG,source_receipt=entry["source_receipt"],members=entry["members"],
            active_dependencies=False,deleted_paths=[],freed_bytes=0,at_utc=now())
        save(record,receipt);sync_index(mapping)
        if not publish("restored-"+group+"-indexed"):
            continue
        removed=[]
        for member in entry["members"]:
            path=Path(member["path"])
            if path.is_file():
                removed.append(dict(path=str(path),bytes=path.stat().st_size))
                path.unlink()
        receipt.update(status="deleted",deleted_paths=removed,freed_bytes=sum(p["bytes"] for p in removed),deleted_at=now())
        save(record,receipt);sync_index(mapping)
        publish("restored-"+group+"-deleted")

def deliver():
    LEDGER.mkdir(parents=True,exist_ok=True)
    lock=(TRANSFER/"queue.lock").open("a")
    fcntl.flock(lock,fcntl.LOCK_EX)
    os.nice(19)
    mapping=read(TRANSFER/"mapping.json")
    register(mapping)
    sync_index(mapping)
    publish("release-queued")
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
    for group,jobs in groups.items():
        for job in jobs:
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
    deliver()
