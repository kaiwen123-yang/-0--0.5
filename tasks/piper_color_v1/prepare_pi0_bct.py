"""Bind existing B/v2 inputs; no restoration, environment changes or backup."""
import shutil
import numpy as np
from bct_common import *

def prepare():
    if (CAMPAIGN / 'contract.json').exists():
        raise FileExistsError('Existing task: inspect run.json and resume supervisor instead')
    if git('branch', '--show-current') != BRANCH:
        raise ValueError('Wrong branch')
    if shutil.disk_usage(ROOT).free < 65 * 1024**3:
        raise RuntimeError('Need 65 GiB free without deleting existing data')
    source = read(OLD / 'resume.json')
    assert source['optimizer_updates'] == BASE
    assert source['train_rng_key_data'] == [1832780943, 270669613]
    anchor = read(ROOT / 'experiments/piper-color-v1' / TASK / 'source_anchor.json')
    actual = inventory(OLD)
    assert [(r['path'], r['bytes']) for r in actual] == [(r['path'], r['bytes']) for r in anchor['checkpoint_files']]
    # Reuse existing large-file digests. Small frozen input files are checked now.
    for required in ('params', 'train_state', f'assets/{ASSET}/norm_stats.json'):
        assert (OLD / required).exists(), required
    entries = read(V2 / 'dataset/index.json')
    assert len(entries) == 120 and all(e['frames'] == 268 and e['split'] == 'train' for e in entries)
    assert {(e['layout_seed'], e['target']) for e in entries} == {(l,c) for l in range(100,140) for c in COLORS}
    cfgpath = ROOT / 'experiments/piper-color-v1' / (TASK + '.json')
    cfg = read(cfgpath)
    CAMPAIGN.mkdir(parents=True)
    (CAMPAIGN / 'logs').mkdir()
    (CAMPAIGN / 'scene').symlink_to(V2 / 'scene', target_is_directory=True)
    (CAMPAIGN / 'assets').symlink_to(OLD / 'assets', target_is_directory=True)
    (CAMPAIGN / 'dataset').symlink_to(V2 / 'dataset', target_is_directory=True)
    cfg.update(old_checkpoint=str(OLD), old_checkpoint_files=anchor['checkpoint_files'], old_resume=source,
        dataset_manifest_sha256=sha(V2 / 'dataset/manifest.json'), dataset_index_sha256=sha(V2 / 'dataset/index.json'),
        scene_sha256=sha(V2 / 'scene/scene.xml'), normalization_sha256=sha(OLD / f'assets/{ASSET}/norm_stats.json'),
        rng_rule='B saved train_rng folded with cumulative optimizer step 4020 + local step before update',
        checkpoint_identity_verification='existing path/size inventory and resume; existing SHA256 reused; no large hash rescan')
    save(CAMPAIGN / 'contract.json', cfg)
    reused=[]
    for split in ('train','validation'):
        for seed in (42,43):
            directory=AB / 'B/evaluations' / f'update_2010_{split}_seed{seed}'
            protocol=read(directory / 'protocol.json')
            assert protocol['max_steps']==420 and protocol['replan_steps']==5 and protocol['seed_scope']=='episode'
            assert protocol['scene_sha256']==cfg['scene_sha256']
            assert protocol['dataset_manifest_sha256']==cfg['dataset_manifest_sha256']
            assert Path(protocol['policy']['checkpoint'])==OLD
            assert sha(Path(protocol['policy']['norm_stats'])/'norm_stats.json')==cfg['normalization_sha256']
            summary=read(directory/'summary.json')
            assert summary['complete'] and not summary['errors'] and summary['total']==(6 if split=='train' else 15)
            for result in summary['episodes']:
                row=dict(split=split,layout=result['layout_seed'],target=result['target'],base_seed=seed)
                stem=directory/f"layout_{row['layout']:05d}_{row['target']}"
                assert all(stem.with_suffix(s).is_file() for s in ('.json','.npz','.mp4'))
                reused.append({**row,'result_json':str(stem.with_suffix('.json')),'trajectory':str(stem.with_suffix('.npz')),
                    'video':str(stem.with_suffix('.mp4')),'reused_from':str(directory),'success':result['success']})
    assert len(reused)==42
    save(CAMPAIGN/'B_reused_trials.json',reused)
    save(CAMPAIGN/'phase1_roster.json',roster('train',range(102,140),(42,43))+roster('validation',range(1000,1005),(44,45,46)))
    save(CAMPAIGN/'test_roster.json',roster('test',range(2000,2010),(42,43)))
    save(CAMPAIGN/'input_verification.json',dict(at_utc=now(),checkpoint=str(OLD),optimizer_updates=BASE,
        checkpoint_files=len(actual),checkpoint_bytes=sum(r['bytes'] for r in actual),reused_trials=42,
        new_phase1_trials=273,source_deleted=False,restoration_performed=False,old_backup_started=False))

def samplers():
    correction=read(CAMPAIGN/'correction_manifest.json')
    assert 6<=len(correction['accepted'])<=20
    entries=read(V2/'dataset/index.json')
    streams=np.random.SeedSequence(42).spawn(3)
    colors=np.random.default_rng(streams[0]).integers(0,3,4000)
    layouts=np.random.default_rng(streams[1]).integers(100,140,4000)
    u=np.random.default_rng(streams[2]).random(4000)
    frames=np.where(u<.4,np.floor(u/.4*10),np.where(u<.7,10+np.floor((u-.4)/.3*52),62+np.floor((u-.7)/.3*206))).astype(np.int64)
    lookup={(e['layout_seed'],e['target']):i for i,e in enumerate(entries)}
    order=np.array([lookup[(int(l),COLORS[int(c)])] for l,c in zip(layouts,colors)])*268+frames
    rng=np.random.default_rng(20261101)
    mask=np.zeros(4000,dtype=bool); mask[rng.choice(4000,800,replace=False)]=True
    corr_entries=read(CAMPAIGN/'correction_dataset/index.json')
    ends=np.cumsum([e['frames'] for e in corr_entries]); starts=np.r_[0,ends[:-1]]
    ep=rng.integers(0,len(corr_entries),800)
    extra=np.array([starts[e]+rng.integers(0,corr_entries[e]['frames']) for e in ep])
    for group in ('C','D'):
        run=CAMPAIGN/group; run.mkdir(exist_ok=True)
        (run/'logs').mkdir(exist_ok=True)
        for name,source in [('scene',V2/'scene'),('assets',OLD/'assets'),('dataset',V2/'dataset')]:
            if not (run/name).exists(): (run/name).symlink_to(source,target_is_directory=True)
        schedule=order.copy()
        if group=='D': schedule[mask]=32160+extra
        np.save(run/'sample_order.npy',schedule,allow_pickle=False)
        save(run/'sample_order.json',schedule.tolist())
        save(run/'sampler.json',dict(group=group,samples=4000,correction_starts=800 if group=='D' else 0,
            sample_order_sha256=sha(run/'sample_order.npy'),source_optimizer_updates=BASE,new_sample_offset=0,
            replacement_indices=np.flatnonzero(mask).tolist() if group=='D' else [],
            original_phase_counts=[int((frames<10).sum()),int(((frames>=10)&(frames<62)).sum()),int((frames>=62).sum())],
            paired_original_positions=True,correction_episode_uniform=True,correction_frame_uniform=True))

if __name__=='__main__':
    import sys
    samplers() if len(sys.argv)>1 and sys.argv[1]=='samplers' else prepare()
