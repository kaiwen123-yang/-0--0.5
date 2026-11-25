import csv
import gzip


def csv_gz(path,rows):
    with gzip.open(path,"wt",encoding="utf-8",newline="") as out:
        w=csv.DictWriter(out,fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
        w.writeheader()
        w.writerows(rows)
