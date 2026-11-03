"""One H500, two independent evaluation lanes, one merge and publication flow."""
import fcntl, os, signal, subprocess, time
from h_common import *
from prepare_pi0_h import prepare_training, prepare_evaluation
from publish_pi0_h import publish
from report_pi0_h import report, summary


def main():
    lock = (ROOT / 'runtime' / (TASK + '.lock')).open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    (CAMPAIGN / 'logs').mkdir(exist_ok=True)
    runfile = CAMPAIGN / 'run.json'
    status = read(runfile) if runfile.exists() else dict(started_at=now(), completed=False, new_complete_tasks=0)
    if status.get('completed'):
        return
    created = []
    def update(**values):
        status.update(values, at_utc=now())
        save(runfile, status)
    def launch(stage, cpus, label, *args):
        log = CAMPAIGN / 'logs' / (label + '.log')
        with log.open('a') as stream:
            proc = subprocess.Popen(['bash', str(ENTRY), stage, *map(str, args)], cwd=ROOT,
                env=dict(os.environ, H_CPUSET=','.join(map(str, cpus))), stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True)
        created.append(proc)
        return proc, log
    def close_service(proc):
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
    try:
        update(stage='recording_formal_inputs', error=None)
        if not (CAMPAIGN / 'contract.json').exists():
            prepare_training()
        resources = read(CAMPAIGN / 'resources.json')
        if not (CHECKPOINT / 'resume.json').exists():
            if (CAMPAIGN / 'H/lora_metrics.jsonl').exists():
                raise RuntimeError('H has partial updates without a completed H500; do not restart or add updates automatically')
            train, log = launch('train', resources['training_cpus'], 'train_H500')
            update(stage='training_H500', training_pid=train.pid, training_log=str(log))
            prepare_evaluation()  # CPU-only roster/reference work overlaps real H training.
            publish('formal-configuration-and-sampling')
            code = train.wait()
            update(training_pid=None, training_exit=code)
            if code:
                raise RuntimeError('Formal H training failed; ' + str(log))
        elif not (CAMPAIGN / 'node_roster.json').exists():
            prepare_evaluation()
        training = read(CAMPAIGN / 'H/lora_training.json')
        if not training['segment_complete']:
            raise RuntimeError('H500 complete save not recorded')
        update(stage='H500_saved_loading_two_services', real_training_updates=training['local_updates'],
               optimizer_updates=training['optimizer_updates'])
        publish('H500-complete-save')
        evaluation_start = time.monotonic()
        evaluation_started_at = now()
        lanes = []
        for lane in resources['lanes']:
            service, log = launch('serve', lane['service_cpus'], f"serve_lane{lane['lane']}", '--port', lane['port'])
            lanes.append(dict(**lane, service=service, service_log=log, worker=None, finished=False,
                              service_started_at=now(), load_deadline=time.monotonic() + 900))
        update(stage='parallel_formal_evaluation', service_pids=[r['service'].pid for r in lanes],
               evaluation_started_at=evaluation_started_at)
        while not all(r['finished'] for r in lanes):
            for lane in lanes:
                if lane['finished']:
                    continue
                service = lane['service']
                if lane['worker'] is None:
                    if service.poll() is not None or time.monotonic() > lane['load_deadline']:
                        raise RuntimeError('H service failed to load: ' + str(lane['service_log']))
                    if 'server listening on' in lane['service_log'].read_text(errors='replace'):
                        worker, log = launch('worker', lane['worker_cpus'], f"worker_lane{lane['lane']}",
                            '--lane', lane['lane'], '--port', lane['port'])
                        lane.update(worker=worker, worker_log=log, worker_started_at=now())
                        update(worker_pids=[r['worker'].pid if r['worker'] else None for r in lanes])
                else:
                    code = lane['worker'].poll()
                    if code is not None:
                        lane.update(finished=True, worker_exit=code, finished_at=now())
                        close_service(service)
                    elif service.poll() is not None:
                        raise RuntimeError('H service exited during a formal lane')
            progress = []
            for lane in lanes:
                path = CAMPAIGN / f"evaluation_progress_lane{lane['lane']}.json"
                progress.append(read(path) if path.exists() else dict(lane=lane['lane'], completed=0, expected=63-lane['lane']))
            update(new_complete_tasks=sum(r['completed'] for r in progress), lanes=progress)
            if not all(r['finished'] for r in lanes):
                time.sleep(5)
        if any(r['worker_exit'] != 0 for r in lanes):
            raise RuntimeError('A formal evaluation lane failed; completed records retained, no automatic reruns')
        shards = [read(CAMPAIGN / f'node_H_500_lane{lane}.json') for lane in (0, 1)]
        by_task = {key(row): row for shard in shards for row in shard['episodes']}
        rows = [by_task[key(task)] for task in read(CAMPAIGN / 'node_roster.json')]
        save(CAMPAIGN / 'node_H_500.json', dict(label='H_500', total=len(rows),
            summary={group: summary([r for r in rows if r['report_group'] == group])
                     for group in ('development', 'validation', 'additional_sources')}, episodes=rows))
        save(CAMPAIGN / 'evaluation_timing.json', dict(started_at=evaluation_started_at, finished_at=now(),
            wall_seconds=time.monotonic() - evaluation_start,
            lanes=[dict(lane=r['lane'], total=len(shard['episodes']), port=r['port'],
                service_cpus=r['service_cpus'], worker_cpus=r['worker_cpus'],
                service_started_at=r['service_started_at'], worker_started_at=r['worker_started_at'],
                finished_at=r['finished_at'], worker_wall_seconds=shard['wall_seconds']) for r, shard in zip(lanes, shards)]))
        decision = report()
        update(stage='experiment_complete', completed=True, finished_at=now(), new_complete_tasks=len(rows),
            retain_H_as_candidate=decision['retain_H_as_candidate'], official_model='B',
            large_artifacts='server_retained_no_H_release_queue')
        delivered = publish('final-125-tasks-paired-analysis')
        update(stage='complete' if delivered else 'complete_small_results_push_pending',
               publication_status='pushed' if delivered else 'pending')
        # Include the final status and preceding push receipt in the remote result snapshot.
        publish('final-status')
    except BaseException as exc:
        update(stage='failed_requires_inspection', error=repr(exc))
        publish('interrupted-records-retained')
        raise
    finally:
        for proc in created:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait()

if __name__ == '__main__':
    main()
