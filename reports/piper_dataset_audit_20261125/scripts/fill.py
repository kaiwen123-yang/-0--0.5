"""Fill only missing Hub blobs, prioritizing selected review cases in an interrupted transfer."""
import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from acquire import SOURCES,download
from hashlib import sha1

root=Path(sys.argv[1])
endpoint=sys.argv[2]
workers=int(sys.argv[3])
selected=json.loads((root/"previews"/"selected.json").read_text())
jobs=[]
for k in SOURCES:
    lock=json.loads((root/"sources"/(k+".json")).read_text())
    for file in lock["files"]:
        name=file["rfilename"]
        path=root/"raw"/k/name
        if path.exists():
            continue
        wanted=name.endswith(".mp4") and int(path.stem.split("_")[-1]) in selected[k]
        jobs.append((not wanted,sha1(name.encode()).hexdigest(),lock,file))
jobs.sort(key=lambda v:v[:2])
with (root/"checks"/"fill.jsonl").open("a",buffering=1) as report, ThreadPoolExecutor(workers) as pool:
    calls=[pool.submit(download,root,endpoint,l,f,".fillpart") for _,_,l,f in jobs]
    for i,c in enumerate(as_completed(calls),1):
        row=c.result()
        report.write(json.dumps(row)+"\n")
        if i%50==0 or row[-1]!="verified":
            print(i,len(jobs),row[0],row[-1],flush=True)
