"""Paired H/B and H/E findings from the 125 formal episodes."""
from collections import Counter
from statistics import median
from h_common import *


def compact(row):
    return {k: row.get(k) for k in ('split', 'layout', 'target', 'base_seed', 'slot', 'success', 'failure_stage')}


def summary(rows):
    result = dict(total=len(rows), successes=sum(r['success'] for r in rows))
    for label, field, values in (('by_color', 'target', COLORS), ('by_slot', 'slot', ('back', 'front_left', 'front_right'))):
        result[label] = {v: dict(total=sum(r[field] == v for r in rows),
            successes=sum(r[field] == v and r['success'] for r in rows)) for v in values}
    result['failure_stages'] = dict(Counter(r['failure_stage'] for r in rows if not r['success']))
    return result


def report():
    node = read(CAMPAIGN / 'node_H_500.json')
    hrows = node['episodes']
    b = read(CAMPAIGN / 'references/node_B.json')['episodes'] + read(CAMPAIGN / 'references/B_additional_sources.json')
    e = read(CAMPAIGN / 'references/node_E_500.json')['episodes']
    bm, em, hm = ({key(r): r for r in rows} for rows in (b, e, hrows))
    groups = ('development', 'validation', 'additional_sources')
    tables, pairs, progression = {}, {}, {}
    for group in groups:
        selected = [r for r in hrows if r['report_group'] == group]
        tables[group] = {'H': summary(selected), 'B': summary([bm[key(r)] for r in selected]),
                         'E': summary([em[key(r)] for r in selected if key(r) in em])}
        for label, reference in (('B', bm), ('E', em)):
            common = [r for r in selected if key(r) in reference]
            if not common:
                continue
            repaired = [compact(r) for r in common if r['success'] and not reference[key(r)]['success']]
            lost = [dict(task=compact(r), previous=compact(reference[key(r)]))
                    for r in common if not r['success'] and reference[key(r)]['success']]
            pairs.setdefault('H_vs_' + label, {})[group] = dict(total=len(common), repaired_count=len(repaired),
                lost_count=len(lost), repaired=repaired, lost=lost)
        p = {}
        for metric in ('grasp_to_lift_seconds', 'held_to_box_seconds', 'remaining_steps_at_box'):
            values = [r['progression'][metric] for r in selected if r['progression'][metric] is not None]
            p[metric] = dict(observed=len(values), median=median(values) if values else None)
        for metric in ('prebox_first_predicted_open_frame', 'prebox_first_executed_open_frame',
                       'prebox_first_bilateral_contact_loss_frame'):
            p[metric] = dict(episodes=sum(r['progression'][metric] is not None for r in selected),
                tasks=[compact(r) for r in selected if r['progression'][metric] is not None])
        progression[group] = p
    sources = []
    for task in read(CAMPAIGN / 'source_roster.json'):
        k = key(task)
        sources.append(dict(task=compact(hm[k]), B_success=bm[k]['success'],
            E_success=em[k]['success'] if k in em else None, H_success=hm[k]['success'],
            report_group=hm[k]['report_group'], progression=hm[k]['progression']))
    source_successes = sum(r['H_success'] for r in sources)
    keep = tables['validation']['H']['successes'] >= 72 and (
        tables['development']['H']['successes'] > 25 or source_successes > 0)
    decision = dict(retain_H_as_candidate=keep, official_model='B', H_source_successes=source_successes,
        criterion=read(CAMPAIGN / 'contract.json')['candidate_rule'],
        reason=('H达到验证工程选择线且相关自主完整任务有改善，保留为后续比较候选，B仍为正式模型。' if keep else
                '这套68/2000恢复混合、500更新配方未达到保留候选条件，本轮结束并保留B。'),
        automatic_continuation=False, new_independent_test_performed=False)
    save(CAMPAIGN / 'paired_comparison.json', pairs)
    save(CAMPAIGN / 'source_task_results.json', sources)
    save(CAMPAIGN / 'color_position_results.json', tables)
    save(CAMPAIGN / 'progression_summary.json', progression)
    save(CAMPAIGN / 'candidate_decision.json', decision)
    lines = ['# H500恢复数据对照结果', '', decision['reason'], '',
        'H从B累计4020的完整模型、optimizer与RNG分叉，沿用B原norm、E的可训练范围和upstream训练步骤。完成500更新，累计4520；batch4、常数1e-6、无新warmup，未使用G视觉置零。', '',
        'E前2000项中固定替换68项，1932项原位保留；替换来自68个不同原episode，三个区间为26/22/20，全部120个原episode保持覆盖。8条恢复后缀均含相对0与25，指定四条另含15。', '',
        '| 集合 | B复用 | E500复用 | H500 |', '|---|---:|---:|---:|']
    def score(item):
        return f"{item['successes']}/{item['total']}" if item['total'] else '未评测'
    for group in groups:
        lines.append('| ' + group + ' | ' + ' | '.join(score(tables[group][label]) for label in ('B', 'E', 'H')) + ' |')
    lines += ['', '48开发、75验证和2个补充来源分别报告；H/E配对仅123个共同任务，H/B为125个已匹配任务。8来源结果直接从本轮125项提取，未增加回合。', '',
              '## 配对修复与丢失', '', '| 配对 | 集合 | 修复 | 丢失 |', '|---|---|---|---|']
    def identity(row):
        return f"{row['layout']}/{row['target']}/{row['base_seed']}"
    for comparison, values in pairs.items():
        for group, data in values.items():
            repaired = '、'.join(identity(r) for r in data['repaired']) or '无'
            lost = '、'.join(identity(r['task']) + '(' + str(r['task']['failure_stage']) + ')' for r in data['lost']) or '无'
            lines.append(f"| {comparison} | {group} | {data['repaired_count']}：{repaired} | {data['lost_count']}：{lost} |")
    lines += ['', '## 八个训练来源', '', '| 任务 | 原位置 | B | E500 | H500 | H失败阶段 |', '|---|---|---|---|---|---|']
    def outcome(value):
        return '未评测' if value is None else ('成功' if value else '失败')
    for row in sources:
        lines.append('| ' + identity(row['task']) + ' | ' + row['task']['slot'] + ' | ' +
            ' | '.join(outcome(row[k]) for k in ('B_success', 'E_success', 'H_success')) + ' | ' + row['task']['failure_stage'] + ' |')
    lines += ['', '## 颜色与位置分项', '', '| 集合 | 分类 | B | E500 | H500 |', '|---|---|---:|---:|---:|']
    for group in groups:
        for category in ('by_color', 'by_slot'):
            for value in tables[group]['H'][category]:
                lines.append('| ' + group + ' | ' + value + ' | ' + ' | '.join(
                    score(tables[group][label][category][value]) for label in ('B', 'E', 'H')) + ' |')
    lines += ['', '## 完整任务中记录的动作进程', '',
        '抓稳定义为连续5帧双侧接触力均大于0.05 N；抬起定义为目标高于半块高度5 cm；时间来自20 Hz仿真帧。预测/执行开度超过0.04 m与失去双侧接触分别记录，事件本身不证明失败原因。逐任务帧号、到箱剩余步数和完整任务成败见紧凑JSON。', '',
        '| 集合 | 抓稳→抬起中位秒/有效数 | 持物→到箱中位秒/有效数 | 到箱剩余步数中位/有效数 | 箱前预测开爪/执行开爪/失去双侧接触 |',
        '|---|---|---|---|---|']
    for group, p in progression.items():
        values = [str(p[k]['median']) + '/' + str(p[k]['observed']) for k in
                  ('grasp_to_lift_seconds', 'held_to_box_seconds', 'remaining_steps_at_box')]
        events = '/'.join(str(p[k]['episodes']) for k in ('prebox_first_predicted_open_frame',
                         'prebox_first_executed_open_frame', 'prebox_first_bilateral_contact_loss_frame'))
        lines.append('| ' + group + ' | ' + ' | '.join(values) + ' | ' + events + ' |')
    timing = read(CAMPAIGN / 'evaluation_timing.json')
    lines += ['', '## 运行与结论范围', '',
        f"两路独立服务和worker按原名册偶/奇编号完成63/62项，总评测墙钟{timing['wall_seconds']:.1f}秒；逐路时间见evaluation_timing.json。每回合使用原身份种子，worker编号未参与seed。",
        '协议保持420步上限、连续40步成功、horizon10、replan5、20Hz、batch1推理与10次flow采样。无教师介入。',
        'H/E用于观察本次恢复数据混合相对同预算续训的变化；H/B用于判断候选完整能力。验证集已多轮参与选择，72/75是工程选择线；本轮不是新的独立泛化测试，单次阴性结果也不否定所有恢复数据方法。',
        '未重跑B/E/F/G，未使用3000–3009，未续训或扩评。所有大检查点、optimizer、完整视频与原始数组保留服务器，用户自行备份；本流程只推代码和小结果，不建立H大文件发布队列、不删除研究资料。']
    (CAMPAIGN / 'final_report_zh.md').write_text('\n'.join(lines) + '\n')
    return decision
