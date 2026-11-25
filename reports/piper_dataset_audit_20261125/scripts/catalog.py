"""Compute the ModelScope corpus size from pinned Git LFS pointers without fetching payloads."""
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from collections import defaultdict
from tables_io import csv_gz

root=Path(sys.argv[1])
repo=root/"sources"/"modelscope-git"
lock=json.loads((root/"sources"/"E.json").read_text())
if not repo.exists():
    subprocess.run(["git","clone","--bare","--depth","1","https://www.modelscope.cn/datasets/"+lock["repo"]+".git",str(repo)],check=True)
cmd=["git","-C",str(repo)]
if subprocess.run(cmd+["cat-file","-e",lock["sha"]+"^{commit}"],capture_output=True).returncode:
    subprocess.run(cmd+["fetch","--depth","1","origin",lock["sha"]],check=True)
names=subprocess.check_output(cmd+["ls-tree","-r",lock["sha"]],text=True).splitlines()
entries=[]
for line in names:
    header,name=line.split("\t",1)
    if name.endswith(".hdf5"):
        entries.append((name,header.split()[-1]))
batch=subprocess.run(cmd+["cat-file","--batch"],input="".join(oid+"\n" for _,oid in entries).encode(),capture_output=True,check=True)
stream=io.BytesIO(batch.stdout)
rows=[]
for path,oid in entries:
    obj,kind,size=stream.readline().decode().split()
    if obj!=oid or kind!="blob":
        raise ValueError(path)
    pointer=stream.read(int(size)).decode()
    stream.read(1)
    sha=re.search(r"oid sha256:([0-9a-f]{64})",pointer).group(1)
    n=int(re.search(r"size (\d+)",pointer).group(1))
    rows.append(dict(path=path,task=path.split("/")[2],size=n,sha256_remote=sha,git_blob=oid))
csv_gz(root/"tables"/"robomind_remote_catalog.csv.gz",rows)
print(len(rows),sum(r["size"] for r in rows),len(set(r["task"] for r in rows)))
