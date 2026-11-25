"""Stack local audit sheets for in-memory review over SSH; no export of raw images."""
import sys
from pathlib import Path
from PIL import Image

args=sys.argv[1:]
compact=args and args[0]=="--grid"
paths=[Path(k) for k in (args[1:] if compact else args)]
images=[Image.open(path).convert("RGB") for path in paths]
if compact:
    for im in images:
        im.thumbnail((560,540))
    height=max(im.height for im in images)
    out=Image.new("RGB",(1120,height*((len(images)+1)//2)),"white")
    for i,im in enumerate(images):
        out.paste(im,(560*(i%2),height*(i//2)))
else:
    out=Image.new("RGB",(max(im.width for im in images),sum(im.height for im in images)),"white")
    y=0
    for im in images:
        out.paste(im,(0,y))
        y+=im.height
out.save(sys.stdout.buffer,format="JPEG",quality=84)
