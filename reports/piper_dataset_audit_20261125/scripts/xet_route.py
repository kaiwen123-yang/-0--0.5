"""Optional direct Hub Xet transport; reconcile all bytes with the locked LFS SHA-256."""
from pathlib import Path
import argparse
import json
import os
import time
from collections import defaultdict
from urllib.parse import quote
import requests
from acquire import digests,now


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    ap.add_argument("key")
    ap.add_argument("--endpoint",default="https://hf-mirror.com")
    ap.add_argument("--batch",type=int,default=12)
    args=ap.parse_args()
    root=args.root
    os.environ["HF_XET_CACHE"]=str(root/"cache"/"xet")
    os.environ.setdefault("HF_XET_CHUNK_CACHE_SIZE_BYTES","0")
    import hf_xet
    data=json.loads((root/"sources"/(args.key+".json")).read_text())
    prefix=args.endpoint+"/api/"+data["kind"]+"/"+data["repo"]
    blobs={f["rfilename"]:f for f in data["files"]}
    dirs=sorted({str(Path(n).parent) for n in blobs if n.endswith(".mp4")})
    api=requests.Session()
    url=prefix+"/xet-read-token/"+data["sha"]

    def token():
        res=api.get(url,timeout=(10,30))
        res.raise_for_status()
        return res.json()

    def refresh():
        t=token()
        return t["accessToken"],t["exp"]

    completed=0
    with (root/"checks"/("xet-"+args.key+".jsonl")).open("a",buffering=1) as receipts:
        for folder in dirs:
            page=prefix+"/tree/"+data["sha"]+"/"+quote(folder)
            entries=[]
            while page:
                res=api.get(page,params={"limit":1000},timeout=(10,60))
                res.raise_for_status()
                entries.extend(res.json())
                page=res.links.get("next",{}).get("url")
                if page:
                    page=page.replace("https://huggingface.co",args.endpoint)
            # Work away from the sequential front and back of the HTTP queues.
            entries=entries[len(entries)//2:]+entries[:len(entries)//2]
            for start in range(0,len(entries),args.batch):
                batch=[]
                for entry in entries[start:start+args.batch]:
                    name=entry["path"]
                    dest=root/"raw"/args.key/name
                    if name not in blobs or dest.exists():
                        continue
                    part=dest.with_name(dest.name+".xetpart")
                    dest.parent.mkdir(exist_ok=True,parents=True)
                    batch.append((entry,dest,part))
                if not batch:
                    continue
                t=token()
                infos=[hf_xet.PyXetDownloadInfo(str(part),e["xetHash"],e["size"]) for e,_,part in batch]
                hf_xet.download_files(infos,t["casUrl"],(t["accessToken"],t["exp"]),refresh,None)
                for entry,dest,part in batch:
                    name=entry["path"]
                    f=blobs[name]
                    sha,_=digests(part)
                    if part.stat().st_size!=f["size"] or sha!=f["lfs"]["sha256"]:
                        raise IOError("Xet integrity mismatch: "+name)
                    part.replace(dest)
                    receipts.write(json.dumps([args.key,name,f["size"],sha,f["blobId"],sha,now(),"verified"])+"\n")
                    completed+=1
                print("verified",completed,flush=True)


if __name__=="__main__":
    main()
