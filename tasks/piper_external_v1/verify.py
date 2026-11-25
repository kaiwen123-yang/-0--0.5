"""Independent real-source checks and CPU-only reader/transform examples; no model construction."""
import argparse
import av
import csv
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from PIL import Image,ImageDraw

from derive import CONFIG,read_json,write_csv
from source_reader import SourceEpisode
from tasks.piper_real_single_v1.policy_config import SingleCameraInputs, DELTA_MASK
from tasks.piper_real_single_v1.dataset import SingleCameraDataset
from openpi.transforms import DeltaActions


def transform(item):
    image=item["camera_rgb"]
    sample=DeltaActions(DELTA_MASK)(SingleCameraInputs("wrist")(item))
    assert sample["actions"].shape==(10,7) and sample["state"].shape==(7,)
    assert image.dtype==np.uint8 and image.ndim==3 and image.shape[-1]==3
    assert [k for k,v in sample["image_mask"].items() if v]==["left_wrist_0_rgb"]
    np.testing.assert_array_equal(sample["image"]["left_wrist_0_rgb"],image)
    np.testing.assert_array_equal(sample["actions"][:,:6],item["actions"][:,:6]-item["state"][:6])
    np.testing.assert_array_equal(sample["actions"][:,6],item["actions"][:,6])
    return sample


def main():
    ap=argparse.ArgumentParser()
    for name in ["audit","work","local"]:
        ap.add_argument(name,type=Path)
    args=ap.parse_args()
    examples=[]
    valid_count=0
    window_count=0
    # The sample grid indices below target grasp/transport/release, and both sides of B371's timing break.
    selections={("A",0):[212,285,336],("A",152):[280],("C",31):[90,126,172],
                ("stack-bowls",319):[54,84,102],("stack-bowls",371):[5,16]}
    rows=list(csv.DictReader((args.work/"grid/episodes.csv").open()))
    for r in rows:
        source=r["source"]
        ep=int(r["episode"])
        spec=CONFIG["sources"][source]
        p=args.work/"grid"/source/f"{ep:06d}"
        raw=pq.read_table(args.audit/"raw"/r["parquet"])
        s,a=[np.stack(raw[k].to_numpy()) for k in (spec["state"],spec["action"])]
        with np.load(p/"grid.npz") as d:
            valid=d["valid"]
            obs,target=d["obs_row"],d["target_row"]
            np.testing.assert_array_equal(d["state"],s[obs])
            np.testing.assert_array_equal(d["original_action"],a[obs])
            np.testing.assert_array_equal(d["future_state"][valid],s[target[valid]])
            assert np.all(d["image_ns"]<=d["query_ns"]) and np.all(d["obs_ns"]<=d["query_ns"])
            assert np.all(d["target_ns"][valid]>d["query_ns"][valid])
            assert np.all(d["target_ns"]<=d["target_query_ns"])
            time=(raw["real_observation_timestamp_s"].to_numpy() if source=="stack-bowls"
                  else np.arange(len(s))/30)
            ns=np.rint((time-time[0])*1e9).astype("int64")
            for idx,q in [(obs,d["query_ns"]),(target,d["target_query_ns"])]:
                has_next=idx+1<len(s)
                assert np.all(ns[idx]<=q) and np.all(ns[idx[has_next]+1]>q[has_next])
            starts=d["starts"]
            assert np.all(valid[starts[:,None]+np.arange(10)])
            cuts=np.r_[0,np.cumsum(np.diff(ns)>CONFIG["max_gap_ns"])]
            assert np.all(cuts[obs[starts]]==cuts[target[starts+9]])
            valid_count+=int(valid.sum())
            window_count+=len(starts)
            if (source,ep) not in selections:
                continue
            reader=SourceEpisode(args.audit/"raw",p)
            for requested in selections[source,ep]:
                i=int(np.argmin(np.abs(starts-requested)))
                j=int(starts[i])
                item=reader[i]
                result=transform(item)
                # Store examples only on D57, including C. Numeric row references can be published.
                with av.open(str(reader.video)) as c:
                    stream=c.streams.video[0]
                    stream.codec_context.thread_count=1
                    frames={int(d["image_frame"][j]),int(target[j+9])}
                    originals={}
                    for number,fr in enumerate(c.decode(stream)):
                        if number in frames:
                            originals[number]=fr.to_ndarray(format="rgb24")
                        if len(originals)==len(frames):
                            break
                native=originals[int(d["image_frame"][j])]
                np.testing.assert_array_equal(native,item["camera_rgb"])
                panel=Image.new("RGB",(810,372),"white")
                for x,im in enumerate((native,item["camera_rgb"],originals[int(target[j+9])])):
                    panel.paste(Image.fromarray(im).resize((250,180)),(x*265,25))
                draw=ImageDraw.Draw(panel)
                draw.text((4,4),f"{source} ep {ep} source RGB #{d['image_frame'][j]}",fill="black")
                draw.text((269,4),f"Reader input at grid {j}",fill="black")
                draw.text((534,4),f"Review only: h10 source row {target[j+9]}",fill="black")
                for k,(label,val) in enumerate([("source state @ obs",s[obs[j],:7]),
                            ("original action @ obs",a[obs[j],:7]),("source state @ target",s[target[j],:7]),
                            ("derived absolute h1",item["actions"][0]),("transformed h1",result["actions"][0]),
                            ("derived absolute h10",item["actions"][-1])]):
                    draw.text((8,211+25*k),label+"   "+" ".join(f"{v:.4f}" for v in val),fill="black")
                preview=f"review/{source}_{ep}_{j}.png"
                panel.save(args.work/preview)
                examples.append(dict(source=source,episode=ep,grid=j,obs_row=int(obs[j]),frame=int(d["image_frame"][j]),
                    query_ns=int(d["query_ns"][j]),image_ns=int(d["image_ns"][j]),obs_ns=int(ns[obs[j]]),
                    target_query_ns=int(d["target_query_ns"][j]),target_ns=int(ns[target[j]]),
                    target_rows=json.dumps(target[j:j+10].tolist()),shape=str(item["camera_rgb"].shape),
                    original=s[obs[j],:7].tolist(),original_action=a[obs[j],:7].tolist(),
                    derived_h1=item["actions"][0].tolist(),transformed_h1=result["actions"][0].tolist(),preview=preview))
    for split in ["train","validation"]:
        ds=SingleCameraDataset(args.local,split,10,20)
        transform(ds[len(ds)//2])
    write_csv(args.work/"reports/examples.csv",examples)
    receipt=dict(episodes=len(rows),verified_rows=valid_count,verified_windows=window_count,
                 source_reader_examples=len(examples),local_reader_splits=["train","validation"],
                 transforms=["SingleCameraInputs(wrist)","DeltaActions(DELTA_MASK)"],model_loaded=False)
    (args.work/"reports/verification.json").write_text(json.dumps(receipt,indent=2))
    print(receipt)


if __name__=="__main__":
    main()
