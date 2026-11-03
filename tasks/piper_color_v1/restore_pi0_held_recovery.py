"""Restore only missing NPZ files from the eight approved B training cases."""
import re, shutil, subprocess, tarfile
from pathlib import Path
from bct_common import ROOT, read, save, now, gh_env
TASK="pi0-held-recovery-20261103"
CASES=[(113,"red",42),(120,"blue",43),(109,"red",42),(139,"red",42),
       (107,"blue",42),(115,"green",43),(105,"red",43),(126,"blue",43)]

def main():
    run=ROOT/"outputs"/TASK;run.mkdir(exist_ok=True)
    stage=ROOT/"runtime"/(TASK+"-inputs");stage.mkdir(exist_ok=True)
    mapping=read(ROOT/"runtime/pi-progressive-upload-20261101/mapping.json")
    roster=[];groups={}
    for layout,color,seed in CASES:
        p=ROOT/f"outputs/pi0-b-coverage-correction-test-20261101/evaluations/B_coverage/train_{layout:05d}_{color}_seed{seed}/attempt000_seed{seed}/layout_{layout:05d}_{color}.npz"
        row=dict(layout=layout,target=color,base_seed=seed,split="train",trajectory=str(p),
            source_result=str(p.with_suffix(".json")).replace("/outputs/","/results/piper-color-v1/",1))
        roster.append(row)
        if p.exists():
            row["input_source"]="existing_server_file"
            continue
        job,member=next((j,x) for j in mapping["jobs"] for x in j["members"] if x["source"]==str(p))
        row.update(input_source="selective_release_member_restore",asset=job["name"],
            asset_id=job["receipt"]["id"],archive_member=member["archive_path"],bytes=member["bytes"])
        groups.setdefault(job["name"],dict(job=job,members=[]))["members"].append(member)
    save(run/"source_roster.json",roster)
    env=gh_env()
    for name,group in groups.items():
        archive=stage/name
        result=subprocess.run(["gh","release","download",mapping["release_tag"],"--repo",
            "kaiwen123-yang/-0--0.5","--pattern",name,"--dir",str(stage),"--clobber"],
            env=env,capture_output=True,text=True,timeout=300)
        if result.returncode:
            save(run/"input_transfer_error.json",dict(at_utc=now(),asset=name,
                error=re.sub(r"https?://\S+","[URL-redacted]",result.stderr)[-1000:],
                transport="autodl_academic_only"))
            raise RuntimeError("Required input transfer failed: "+name)
        with tarfile.open(archive,"r:") as tf:
            for member in group["members"]:
                destination=Path(member["source"]);destination.parent.mkdir(parents=True,exist_ok=True)
                with tf.extractfile(member["archive_path"]) as src,destination.open("wb") as dst:
                    shutil.copyfileobj(src,dst)
        archive.unlink()
    save(run/"input_restore.json",dict(at_utc=now(),status="required_inputs_available",
        transport="autodl_academic_only",roster=roster,
        restored_npz_count=sum(len(g["members"]) for g in groups.values()),
        only_selected_members_extracted=True,temporary_archives_removed=True))

if __name__=="__main__":
    main()
