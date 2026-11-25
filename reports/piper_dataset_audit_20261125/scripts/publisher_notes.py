"""Record public documentation, Hub name search and disputed layer/identity evidence."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sys
import requests
from acquire import SOURCES,now,write_json

root=Path(sys.argv[1])
docs={
 "RoboMIND2.html":"https://log2r.github.io/RoboMIND2.0/",
 "RoboNever-paper.html":"https://arxiv.org/html/2605.26820",
 "RoboNever-original-paper.html":"https://arxiv.org/html/2605.26820v1",
 "community-card.html":"https://huggingface.co/datasets/axiboai/robomind2-ee",
}
terms=[v[1].split("/")[-1] for k,v in SOURCES.items() if k!="D"]+["piper_aaai_4task","piperx-four-color-block-sorting"]


def fetch(item):
    name,url=item
    path=root/"sources"/name
    try:
        if not path.exists():
            if name=="community-card.html" and (path.parent/"community-public-card.html").exists():
                saved=path.parent/"community-public-card.html"
                return dict(file=saved.name,url=url,transport="https://hf-mirror.com/datasets/axiboai/robomind2-ee",
                            bytes=saved.stat().st_size,sha256=hashlib.sha256(saved.read_bytes()).hexdigest())
            res=requests.get(url,timeout=(8,30))
            res.raise_for_status()
            path.write_bytes(res.content)
        return dict(file=name,url=url,bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    except Exception as e:
        return dict(file=name,url=url,error=type(e).__name__)


def lookup(term):
    try:
        res=requests.get("https://hf-mirror.com/api/datasets",params={"search":term,"limit":50},timeout=(8,30))
        res.raise_for_status()
        return dict(term=term,ids=[v["id"] for v in res.json()])
    except Exception as e:
        return dict(term=term,error=type(e).__name__)


with ThreadPoolExecutor(8) as pool:
    evidence=list(pool.map(fetch,docs.items()))
    hits=list(pool.map(lookup,terms))
write_json(root/"tables"/"public_documents.json",dict(fetched=now(),documents=evidence,repository_name_search=hits))
