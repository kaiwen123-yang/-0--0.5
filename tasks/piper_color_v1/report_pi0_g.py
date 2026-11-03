"""Paired task comparisons and the single G experiment report."""
from collections import Counter
from g_common import *

def compact(row):
    return {field: row.get(field) for field in ("split", "layout", "target", "base_seed", "slot", "success", "failure_stage")}

def compare(reference, candidate):
    before = {key(r): r for r in reference}
    after = {key(r): r for r in candidate}
    result = {}
    for split in ("train", "validation"):
        keys = [k for k in before if k[0] == split]
        fixed = [compact(after[k]) for k in keys if not before[k]["success"] and after[k]["success"]]
        lost = [dict(task=compact(after[k]), previous=compact(before[k])) for k in keys if before[k]["success"] and not after[k]["success"]]
        result[split] = dict(repaired_count=len(fixed), lost_count=len(lost), repaired=fixed, lost=lost)
    return result

def report():
    b = read(PREVIOUS / "node_B.json")
    e = read(PREVIOUS / "node_E_500.json")
    f = read(PREVIOUS / "node_F_500.json")
    g = read(CAMPAIGN / "node_G_500.json")
    maps = [{key(r): r for r in node["episodes"]} for node in (b,e,g)]
    bm, em, gm = maps
    e_validation_losses = [k for k in bm if k[0]=="validation" and bm[k]["success"] and not em[k]["success"]]
    e_training_repairs = [k for k in bm if k[0]=="train" and not bm[k]["success"] and em[k]["success"]]
    paired = dict(G_vs_B=compare(b["episodes"],g["episodes"]), G_vs_E=compare(e["episodes"],g["episodes"]),
        E_lost_B_validation=dict(total=len(e_validation_losses), restored_by_G=sum(gm[k]["success"] for k in e_validation_losses),
            tasks=[compact(gm[k]) for k in e_validation_losses]),
        E_repaired_B_training=dict(total=len(e_training_repairs), retained_by_G=sum(gm[k]["success"] for k in e_training_repairs),
            tasks=[compact(gm[k]) for k in e_training_repairs]),
        G_failure_stages={split:dict(Counter(r["failure_stage"] for r in g["episodes"] if r["split"]==split and not r["success"]))
            for split in ("train","validation")})
    save(CAMPAIGN / "paired_comparison.json", paired)
    status = read(CAMPAIGN / "run.json")
    lines = ["# G500 固定视觉最终更新对照", "",
        "G从B累计4020完整状态接续500次真实更新，最终累计4520。原filter、dtype、梯度裁剪、optimizer buffer、学习率schedule与数据/RNG规则沿用E。仅在tx.update之后、apply_updates之前将PaliGemma/img/.*最终update置零。",
        "", "| 指标 | B（复用） | E500（复用） | F500（复用） | G500（本轮） |",
        "|---|---:|---:|---:|---:|"]
    for label, split, field, denom in (("困难开发","train","successes",48),("开发后排","train","back_successes",32),
                                       ("验证","validation","successes",75),("验证后排","validation","back_successes",25)):
        values = [str(node["summary"][split][field])+"/"+str(denom) for node in (b,e,f,g)]
        lines.append("| "+label+" | "+" | ".join(values)+" |")
    lines += ["", "开发48项与验证75项独立报告；推理种子不是独立训练种子。", "",
              "| 配对 | 集合 | 修复 | 丢失 |", "|---|---|---:|---:|"]
    for reference in ("B","E"):
        for split in ("train","validation"):
            value = paired["G_vs_"+reference][split]
            lines.append("| G对"+reference+" | "+split+" | "+str(value["repaired_count"])+" | "+str(value["lost_count"])+" |")
    lines += ["", "## 逐任务修复与丢失", "",
        "任务记法为layout/target/seed；train与validation分别比较，不合并评分。", "",
        "| 配对 | 集合 | 修复任务 | 丢失任务及G失败阶段 |", "|---|---|---|---|"]
    def identity(row):
        return f"{row['layout']}/{row['target']}/s{row['base_seed']}"
    for reference in ("B","E"):
        for split in ("train","validation"):
            value=paired["G_vs_"+reference][split]
            repaired="、".join(identity(r) for r in value["repaired"]) or "无"
            lost="、".join(identity(r["task"])+"("+r["task"]["failure_stage"]+")" for r in value["lost"]) or "无"
            lines.append("| G对"+reference+" | "+split+" | "+repaired+" | "+lost+" |")
    lines += ["", f"G恢复E丢失的B验证成功{paired['E_lost_B_validation']['restored_by_G']}/8项；保留E修复的B训练难例{paired['E_repaired_B_training']['retained_by_G']}/13项。",
        "完整任务身份与失败阶段见paired_comparison.json；逐任务结果见node_G_500.json。", "",
        "## 选择与证据边界", "", "当前选择："+status["selected_candidate"]+"。"+status["selection_reason"]]
    if (CAMPAIGN/"candidate_coverage.json").exists():
        coverage = read(CAMPAIGN/"candidate_coverage.json")
        lines.append("G全训练："+str(coverage["summary"]["train"]["successes"])+"/240；其中48项复用本轮开发任务，仅新增192项。")
    test = read(CAMPAIGN/"new_layout_comparison.json")
    if test["performed"]:
        lines += ["本轮3000–3009新布局：B "+str(test["B_successes"])+"/60，G "+str(test["G_successes"])+"/60。",
                  "测试前G500已冻结；本轮到此停止，不使用这些布局追加训练或调参。"]
    else:
        lines.append("本轮新布局测试未执行："+test["reason"]+"。")
    lines += ["旧独立测试53/60仅为B历史成绩，不能改称本轮成绩。",
        "该对照检验限制视觉权重移动对本次适配收益与退化的影响。单次训练对照不能证明SigLIP灾难性遗忘；验证布局已反复用于开发。",
        "", "## G失败阶段", ""]
    for split, counts in paired["G_failure_stages"].items():
        lines.append(split+"："+str(counts))
    lines += ["", "## 任务与交付", "",
        f"真实训练500次；新增自主完整任务{status['new_complete_tasks']}次；E/F训练与B/E/F开发评测未重复。",
        "源码、配置、正常日志、紧凑结果与本报告入Git；完整检查点及新轨迹/视频入Release。发布、保留与pending范围见publication/pi0-g-fixed-vision-20261103/delivery_status.json。",
        "按用户最新更正，B/v2恢复副本、G完整检查点、optimizer/RNG/norm/采样与训练数据、轨迹视频和相关记录全部保留；只清理无活动依赖的传输临时副本。B/v2已有Release资产不重复上传。"]
    (CAMPAIGN/"final_report_zh.md").write_text("\n".join(lines)+"\n")
    return paired

if __name__ == "__main__":
    report()
