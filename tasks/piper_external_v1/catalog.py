"""Join reviewed outcomes, inclusive start ranges and frozen provenance. No random frame split."""
import argparse
import csv
import gzip
import json
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from derive import CONFIG,HERE,read_json,write_csv
from review_frames import phase_rows


def read_rows(path):
    with (gzip.open(path,"rt",encoding="utf-8-sig") if path.suffix==".gz" else path.open(encoding="utf-8-sig")) as f:
        return list(csv.DictReader(f))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("audit",type=Path)
    ap.add_argument("work",type=Path)
    args=ap.parse_args()
    out=args.work/"reports"
    audit=args.audit
    d=read_json(HERE/"decisions.json")
    a={int(r["episode"]):r for r in read_rows(args.work/"review/A_review_frames.csv")}
    b={int(r["episode"]):r for r in read_rows(args.work/"review/B_review_frames.csv")}
    v={(r["source"],int(r["episode"])):r for r in read_rows(audit/"reports/visual_review.csv") if r["episode"].isdigit()}
    grid={(r["source"],r["episode"]):r for r in read_rows(args.work/"grid/episodes.csv")}
    source_meta={r["source"]:r for r in read_rows(audit/"reports/sources.csv")}
    rows=[]
    statistics=defaultdict(lambda:defaultdict(list))
    by_ep_phase=[]
    carry_frames=[]
    candidate=[]
    for raw in read_rows(audit/"reports/episodes.csv.gz"):
        k,e=raw["source"],raw["episode"]
        info=grid.get((k,e),{})
        ep=int(e) if e.isdigit() else e
        audit_visual=v.get((k,ep),{})
        frames=audit_visual.get("sampled_frame_indices","")
        visual_path=audit_visual.get("local_sheet","")
        status="not_reviewed_for_adaptation"
        reason={"D":"state reference unresolved; pen/carrot deferred","E":"original sample audit only"}.get(k,"other task outside active subset")
        accepted=False
        if k=="A":
            frames=a[ep]["global_frames"]
            visual_path="review/"+a[ep]["sheet"]
            status="partial_evidence"
            reason="sampled start/grasp/transport/release/end does not establish every stage"
            if ep in d["A_setup_or_previous_trial_visible"]:
                reason="scene setup, previous placement or hand visible; isolate task start before selection"
            if ep in d["A_terminal_unclear"]:
                status="uncertain_terminal"
                reason="release, destination or clear terminal view unresolved"
            if ep==152:
                reason="hand resets scene; green block remains between fingers near box through final view"
            if ep==197:
                reason="scene reset and long wait; final wrist still around block at pickup"
            if ep==2:
                reason="terminal box interior cropped even on wrist/global recheck"
            if ep==12:
                status="complete_with_setup"
                reason="block placed in box, but operator sets it up after recording starts"
            if ep in d["A_complete"]:
                accepted=True
                status="complete_visible"
                reason="separate block, grasp, carried block, release inferred from deposited block and empty/withdrawn gripper"
                if str(ep) in d["A_recheck_evidence"]:
                    frames+=" | "+" ".join(map(str,d["A_recheck_evidence"][str(ep)]))
        elif k=="stack-bowls":
            status="uncertain_unreviewed"
            reason="no episode-specific visual evidence of complete stacking in reviewed set"
            if ep in b:
                frames=b[ep]["front_frames"]
                visual_path="review/"+b[ep]["sheet"]
            if ep==260:
                status="partial_only"
                reason="bowls already nested before approach"
            if ep in d["B_uncertain_terminal"]:
                status="uncertain_terminal"
                reason="yellow bowl appears tilted; depth of seating unclear in sampled front frames"
            if str(ep) in d["B_complete_stage_frames"] or ep in d["B_extended_complete"]:
                accepted=True
                status="complete_visible"
                reason="separate bowls, one gripper lifts/transfers yellow bowl onto green, withdraws; stable nested appearance"
                if str(ep) in d["B_complete_stage_frames"]:
                    frames+=" | "+" ".join(map(str,d["B_complete_stage_frames"][str(ep)]))
        elif k=="C":
            status="partial_evidence" if audit_visual else "uncertain_unreviewed"
            if ep in d["C_reviewed_completion"]:
                status="complete_visible"
            reason="licence pending; global task visibility does not establish single-current-wrist observability"
        split="candidate_train_only" if accepted else "held_out_of_candidate_pool"
        starts=int(info.get("starts",0))
        source_path=Path(raw["path"])
        if source_path.parts[0]!=k:
            source_path=Path(k)/source_path
        assert (audit/"raw"/source_path).is_file(),source_path
        rows.append(dict(source=k,revision=source_meta.get(k,{}).get("sha",""),episode=e,
                         parquet_or_hdf=str(source_path),task=raw.get("instruction") or raw["task"],
                         rows=raw["n"],grid_rows=info.get("grid_rows",0),valid_rows=info.get("valid_rows",0),starts=starts,
                         outcome=status,reason=reason,frames=frames,visual=visual_path,split=split,
                         group="entire published collection" if k in ["A","C"] else "2026-04-13 UTC" if k=="stack-bowls" else "",
                         candidate_starts=starts if accepted else 0,default_local_train=False))
        if accepted:
            candidate.append(dict(source=k,episode=ep,revision=info["revision"],directory=f"{k}/{ep:06d}",
                             group=rows[-1]["group"],split=split,prompt=info["prompt"],
                             starts=starts,start_ranges=info["start_ranges"],local_eligible=False))
        if k not in CONFIG["sources"]:
            continue
        spec=CONFIG["sources"][k]
        tab=pq.read_table(audit/"raw"/info["parquet"],columns=[spec["state"],spec["action"]])
        s,g=[np.stack(tab[f].to_numpy())[:,6] for f in [spec["state"],spec["action"]]]
        phase=np.full(len(s),"unassigned",dtype="U32")
        if k=="A":
            sampled=list(map(int,a[ep]["global_frames"].split()))
            if accepted and len(set(sampled))==6:
                mid=sampled[2]
                carry_frames.append(dict(episode=ep,frame=mid,source_state=float(s[mid]),
                                         original_action=float(g[mid]),sheet=a[ep]["sheet"]))
            op,cl,rel=phase_rows(s)
            phase[:op]="before_first_open"
            phase[op:cl]="open_approach"
            phase[cl:rel]="close_and_carry_hint"
            if rel<len(s)-1:
                end=np.flatnonzero(s[rel:]<.015)
                end=rel+int(end[0]) if len(end) else len(s)
                phase[rel:end]="release_open_hint"
                phase[end:]="post_release_closed_hint"
        elif k=="C":
            low=np.flatnonzero(g<.035)
            if len(low):
                cl=low[0]
                hi=np.flatnonzero(g[cl:]>.055)
                rel=cl+hi[0] if len(hi) else len(s)
                phase[:cl]="approach"
                phase[cl:rel]="close_and_carry_hint"
                phase[rel:]="release_open_hint"
        else:
            continue
        for name in np.unique(phase):
            mask=phase==name
            statistics[(k,name)]["state"].append(s[mask])
            statistics[(k,name)]["orig_action"].append(g[mask])
            by_ep_phase.append(dict(source=k,episode=ep,phase=name,first=int(np.flatnonzero(mask)[0]),
                                    last=int(np.flatnonzero(mask)[-1]),rows=int(mask.sum()),
                                    negative_actions=int((g[mask]<0).sum()),
                                    state_median=float(np.median(s[mask])),orig_action_median=float(np.median(g[mask]))))
    assert len(rows)==2450 and len({(r["source"],r["episode"]) for r in rows})==len(rows)
    write_csv(out/"decisions.csv",rows)
    write_csv(out/"source_candidates.csv",candidate)
    write_csv(out/"phase_by_episode.csv",by_ep_phase)
    write_csv(out/"A_carry_frames.csv",carry_frames)
    phases=[]
    for (k,name),values in sorted(statistics.items()):
        s,g=[np.concatenate(values[key]) for key in ["state","orig_action"]]
        phases.append(dict(source=k,phase=name,rows=len(g),negative=int((g<0).sum()),
                           state_p10_p50_p90=np.quantile(s,[.1,.5,.9]).tolist(),
                           orig_action_p10_p50_p90=np.quantile(g,[.1,.5,.9]).tolist()))
    write_csv(out/"phase_summary.csv",phases)
    summary={}
    for k in source_meta:
        subset=[r for r in rows if r["source"]==k]
        summary[k]=dict(episodes=len(subset),derived=sum(bool(int(r["grid_rows"])) for r in subset),
                        raw_rows=sum(int(r["rows"]) for r in subset),grid_rows=sum(int(r["grid_rows"]) for r in subset),
                        valid_rows=sum(int(r["valid_rows"]) for r in subset),starts=sum(r["starts"] for r in subset),
                        candidate_episodes=sum(bool(r["candidate_starts"]) for r in subset),
                        candidate_starts=sum(r["candidate_starts"] for r in subset),
                        outcomes=dict(Counter(r["outcome"] for r in subset)),padded_slots=0,local_eligible=0)
    (out/"summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))


if __name__=="__main__":
    main()
