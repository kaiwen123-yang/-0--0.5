"""Execute only this lane's assigned formal episodes, with independent progress."""
import argparse, sys, time
import numpy as np
import evaluate_pi0_ef as evaluator
from worker_pi0_g import metrics as outcome_metrics
from sim import BOX, HALF
from h_common import *


def progression(stem):
    with np.load(stem.with_suffix('.npz'), allow_pickle=False) as trace:
        pos = trace['diagnostic_target_position']
        bilateral = (trace['diagnostic_normal_force'] > .05).all(axis=1)
        lifted = pos[:, 2] - HALF > .05
        over_box = ((abs(pos[:, 0] - BOX[0]) < .072 - HALF) &
                    (abs(pos[:, 1] - BOX[1]) < .064 - HALF))
        def first(mask):
            indices = np.flatnonzero(mask)
            return int(indices[0]) if len(indices) else None
        stable = np.convolve(bilateral.astype(int), np.ones(5, dtype=int), mode='valid') == 5
        grasp = first(stable)  # Start of the first 5-frame bilateral-contact interval.
        lift = first(lifted)
        held = first(lifted & bilateral)
        box = first(over_box)
        frame = np.arange(len(pos))
        before_box_after_held = np.zeros(len(pos), dtype=bool) if held is None else (
            (frame > held) & (frame < (box if box is not None else len(pos))))
        opening = first(before_box_after_held & (trace['raw_action'][:, 6] > .04))
        executed_opening = first(before_box_after_held & (trace['executed_command'][:, 6] > .04))
        lost_contact = first(before_box_after_held & ~bilateral)
        def elapsed(a, b):
            return None if a is None or b is None or b < a else (b - a) / 20
        return dict(first_reliable_grasp_frame=grasp, first_lifted_5cm_frame=lift,
            first_bilateral_lift_frame=held, first_over_box_frame=box,
            grasp_to_lift_seconds=elapsed(grasp, lift), held_to_box_seconds=elapsed(held, box),
            prebox_first_predicted_open_frame=opening, prebox_first_executed_open_frame=executed_opening,
            prebox_first_bilateral_contact_loss_frame=lost_contact,
            remaining_steps_at_box=None if box is None else 420 - box,
            remaining_40_step_budget_at_box=None if box is None else 420 - box >= 40,
            definitions=dict(grasp='both normal forces >0.05 N for 5 consecutive recorded frames; report interval start',
                lift='target height > block half-height +0.05 m', held='lift and bilateral contact',
                prebox_open='width command >0.04 m after first bilateral lift and before first over-box frame; descriptive event, not proof of cause',
                contact_loss='first loss of bilateral contact in same interval, not necessarily a drop',
                times='recorded pre-action frame /20; normal complete-task trajectory only'))


def evaluate(lane, port):
    tasks = read(CAMPAIGN / f'roster_lane{lane}.json')
    rows = []
    began = now()
    started = time.monotonic()
    for task in tasks:
        unit = CAMPAIGN / 'evaluations/H_500' / trial_id(task)
        done = unit / 'completed.json'
        if done.exists():
            rows.append(read(done))
            continue
        output = unit / ('attempt000_seed' + str(task['base_seed']))
        stem = output / ('layout_%05d_%s' % (task['layout'], task['target']))
        if not stem.with_suffix('.json').exists():
            sys.argv = ['evaluate_pi0_ef.py', '--mode', 'lora', '--model-family', 'pi0',
                '--split', task['split'], '--steps', '420', '--replan-steps', '5',
                '--seed', str(task['base_seed']), '--seed-scope', 'episode',
                '--layout-seeds', str(task['layout']), '--targets', task['target'],
                '--data', str(CAMPAIGN / 'evaluation_layouts'), '--output', str(output),
                '--checkpoint', str(CHECKPOINT), '--norm-stats', str(NORM),
                '--policy-host', '127.0.0.1', '--policy-port', str(port)]
            evaluator.main()
            protocol = read(output / 'protocol.json')
            protocol.update(source_revision=read(CAMPAIGN / 'contract.json')['implementation_commit'], lane=lane)
            save(output / 'protocol.json', protocol)
        row = outcome_metrics(task, stem)
        if row['error']:
            raise RuntimeError('Formal episode execution error: ' + str(stem))
        row['progression'] = progression(stem)
        row['episode_seed'] = task['base_seed'] + task['layout'] * 3 + COLORS.index(task['target'])
        save(done, row)
        rows.append(row)
        save(CAMPAIGN / f'evaluation_progress_lane{lane}.json', dict(lane=lane, completed=len(rows),
            expected=len(tasks), last=task, started_at=began, at_utc=now(), wall_seconds=time.monotonic() - started))
        print('FORMAL_EPISODE_COMPLETE', lane, len(rows), len(tasks), trial_id(task), row['success'], flush=True)
    save(CAMPAIGN / f'node_H_500_lane{lane}.json', dict(lane=lane, episodes=rows,
        started_at=began, finished_at=now(), wall_seconds=time.monotonic() - started))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--lane', type=int, choices=(0, 1), required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    evaluate(args.lane, args.port)
