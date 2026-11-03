"""Append recovery artifacts after the active legacy upload releases its existing queue lock."""
import fcntl, math, os, subprocess
from pathlib import Path
from bct_common import ROOT, read, save, now
from publish_pi0_held_recovery import publish
import upload_pi_progressive as upload
TASK="pi0-held-recovery-20261103"
RUN=ROOT/"outputs"/TASK
LEDGER=ROOT/"publication"/TASK
TRANSFER=ROOT/"runtime/pi-progressive-upload-20261101"

def register():
    LEDGER.mkdir(parents=True,exist_ok=True)
    jobs=[];small=[];size=0;serial=0
    def bundle():
        nonlocal small,size,serial
        if small:
            jobs.append(dict(name=f"held-recovery-20261103-records-{serial:04d}.tar",
                group=TASK,kind="small_records_bundle",members=small,source_bytes=size,status="queued",attempts=0))
            small=[];size=0;serial+=1
    for p in sorted((RUN/"dataset").rglob("*")):
        if not p.is_file() or p.suffix not in (".npz",".npy",".mp4"):
            continue
        st=p.stat()
        member=dict(source=str(p),archive_path=str(p.relative_to(ROOT.parent)),
                    bytes=st.st_size,mtime_ns=st.st_mtime_ns)
        if st.st_size<=8*1024**2:
            if size+st.st_size>64*1024**2:bundle()
            small.append(member);size+=st.st_size
        else:
            parts=math.ceil(st.st_size/(256*1024**2))
            for part in range(parts):
                offset=part*256*1024**2
                n=min(256*1024**2,st.st_size-offset)
                jobs.append(dict(name=f"held-recovery-20261103-file-{serial:04d}-part-{part:03d}",
                    group=TASK,kind="raw_file_range",members=[member],source_bytes=n,bytes=n,
                    offset=offset,part=part,parts=parts,status="queued",attempts=0))
            serial+=1
    bundle()
    save(LEDGER/"asset_index.json",dict(release_tag=upload.TAG,jobs=jobs,
        queue_lock=str(TRANSFER/"queue.lock"),source_deletion=False,
        enqueue_policy="Wait for existing active uploader; then append under its queue lock"))
    save(LEDGER/"delivery_status.json",dict(at_utc=now(),status="queued_for_existing_lock",
        assets=len(jobs),uploaded=0,source_bytes=sum(j["source_bytes"] for j in jobs),
        source_deletion=False,transport="autodl_academic_only"))
    print("RECOVERY_ASSETS_QUEUED",len(jobs),sum(j["source_bytes"] for j in jobs),flush=True)

def deliver():
    index=read(LEDGER/"asset_index.json")
    status=read(LEDGER/"delivery_status.json")
    status.update(status="waiting_for_existing_queue",pid=os.getpid(),at_utc=now())
    save(LEDGER/"delivery_status.json",status)
    with (TRANSFER/"queue.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        os.nice(19)
        subprocess.run(["ionice","-c","3","-p",str(os.getpid())],check=True)
        mapping=read(TRANSFER/"mapping.json")
        present={j["name"] for j in mapping["jobs"]}
        mapping["jobs"] += [j for j in index["jobs"] if j["name"] not in present]
        jobs=[j for j in mapping["jobs"] if j["group"]==TASK]
        upload.write_status(mapping,"held_recovery_registered")
        def sync(state,error=None):
            save(LEDGER/"asset_index.json",{**index,"jobs":jobs})
            save(LEDGER/"delivery_status.json",dict(at_utc=now(),status=state,pid=os.getpid(),
                assets=len(jobs),uploaded=sum(j["status"]=="uploaded" for j in jobs),
                source_bytes=sum(j["source_bytes"] for j in jobs),source_deletion=False,
                transport="autodl_academic_only",error=error))
        try:
            release_id,assets=upload.release(upload.TAG)
            for job in jobs:
                if job["status"]=="uploaded":continue
                path=None;temporary=False
                try:
                    path,offset,size,temporary=upload.materialize(job)
                    existing=assets.get(job["name"])
                    if existing:
                        if existing["state"]!="uploaded" or existing["size"]!=size:
                            raise RuntimeError("Existing asset size/state differs")
                        receipt={k:existing.get(k) for k in ("id","name","size","state","browser_download_url")}
                    else:
                        job.update(status="uploading",attempts=job.get("attempts",0)+1)
                        upload.write_status(mapping,"held_recovery_uploading",job["name"])
                        receipt=upload.stream_upload(release_id,job,path,offset,size)
                    job.update(status="uploaded",receipt=receipt,uploaded_at=now())
                    upload.write_status(mapping,"held_recovery_uploading")
                    sync("uploading")
                    print("RECOVERY_ASSET_UPLOADED",job["name"],flush=True)
                finally:
                    if temporary and path is not None and path.exists():path.unlink()
            sync("complete")
            publish("artifacts-published-retained")
        except Exception as exc:
            sync("pending",type(exc).__name__)
            upload.write_status(mapping,"held_recovery_transfer_pending")
            publish("artifacts-transfer-pending")
            print("RECOVERY_UPLOAD_PENDING",type(exc).__name__,flush=True)

if __name__=="__main__":
    import sys
    register() if sys.argv[1]=="register" else deliver()
