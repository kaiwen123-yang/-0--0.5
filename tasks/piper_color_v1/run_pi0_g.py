"""One G500 training run, gated full-task evaluation, then publication."""
import contextlib, os, shutil, signal, subprocess, time
import numpy as np
from g_common import *
from publish_pi0_g import publish
from run_pi0_ef import partition
ENTRY = ROOT / "scripts/run_pi0_g_d57.sh"

def prepare():
    input_ledger=ROOT/"publication"/TASK/"input_pending.json"
    record=read(input_ledger)
    record.update(status="restored",missing_bytes=0,received_bytes=sum(a["expected_bytes"] for g in record["groups"] for a in g["assets"]),at_utc=now(),temporary_volumes_deleted=True)
    for group in record["groups"]:
        group.update(complete_parts=group["total_parts"],expanded=True,temporary_volumes_deleted=True)
        for asset in group["assets"]:
            asset.update(received_bytes=asset["expected_bytes"],missing_bytes=0,status="restored_and_temporary_volume_removed")
    for name in ("new_training_updates","new_complete_tasks","G_checkpoint_created","G_results_available","new_layout_test_performed"):
        record.pop(name,None)
    save(input_ledger,record)
    for name in ("node_roster.json", "new_layout_roster.json"):
        shutil.copyfile(PREVIOUS/name, CAMPAIGN/name)
    (CAMPAIGN/"evaluation_layouts").mkdir(exist_ok=True)
    shutil.copyfile(PREVIOUS/"evaluation_layouts/manifest.json", CAMPAIGN/"evaluation_layouts/manifest.json")
    (CAMPAIGN/"G").mkdir(exist_ok=True)
    order = read(PREVIOUS/"E/sample_order.json")[:2000]
    save(CAMPAIGN/"G/sample_order.json", order)
    np.save(CAMPAIGN/"G/sample_order.npy", np.asarray(order,dtype=np.int64), allow_pickle=False)
    NORM.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(OLD/"assets"/ASSET/"norm_stats.json",NORM/"norm_stats.json")
    save(CAMPAIGN/"contract.json",dict(task=TASK, source_commit="c912dc5efbbec7dce53361fe989bf71eac0b2351",
        implementation_commit=git("rev-parse","HEAD"), source_checkpoint=str(OLD), source_cumulative_updates=4020,
        max_new_updates=500, final_cumulative_updates=4520, batch=4, learning_rate=1e-6,
        schedule=dict(warmup_steps=0,peak_lr=1e-6,decay_lr=1e-6,decay_steps=5020),
        train_rng_key_data=read(OLD/"resume.json")["train_rng_key_data"], rng_fold_in_steps=[4020,4519],
        sampler_source=str(PREVIOUS/"E/sample_order.json"), sampler_slice=[0,2000], sampler_operation="ordered format conversion",
        dataset="PiperDataset(v2, train, 10)", normalization_source=str(OLD/"assets"/ASSET/"norm_stats.json"),
        intervention="PaliGemma/img/.* final updates zeroed after tx.update before apply_updates",
        visual_gradients_and_optimizer_buffers="unchanged rule; retain full optimizer tree and original filter/dtype",
        horizon=10,replan=5,hz=20,max_steps=420,continuous_success_steps=40,
        initial_tasks=123,max_new_complete_tasks=435,
        reused_results={name:str(PREVIOUS/("node_"+name+".json")) for name in ("B","E_500","F_500")}))

def main():
    runfile=CAMPAIGN/"run.json"
    status=read(runfile) if runfile.exists() else dict(started_at=now(),completed=False,new_complete_tasks=0)
    if status.get("completed"):
        from deliver_pi0_g import deliver
        deliver()
        return
    def update(**kw):
        status.update(kw,at_utc=now())
        save(runfile,status)
    def execute(stage,*args,label,run=CAMPAIGN):
        log=CAMPAIGN/"logs"/(label+".log")
        update(stage=label,child_log=str(log))
        with log.open("a") as stream:
            proc=subprocess.Popen(["bash",str(ENTRY),stage,*map(str,args)],
                env=dict(os.environ,PIPER_COLOR_RUN=str(run)),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            update(child_pid=proc.pid)
            rc=proc.wait()
            update(child_pid=None)
            if rc: raise RuntimeError(label+" failed; "+str(log))
    @contextlib.contextmanager
    def service(checkpoint,label):
        log=CAMPAIGN/"logs"/("serve_"+label+".log")
        with log.open("a") as stream:
            proc=subprocess.Popen(["bash",str(ENTRY),"serve","--checkpoint",str(checkpoint),"--norm-stats",str(NORM)],
                env=dict(os.environ,PIPER_COLOR_RUN=str(CAMPAIGN/"G")),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            update(stage="loading_"+label,service_pid=proc.pid)
            try:
                while "MODEL_LOADED " not in log.read_text(errors="replace"):
                    if proc.poll() is not None: raise RuntimeError("Model service failed; "+str(log))
                    time.sleep(1)
                time.sleep(2)
                yield
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGTERM)
                    proc.wait()
                update(service_pid=None)
    def evaluate(label, roster_path, checkpoint):
        node=CAMPAIGN/("node_"+label+".json")
        if not node.exists():
            execute("worker","--label",label,"--roster",roster_path,"--checkpoint",checkpoint,label=label)
        status["new_complete_tasks"]=len(list((CAMPAIGN/"evaluations").glob("*/*/completed.json")))
        update(stage=label+"_complete")
        publish(label+"-complete")
        return read(node)
    try:
        update(stage="waiting_input_restore",error=None)
        while True:
            restored=read(CAMPAIGN/"input_restore.json")
            if restored.get("status")=="ready": break
            pending=[g for g,r in restored["groups"].items() if r["status"]=="pending"]
            if pending: raise RuntimeError("Required input restore pending: "+str(pending))
            time.sleep(10)
        if not (CAMPAIGN/"contract.json").exists(): prepare()
        publish("configuration")
        if not (CHECKPOINT/"resume.json").exists():
            upload_log=(CAMPAIGN/"logs/historical_upload.log").open("a")
            historical=subprocess.Popen([str(ROOT/"runtime/d57-color-sim/bin/python"),
                str(ROOT/"tasks/piper_color_v1/deliver_pi0_g.py"),"--history-only"],
                cwd=ROOT,stdout=upload_log,stderr=subprocess.STDOUT,start_new_session=True)
            upload_log.close()
            update(historical_upload_pid=historical.pid,history_upload="separate low-priority queue; see transfer progress")
            execute("train",label="train_G_500",run=CAMPAIGN/"G")
        training=read(CAMPAIGN/"G/lora_training.json")
        update(real_training_updates=training["local_updates"],optimizer_updates=training["optimizer_updates"],
               selection_reason="G500 evaluation is pending; B remains the current best")
        publish("G500-checkpoint")
        with service(CHECKPOINT,"G500"):
            g=evaluate("G_500",CAMPAIGN/"node_roster.json",CHECKPOINT)
        passed=g["summary"]["validation"]["successes"]>=72 and g["summary"]["train"]["back_successes"]>14
        save(CAMPAIGN/"development_decision.json",dict(qualified=passed,
            criterion="validation >=72/75 AND difficult rear >14/32",summary=g["summary"]))
        selected="B"
        reason="G开发门槛未通过，保留B并停止本轮路线"
        test=dict(performed=False,reason="G开发门槛未通过")
        if passed:
            save(CAMPAIGN/"candidate_freeze.json",dict(at_utc=now(),candidate="G500",checkpoint=str(CHECKPOINT),
                optimizer_updates=4520,training_finished=True,new_test_seen=False))
            publish("G500-frozen")
            seen={key(r) for r in g["episodes"] if r["split"]=="train"}
            missing=[r for r in roster("train",range(100,140),(42,43)) if key(r) not in seen]
            save(CAMPAIGN/"candidate_coverage_roster.json",missing)
            with service(CHECKPOINT,"coverage"):
                extra=evaluate("candidate_coverage",CAMPAIGN/"candidate_coverage_roster.json",CHECKPOINT)
            full=[r for r in g["episodes"] if r["split"]=="train"]+extra["episodes"]
            coverage=dict(summary=partition(full),episodes=full)
            save(CAMPAIGN/"candidate_coverage.json",coverage)
            if coverage["summary"]["train"]["successes"]>=211:
                publish("coverage-qualified-before-new-test")
                for label,ckpt in (("new_layout_G",CHECKPOINT),("new_layout_B",OLD)):
                    with service(ckpt,label):
                        evaluate(label,CAMPAIGN/"new_layout_roster.json",ckpt)
                gs=read(CAMPAIGN/"node_new_layout_G.json")["summary"]["test"]["successes"]
                bs=read(CAMPAIGN/"node_new_layout_B.json")["summary"]["test"]["successes"]
                test=dict(performed=True,layouts=list(range(3000,3010)),B_successes=bs,G_successes=gs,total_per_model=60,
                    no_post_test_tuning=True)
                if gs>bs:
                    selected="G500";reason="开发和全训练达到门槛，冻结后新布局成绩高于B"
                elif gs==bs:
                    reason="新布局本次成绩相当，保留B；不将相同成绩称为新的最佳"
                else:
                    reason="新布局未改善，保留B"
            else:
                test=dict(performed=False,reason="G全训练低于211/240")
                reason="G全训练低于211/240，保留B并停止"
        save(CAMPAIGN/"new_layout_comparison.json",test)
        update(stage="experiment_complete",completed=True,selected_candidate=selected,selection_reason=reason,finished_at=now(),
            real_training_updates=500,optimizer_updates=4520)
        from report_pi0_g import report
        report()
        publish("experiment-complete")
        from deliver_pi0_g import deliver
        deliver()
    except Exception as exc:
        update(stage="pending" if "restore pending" in str(exc) else "failed_requires_inspection",error=str(exc))
        publish("interrupted")
        raise

if __name__=="__main__":
    main()
