"""Finish the five interrupted G input volumes through official academic acceleration."""
import base64, concurrent.futures, json, subprocess, threading, time
from urllib.parse import urlsplit, urlunsplit, parse_qs
import requests
from pathlib import Path
from bct_common import ROOT, gh_env, read, save, now

STAGE=ROOT/"runtime/pi0-g-fixed-vision-20261103-restore"
RUN=ROOT/"outputs/pi0-g-fixed-vision-20261103"

def main():
    env=gh_env()
    order={"ab-b-checkpoint-2010.tar.zst.part-015":0,
           "ab-b-checkpoint-2010.tar.zst.part-017":1,
           "v2-training-data.tar.zst.part-000":2,
           "v2-training-data.tar.zst.part-001":3,
           "ab-b-checkpoint-2010.tar.zst.part-016":4}
    remote=json.loads(subprocess.check_output(["gh","release","view","pi-complete-backup-20261101",
        "--repo","kaiwen123-yang/-0--0.5","--json","assets"],env=env,text=True,timeout=60))
    assets=[a for a in remote["assets"] if a["name"] in order]
    assets.sort(key=lambda a:order[a["name"]])
    records=[]
    def fetch(asset):
        group="ab-b-checkpoint-2010" if asset["name"].startswith("ab-") else "v2-training-data"
        part=STAGE/group/asset["name"]
        offset=part.stat().st_size
        if offset==asset["size"]:
            return dict(name=asset["name"],status="complete_reused",bytes=offset)
        token=subprocess.check_output(["gh","auth","token"],env=env,text=True).strip()
        redirect_headers=STAGE/(asset["name"]+".redirect-headers")
        redirect=subprocess.run(["curl","--config","-","--fail","--dump-header",str(redirect_headers),
            "--output","/dev/null","--header","Accept: application/octet-stream",
            "--connect-timeout","30","--max-time","90","--silent","--show-error",
            asset["apiUrl"]+"?required_input="+str(time.time_ns())],
            input='header = "Authorization: Bearer '+token+'"'+chr(10),env=env,capture_output=True,text=True)
        if redirect.returncode:
            return dict(name=asset["name"],status="pending",phase="asset_redirect",returncode=redirect.returncode)
        url=next(line.split(":",1)[1].strip() for line in redirect_headers.read_text().splitlines()
                 if line.lower().startswith("location:"))
        u=urlsplit(url)
        encoded=parse_qs(u.query)["jwt"][0].split(".")[1]
        payload=json.loads(base64.urlsafe_b64decode(encoded+"="*(-len(encoded)%4)))
        # Same GitHub-signed blob, through the same official AutoDL proxy.
        origin=urlunsplit((u.scheme,payload["path"],u.path,u.query,""))
        block_size=1<<20
        ranges=[(a,min(a+block_size,asset["size"])-1) for a in range(offset,asset["size"],block_size)]
        local=threading.local()
        def read_range(bounds):
            a,b=bounds
            path=STAGE/(asset["name"]+f".range-{a}-{b}")
            if not hasattr(local,"session"):
                local.session=requests.Session()
                local.session.trust_env=False
                local.session.proxies={"http":env["http_proxy"],"https":env["https_proxy"]}
            error=None
            for attempt in range(2):
                have=path.stat().st_size if path.exists() else 0
                if have==b-a+1:break
                start=a+have
                try:
                    with local.session.get(origin+"&required_input="+str(time.time_ns()),
                        headers={"Range":f"bytes={start}-{b}","Accept-Encoding":"identity"},
                        stream=True,timeout=(30,120),verify=env.get("REQUESTS_CA_BUNDLE",True)) as response:
                        response.raise_for_status()
                        if response.headers.get("Content-Range")!=f"bytes {start}-{b}/{asset['size']}":
                            error="range_response_mismatch";break
                        with path.open("ab") as stream:
                            for block in response.iter_content(64<<10):
                                if block:stream.write(block)
                except requests.RequestException as exc:
                    error=type(exc).__name__
            size=path.stat().st_size if path.exists() else 0
            return dict(start=a,end=b,received=size,complete=size==b-a+1,error=error)
        print("FETCH_REMAINING_INPUT",asset["name"],asset["size"]-offset,"bytes",len(ranges),"ranges",flush=True)
        pieces=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(read_range,bounds) for bounds in ranges]
            for future in concurrent.futures.as_completed(futures):
                pieces.append(future.result())
                if len(pieces)%16==0:
                    print("RANGE_PROGRESS",asset["name"],len(pieces),len(ranges),
                          sum(x["received"] for x in pieces),flush=True)
        # Append the completed contiguous prefix; incomplete ranges remain for continuation.
        for a,b in ranges:
            path=STAGE/(asset["name"]+f".range-{a}-{b}")
            if not path.exists() or path.stat().st_size!=b-a+1:break
            with part.open("ab") as destination,path.open("rb") as source:
                while block:=source.read(1<<20):destination.write(block)
            path.unlink()
        size=part.stat().st_size
        return dict(name=asset["name"],status="downloaded" if size==asset["size"] else "pending",
            bytes=size,expected=asset["size"],ranges=pieces,origin_host=payload["path"],
            transport="autodl_academic_only",at_utc=now())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for future in concurrent.futures.as_completed([pool.submit(fetch,a) for a in assets]):
            records.append(future.result())
            save(RUN/"priority_input_transfer.json",dict(transport="autodl_academic_only",records=records,at_utc=now()))
    if any(r["status"]=="pending" for r in records):
        print("INPUTS_PENDING",flush=True)
        return
    subprocess.run(["/root/miniconda3/bin/python","-u",str(ROOT/"tasks/piper_color_v1/restore_pi0_g.py")],cwd=ROOT,check=True)
    for asset in assets:
        replacement=STAGE/(asset["name"]+".replacement")
        if replacement.exists(): replacement.unlink()
    state=read(RUN/"run.json")
    state.update(stage="inputs_restored",error=None,at_utc=now())
    save(RUN/"run.json",state)
    from publish_pi0_g import publish
    publish("required-inputs-restored")
    subprocess.run([str(ROOT/"runtime/d57-color-sim/bin/python"),"-u",str(ROOT/"tasks/piper_color_v1/run_pi0_g.py")],cwd=ROOT,check=True)

if __name__=="__main__":
    main()
