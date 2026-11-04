"""Explain the completed H episodes from existing compact JSON; no rollout or array reads."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'results/piper-color-v1/pi0-h500-recovery-20261103'
OUT = ROOT / 'results/piper-color-v1/pi0-h-numeric-review-20261104'

LABELS = {
    'contact_without_lift': '已记录连续双侧接触，未抬高5cm',
    'lift_without_box': '已抬起，始终未到箱上',
    'box_with_less_than_40_steps': '到箱上余步少于40',
    'box_with_exactly_40_steps': '到箱上恰剩40步',
    'box_with_more_than_40_steps': '到箱上余步超过40，仍未完整成功',
}


def identity(row):
    return (row['split'], row['layout'], row['target'], row['base_seed'])


def task_name(row):
    return f"{row['layout']}/{row['target']}/{row['base_seed']}"


def category(row):
    p = row['progression']
    if p['first_lifted_5cm_frame'] is None:
        return 'contact_without_lift'
    if p['first_over_box_frame'] is None:
        return 'lift_without_box'
    if p['remaining_steps_at_box'] < 40:
        return 'box_with_less_than_40_steps'
    if p['remaining_steps_at_box'] == 40:
        return 'box_with_exactly_40_steps'
    return 'box_with_more_than_40_steps'


def describe(row, result):
    p = row['progression']
    d = result['diagnostics']
    if p['first_lifted_5cm_frame'] is None:
        text = (f"第{p['first_reliable_grasp_frame']}帧为首个连续5帧双侧接触区间起点；"
                f"累计{d['bilateral_contact_frames']}帧双侧接触，但目标未高于半块高度5cm。"
                '旧标签不能被解释为从未接触或从未抓到。')
    elif p['first_over_box_frame'] is None:
        text = (f"第{p['first_bilateral_lift_frame']}帧已同时满足抬高与双侧接触，"
                f"到420步结束始终未记录到箱上；接触区间起点至首次抬起为{p['grasp_to_lift_seconds']:g}秒。")
    else:
        text = (f"第{p['first_bilateral_lift_frame']}帧持物，第{p['first_over_box_frame']}帧首次到箱上，"
                f"剩{p['remaining_steps_at_box']}步；持物至到箱耗时{p['held_to_box_seconds']:g}秒。")
        if p['remaining_steps_at_box'] < 40:
            text += '到箱已不足连续40步的稳定计时预算，不能仅凭旧标签归因为释放控制。'
        elif p['remaining_steps_at_box'] == 40:
            text += '到箱只留下40步，无额外下降/释放余量；最终仍未入箱或开爪。'
        else:
            text += '首次到箱时理论余步超过40，但到箱不是完整成功条件。'
    if identity(row) == ('validation', 1003, 'green', 43):
        text += ('第105帧首次失去双侧接触，第107帧记录目标回落至低于半块高度1cm；'
                 '第292帧才出现超过0.04m的预测/执行开爪，掉落前大开爪命令为0帧。'
                 '这排除了“该次已记录的大开爪先于掉落”的解释，未确定最初失去接触的原因。')
    if identity(row) == ('train', 102, 'blue', 43):
        text += ('终态correct_in_box=true、gripper_open=true、wrong_in_box=false，'
                 '红/绿扰动物位移均为0、最大关节越界0，但stable_2s=false。'
                 '因此旧stability_or_distractor标签不能写成碰撞扰动物；未累计40步稳定成功。'
                 '紧凑JSON未保存最终连续成功计数，不能据此给出缺少的确切帧数。')
    if identity(row) == ('validation', 1003, 'blue', 44):
        text += ('虽然首次到箱余72步，累计到箱仅13帧；终态仍未入箱、未开爪。'
                 '不能把72步余量误作72帧持续在箱上或稳定成功。')
    return text


def display(value):
    return '未记录' if value is None else str(value)


def main():
    node = json.loads((SOURCE / 'node_H_500.json').read_text())
    sources = json.loads((SOURCE / 'source_task_results.json').read_text())
    failures = []
    for row in node['episodes']:
        if row['success']:
            continue
        result_path = Path(row['result_json'])
        result = json.loads(result_path.read_text())
        diagnostic = result['diagnostics']
        record = {k: row[k] for k in ('split', 'layout', 'target', 'base_seed', 'episode_seed', 'report_group', 'slot')}
        record.update(success=False, original_failure_stage=row['failure_stage'],
                      temporal_category=category(row), progression=row['progression'],
                      total_preaction_records=row['frames'],
                      bilateral_contact_frames=diagnostic['bilateral_contact_frames'],
                      over_box_frames=row['over_box_frames'], drop_frame=diagnostic['drop_frame'],
                      gripper_open_command_frames_before_drop=diagnostic['gripper_open_command_frames_before_drop'],
                      terminal={k: result[k] for k in ('steps', 'success', 'stable_2s', 'correct_in_box',
                          'wrong_in_box', 'gripper_open', 'distractor_displacement_m',
                          'max_joint_violation_rad', 'error')},
                      source_result_json=str(result_path.relative_to(ROOT)),
                      published_result_json=str(Path('results/piper-color-v1/pi0-h500-recovery-20261103') /
                                                result_path.relative_to(ROOT / 'outputs/pi0-h500-recovery-20261103')),
                      explanation_zh=describe(row, result))
        failures.append(record)
    source_rows = []
    failure_map = {identity(row): row for row in failures}
    for item in sources:
        row = item['task']
        source_rows.append(dict(task=row, B_success=item['B_success'], E_success=item['E_success'],
            H_success=item['H_success'], report_group=item['report_group'], progression=item['progression'],
            temporal_explanation_zh=(failure_map[identity(row)]['explanation_zh'] if not item['H_success'] else
               ('H完整成功；E也已成功，不能把该例全部归为H新增收益。' if item['E_success'] else
                'H完整成功；E该例失败，这是八来源中相对E的新增修复。' if item['E_success'] is False else
                'H完整成功；E未评测，保留缺失对照。'))))
    counts = Counter(row['temporal_category'] for row in failures)
    common = [row for row in source_rows if row['E_success'] is not None]
    payload = dict(
        source_revision='3dd547a169c7a821fabd278af3b86a1f3d099b95',
        source_node='results/piper-color-v1/pi0-h500-recovery-20261103/node_H_500.json',
        source_source_results='results/piper-color-v1/pi0-h500-recovery-20261103/source_task_results.json',
        scope='Existing compact JSON only; no NPZ reads, policy forward, simulation, training, or tests.',
        definitions=dict(
            frame='Zero-based pre-action record index; frame n is at n/20 seconds before action n.',
            steps='Terminal steps=420 is a count of executed actions, not the final pre-action index (419).',
            grasp='Start of the first 5-record interval with both normal forces >0.05 N; known retrospectively after n+4.',
            lift='Target z - block half-height >0.05 m; held additionally requires bilateral contact.',
            over_box='Target XY within box interior bounds; no height, release, or stability requirement.',
            remaining='420 - first_over_box_frame; theoretical action budget, not stable-success dwell time.',
            success='Original post-action complete-task condition for 40 consecutive steps; unchanged.',
            drop='Existing diagnostic: first height < HALF+0.01 after the maximum, with prior >5cm lift and no over-box frame.',
            contact_loss='First loss of bilateral contact after first held frame and before first box frame; not by itself a drop.'),
        counts=dict(total_formal_tasks=node['total'], failures=len(failures),
                    by_temporal_category={k: counts[k] for k in LABELS},
                    original_failure_stage=dict(Counter(row['original_failure_stage'] for row in failures)),
                    by_group=dict(Counter(row['report_group'] for row in failures))),
        failures=failures, eight_sources=source_rows,
        source_summary=dict(H_successes=sum(row['H_success'] for row in source_rows), total=len(source_rows),
                            E_common_total=len(common), E_common_successes=sum(row['E_success'] for row in common),
                            H_common_successes=sum(row['H_success'] for row in common)),
        limits=['Descriptions explain existing outcomes and do not establish the cause of H training loss.',
                'Compact JSON lacks per-step success-counter history; exact missing stable frames are not inferred.',
                'No old outcome, failure label, success threshold, or original artifact was edited.'])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'failure_timing.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    lines = ['# H500已有失败时序复核', '',
        'H原125项中21项失败：开发11、验证10。以下复用已保存JSON，原success与粗failure_stage保持；新增时序解释不改成绩。', '',
        '帧号为0起始的动作前记录，n帧时间为n/20秒；420是已执行动作数，最后动作前帧为419。抓稳帧是首个连续5帧双侧接触区间的起点，不是在线判据在起点已获知未来4帧。到箱仅是XY范围满足，不等于入箱、释放或开始稳定计时。', '',
        '| 时序观察 | 数量 |', '|---|---:|']
    lines += [f'| {LABELS[k]} | {counts[k]} |' for k in LABELS]
    lines += ['', '## 21例逐项事实', '',
              '| 集合/任务 | 原标签 | 接触区间起点 | 抬高/持物 | 到箱 | 余步 | 双侧接触累计 | 终态入箱/开爪/稳定 |',
              '|---|---|---:|---|---:|---:|---:|---|']
    for row in failures:
        p,t = row['progression'],row['terminal']
        lines.append(f"| {row['report_group']} {task_name(row)} | {row['original_failure_stage']} | "
                     f"{display(p['first_reliable_grasp_frame'])} | "
                     f"{display(p['first_lifted_5cm_frame'])}/{display(p['first_bilateral_lift_frame'])} | "
                     f"{display(p['first_over_box_frame'])} | {display(p['remaining_steps_at_box'])} | "
                     f"{row['bilateral_contact_frames']} | {t['correct_in_box']}/{t['gripper_open']}/{t['stable_2s']} |")
    lines += ['', '## 与旧宽标签不同的具体解释', '']
    for row in failures:
        url = ('https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/'
               + row['published_result_json'])
        lines += [f"- **{row['report_group']} {task_name(row)}**：{row['explanation_zh']} [原回合JSON]({url})", '']
    lines += ['## 八个恢复来源', '',
              '| 任务 | B | E | H | H接触/持物/到箱帧 |', '|---|---|---|---|---|']
    def result(value):
        return '未评' if value is None else '成功' if value else '失败'
    for row in source_rows:
        p=row['progression']
        lines.append(f"| {task_name(row['task'])} | {result(row['B_success'])} | {result(row['E_success'])} | "
                     f"{result(row['H_success'])} | {display(p['first_reliable_grasp_frame'])}/"
                     f"{display(p['first_bilateral_lift_frame'])}/{display(p['first_over_box_frame'])} |")
    lines += ['', 'H为5/8；有E对照的六例是E2/6、H3/6，只有113/red/42是H相对E新增成功。'
              '109/red/42与115/green/43在E已成功，120/blue/43与139/red/42没有E结果。教师恢复8/8不计入这些自主成绩。', '',
              '本表只解释已记录事件，不把训练监督异常直接写成这些失败的已证原因；未新增回合、训练、VLA前向、NPZ扫描或测试。'
              '102/blue/43的具体连续成功帧数不在紧凑JSON中，保留为未知。', '']
    (OUT / 'failure_timing_zh.md').write_text('\n'.join(lines))
    print(json.dumps({'counts':payload['counts'], 'source_summary':payload['source_summary'],
                      'outputs':['failure_timing.json','failure_timing_zh.md']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
