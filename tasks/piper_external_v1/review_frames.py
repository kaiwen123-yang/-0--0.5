"""Targeted A start, grasp, carry, release and terminal frames. Thresholds select review frames only."""
import argparse
from pathlib import Path

import av
import numpy as np
import pyarrow.parquet as pq
from PIL import Image, ImageDraw

from derive import write_csv


def frames_at(video, indices):
    with av.open(str(video)) as container:
        st=container.streams.video[0]
        st.codec_context.thread_count=1
        for i in indices:
            # A's frozen audit established CFR with first PTS zero.
            pts=round(i / 30 / st.time_base)
            container.seek(pts,stream=st)
            for fr in container.decode(st):
                if fr.pts >= pts:
                    assert fr.pts == pts
                    yield fr.to_image().resize((116,87))
                    break
            else:
                raise ValueError((video,i))


def phase_rows(g):
    def first(lo, cond):
        rows=np.flatnonzero(cond[lo:])
        return int(lo+rows[0]) if len(rows) else len(g)-1
    opening=first(0,g>.05)
    grasp=first(opening,g<.040)
    release=first(grasp,g>.045)
    return opening,grasp,release


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("audit",type=Path)
    ap.add_argument("out",type=Path)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    base=args.audit/"raw/A"
    records=[]
    for j,p in enumerate(sorted(base.glob("data/*/*.parquet"))):
        ep=int(p.stem.split("_")[-1])
        g=np.stack(pq.read_table(p,columns=["observation.state"])["observation.state"].to_numpy())[:,6]
        opening,grasp,release=phase_rows(g)
        indices=[0, min(grasp+4,len(g)-1), (grasp+release)//2, max(release-3,0),
                 min(release+12,len(g)-1),len(g)-1]
        if j%10==0:
            sheet=Image.new("RGB",(6*116,10*104),"white")
            draw=ImageDraw.Draw(sheet)
        video=next(base.glob(f"videos/*/observation.images.cam_global/{p.stem}.mp4"))
        for x,(i,img) in enumerate(zip(indices,frames_at(video,indices),strict=True)):
            xy=(x*116,(j%10)*104)
            sheet.paste(img,xy)
            draw.text((xy[0],xy[1]+87),f"A{ep}/{i}",fill="black")
        records.append(dict(episode=ep,open_hint=opening,grasp_hint=grasp,release_hint=release,
                            global_frames=" ".join(map(str,indices)),sheet=f"A_{j//10:02d}.jpg"))
        if j%10==9:
            sheet.save(args.out/f"A_{j//10:02d}.jpg",quality=85)
    write_csv(args.out/"A_review_frames.csv",records)


if __name__=="__main__":
    main()
