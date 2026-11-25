"""Public official catalog plus three complete source HDF5 samples. Read-only HTTP."""
import concurrent.futures as cf
from pathlib import Path
import json
import sys
from urllib.parse import quote
from acquire import session, now, digests, write_json

ROOT = Path(sys.argv[1])
REPO = "X-Humanoid/RoboMIND2.0-Agilex"
API = "https://modelscope.cn/api/v1/datasets/" + REPO
SHA = "5cb0e3a4fa5cf144f75ec4927c9c1d23ccd5c382"
SAMPLES = {"pick_red_yellow_buttons_and_place_in_box": None,
           "place_pomegranate_in_white_plate": "2024_12_12-10_29_11-173637122753700320.00",
           "put_pen_and_scissors_into_bin": "0415_102035",
           "place_colored_items_on_matching_plates": None,
           "close_fridge_door": "0306_204419"}


def tree(folder):
    entries = []
    page = 1
    while True:
        res = session().get(API+"/repo/tree",params=dict(Revision=SHA, Root=folder,
                            PageNumber=page,PageSize=100),timeout=(15,60))
        res.raise_for_status()
        batch=res.json()["Data"]["Files"]
        if page>1 and batch and batch[0]["Path"]==entries[0]["Path"]:
            raise RuntimeError("pagination repeated")
        entries.extend(batch)
        if len(batch)<100:
            return entries
        page+=1


def fetch(entry):
    name=entry["Path"]
    dst=ROOT/"raw"/"E"/name
    dst.parent.mkdir(parents=True, exist_ok=True)
    part=dst.with_suffix(dst.suffix+".part")
    url=API+"/repo"
    if not dst.exists():
        offset=part.stat().st_size if part.exists() else 0
        if offset!=entry["Size"] or not part.exists():
            with session().get(url,params=dict(Revision=SHA,FilePath=name),
                               headers={"Range":f"bytes={offset}-"} if offset else {},
                               stream=True,timeout=(20,120)) as res:
                res.raise_for_status()
                if res.status_code==206 and not res.headers["Content-Range"].startswith(f"bytes {offset}-"):
                    raise IOError("incorrect range")
                with part.open("ab" if res.status_code==206 and offset else "wb") as out:
                    for block in res.iter_content(1<<20):
                        out.write(block)
    target=dst if dst.exists() else part
    sha,_=digests(target)
    if target.stat().st_size!=entry["Size"] or sha!=entry["Sha256"]:
        raise ValueError(name+" hash or size mismatch")
    if target==part:
        part.replace(dst)
    return dict(path=name,size=entry["Size"],sha256=sha,remote_sha256=entry["Sha256"],verified=now())


def main():
    src=ROOT/"sources"
    folders=tree("data/agilex")
    tasks=[x["Name"] for x in folders if x["Type"]=="tree"]
    selections=[x for x in tree("") if x["Type"]=="blob"]
    episodes={}
    for task,ep in SAMPLES.items():
        folder="data/agilex/"+task
        selections.extend(x for x in tree(folder) if x["Type"]=="blob")
        eps=tree(folder+"/success_episodes")
        ep=ep or eps[len(eps)//2]["Name"]
        episodes[task]=ep
        selections.extend(tree(folder+"/success_episodes/"+ep+"/data"))
    card=session().get(API,timeout=30).json()["Data"]
    write_json(src/"E.json",dict(repo=REPO,sha=SHA,license=card["License"],tasks=tasks,
               selected=episodes,files=selections,locked=now(),endpoint=API))
    with cf.ThreadPoolExecutor(3) as pool:
        results=list(pool.map(fetch,selections))
    write_json(ROOT/"checks"/"E_files.json",results)


if __name__=="__main__":
    main()
