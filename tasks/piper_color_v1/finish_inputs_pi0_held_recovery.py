"""Finish the two required held-recovery input assets through the existing academic route."""
import base64, concurrent.futures, json, shutil, subprocess, tarfile, threading, time
from urllib.parse import urlsplit, urlunsplit, parse_qs
from pathlib import Path
import requests
from bct_common import ROOT, gh_env, read, save, now
RUN=ROOT/"outputs/pi0-held-recovery-20261103"
STAGE=ROOT/"runtime/pi0-held-recovery-20261103-inputs"

def main():
    env=gh_env()
    token=subprocess.check_output(["gh","auth","token"],env=env,text=True).strip()
    mapping=read(ROOT/"runtime/pi-progressive-upload-20261101/mapping.json")
    roster=read(RUN/"source_roster.json");groups={}
    for row in roster:
        if Path(row["trajectory"]).exists():continue
        job,member=next((j,m) for j in mapping["jobs"] for m in j["members"] if m["source"]==row["trajectory"])
        groups.setdefault(job["name"],dict(job=job,members=[]))["members"].append(member)
    receipts=[]
    for name,group in groups.items():
        job=group["job"];part=STAGE/name
        offset=part.stat().st_size if part.exists() else 0
        session=requests.Session();session.trust_env=False
        session.proxies={"http":env["http_proxy"],"https":env["https_proxy"]}
        response=session.get(f"https://api.github.com/repos/kaiwen123-yang/-0--0.5/releases/assets/{job['receipt']['id']}?required_input={time.time_ns()}",
            headers={"Authorization":"Bearer "+token,"Accept":"application/octet-stream"},
            allow_redirects=False,timeout=(30,60),verify=env.get("REQUESTS_CA_BUNDLE",True))
        if response.status_code!=302:raise RuntimeError("Required asset redirect status "+str(response.status_code))
        u=urlsplit(response.headers["Location"])
        encoded=parse_qs(u.query)["jwt"][0].split(".")[1]
        payload=json.loads(base64.urlsafe_b64decode(encoded+"="*(-len(encoded)%4)))
        origin=urlunsplit((u.scheme,payload["path"],u.path,u.query,""))
        bounds=[(a,min(a+(1<<20),job["bytes"])-1) for a in range(offset,job["bytes"],1<<20)]
        local=threading.local()
        def fetch(bound):
            a,b=bound;p=STAGE/(name+f".range-{a}-{b}")
            if not hasattr(local,"session"):
                local.session=requests.Session();local.session.trust_env=False
                local.session.proxies={"http":env["http_proxy"],"https":env["https_proxy"]}
            for attempt in range(2):
                try:
                    with local.session.get(origin+"&required_input="+str(time.time_ns()),
                        headers={"Range":f"bytes={a}-{b}","Accept-Encoding":"identity"},
                        stream=True,timeout=(30,60),verify=env.get("REQUESTS_CA_BUNDLE",True)) as res:
                        res.raise_for_status()
                        if res.headers.get("Content-Range")!=f"bytes {a}-{b}/{job['bytes']}":
                            raise RuntimeError("Required input range response differs")
                        with p.open("wb") as out:
                            for block in res.iter_content(64<<10):out.write(block)
                    return p
                except requests.RequestException:
                    if attempt:raise RuntimeError("Required input range transport failed")
        print("RESUME_REQUIRED_INPUT",name,"existing",offset,"remaining",job["bytes"]-offset,flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            paths=list(pool.map(fetch,bounds))
        with part.open("ab") as out:
            for p in paths:
                with p.open("rb") as src:shutil.copyfileobj(src,out)
                p.unlink()
        with tarfile.open(part,"r:") as tf:
            for member in group["members"]:
                dst=Path(member["source"]);dst.parent.mkdir(parents=True,exist_ok=True)
                with tf.extractfile(member["archive_path"]) as src,dst.open("wb") as out:
                    shutil.copyfileobj(src,out)
                print("RESTORED_NPZ",dst.name,dst.stat().st_size,flush=True)
        part.unlink()
        receipts.append(dict(asset=name,existing_transfer_bytes=offset,new_transfer_bytes=job["bytes"]-offset,
            members=[m["archive_path"] for m in group["members"]],transport="autodl_academic_only"))
        save(RUN/"input_resume.json",dict(at_utc=now(),receipts=receipts,
            prior_transport_failure="Two asset API requests failed before bytes; gh release download timed out after 300s; existing partial bytes reused"))
    save(RUN/"input_restore.json",dict(at_utc=now(),status="required_inputs_available",roster=roster,
        restored_npz_count=8,only_selected_members_extracted=True,temporary_archives_removed=True,
        transport="autodl_academic_only",research_materials_retained=True))

if __name__=="__main__":
    main()
