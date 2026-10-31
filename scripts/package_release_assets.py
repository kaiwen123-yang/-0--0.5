"""Package only the fy-5080 assets omitted from the preserved 2026-10-25 archive."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import datetime

parser=argparse.ArgumentParser()
parser.add_argument("--root",type=Path,required=True)
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args()
root=args.root.resolve()
out=args.output.resolve()
out.mkdir(parents=True,exist_ok=True)
coverage=json.loads((root/"publication/fy5080-release-members.json").read_text())
result={"source":"fy-5080","source_inventory":"publication/fy5080-source-inventory.json","legacy_commit":coverage["legacy_commit"],"part_limit_bytes":512*1024*1024,"groups":{},"assets":[]}
for group in ("dataset","checkpoints","supplement"):
    members=[x for x in coverage["new_files"] if x["group"]==group]
    paths=out/(group+".files0")
    paths.write_bytes(b"\0".join(x["path"].encode() for x in members)+b"\0")
    tar=subprocess.Popen(["nice","-n","10","tar","--null","--no-recursion","-C",str(root),"-T",str(paths),"-cf","-"],stdout=subprocess.PIPE)
    gz=subprocess.Popen(["nice","-n","10","gzip","-1","-c"],stdin=tar.stdout,stdout=subprocess.PIPE)
    tar.stdout.close()
    parts=[]; whole=hashlib.sha256(); index=0; count=0
    block=gz.stdout.read(8*1024*1024)
    while block:
        path=out/f"fy5080-{group}.tar.gz.part-{index:03d}"
        digest=hashlib.sha256(); size=0
        with path.open("wb") as stream:
            while block and size<result["part_limit_bytes"]:
                stream.write(block); digest.update(block); whole.update(block); size+=len(block)
                if size==result["part_limit_bytes"]:break
                block=gz.stdout.read(min(8*1024*1024,result["part_limit_bytes"]-size))
        rec={"name":path.name,"bytes":size,"sha256":digest.hexdigest(),"group":group}
        parts.append(rec);result["assets"].append(rec);count+=size
        print(json.dumps({"packaged":path.name,"bytes":size}),flush=True)
        index+=1
        if size==result["part_limit_bytes"]:block=gz.stdout.read(8*1024*1024)
    gz.stdout.close()
    codes=[tar.wait(),gz.wait()]
    if codes!=[0,0]:raise RuntimeError(f"{group}: tar/gzip exit codes {codes}")
    result["groups"][group]={"files":len(members),"source_bytes":sum(x["bytes"] for x in members),"archive_bytes":count,"archive_sha256":whole.hexdigest(),"parts":[p["name"] for p in parts]}
result["completed_at_utc"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
(out/"package-manifest.json").write_text(json.dumps(result,indent=2))
(out/"SHA256SUMS").write_text("".join(f'{x["sha256"]}  {x["name"]}\n' for x in result["assets"]))
print(json.dumps({"status":"packaged","assets":len(result["assets"]),"bytes":sum(x["bytes"] for x in result["assets"])}),flush=True)
