"""Compare numeric lattices to published conversion factors without applying a unit conversion."""
import argparse
import csv
import numpy as np
import pyarrow.parquet as pq
from pathlib import Path
from derive import CONFIG,write_csv


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("audit",type=Path)
    ap.add_argument("work",type=Path)
    args=ap.parse_args()
    rows=[]
    for k,spec in CONFIG["sources"].items():
        base=args.audit/"raw"/k
        for key in [spec["state"],spec["action"]]:
            data=np.concatenate([np.stack(pq.read_table(p,columns=[key])[key].to_numpy())
                                 for p in sorted(base.glob("data/*/*.parquet"))]).astype(float)
            for name,val in [("joint",data[:,:6]),("grip",data[:,6])]:
                scales=([("ros_0.017444_per_degree",.017444/1000),("3.14_over_180000",3.14/180000),
                         ("pi_over_180000",np.pi/180000)] if name=="joint" else
                        [("0.00007_native",.00007),("0.0001_native",.0001)])
                for code,scale in scales:
                    x=val/scale
                    residual=np.abs(x-np.rint(x))
                    rows.append(dict(source=k,field=key,component=name,grid=code,values=val.size,
                                median_tick_distance=float(np.median(residual)),
                                p99_tick_distance=float(np.quantile(residual,.99)),
                                max_tick_distance=float(residual.max())))
    write_csv(args.work/"reports/quantization.csv",rows)


if __name__=="__main__":
    main()
