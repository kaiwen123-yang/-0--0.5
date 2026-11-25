"""Create local-only contact sheets and exhaustive contiguous frame strips for selected events."""
import argparse
import json
from pathlib import Path
import numpy as np
import av
import h5py
from PIL import Image,ImageDraw
from io import BytesIO
from acquire import SOURCES,write_json


def strip(frames,label,ids,w=140,h=102):
    canvas=Image.new("RGB",(len(ids)*w,h+17),"white")
    for i,n in enumerate(ids):
        im=frames.get(n)
        if im:
            im.thumbnail((w,h))
            canvas.paste(im,(i*w+(w-im.width)//2,17))
    ImageDraw.Draw(canvas).text((2,1),label+"   "+",".join(map(str,ids)),fill="black")
    return canvas


def select(root):
    result={}
    for k in SOURCES:
        items=[json.loads(p.read_text()) for p in sorted((root/"checks"/"arrays"/k).glob("*.json"))]
        ids={v["episode"] for v in (items[0],items[len(items)//2],items[-1],min(items,key=lambda x:x["n"]),
                                      max(items,key=lambda x:x["n"]))}
        def max_step(e):
            q=e["profile"]["state"]["delta_q"]
            return max(q[-1][:6]) if q else 0
        ids.add(max(items,key=max_step)["episode"])
        if len(items[0]["profile"]["state"]["start"])==14:
            def other_arm(e):
                q=np.asarray(e["profile"]["state"]["q"])
                return float(np.max(q[-1,7:]-q[0,7:]))
            ids.add(max(items,key=other_arm)["episode"])
        ids.update({"D":[77],"C":[22],"hang-cup":[187],"fold-towel":[393]}.get(k,[]))
        groups={}
        for row in items:
            groups.setdefault(row["task_indices"][0],[]).append(row["episode"])
        if len(groups)>1:
            for ix,group in enumerate(groups.values()):
                ids.add(group[(len(group)-1)*(ix%3)//2])
        result[k]=sorted(ids)
    return result


def sheets(root,key,eid,continuous):
    base=root/"raw"/key
    paths=sorted(base.rglob(f"videos/*/*/episode_{eid:06}.mp4"))
    n=json.loads((root/"checks"/"arrays"/key/f"episode_{eid:06}.json").read_text())["n"]
    if len(paths)!=len([v for v in json.loads(next(base.rglob("meta/info.json")).read_text())["features"].values() if v["dtype"]=="video"]):
        return False
    dest=root/"previews"/key
    dest.mkdir(parents=True,exist_ok=True)
    out=dest/f"{eid:04}.jpg"
    if out.exists() and not continuous:
        return True
    ids=sorted(set(np.rint(np.linspace(0,n-1,9)).astype(int).tolist()))
    bands=[]
    for path in paths:
        cam=path.parent.name.split(".")[-1]
        frames={}
        chunk=[]
        with av.open(str(path)) as container:
            stream=container.streams.video[0]
            stream.codec_context.thread_count=1
            for i,f in enumerate(container.decode(stream)):
                if i in ids or continuous:
                    img=f.to_image()
                    if i in ids:
                        frames[i]=img.copy()
                    if continuous:
                        img.thumbnail((96,72))
                        chunk.append(img)
                        if len(chunk)==120:
                            save_page(dest,eid,cam,i+1-len(chunk),chunk)
                            chunk=[]
            if chunk:
                save_page(dest,eid,cam,i+1-len(chunk),chunk)
        bands.append(strip(frames,f"{key} {eid} {cam}",ids))
    save_bands(bands,out)
    return True


def save_page(dest,ep,cam,first,frames):
    out=Image.new("RGB",(960,16+72*((len(frames)+9)//10)),"white")
    ImageDraw.Draw(out).text((0,0),f"{ep} {cam} {first}..{first+len(frames)-1}: L-R then down",fill="black")
    for j,img in enumerate(frames):
        out.paste(img,(96*(j%10),16+72*(j//10)))
    out.save(dest/f"full_{ep:04}_{cam}_{first:05}.jpg",quality=82)


def save_bands(bands,out):
    canvas=Image.new("RGB",(max(b.width for b in bands),sum(b.height for b in bands)),"white")
    y=0
    for b in bands:
        canvas.paste(b,(0,y))
        y+=b.height
    canvas.save(out,quality=84)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    ap.add_argument("--full",nargs="*",default=[])
    args=ap.parse_args()
    root=args.root
    selected=select(root)
    for entry in args.full:
        key,num=entry.split("/")
        selected[key]=sorted(set(selected[key])|{int(num)})
    write_json(root/"previews"/"selected.json",selected)
    for key,ids in selected.items():
        for ep in ids:
            sheets(root,key,ep,f"{key}/{ep}" in args.full)
    for path in (root/"raw"/"E").rglob("trajectory.hdf5"):
        dest=root/"previews"/"E"
        dest.mkdir(exist_ok=True)
        with h5py.File(path,"r") as f:
            bands=[]
            for cam,ds in f["camera_observations/color_images"].items():
                ids=np.rint(np.linspace(0,len(ds)-1,9)).astype(int).tolist()
                frames={i:Image.open(BytesIO(bytes(ds[i]))).convert("RGB") for i in ids}
                bands.append(strip(frames,path.parts[-5]+" "+cam,ids))
            save_bands(bands,dest/(path.parts[-3]+".jpg"))


if __name__=="__main__":
    main()
