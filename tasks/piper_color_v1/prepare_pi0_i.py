"""Record the actual corrected data and reuse H's exact sampling and task roster."""
import os, shutil
from i_common import *


def prepare_training():
    manifest = read(COLLECTION/'manifest.json')
    revised = read(COLLECTION/'dataset/index.json')
    original = read(ORIGINAL_RECOVERY/'index.json')
    stages = dict(lift=30, transfer=40, lower=26, release=20, retreat=30, settle=4)
    # This is the plan 7.2 scientific acceptance gate on the three real attempts.
    if not manifest['complete'] or manifest['attempted'] != 3 or manifest['accepted_count'] != 3:
        raise RuntimeError('Three successful complete suffixes are required; publish proposal without training')
    if any(r['frames'] != 150 or r['stage_frames'] != stages for r in revised):
        raise RuntimeError('Original window/phase structure changed; publish proposal without training')
    if {r['layout_seed'] for r in revised} != {107,115,105}:
        raise RuntimeError('The real revised sources do not match the three authorized sources')
    RECOVERY.mkdir(parents=True, exist_ok=True)
    revised_map = {r['directory']:r for r in revised}
    combined, provenance = [], []
    for entry in original:
        name = entry['directory']; corrected = name in revised_map
        source = (COLLECTION/'dataset' if corrected else ORIGINAL_RECOVERY) / name
        destination = RECOVERY/name
        if not destination.is_symlink():
            destination.symlink_to(source, target_is_directory=True)
        combined.append(dict(revised_map.get(name,entry)))
        provenance.append(dict(directory=name, source=str(source), corrected=corrected,
                               frames=entry['frames'], original_source=str(ORIGINAL_RECOVERY/name)))
    save(RECOVERY/'index.json', combined)
    save(CAMPAIGN/'recovery_provenance.json', provenance)
    run = CAMPAIGN/'I'; run.mkdir(parents=True, exist_ok=True)
    (CAMPAIGN/'logs').mkdir(exist_ok=True)
    for name in ('sample_order.npy','sample_order.json'):
        shutil.copyfile(HISTORY/'H'/name,run/name)
    sampler = read(HISTORY/'H/sampler.json')
    sampler.update(source_H_sampler=str(HISTORY/'H/sampler.json'),
        source_H_order=str(HISTORY/'H/sample_order.json'), order_changed=False,
        teacher_only_change='three rotation-interpolated suffixes; same indices, positions, window starts and stage lengths',
        corrected_sources=list(revised_map), corrected_recovery_windows=sum(r['suffix'] in revised_map for r in sampler['replacements']))
    save(run/'sampler.json',sampler)
    NORM.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(OLD/'assets'/ASSET/'norm_stats.json',NORM/'norm_stats.json')
    save(run/'normalization.json',read(HISTORY/'H/normalization.json'))
    allowed = sorted(os.sched_getaffinity(0))
    resources = dict(allowed_cpus=allowed, training_cpus=allowed[8:16],
        lanes=[dict(lane=0,port=18774,service_cpus=allowed[8:16],worker_cpus=allowed[16:20]),
               dict(lane=1,port=18775,service_cpus=allowed[20:28],worker_cpus=allowed[28:32])],
        preallocate=False,memory_fraction=.50,omp_threads=2,blas_threads=2)
    save(CAMPAIGN/'resources.json',resources)
    contract = read(HISTORY/'contract.json')
    contract.update(task=TASK, implementation_commit=git('rev-parse','HEAD'),
        main_plan_commit='71f927b1baa26cc5994ba9e9ee20231edb3dbfc6', research_parent='3dd547a169c7a821fabd278af3b86a1f3d099b95',
        recovery_dataset=str(RECOVERY), recovery_index=combined, parallel_resources=resources,
        candidate_rule='I validation >=72/75 and (development complete successes >25/48 or recovery source autonomous successes >0/8); retain as candidate only, B remains official',
        teacher_correction='Only the existing lift phase uses SO(3) shortest-path SLERP with the same smoothstep as position, from measured takeover rotation to original reset orientation over 30 frames. No policy/controller changes.',
        corrected_recovery_sources=[dict(layout=r['layout_seed'],target=r['target'],directory=r['directory'],
          base_seed=int(r['directory'].split('seed')[-1])) for r in revised],
        replaced_teacher_frames=sum(r['frames'] for r in revised),
        reused_teacher_frames=sum(r['frames'] for r in original if r['directory'] not in revised_map),
        corrected_recovery_windows=sampler['corrected_recovery_windows'],
        collection_wall_seconds=manifest['wall_seconds'], collection_metadata=str(COLLECTION/'manifest.json'),
        collection_contract=str(COLLECTION/'collection_contract.json'),
        original_H_order_unchanged=True, stage_order_unchanged=True, normalization_changed=False,
        diagnostic_forwards=0, baseline_reruns=0,
        decision_branch='7.2 confirmed teacher attitude transition, corrected complete data preserves original windows',
        large_artifacts='retained on server for user backup; no I release queue or deletion',
        evidence_directory=str(ROOT/'results/piper-color-v1/pi0-h-numeric-review-20261104'))
    save(CAMPAIGN/'contract.json',contract)
    print('I_INPUTS_RECORDED: exact H order 2000; 1932 original +68 recovery; 27 recovery windows use 450 revised frames; 750 frames reused',flush=True)


def prepare_evaluation():
    for name in ('node_roster.json','roster_lane0.json','roster_lane1.json','development_training_roster.json','source_roster.json'):
        shutil.copyfile(HISTORY/name,CAMPAIGN/name)
    (CAMPAIGN/'evaluation_layouts').mkdir(exist_ok=True)
    shutil.copyfile(HISTORY/'evaluation_layouts/manifest.json',CAMPAIGN/'evaluation_layouts/manifest.json')
    references=CAMPAIGN/'references'; references.mkdir(exist_ok=True)
    for name in ('node_B.json','node_E_500.json','B_additional_sources.json'):
        shutil.copyfile(HISTORY/'references'/name,references/name)
    shutil.copyfile(HISTORY/'node_H_500.json',references/'node_H_500.json')
    print('I_ROSTERS_REUSED: same H 125 =63+62; B/E/H reused; no baseline executions',flush=True)
