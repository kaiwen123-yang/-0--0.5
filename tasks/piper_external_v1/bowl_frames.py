"""Stratified visual extension and timing/second-arm outliers, from original PTS."""
import argparse
import csv
from pathlib import Path
import av
import numpy as np
import pyarrow.parquet as pq
from PIL import Image,ImageDraw
from derive import video_clock,write_csv


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("audit",type=Path)
    ap.add_argument("work",type=Path)
    args=ap.parse_args()
    rows=[r for r in csv.DictReader((args.work/"grid/episodes.csv").open()) if r["source"]=="stack-bowls"]
    ids=set(range(0,500,20))|{int(r["episode"]) for r in rows if r["gap_after_source_rows"]}
    ids.update(int(r["episode"]) for r in sorted(rows,key=lambda r:float(r["second_arm_max_joint_range"]))[-3:])
    records=[]
    for j,ep in enumerate(sorted(ids)):
        r=rows[ep]
        assert int(r["episode"])==ep
        s=np.stack(pq.read_table(args.audit/"raw"/r["parquet"],columns=["observation.state"]).column(0).to_numpy())
        def edge(lo,mask):
            candidates=np.flatnonzero(mask[lo:])
            return lo+int(candidates[0]) if len(candidates) else len(s)-1
        opened=edge(0,s[:,6]>.06)
        closed=edge(opened,s[:,6]<.025)
        released=edge(closed,s[:,6]>.06)
        indices=[0,closed,(closed+released)//2,max(closed,released-3),min(released+8,len(s)-1),len(s)-1]
        if j%8==0:
            sheet=Image.new("RGB",(6*124,8*106),"white")
            draw=ImageDraw.Draw(sheet)
        video=Path(r["video"].replace(".right_wrist",".front_view"))
        pts,_=video_clock(args.audit,video,len(s))
        with av.open(str(args.audit/"raw"/video)) as c:
            st=c.streams.video[0]
            st.codec_context.thread_count=1
            for col,i in enumerate(indices):
                c.seek(int(pts[i]),stream=st)
                frame=next(f for f in c.decode(st) if f.pts>=pts[i])
                assert frame.pts==pts[i]
                x,y=124*col,106*(j%8)
                sheet.paste(frame.to_image().resize((124,88)),(x,y))
                draw.text((x,y+88),f"B{ep}/{i}",fill="black")
        name=f"B_{j//8:02d}.jpg"
        records.append(dict(episode=ep,front_frames=" ".join(map(str,indices)),sheet=name))
        if j%8==7 or j==len(ids)-1:
            sheet.save(args.work/"review"/name,quality=90)
    write_csv(args.work/"review/B_review_frames.csv",records)


if __name__=="__main__":
    main()
