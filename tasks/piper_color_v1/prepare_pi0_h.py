"""Construct the actual H inputs; no dataset conversion or baseline execution."""
from collections import Counter
import os, shutil
import numpy as np
from h_common import *


def prepare_training():
    run = CAMPAIGN / 'H'
    run.mkdir(parents=True, exist_ok=True)
    (CAMPAIGN / 'logs').mkdir(exist_ok=True)
    original = read(DATA / 'index.json')
    recovery = read(RECOVERY / 'index.json')
    mother = read(PREVIOUS / 'E/sample_order.json')[:2000]
    order = mother.copy()
    ends = np.cumsum([r['frames'] for r in original])
    episodes = np.searchsorted(ends, mother, side='right')
    offsets = np.r_[0, ends[:-1]]
    frames = np.array(mother) - offsets[episodes]
    categories = np.where(frames < 10, 0, np.where(frames < 62, 1, 2))
    # Weighted interleaving gives 26/22/20 anchors distributed across all 2000 slots.
    quotas = (26, 22, 20)
    category_order = [c for _, c, _ in sorted(((j + .5) / n, c, j)
                      for c, n in enumerate(quotas) for j in range(n))]
    suffix_frames = [sorted([0, 25, 45, 65, 85, 105, 125, 140] +
                    ([15] if r['layout_seed'] in (107, 115, 105, 126) else [])) for r in recovery]
    suffix_offsets = np.r_[0, np.cumsum([r['frames'] for r in recovery])[:-1]]
    starts = [(ep, fs[round_index]) for round_index in range(9)
              for ep, fs in enumerate(suffix_frames) if round_index < len(fs)]
    used_episodes, replacements = set(), []
    for i, (category, (new_ep, relative_frame)) in enumerate(zip(category_order, starts, strict=True)):
        anchor = (i + .5) * len(mother) / len(starts)
        positions = [p for p, c in enumerate(categories)
                     if c == category and int(episodes[p]) not in used_episodes]
        position = min(positions, key=lambda p: (abs(p - anchor), p))
        old_ep = int(episodes[position])
        used_episodes.add(old_ep)
        entry = recovery[new_ep]
        new_index = int(ends[-1] + suffix_offsets[new_ep] + relative_frame)
        order[position] = new_index
        replacements.append(dict(position=position, update=position // 4 + 1, batch_slot=position % 4,
            original_index=mother[position], original_episode=old_ep,
            original_directory=original[old_ep]['directory'], original_frame=int(frames[position]),
            original_range=category, new_index=new_index, suffix=entry['directory'],
            suffix_episode=new_ep, layout=entry['layout_seed'], target=entry['target'],
            relative_frame=relative_frame, takeover_frame=entry['intervention_frame']))
    retained = Counter(int(episodes[i]) for i, index in enumerate(order) if index < ends[-1])
    save(run / 'sample_order.json', order)
    np.save(run / 'sample_order.npy', np.asarray(order, dtype=np.int64), allow_pickle=False)
    save(run / 'sampler.json', dict(mother=str(PREVIOUS / 'E/sample_order.json'), mother_slice=[0, 2000],
        samples=len(order), original_samples=sum(retained.values()), recovery_samples=len(replacements),
        original_episode_coverage=len(retained), original_episode_exposures=dict(sorted(retained.items())),
        mother_range_counts=Counter(map(int, categories)), replacement_range_counts=list(quotas),
        retained_range_counts=[int(sum(categories == c)) - n for c, n in enumerate(quotas)],
        distinct_replaced_original_episodes=len(used_episodes),
        position_rule='68 evenly spaced anchors; 26/22/20 weighted range order; nearest available position from a previously unselected original episode; lower position breaks ties',
        suffix_assignment='round robin over dataset index order, ascending fixed relative frames per suffix',
        replacement_positions_zero_based=True, replacements=replacements,
        suffix_relative_frames={r['directory']: fs for r, fs in zip(recovery, suffix_frames)}))
    NORM.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OLD / 'assets' / ASSET / 'norm_stats.json', NORM / 'norm_stats.json')
    save(run / 'normalization.json', dict(source=str(OLD / 'assets' / ASSET / 'norm_stats.json'),
        method='unchanged B mean/std', recomputed=False, action_delta_mask=[True]*6+[False],
        norm_stats=read(NORM / 'norm_stats.json')))
    allowed = sorted(os.sched_getaffinity(0))
    resources = dict(allowed_cpus=allowed, training_cpus=allowed[8:16],
        lanes=[dict(lane=0, port=18772, service_cpus=allowed[8:16], worker_cpus=allowed[16:20]),
               dict(lane=1, port=18773, service_cpus=allowed[20:28], worker_cpus=allowed[28:32])],
        preallocate=False, memory_fraction=.50, omp_threads=2, blas_threads=2)
    save(CAMPAIGN / 'resources.json', resources)
    save(CAMPAIGN / 'contract.json', dict(task=TASK, implementation_commit=git('rev-parse', 'HEAD'),
        research_parent='d36db6b174f37bc1fb34d9d22cbd67a127c5f908', main_plan_commit=git('rev-parse', 'origin/main'),
        source_checkpoint=str(OLD), source_resume=read(OLD / 'resume.json'),
        source_cumulative_updates=4020, new_updates=500, final_cumulative_updates=4520, batch=4,
        learning_rate=1e-6, warmup_steps=0, schedule_decay_steps=5020,
        train_step='openpi/scripts/train.py::train_step (same upstream path as E)', visual_update_zeroing=False,
        train_rng_key_data=read(OLD / 'resume.json')['train_rng_key_data'], rng_fold_in_steps=[4020, 4519],
        original_dataset=str(DATA), recovery_dataset=str(RECOVERY), recovery_index=recovery,
        model_inputs=['external_rgb', 'wrist_rgb', 'measured_state', 'language'],
        horizon=10, replan=5, hz=20, max_steps=420, continuous_success_steps=40,
        inference_batch=1, flow_sampling_steps=10,
        episode_seed_formula='base_seed + layout_seed * 3 + color_index',
        evaluation_budget=dict(development=48, validation=75, additional_sources=2, total=125, lanes=[63, 62]),
        candidate_rule='validation >=72/75 and (development complete successes >25/48 or recovery source autonomous successes >0/8); retain as candidate only, B remains official',
        large_artifacts='retained on server for user backup; no H release queue or deletion',
        transport='autodl_academic_only', parallel_resources=resources))
    print('H_INPUTS_RECORDED', len(order), len(replacements), sum(retained.values()), len(retained), flush=True)


def prepare_evaluation():
    # Keep the original 123 task ordering, then append only the two new source identities.
    tasks = [{**r, 'report_group': 'development' if r['split'] == 'train' else 'validation'}
             for r in read(PREVIOUS / 'node_roster.json')]
    tasks += [dict(split='train', layout=l, target=c, base_seed=s, report_group='additional_sources')
              for l, c, s in ((120, 'blue', 43), (139, 'red', 42))]
    for number, row in enumerate(tasks):
        row.update(roster_index=number, lane=number % 2)
    save(CAMPAIGN / 'node_roster.json', tasks)
    for lane in (0, 1):
        save(CAMPAIGN / f'roster_lane{lane}.json', tasks[lane::2])
    shutil.copyfile(PREVIOUS / 'development_training_roster.json', CAMPAIGN / 'development_training_roster.json')
    (CAMPAIGN / 'evaluation_layouts').mkdir(exist_ok=True)
    manifest = read(PREVIOUS / 'evaluation_layouts/manifest.json')
    manifest['split_seeds']['test'] = []
    save(CAMPAIGN / 'evaluation_layouts/manifest.json', manifest)
    references = CAMPAIGN / 'references'
    references.mkdir(exist_ok=True)
    for name in ('node_B.json', 'node_E_500.json'):
        shutil.copyfile(PREVIOUS / name, references / name)
    sources = read(RECOVERY_RECORDS / 'source_roster.json')
    save(CAMPAIGN / 'source_roster.json', sources)
    extras = []
    for task in tasks[-2:]:
        source = next(r for r in sources if key(r) == key(task))
        result = read(source['source_result'])
        save(references / (trial_id(task) + '_B_result.json'), result)
        extras.append(dict(**task, success=result['success'], error=result['error'],
            frames=result['steps'], slot='front_left', failure_stage='historical_failure',
            result_json=source['source_result'], reused_from='B_coverage'))
    save(references / 'B_additional_sources.json', extras)
    print('H_ROSTERS_RECORDED 125 = 63 + 62; B/E reused', flush=True)
