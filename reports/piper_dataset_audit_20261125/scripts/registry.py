import csv
import json
import sys
from pathlib import Path

root=Path(sys.argv[1])
out=root/"tables"
summary=json.loads((out/"completion.json").read_text())
rows=[]
for s in summary["sources"]:
    key=s["source"]
    repo=s["repo"]
    base=("https://modelscope.cn/datasets/" if key=="E" else
          "https://huggingface.co/" if key=="D" else "https://huggingface.co/datasets/")+repo
    authority=base+("/tree/"+s["sha"] if key!="E" else "/files")
    if key=="A":
        license,proof="Apache-2.0",base+"/blob/"+s["sha"]+"/README.md"
        relation="LeRobot v2.1 发布版，未提供采集实现"
    elif key=="C":
        license,proof="未声明，未确认可再分发",base+"/blob/"+s["sha"]+"/README.md"
        relation="CSV 到 LeRobot 转换，原 CSV 不在发布树中"
    elif key=="D":
        license,proof="Apache-2.0（发布仓库数据卡）",base+"/blob/"+s["sha"]+"/README.md"
        relation="模型仓库内的 Piper LeRobot 数据子目录和仓库说明，不含权重"
    elif key=="E":
        license,proof="Apache License 2.0（ModelScope 数据卡及 README）",base+"/summary"
        relation="官方 per-episode HDF5 小样本，22,206 个原件指针另列"
    else:
        license="MIT（项目明确指向数据集）"
        proof="https://github.com/Agentic-Intelligence-Lab/RoboNever/blob/f5a2f5f649947b71c0aa431b750d547e86c1a36f/README.md#license"
        relation="RoboNever 官方 README 指向的 HF 子集，ContinualVLA 为消费端代码"
    rows.append(dict(publisher=repo.split("/")[0],url=base,version_url=authority,license=license,
        license_evidence=proof,relationship=relation,scope="指定范围完整" if key!="E" else "官方目录完整、五条原件取样",
        raw=str(root/"raw"/key),**{k:v for k,v in s.items() if k!="frame_or_decode_errors"}))
rows.append(dict(publisher="axiboai",source="E_community",repo="axiboai/robomind2-ee",
    url="https://huggingface.co/datasets/axiboai/robomind2-ee",sha="3da5fec74ad8d6e9b16b1c87ea30371d7c3ba759",
    license="数据卡列 Apache-2.0",license_evidence="https://huggingface.co/datasets/axiboai/robomind2-ee",
    relationship="社区 FK/夹爪缩放/视频缩小与重新编码，官方 AgileX 另按型号拆分",
    scope="公开说明与 API；原件访问须手动批准，未申请",file_count=0,bytes=0,episodes=0,streams=0))
with (out/"sources.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
