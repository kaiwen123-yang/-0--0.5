"""Lock Hub file manifests and download byte-exact blobs, resumably; no hub cache."""
import argparse
import concurrent.futures as futures
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

SOURCES = {
    "A": ("datasets", "DRMNmadhan/piper_pickdrop_200"),
    **{k: ("datasets", "Ray0v0/cl-piper-single-" + k) for k in
       ("stack-bowls", "hang-cup", "fold-towel", "press-button")},
    "C": ("datasets", "tianxiwei/piper-four-color-block-sorting"),
    "D": ("models", "siyuhsu/openpi_lab"),
}
tls = threading.local()
REVISIONS = {
    "A":"867554b0b60c78d779e048203acb28e19fab650b",
    "stack-bowls":"f81ff5e07c31053b39e64aa621882d6d17705d52",
    "hang-cup":"f78ac4a1c8ce11355094e617f424c2e91a7d5772",
    "fold-towel":"311f308e21338ba6b46566b81c5dfb3c7b3f767f",
    "press-button":"d4c8c116d0c70f82ca131d4230f4616f9e7890aa",
    "C":"8d5ee5d2a44dfe1798489d13c1fc0bdd168be12e",
    "D":"c2e5619878c2bf2188e6d04d727deee605fdd1e2",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def session():
    if not hasattr(tls, "session"):
        tls.session = requests.Session()
    return tls.session


def write_json(path, data):
    temp = path.with_suffix(".new")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(temp, path)


def lock(root, endpoint):
    for key, (kind, repo) in SOURCES.items():
        path = root / "sources" / (key + ".json")
        if path.exists():
            continue
        resp = session().get(f"{endpoint}/api/{kind}/{repo}/revision/{REVISIONS[key]}?blobs=true", timeout=(15, 90))
        resp.raise_for_status()
        data = resp.json()
        if data["sha"]!=REVISIONS[key]:
            raise ValueError("revision mismatch: "+key)
        files = data["siblings"]
        if key == "D":
            files = [f for f in files if f["rfilename"].startswith("piper/dataset/")
                     or f["rfilename"] in ("README.md", ".gitattributes", "LICENSE")
                     or (f["rfilename"].startswith("piper/") and "/model" not in f["rfilename"]
                         and f["rfilename"].endswith((".md", ".py", ".sh")))]
        write_json(path, dict(key=key, kind=kind, repo=repo, sha=data["sha"], locked=now(),
                              endpoint=endpoint, card=data.get("cardData"), tags=data.get("tags"),
                              gated=data.get("gated"), files=files))


def digests(path):
    size = path.stat().st_size
    sha = hashlib.sha256()
    git = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            sha.update(block)
            git.update(block)
    return sha.hexdigest(), git.hexdigest()


def download(root, endpoint, lock, file, part_suffix=".part"):
    name = file["rfilename"]
    path = root / "raw" / lock["key"] / name
    path.parent.mkdir(exist_ok=True, parents=True)
    part = path.with_name(path.name + part_suffix)
    size = file["size"]
    prefix = "datasets/" if lock["kind"] == "datasets" else ""
    url = f"{endpoint}/{prefix}{lock['repo']}/resolve/{lock['sha']}/{quote(name)}"
    for attempt in range(4):
        try:
            if not path.exists():
                start = part.stat().st_size if part.exists() else 0
                if not part.exists() or start != size:
                    hdr = {"Range": f"bytes={start}-"} if start else {}
                    with session().get(url, stream=True, headers=hdr, timeout=(12, 60)) as res:
                        res.raise_for_status()
                        append = start and res.status_code == 206
                        if append and not res.headers.get("Content-Range","").startswith(f"bytes {start}-"):
                            raise ValueError("unexpected Content-Range")
                        with part.open("ab" if append else "wb") as out:
                            for block in res.iter_content(262144):
                                out.write(block)
                if part.stat().st_size != size:
                    raise IOError("size mismatch")
            target = path if path.exists() else part
            sha, git = digests(target)
            lfs = (file.get("lfs") or {}).get("sha256")
            git_ref = file.get("blobId")
            if target.stat().st_size != size or (lfs and lfs != sha) or (not lfs and git_ref != git):
                if target == part:
                    part.unlink()
                raise ValueError("remote digest mismatch")
            if target == part:
                os.replace(part, path)
            return [lock["key"], name, size, sha, git_ref, lfs, now(), "verified"]
        except Exception as e:
            err = type(e).__name__ + ": " + str(e).split("?")[0][:240]
            time.sleep(1+attempt)
    return [lock["key"], name, size, None, file.get("blobId"), None, now(), err]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--endpoint", default="https://huggingface.co")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--lock-only", action="store_true")
    ap.add_argument("--keys", nargs="+", default=list(SOURCES))
    ap.add_argument("--reverse",action="store_true",help="complement primary route from the tail")
    args = ap.parse_args()
    root = args.root
    for k in ("sources","raw","checks"):
        (root/k).mkdir(parents=True, exist_ok=True)
    lock(root, args.endpoint)
    if args.lock_only:
        return
    receipt = root/"checks"/("relay.jsonl" if args.reverse else "downloads.jsonl")
    done = set()
    if receipt.exists():
        for line in receipt.read_text().splitlines():
            row = json.loads(line)
            f = root/"raw"/row[0]/row[1]
            if row[-1]=="verified" and f.exists() and f.stat().st_size==row[2]:
                done.add((row[0], row[1]))
    jobs = []
    for i,key in enumerate(args.keys):
        data = json.loads((root/"sources"/(key+".json")).read_text())
        for f in data["files"]:
            nm = f["rfilename"]
            if (key,nm) not in done:
                phase = 2 if nm.endswith(".mp4") else int(nm.endswith(".parquet"))
                jobs.append((phase,i,nm,data,f))
    jobs.sort(key=lambda x:x[:3],reverse=args.reverse)
    with receipt.open("a",buffering=1) as out, futures.ThreadPoolExecutor(args.workers) as pool:
        calls = [pool.submit(download,root,args.endpoint,j[3],j[4],
                             ".relaypart" if args.reverse else ".part") for j in jobs]
        for n,call in enumerate(futures.as_completed(calls),1):
            row=call.result()
            out.write(json.dumps(row)+"\n")
            if n%100==0 or row[-1]!="verified":
                print(n, len(jobs),row[0],row[-1],flush=True)


if __name__ == "__main__":
    main()
