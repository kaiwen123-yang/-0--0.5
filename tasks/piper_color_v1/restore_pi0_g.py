"""Restore the published B/v2 members used by G500, with four input transfers."""
import concurrent.futures, shutil, subprocess, tarfile
from pathlib import Path
import zstandard
from bct_common import ROOT, read, save, now, gh_env
TASK = "pi0-g-fixed-vision-20261103"
RUN = ROOT / "outputs" / TASK
STAGE = ROOT / "runtime" / (TASK + "-restore")
REPO = "kaiwen123-yang/-0--0.5"
TAG = "pi-complete-backup-20261101"

def main():
    STAGE.mkdir(parents=True, exist_ok=True)
    receipt_path = RUN / "input_restore.json"
    receipt = read(receipt_path) if receipt_path.exists() else {"transport":"autodl_academic_only","groups":{}}
    env = gh_env()
    for group in ("ab-b-checkpoint-2010", "v2-training-data"):
        if receipt["groups"].get(group, {}).get("status") == "restored":
            continue
        source = read(ROOT/"publication/pi-ef-cleanup-20261102"/(group+".json"))
        members = [r for r in source["source_paths"] if group.startswith("ab-") or
                   Path(r["path"]).name in ("index.json","manifest.json") or
                   ("/dataset/train/" in r["path"] and Path(r["path"]).name in ("state.npy","action.npy","external_rgb.npy","wrist_rgb.npy"))]
        target = STAGE/group
        target.mkdir(exist_ok=True)
        entry = dict(status="downloading", source_receipt=str(ROOT/"publication/pi-ef-cleanup-20261102"/(group+".json")),
                     members=members, downloaded=[])
        receipt["groups"][group] = entry
        save(receipt_path,receipt)
        def download(asset):
            part=target/asset["name"]
            if not part.exists() or part.stat().st_size!=asset["size"]:
                print("DOWNLOAD",asset["name"],flush=True)
                subprocess.run(["gh","release","download",TAG,"--repo",REPO,"--pattern",asset["name"],
                    "--dir",str(target),"--clobber"],env=env,check=True,timeout=1800)
            return dict(name=asset["name"],bytes=part.stat().st_size)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(download,asset) for asset in source["remote_assets"]]
                for future in concurrent.futures.as_completed(futures):
                    item=future.result()
                    entry["downloaded"].append(item)
                    save(receipt_path,receipt)
                    print("DOWNLOADED",item["name"],item["bytes"],flush=True)
            entry["status"]="extracting"
            save(receipt_path,receipt)
            wanted={str(Path(r["path"]).relative_to(ROOT.parent)) for r in members}
            joined=subprocess.Popen(["cat",*[str(target/a["name"]) for a in source["remote_assets"]]],stdout=subprocess.PIPE)
            with zstandard.ZstdDecompressor().stream_reader(joined.stdout) as stream:
                with tarfile.open(fileobj=stream,mode="r|") as archive:
                    for member in archive:
                        if member.name in wanted:
                            destination=ROOT.parent/member.name
                            destination.parent.mkdir(parents=True,exist_ok=True)
                            with archive.extractfile(member) as src,destination.open("wb") as dst:
                                shutil.copyfileobj(src,dst,8<<20)
            if joined.wait()!=0:
                raise RuntimeError("Input volume stream failed")
            for asset in source["remote_assets"]:
                (target/asset["name"]).unlink()
            target.rmdir()
            entry.update(status="restored",restored_at=now(),temporary_volumes_deleted=True)
            save(receipt_path,receipt)
            print("RESTORED",group,len(members),flush=True)
        except Exception as exc:
            entry.update(status="pending",error=str(exc),at_utc=now())
            save(receipt_path,receipt)
            raise
    receipt.update(status="ready",at_utc=now())
    save(receipt_path,receipt)

if __name__=="__main__":
    main()
