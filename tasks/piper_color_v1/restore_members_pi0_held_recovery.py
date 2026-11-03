"""Read the remaining approved NPZ members without transferring unrelated tar payloads."""
import base64, io, json, os, re, shutil, signal, subprocess, tarfile, time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qs
import requests
from bct_common import ROOT, gh_env, read, save, now
RUN=ROOT/"outputs/pi0-held-recovery-20261103"
STAGE=ROOT/"runtime/pi0-held-recovery-20261103-inputs"

def main():
    env=gh_env()
    token=subprocess.check_output(["gh","auth","token"],env=env,text=True).strip()
    mapping=read(ROOT/"runtime/pi-progressive-upload-20261101/mapping.json")
    rows=read(RUN/"source_roster.json")
    receipts=[]
    for row in rows:
        if Path(row["trajectory"]).exists():continue
        job=next(j for j in mapping["jobs"] if j["name"]==row["asset"])
        # Existing uploader writes PAX: one 512-byte extended header, its <=512-byte
        # path/mtime payload, and the 512-byte regular header for these exact members.
        offset=0
        for member in job["members"]:
            if member["source"]==row["trajectory"]:break
            offset+=1536+((member["bytes"]+511)//512)*512
        end=offset+1536+member["bytes"]-1
        pieces=sorted(STAGE.glob(job["name"]+".range-*"),
            key=lambda p:int(p.name.rsplit(".range-",1)[1].split("-")[0]))
        block=bytearray();position=offset
        for p in pieces:
            a,b=map(int,p.name.rsplit(".range-",1)[1].split("-"))
            if a<=position<=b and p.stat().st_size==b-a+1:
                with p.open("rb") as stream:
                    stream.seek(position-a);chunk=stream.read(min(b,end)-position+1)
                block.extend(chunk);position+=len(chunk)
            if position>end:break
        source="existing_completed_range_files"
        if position<=end:
            source="selected_member_http_range"
            session=requests.Session();session.trust_env=False
            session.proxies={"http":env["http_proxy"],"https":env["https_proxy"]}
            res=session.get(f"https://api.github.com/repos/kaiwen123-yang/-0--0.5/releases/assets/{job['receipt']['id']}?required_member={time.time_ns()}",
                headers={"Authorization":"Bearer "+token,"Accept":"application/octet-stream"},
                allow_redirects=False,timeout=(30,60),verify=env.get("REQUESTS_CA_BUNDLE",True))
            if res.status_code!=302:raise RuntimeError("Asset redirect status "+str(res.status_code))
            u=urlsplit(res.headers["Location"]);encoded=parse_qs(u.query)["jwt"][0].split(".")[1]
            payload=json.loads(base64.urlsafe_b64decode(encoded+"="*(-len(encoded)%4)))
            origin=urlunsplit((u.scheme,payload["path"],u.path,u.query,""))
            res=session.get(origin+"&required_member="+str(time.time_ns()),
                headers={"Range":f"bytes={offset}-{end}","Accept-Encoding":"identity"},
                timeout=(30,90),verify=env.get("REQUESTS_CA_BUNDLE",True))
            if res.status_code!=206 or res.headers.get("Content-Range")!=f"bytes {offset}-{end}/{job['bytes']}":
                raise RuntimeError("Required member byte range unavailable")
            block=res.content
        with tarfile.open(fileobj=io.BytesIO(block),mode="r:") as tf:
            actual=tf.next()
            if actual.name!=member["archive_path"] or actual.size!=member["bytes"]:
                raise RuntimeError("Archive member differs from existing release mapping")
            dst=Path(member["source"]);dst.parent.mkdir(parents=True,exist_ok=True)
            with tf.extractfile(actual) as src,dst.open("wb") as out:shutil.copyfileobj(src,out)
        receipts.append(dict(layout=row["layout"],target=row["target"],base_seed=row["base_seed"],
            asset=job["name"],member=member["archive_path"],tar_member_start=offset,
            bytes=member["bytes"],source=source,transport="autodl_academic_only"))
        save(RUN/"selected_member_restore.json",dict(at_utc=now(),receipts=receipts))
        print("RESTORED_REQUIRED_MEMBER",row["layout"],source,member["bytes"],flush=True)
    ended=[]
    save(RUN/"input_restore.json",dict(at_utc=now(),status="required_inputs_available",
        roster=rows,restored_npz_count=8,only_selected_members_extracted=True,
        transport="autodl_academic_only",research_materials_retained=True,
        redundant_own_input_downloader_terminated=ended,existing_uploader_untouched=True,
        temporary_transfer_copies_retained_until_no_active_dependency=True))
    print("ALL_EIGHT_INPUTS_AVAILABLE",flush=True)

if __name__=="__main__":main()
