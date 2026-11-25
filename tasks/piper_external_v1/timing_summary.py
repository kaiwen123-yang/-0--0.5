"""Summarize declared clocks, sample reuse and independent validity flags on the derived grid."""
import argparse
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from derive import write_csv


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("work",type=Path)
    args=ap.parse_args()
    rows=[]
    for source in ["A","stack-bowls","C"]:
        counts=Counter()
        values=defaultdict(list)
        for path in sorted((args.work/"grid"/source).glob("*/grid.npz")):
            with np.load(path) as d:
                valid=d["valid"]
                counts["episodes"]+=1
                counts["rows"]+=len(valid)
                counts["valid"]+=int(valid.sum())
                counts["gap_episodes"]+=int(d["gap"].any())
                for k in ["obs_repeat","image_repeat","target_repeat","missing","gap","stale","invalid_source","padded"]:
                    counts[k]+=int(d[k].sum())
                for k in ["obs_age_ns","image_age_ns","target_age_ns","span_ns"]:
                    values[k].append(d[k][valid]/1e6)
        row=dict(source=source,**counts)
        for k in values:
            x=np.concatenate(values[k])
            for q in [0,50,95,100]:
                row[f"{k[:-3]}_ms_p{q}"]=float(np.percentile(x,q))
        rows.append(row)
    write_csv(args.work/"reports/timing_summary.csv",rows)


if __name__=="__main__":
    main()
