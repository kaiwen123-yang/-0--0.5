"""Finish the already-running I task's compact analysis and Git delivery only."""
import time
from i_common import *
from report_pi0_i import report
from publish_pi0_i import publish


def main():
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        status = read(CAMPAIGN/'run.json')
        if status['stage'] == 'failed_requires_inspection':
            save(CAMPAIGN/'background_finalization.json',dict(status='parent_failed_no_restart',
                at_utc=now(),error=status.get('error'),new_training_or_evaluation_started=False))
            publish('parent-failure-retained')
            return
        receipt = read(CAMPAIGN/'publication_delivery.json')
        if status.get('completed') and receipt.get('stage') == 'final-status':
            break
        time.sleep(10)
    else:
        save(CAMPAIGN/'background_finalization.json',dict(status='waiting_deadline_reached_no_interruption',
            at_utc=now(),new_training_or_evaluation_started=False))
        publish('background-wait-deadline')
        return
    decision = report()
    tables = read(CAMPAIGN/'color_position_results.json')
    counts = {g:tables[g]['I'] for g in ('development','validation','additional_sources')}
    status = read(CAMPAIGN/'run.json')
    status.update(retain_I_as_candidate=decision['retain_I_as_candidate'],official_model='B',
        final_analysis_at_utc=now(),final_analysis_includes_all_27_changed_windows=True)
    save(CAMPAIGN/'run.json',status)
    message = (f"I500已完成500更新、125项正式评测：开发{counts['development']['successes']}/48、"
        f"验证{counts['validation']['successes']}/75、补充{counts['additional_sources']['successes']}/2、"
        f"八来源{decision['I_source_successes']}/8；B继续正式。")
    agents = ROOT/'AGENTS.md'
    agents.write_text('## 2026-11-04 I500完成后的当前状态\n\n- '+message+'\n'
        '- 唯一I已结束，不重跑、不续I/H1000、不扩评。结果见 results/piper-color-v1/pi0-i500-rotation-20261104/final_report_zh.md。\n'
        '- 本轮仅教师姿态衔接修正：三条新版后缀450帧、其余750帧复用，原H采样不动。原版本与全部研究资料保留服务器，小结果入Git；大产物无新增队列。\n'
        '- 115后续窗口仍有大尺度动作；不能仅凭更新33下降宣称数值问题全消失。416仍为跨实验共有尖峰，不归罪113。\n\n'+agents.read_text())
    doc=ROOT/'docs/PI0_I500_ROTATION_EXECUTION_20261104.md'
    doc.write_text(doc.read_text()+'\n## 本轮实际完成结果\n\n'+message+'\n\n'+decision['reason']+'\n')
    save(CAMPAIGN/'background_finalization.json',dict(status='analysis_complete_publication_in_progress',
        at_utc=now(),new_training_or_evaluation_started=False,summary=message))
    delivered=publish('complete-numerical-and-temporal-analysis')
    save(CAMPAIGN/'background_finalization.json',dict(status='pushed' if delivered else 'push_pending',
        at_utc=now(),new_training_or_evaluation_started=False,summary=message))
    publish('final-handoff-status')
    print(message,flush=True)

if __name__=='__main__':
    main()
