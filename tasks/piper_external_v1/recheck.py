"""Compare wrist and global evidence around ambiguous A transitions, indexed by original frame."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from review_frames import frames_at

audit,out=map(Path,sys.argv[1:])
for j,ep in enumerate([2,12,18,34,65,73,104,136,152,160,197,198]):
    d=np.load(out/"grid/A"/f"{ep:06}"/"grid.npz")
    end=int(d["obs_row"][-1])
    indices=np.unique(np.rint(np.r_[np.linspace(0,end,7),end-12,end-4]).astype(int))
    if j%3==0:
        sheet=Image.new("RGB",(len(indices)*124,3*210),"white")
    draw=ImageDraw.Draw(sheet)
    for side,cam in enumerate(["cam_global","cam_gripper"]):
        path=next((audit/"raw/A").glob(f"videos/*/observation.images.{cam}/episode_{ep:06}.mp4"))
        for k,(i,img) in enumerate(zip(indices,frames_at(path,indices),strict=True)):
            x,y=k*124,(j%3)*210+side*104
            sheet.paste(img,(x,y))
            draw.text((x,y+86),f"{ep}/{i} {cam[4:5]}",fill="black")
    if j%3==2:
        sheet.save(out/"review"/f"recheck_{j//3}.jpg",quality=86)
