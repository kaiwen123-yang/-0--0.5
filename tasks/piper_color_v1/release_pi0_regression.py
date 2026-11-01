"""Archive raw diagnostic evidence on D57 and verify a dedicated GitHub release."""
import datetime
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"
RUN = ROOT / "outputs/pi0-120-demo-v2-20261101"
TAG = "pi0-120-regression-diagnosis-20261101"
REPO = "kaiwen123-yang/-0--0.5"
STAGE = ROOT / "runtime/releases" / TAG


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2)); temp.replace(path)


def get_release():
    # Draft releases can have an untagged URL and return 404 from /releases/tags.
    releases = json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/releases?per_page=100"], text=True, timeout=120))
    matches = [r for r in releases if r["tag_name"] == TAG]
    if len(matches) != 1: raise ValueError("Expected exactly the owned diagnostic release")
    return matches[0]


def verify_and_publish(local, records, target, attempts):
    release = get_release()
    def receipts_for(release):
        receipts = []
        for a in release["assets"]:
            if a["name"] in local:
                ref = local[a["name"]]
                assert a["state"] == "uploaded" and a["size"] == ref["size"]
                assert a["digest"] == "sha256:" + ref["sha256"]
                receipts.append({"name": a["name"], "bytes": a["size"], "digest": a["digest"], "url": a["browser_download_url"]})
        assert len(receipts) == 3
        return receipts
    receipts_for(release)
    if release["draft"]:
        subprocess.run(["gh", "release", "edit", TAG, "--repo", REPO, "--draft=false"], check=True, timeout=120)
    release = get_release()
    assert not release["draft"]
    receipts = receipts_for(release)
    record = {"tag": TAG, "url": release["html_url"], "release_id": release["id"], "draft": release["draft"],
        "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "target_commit": target,
        "assets": receipts, "member_files": len(records), "source_bytes": sum(r["bytes"] for r in records),
        "verification": "Archive member paths/sizes verified; every GitHub asset size and SHA256 digest equals its local file", "upload_attempts": attempts,
        "scope": "raw diagnosis evidence; model checkpoints and videos remain on D57"}
    save(OUT / "raw_artifact_release.json", record)
    save(OUT / "raw_release_progress.json", {"stage": "published_and_verified", "url": release["html_url"]})
    print(json.dumps(record, indent=2), flush=True)


def main(finalize_existing=False):
    status = json.loads((OUT / "probe_status.json").read_text())
    assert status["completed"] and status["optimizer_updates"] == 0
    if finalize_existing:
        manifest = json.loads((STAGE / "raw-evidence-manifest.json").read_text())
        files = [STAGE / name for name in ("pi0-120-regression-raw-evidence.tar.gz", "raw-evidence-manifest.json", "SHA256SUMS")]
        local = {p.name: {"size": p.stat().st_size, "sha256": sha(p)} for p in files}
        release = get_release()
        verify_and_publish(local, manifest["files"], release["target_commitish"],
                           [{"attempt": 1, "upload": "completed", "verification_retry": "draft tag endpoint 404; queried owned draft by release list"}])
        return
    STAGE.mkdir(parents=True, exist_ok=False)
    members = []
    for p in sorted((RUN / "evaluations").glob("*/*")):
        if p.suffix in (".npz", ".json"):
            members.append((p, "autonomous_evaluations/" + str(p.relative_to(RUN / "evaluations"))))
    for category in ("teacher_reference", "fixed", "prefix"):
        for p in sorted((OUT / category).rglob("*")):
            if p.is_file() and p.suffix in (".npz", ".json"):
                members.append((p, "diagnostic/" + str(p.relative_to(OUT))))
    for layout in (100, 101):
        for color in ("red", "green", "blue"):
            p = RUN / "dataset/train" / f"layout_{layout:05d}_{color}.npz"
            members.append((p, "diagnostic/train_reference/" + p.name))
    records = [{"archive_path": arc, "source": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": sha(p)} for p, arc in members]
    manifest = STAGE / "raw-evidence-manifest.json"
    save(manifest, {"tag": TAG, "files": records, "file_count": len(records),
        "bytes": sum(r["bytes"] for r in records), "optimizer_updates_this_diagnosis": 0,
        "scope": "all 156 existing autonomous trajectory arrays/JSON, 21 teacher references (including six original train inputs), all fixed predictions, 40 prefix interventions",
        "excluded": ["model parameters and optimizer states", "videos", "full 120-demo expanded arrays"],
        "restore": {"autonomous_evaluations": "outputs/pi0-120-demo-v2-20261101/evaluations",
                    "diagnostic": "outputs/pi0-120-regression-diagnosis-20261101",
                    "diagnostic/train_reference": "six NPZ inputs can be copied to outputs/pi0-120-demo-v2-20261101/dataset/train for fixed-input probe replay"}})
    archive = STAGE / "pi0-120-regression-raw-evidence.tar.gz"
    with tarfile.open(archive, "w:gz", compresslevel=1) as tar:
        for p, arc in members: tar.add(p, arcname=arc, recursive=False)
    with tarfile.open(archive, "r:gz") as tar:
        entries = tar.getmembers()
        assert len(entries) == len(records)
        assert [(e.name, e.size) for e in entries] == [(r["archive_path"], r["bytes"]) for r in records]
    sums = STAGE / "SHA256SUMS"
    sums.write_text("".join(f"{sha(p)}  {p.name}\n" for p in (archive, manifest)))
    files = (archive, manifest, sums)
    local = {p.name: {"size": p.stat().st_size, "sha256": sha(p)} for p in files}
    save(OUT / "raw_release_progress.json", {"stage": "packaged", "assets": local, "members": len(records)})
    target = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    notes = STAGE / "release-notes.md"
    notes.write_text("""Raw evidence for the 2026-11-01 Pi0 120-demo regression diagnosis.

Includes all 156 existing autonomous trajectory arrays and their JSON records, 21 teacher references, four frozen-checkpoint prediction sets and 40 teacher-prefix interventions. The manifest records every member's source, size and SHA256. No optimizer updates were run during diagnosis; the independent test split was unused.

Teacher-prefix results are interventions, not autonomous success rates. Model/optimizer checkpoints and videos remain on D57. The archive supports trajectory reanalysis and figure reproduction; fresh inference additionally requires the preserved model checkpoints and environments.

Analysis: docs/PI0_120_REGRESSION_ANALYSIS_20261101.md
Next plan: docs/PI0_120_REGRESSION_NEXT_PLAN_20261101.md
""")
    subprocess.run(["gh", "release", "create", TAG, "--repo", REPO, "--target", target, "--draft",
                    "--title", "Pi0 120-demo regression: targeting, prompt and grasp diagnosis", "--notes-file", str(notes)], check=True, timeout=120)
    attempts = []
    for attempt in range(1, 4):
        save(OUT / "raw_release_progress.json", {"stage": "uploading", "attempt": attempt, "assets": local})
        try:
            result = subprocess.run(["gh", "release", "upload", TAG, "--repo", REPO, "--clobber", *map(str, files)], timeout=600)
            attempts.append({"attempt": attempt, "returncode": result.returncode})
            if result.returncode == 0: break
        except subprocess.TimeoutExpired:
            attempts.append({"attempt": attempt, "error": "upload timeout after 600 seconds"})
        if attempt < 3: time.sleep(5 * attempt)
    else:
        save(OUT / "raw_release_progress.json", {"stage": "upload_failed", "attempts": attempts, "assets": local})
        raise RuntimeError("Raw release upload failed after three attempts; draft retained")
    verify_and_publish(local, records, target, attempts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--finalize-existing", action="store_true")
    main(parser.parse_args().finalize_existing)
