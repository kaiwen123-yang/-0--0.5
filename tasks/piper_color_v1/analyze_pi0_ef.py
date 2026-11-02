"""Read saved B trajectories; select train-only local intervention states."""
import json
from pathlib import Path
import numpy as np
from bct_common import read,save,key,COLORS,ROOT,OLD,V2,now
C=ROOT/'outputs/pi0-ef-local-20261102'
H=ROOT/'outputs/pi0-b-coverage-correction-test-20261101'
def analyze():
    C.mkdir(exist_ok=True)
    for name,src in [('scene',V2/'scene'),('assets',OLD/'assets'),('dataset',V2/'dataset')]:
        if not (C/name).exists(): (C/name).symlink_to(src,target_is_directory=True)
    (C/'logs').mkdir(exist_ok=True)
    coverage=read(H/'coverage_summary.json')
    rows=[]
    for r in coverage['train']['episodes']:
        with np.load(r['trajectory']) as d:
            p=d['object_positions'][:,COLORS.index(r['target'])]
            tcp=d['tcp']; xy=np.linalg.norm(tcp[:,:2]-p[:,:2],axis=1)
            cmd=d['executed_command']; chunks=d['predicted_chunks']; raw=d['raw_action']
            sliced=chunks[:,:5].reshape(-1,7)[:len(raw)]
            close=np.flatnonzero(cmd[:,6]<.06)
            first=int(close[0]) if len(close) else len(cmd)
            tailonly=(chunks[:,:5,6].min(axis=1)>=.06)&(chunks[:,5:,6].min(axis=1)<.06)
            slot='back' if p[0,1]>-.09 else ('front_left' if p[0,0]<-.18 else 'front_right')
            # Earliest sustained drift after reaching vicinity, or sustained low/open stall.
            near=np.flatnonzero((xy<.015)&(np.arange(len(xy))>=15))
            anchor=int(near[0]) if len(near) else 20
            events=[]
            for i in range(anchor+5,min(first+1,len(xy)-10)):
                drift=np.all(xy[i:i+10]>.018) and float(xy[i:i+10].mean()-xy[max(anchor,i-20):i].min())>.008
                stall=i>=60 and np.all(cmd[i-10:i+1,6]>.06) and tcp[i,2]<.10 and abs(tcp[i,2]-tcp[i-10,2])<.004
                if drift or stall:
                    events.append((max(5,i-10),'sustained_xy_drift' if drift else 'low_open_stall')); break
            frame,reason=events[0] if events else (max(10,min(first-15,180)),'preclosure_or_late_stage')
            row={**r,'slot':slot,'intervention_frame':frame,'intervention_reason':reason,
                 'raw_slice_max_error':float(np.max(abs(raw-sliced))),
                 'tail_only_close_chunks':int(tailonly[:max(1,first//5)].sum()),
                 'close_seconds':first/20 if len(close) else None,
                 'close_xy_mm':float(xy[first]*1000) if len(close) else None,
                 'frame30_xy_mm':float(xy[30]*1000),
                 'handoff_tcp':tcp[frame].tolist(),'handoff_width':float(d['state'][frame,6]),
                 'handoff_target':p[frame].tolist(),
                 'executed_raw_max_difference':float(abs(cmd-raw).max())}
            rows.append(row)
    failed=[r for r in rows if not r['success']]
    pairs=[]
    for f in failed:
        good=[r for r in rows if r['success'] and r['target']==f['target'] and r['slot']==f['slot']]
        g=min(good,key=lambda r:(r['layout']!=f['layout'],abs(r['layout']-f['layout']),r['base_seed']))
        pairs.append({'failure':f,'matched_success':g})
    summary={}
    for ok in (True,False):
        rr=[r for r in rows if r['success']==ok]
        summary[str(ok)]={'episodes':len(rr),'close_median_s':float(np.median([r['close_seconds'] for r in rr if r['close_seconds'] is not None])),
          'close_xy_median_mm':float(np.median([r['close_xy_mm'] for r in rr if r['close_xy_mm'] is not None])),
          'tail_only_close_total':sum(r['tail_only_close_chunks'] for r in rr),
          'episodes_tail_only':sum(r['tail_only_close_chunks']>0 for r in rr)}
    save(C/'trajectory_diagnosis.json',{'created_at':now(),'summary':summary,'pairs':pairs,
        'max_raw_slice_error':max(r['raw_slice_max_error'] for r in rows),
        'path':'E_F_learning_comparison','execution_change':False,
        'interpretation':'Replan-five slicing matches saved raw commands. Tail-only closure is a policy planning behavior, not proof of an execution implementation error. Physics pauses during inference.'})
    # 24 task pairs: 12 back red/blue weaknesses, four back green, four front-left, four front-right.
    tasks=[]
    for slot,colors,n in [('back',('red','blue'),12),('back',('green',),4),('front_left',COLORS,4),('front_right',COLORS,4)]:
        pool=[r for r in rows if r['slot']==slot and r['target'] in colors]
        pool.sort(key=lambda r:(r['success'],r['layout'],r['target'],r['base_seed']))
        for r in pool:
            t=(r['layout'],r['target'])
            if t in tasks: continue
            tasks.append(t); n-=1
            if n==0: break
    roster=[dict(split='train',layout=l,target=c,base_seed=s) for l,c in tasks for s in (42,43)]
    save(C/'development_training_roster.json',roster)
    dev=[r for r in rows if key(r) in {key(x) for x in roster}]
    save(C/'B_development.json',{'train':dev,'validation':coverage['validation']['episodes']})
    # Attempt roster includes all failures, prioritizes distinct tasks, supplements actual stalls in green/front success.
    attempts=[]; seen=set()
    for r in sorted(failed,key=lambda r:(r['slot']!='back',r['layout'],r['target'],r['base_seed'])):
        t=(r['layout'],r['target'])
        if t not in seen: attempts.append(r); seen.add(t)
    for r in sorted(rows,key=lambda r:(r['target']!='green',r['slot']=='back',r['layout'])):
        if len(attempts)>=24: break
        t=(r['layout'],r['target'])
        if t not in seen and r['intervention_reason']!='preclosure_or_late_stage':
            attempts.append(r); seen.add(t)
    for r in failed:
        if len(attempts)>=36: break
        if key(r) not in {key(x) for x in attempts}: attempts.append(r)
    save(C/'correction_roster.json',attempts[:36])
    print(json.dumps({'summary':summary,'max_slice_error':max(r['raw_slice_max_error'] for r in rows),
          'dev_tasks':len(tasks),'attempt_roster':len(attempts[:36]),
          'handoff_range':[min(r['intervention_frame'] for r in attempts),max(r['intervention_frame'] for r in attempts)]}))
if __name__=='__main__': analyze()

