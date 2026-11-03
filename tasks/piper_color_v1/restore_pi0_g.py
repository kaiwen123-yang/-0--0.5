"""Restore only the published inputs consumed by G500."""
import shutil, subprocess
from pathlib import Path
from bct_common import ROOT, read, save, now, gh_env
TASK = "pi0-g-fixed-vision-20261103"
RUN = ROOT / "outputs" / TASK
STAGE = ROOT / "runtime" / (TASK + "-restore")
REPO = "kaiwen123-yang/-0--0.5"
TAG = "pi-complete-backup-20261101"

def main():
    STAGE.mkdir(parents=True, exist_ok=True)
    receipt_path = RUN / "input_restore.json"
    receipt = read(receipt_path) if receipt_path.exists() else {"transport": "autodl_academic_only", "groups": {}}
    env = gh_env()
    for group in ("ab-b-checkpoint-2010", "v2-training-data"):
        if receipt["groups"].get(group, {}).get("status") == "restored":
            continue
        source = read(ROOT / "publication/pi-ef-cleanup-20261102" / (group + ".json"))
        members = [r for r in source["source_paths"] if group.startswith("ab-") or
                   Path(r["path"]).name in ("index.json", "manifest.json") or
                   ("/dataset/train/" in r["path"] and Path(r["path"]).name in ("state.npy", "action.npy", "external_rgb.npy", "wrist_rgb.npy"))]
        target = STAGE / group
        target.mkdir(exist_ok=True)
        entry = {"status": "downloading", "source_receipt": str(ROOT / "publication/pi-ef-cleanup-20261102" / (group + ".json")), "members": members, "downloaded": []}
        receipt["groups"][group] = entry
        save(receipt_path, receipt)
        try:
            for asset in source["remote_assets"]:
                part = target / asset["name"]
                if not part.exists() or part.stat().st_size != asset["size"]:
                    print("DOWNLOAD", asset["name"], flush=True)
                    subprocess.run(["gh", "release", "download", TAG, "--repo", REPO, "--pattern", asset["name"], "--dir", str(target), "--clobber"], env=env, check=True, timeout=600)
                entry["downloaded"].append({"name": asset["name"], "bytes": part.stat().st_size})
                save(receipt_path, receipt)
            listing = target / "members.txt"
            listing.write_text("".join(str(Path(r["path"]).relative_to(ROOT.parent)) + "\n" for r in members))
            entry["status"] = "extracting"
            save(receipt_path, receipt)
            proc = subprocess.Popen(["tar", "-I", "zstd", "-x", "-f", "-", "-C", str(ROOT.parent), "-T", str(listing)], stdin=subprocess.PIPE)
            for asset in source["remote_assets"]:
                with (target / asset["name"]).open("rb") as stream:
                    shutil.copyfileobj(stream, proc.stdin, 8 << 20)
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError("Required input extraction failed")
            for asset in source["remote_assets"]:
                (target / asset["name"]).unlink()
            listing.unlink()
            target.rmdir()
            entry.update(status="restored", restored_at=now(), temporary_volumes_deleted=True)
            save(receipt_path, receipt)
            print("RESTORED", group, len(members), flush=True)
        except Exception as exc:
            entry.update(status="pending", error=str(exc), at_utc=now())
            save(receipt_path, receipt)
            raise
    receipt.update(status="ready", at_utc=now())
    save(receipt_path, receipt)

if __name__ == "__main__":
    main()
