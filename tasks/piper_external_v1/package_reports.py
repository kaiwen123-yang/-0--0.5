"""Package the lightweight branch deliverables from the independent server work directory."""
import argparse
import csv
import gzip
import shutil
from pathlib import Path
from derive import write_csv


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("work",type=Path)
    ap.add_argument("out",type=Path)
    args=ap.parse_args()
    src=args.work
    out=args.out
    out.mkdir(parents=True,exist_ok=True)
    for path in sorted((src/"reports").iterdir()):
        if path.name=="examples.csv":
            with path.open() as f:
                rows=list(csv.DictReader(f))
            for r in rows:
                if r["source"]=="C":
                    for key in ("original","original_action","derived_h1","transformed_h1"):
                        r[key]="see D57 local analysis"
            write_csv(out/path.name,rows)
        elif path.stat().st_size>60000:
            (out/(path.name+".gz")).write_bytes(gzip.compress(path.read_bytes(),mtime=0))
        else:
            shutil.copyfile(path,out/path.name)
    (out/"grid_episodes.csv.gz").write_bytes(gzip.compress((src/"grid/episodes.csv").read_bytes(),mtime=0))
    for name in ["A_review_frames.csv","B_review_frames.csv","A_0_212.png","stack-bowls_319_84.png"]:
        shutil.copyfile(src/"review"/name,out/name)


if __name__=="__main__":
    main()
