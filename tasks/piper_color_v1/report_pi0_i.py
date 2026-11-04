"""Report the single I500 teacher-rotation contrast from its completed formal records."""
from collections import Counter
from datetime import datetime
from statistics import median
from i_common import *

GROUPS = ('development', 'validation', 'additional_sources')
MODEL_ORDER = ('I', 'H', 'E', 'B')
H_RESULTS = ROOT / 'results/piper-color-v1/pi0-h500-recovery-20261103'
E_RESULTS = ROOT / 'results/piper-color-v1/pi0-ef-local-20261102'


def compact(row):
    return {k: row.get(k) for k in ('split', 'layout', 'target', 'base_seed', 'slot', 'success', 'failure_stage')}


def summary(rows):
    result = dict(total=len(rows), successes=sum(r['success'] for r in rows))
    for label, field, values in (('by_color', 'target', COLORS),
                                 ('by_slot', 'slot', ('back', 'front_left', 'front_right'))):
        result[label] = {v: dict(total=sum(r[field] == v for r in rows),
            successes=sum(r[field] == v and r['success'] for r in rows)) for v in values}
    result['failure_stages'] = dict(Counter(r['failure_stage'] for r in rows if not r['success']))
    return result


def pairing(current, reference):
    common = [r for r in current if key(r) in reference]
    repaired = [dict(task=compact(r), previous=compact(reference[key(r)]))
                for r in common if r['success'] and not reference[key(r)]['success']]
    lost = [dict(task=compact(r), previous=compact(reference[key(r)]))
            for r in common if not r['success'] and reference[key(r)]['success']]
    return dict(total=len(common), I_successes=sum(r['success'] for r in common),
        reference_successes=sum(reference[key(r)]['success'] for r in common),
        repaired_count=len(repaired), lost_count=len(lost), net_change=len(repaired)-len(lost),
        repaired=repaired, lost=lost)


def temporal_category(row):
    p = row['progression']
    if p['first_lifted_5cm_frame'] is None:
        return ('no_sustained_contact_or_lift' if p['first_reliable_grasp_frame'] is None
                else 'contact_without_lift')
    if p['first_over_box_frame'] is None:
        return 'lift_without_box'
    if p['remaining_steps_at_box'] < 40:
        return 'box_with_less_than_40_steps'
    if p['remaining_steps_at_box'] == 40:
        return 'box_with_exactly_40_steps'
    return 'box_with_more_than_40_steps'


def score(item):
    return f"{item['successes']}/{item['total']}" if item['total'] else '未评'


def identity(row):
    return f"{row['layout']}/{row['target']}/{row['base_seed']}"


def show(value):
    return '未记录' if value is None else str(value)


def report():
    node = read(CAMPAIGN / 'node_I_500.json')
    rows = node['episodes']
    references = {
        'B': read(CAMPAIGN / 'references/node_B.json')['episodes'] +
             read(CAMPAIGN / 'references/B_additional_sources.json'),
        'E': read(CAMPAIGN / 'references/node_E_500.json')['episodes'],
        'H': read(CAMPAIGN / 'references/node_H_500.json')['episodes'],
    }
    maps = {label: {key(r): r for r in items} for label, items in references.items()}
    maps['I'] = {key(r): r for r in rows}
    tables, pairs, progression = {}, {}, {}
    for group in GROUPS:
        selected = [r for r in rows if r['report_group'] == group]
        tables[group] = {label: summary([maps[label][key(r)] for r in selected if key(r) in maps[label]])
                         for label in MODEL_ORDER}
        for label in ('H', 'E', 'B'):
            pairs.setdefault('I_vs_' + label, {})[group] = pairing(selected, maps[label])
        p = {}
        for metric in ('grasp_to_lift_seconds', 'held_to_box_seconds', 'remaining_steps_at_box'):
            values = [r['progression'][metric] for r in selected if r['progression'][metric] is not None]
            p[metric] = dict(observed=len(values), median=median(values) if values else None)
        for metric in ('prebox_first_predicted_open_frame', 'prebox_first_executed_open_frame',
                       'prebox_first_bilateral_contact_loss_frame'):
            p[metric] = dict(episodes=sum(r['progression'][metric] is not None for r in selected),
                tasks=[compact(r) for r in selected if r['progression'][metric] is not None])
        progression[group] = p
    for label in ('H', 'E', 'B'):
        pairs['I_vs_' + label]['original_123'] = pairing(
            [r for r in rows if r['report_group'] != 'additional_sources'], maps[label])
        pairs['I_vs_' + label]['all_available_common'] = pairing(rows, maps[label])

    sources = []
    for task in read(CAMPAIGN / 'source_roster.json'):
        k = key(task)
        current = maps['I'][k]
        sources.append(dict(task=compact(current), report_group=current['report_group'],
            **{label + '_success': maps[label][k]['success'] if k in maps[label] else None
               for label in MODEL_ORDER}, progression=current['progression'],
            H_progression=maps['H'][k]['progression']))
    source_successes = sum(r['I_success'] for r in sources)
    source_B_successes = sum(r['B_success'] for r in sources)
    benefit = (tables['development']['I']['successes'] > tables['development']['B']['successes'] or
               source_successes > source_B_successes)
    keep = tables['validation']['I']['successes'] >= 72 and benefit
    contract = read(CAMPAIGN / 'contract.json')
    sampler = read(CAMPAIGN / 'I/sampler.json')
    training = read(CAMPAIGN / 'I/lora_training.json')
    evaluation = read(CAMPAIGN / 'evaluation_timing.json')
    run = read(CAMPAIGN / 'run.json')
    decision = dict(retain_I_as_candidate=keep, official_model='B',
        I_validation_successes=tables['validation']['I']['successes'],
        I_development_successes=tables['development']['I']['successes'],
        I_source_successes=source_successes, B_source_successes=source_B_successes,
        related_complete_task_benefit_over_B=benefit, criterion=contract['candidate_rule'],
        reason=('I达到验证工程选择线且相关完整任务相对B有改善，保留为候选；B继续正式。' if keep else
                '本次教师姿态衔接修正的I500未达到候选保留条件；B继续正式，本轮结束。'),
        automatic_continuation=False, new_independent_test_performed=False,
        scope='Only teacher rotation transition changes; original H order and B coordinates retained.')

    fine = {}
    combinations = (('by_layout', ('layout',)), ('by_color_slot', ('target', 'slot')),
                    ('by_color_slot_layout', ('target', 'slot', 'layout')))
    for group in GROUPS:
        selected = [r for r in rows if r['report_group'] == group]
        fine[group] = {}
        for category, fields in combinations:
            entries = []
            for values in sorted({tuple(r[f] for f in fields) for r in selected}):
                subset = [r for r in selected if tuple(r[f] for f in fields) == values]
                entries.append(dict(**dict(zip(fields, values)),
                    models={label: summary([maps[label][key(r)] for r in subset if key(r) in maps[label]])
                            for label in MODEL_ORDER},
                    paired={label: pairing(subset, maps[label]) for label in ('H', 'E', 'B')}))
            fine[group][category] = entries

    failures = []
    for row in rows:
        if row['success']:
            continue
        result = read(row['result_json'])
        d = result['diagnostics']
        p = row['progression']
        category = temporal_category(row)
        facts = [f"接触区间起点{show(p['first_reliable_grasp_frame'])}，抬高{show(p['first_lifted_5cm_frame'])}，"
                 f"双侧持物{show(p['first_bilateral_lift_frame'])}，到箱{show(p['first_over_box_frame'])}，"
                 f"到箱余步{show(p['remaining_steps_at_box'])}。"]
        if category == 'contact_without_lift':
            facts.append('已有连续双侧接触，旧approach_or_grasp不能解释为从未抓到。')
        elif category == 'box_with_less_than_40_steps':
            facts.append('首次到箱已不足40步稳定计时预算，不能仅凭旧标签归因为释放控制。')
        elif category == 'box_with_exactly_40_steps':
            facts.append('首次到箱只留下40步；到箱条件未包含下降、释放和稳定。')
        if d['drop_frame'] is not None:
            opening = p['prebox_first_executed_open_frame']
            facts.append(f"既有诊断掉落帧{d['drop_frame']}；掉落前大开爪命令"
                         f"{show(d['gripper_open_command_frames_before_drop'])}帧；"
                         f"箱前首次执行大开爪{show(opening)}。")
            if opening is not None and opening > d['drop_frame']:
                facts.append('该次大开爪晚于掉落，不能把这次开爪写成先行原因。')
        if result['correct_in_box'] and result['gripper_open'] and not result['stable_2s']:
            facts.append('终态入箱且开爪，但未累计40步连续成功；JSON无最终连续计数，不推断具体缺几帧。')
        failures.append(dict(task=compact(row), report_group=row['report_group'],
            original_failure_stage=row['failure_stage'], temporal_category=category, progression=p,
            bilateral_contact_frames=d['bilateral_contact_frames'], over_box_frames=row['over_box_frames'],
            drop_frame=d['drop_frame'],
            gripper_open_command_frames_before_drop=d['gripper_open_command_frames_before_drop'],
            terminal={k: result[k] for k in ('steps', 'success', 'stable_2s', 'correct_in_box',
                'wrong_in_box', 'gripper_open', 'distractor_displacement_m', 'max_joint_violation_rad', 'error')},
            result_json=row['result_json'], explanation_zh=''.join(facts)))

    # Read recorded scalar logs only. These are actual batch means, not per-sample causal assignments.
    import json
    batch_comparison = {}
    scalar_summary = {}
    corrected_names = {r['directory'] for r in contract['corrected_recovery_sources']}
    tracked_updates = {19,33,48,416} | {r['update'] for r in sampler['replacements'] if r['suffix'] in corrected_names}
    for label, path in (('I', CAMPAIGN / 'I/lora_metrics.jsonl'),
                        ('H', H_RESULTS / 'H/lora_metrics.jsonl'),
                        ('E', E_RESULTS / 'E/lora_metrics.jsonl')):
        metrics = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        recovery_updates = {r['update'] for r in sampler['replacements']}
        changed_updates = {r['update'] for r in sampler['replacements'] if r['suffix'] in corrected_names}
        def scalar_group(selected):
            losses = [r['loss'] for r in selected]
            return dict(batches=len(selected), loss_median=median(losses), loss_sum=sum(losses),
                loss_mean=sum(losses)/len(losses), max_loss=max(losses),
                top_five=[{k:r[k] for k in ('local_update','loss','grad_norm','sample_indices')}
                          for r in sorted(selected,key=lambda r:r['loss'],reverse=True)[:5]])
        scalar_summary[label] = {name:scalar_group([r for r in metrics if predicate(r['local_update'])])
            for name,predicate in [('all',lambda u:True),('H_pure_original_batch_positions',lambda u:u not in recovery_updates),
                ('H_mixed_batch_positions',lambda u:u in recovery_updates),
                ('changed_recovery_batch_positions',lambda u:u in changed_updates),
                ('unchanged_recovery_batch_positions',lambda u:u in recovery_updates and u not in changed_updates)]}
        if label=='I':
            observed=[index for r in metrics for index in r['sample_indices']]
            planned=read(CAMPAIGN/'I/sample_order.json')
            h_order=read(H_RESULTS/'H/sample_order.json')
            scalar_summary['actual_sampling']=dict(recorded_batches=len(metrics),recorded_samples=len(observed),
                actual_matches_recorded_I_order=observed==planned, actual_matches_H_order=observed==h_order,
                original_samples=sum(i<32160 for i in observed),recovery_samples=sum(i>=32160 for i in observed),
                changed_recovery_batch_positions=sorted(changed_updates),
                observation='Index equality preserves order; the specified three underlying recovery trajectories have changed.')
        batch_comparison[label] = [{k: item.get(k) for k in ('local_update', 'loss', 'grad_norm',
            'sample_indices', 'sample_components', 'rng_fold_in_step')}
            for item in metrics if item['local_update'] in tracked_updates]
    data_change = {k: contract[k] for k in ('teacher_correction', 'corrected_recovery_sources',
        'replaced_teacher_frames', 'reused_teacher_frames', 'corrected_recovery_windows',
        'collection_wall_seconds', 'collection_metadata', 'collection_contract')}
    collection = read(contract['collection_metadata'])
    collection_contract = read(contract['collection_contract'])
    data_change['collection_actual'] = {k: collection[k] for k in ('attempted', 'accepted_count', 'expert_frames', 'wall_seconds', 'stage_frames')}
    data_change['collection_cases'] = [{k: r[k] for k in ('layout', 'target', 'base_seed', 'success', 'accepted',
        'intervention_frame', 'teacher_frames', 'stage_frames', 'continuous_success_steps',
        'prefix_qpos_max_difference', 'prefix_qvel_max_difference', 'prefix_command_max_difference')}
        for r in collection['attempts']]
    data_change['original_stage_frames'] = collection_contract['original_stage_frames']
    timing = dict(collection_seconds=contract['collection_wall_seconds'],
        training_seconds=training['wall_seconds'], evaluation_seconds=evaluation['wall_seconds'],
        pipeline_execution_seconds=run['execution_wall_seconds'],
        collection_training_evaluation_sum_seconds=contract['collection_wall_seconds'] +
            training['wall_seconds'] + evaluation['wall_seconds'],
        pipeline_started_at=run['started_at'], pipeline_finished_at=run['finished_at'],
        pipeline_elapsed_from_timestamps_seconds=(datetime.fromisoformat(run['finished_at']) -
                                                 datetime.fromisoformat(run['started_at'])).total_seconds(),
        scope='Pipeline wall time starts at I pipeline launch; collection listed separately. Not time since user instruction.',
        evaluation_lanes=evaluation['lanes'])
    save(CAMPAIGN / 'paired_comparison.json', pairs)
    save(CAMPAIGN / 'source_task_results.json', sources)
    save(CAMPAIGN / 'color_position_results.json', tables)
    save(CAMPAIGN / 'color_position_layout_results.json', fine)
    save(CAMPAIGN / 'progression_summary.json', progression)
    save(CAMPAIGN / 'failure_timing.json', dict(
        frame_definition='Zero-based pre-action frame; time=frame/20; terminal steps counts executed actions.',
        grasp_definition='Start of first five-record bilateral contact interval, known retrospectively after frame+4.',
        box_definition='XY interior only; remaining=420-frame, not stable-success dwell time.',
        total=len(failures), categories=dict(Counter(r['temporal_category'] for r in failures)), episodes=failures))
    save(CAMPAIGN / 'candidate_decision.json', decision)
    save(CAMPAIGN / 'data_change.json', data_change)
    save(CAMPAIGN / 'observed_training_batch_comparison.json', batch_comparison)
    save(CAMPAIGN / 'stage_timing.json', timing)
    save(CAMPAIGN / 'training_scalar_summary.json', scalar_summary)

    lines = ['# I500教师姿态衔接修正结果', '', decision['reason'], '',
        f"本轮仅改变任务教师的接管旋转衔接：{contract['teacher_correction']}。"
        '实际measured state、执行绝对命令、起点state对应的10步delta和B norm数值见本轮定点来源表；'
        '导出与完整NPZ对应，实际修改针对固定姿态突然回正。'
        '原B输入state的尺度偏移仍然存在，不能把教师动作更平滑写成state分布已被修复。', '',
        f"重新生成{len(contract['corrected_recovery_sources'])}条完整教师后缀，共"
        f"{contract['replaced_teacher_frames']}帧作为新版本；另外{contract['reused_teacher_frames']}帧恢复数据复用。"
        f"原H采样顺序和位置保持，{sampler['original_samples']}个原起点＋{sampler['recovery_samples']}个恢复起点中，"
        f"{contract['corrected_recovery_windows']}个恢复窗口对应三条新版轨迹。原版均保留。"
        '这是教师衔接修正对照，不是采样重排消融，也未删除高loss样本。', '',
        f"正式教师采集{collection['accepted_count']}/{collection['attempted']}条被接受，实际新增版本共{collection['expert_frames']}教师帧。"
        f"原每条阶段帧数{collection_contract['original_stage_frames']}保持；前缀物理状态/command比较和真实接管时刻逐条见data_change.json及采集manifest。"
        '教师成功不计入自主成绩。', '',
        f"I从B累计{contract['source_cumulative_updates']}的完整状态分叉，完成"
        f"{training['local_updates']}次更新、累计{training['optimizer_updates']}；"
        f"batch {contract['batch']}、学习率{contract['learning_rate']:g}，沿用原optimizer/RNG/norm、"
        'E/upstream更新范围。未续H，未改norm、梯度clip、关节监督或自主执行器。', '',
        '| 集合 | I | H复用 | E复用 | B复用 |', '|---|---:|---:|---:|---:|']
    for group in GROUPS:
        lines.append('| ' + group + ' | ' + ' | '.join(score(tables[group][label]) for label in MODEL_ORDER) + ' |')
    lines += ['', '48开发、75验证和2个补充来源分组报告；E仅有原123项，未补造其两项来源结果。'
              '八来源从本轮同一125项提取，没有另加回合。', '',
              '## 配对变化', '', '| 对照 | 集合 | 共同项 | 修复 | 丢失 | 净变化 |', '|---|---|---:|---:|---:|---:|']
    for label in ('H', 'E', 'B'):
        for group in GROUPS:
            item = pairs['I_vs_' + label][group]
            lines.append(f"| I/{label} | {group} | {item['total']} | {item['repaired_count']} | "
                         f"{item['lost_count']} | {item['net_change']:+d} |")
    for label in ('H', 'E', 'B'):
        lines += ['', f'### I相对{label}的具体任务', '']
        for group in GROUPS:
            item = pairs['I_vs_' + label][group]
            repaired = '、'.join(identity(r['task']) for r in item['repaired']) or '无'
            lost = '、'.join(identity(r['task']) for r in item['lost']) or '无'
            lines.append(f"- {group}：修复{repaired}；丢失{lost}。")
    lines += ['', '## 八个恢复来源', '', '| 任务 | I | H | E | B | I接触/持物/到箱帧 |',
              '|---|---|---|---|---|---|']
    def outcome(value):
        return '未评' if value is None else '成功' if value else '失败'
    for row in sources:
        p = row['progression']
        lines.append('| ' + identity(row['task']) + ' | ' +
            ' | '.join(outcome(row[label + '_success']) for label in MODEL_ORDER) + ' | ' +
            '/'.join(show(p[k]) for k in ('first_reliable_grasp_frame','first_bilateral_lift_frame','first_over_box_frame')) + ' |')
    common_sources = [r for r in sources if r['E_success'] is not None]
    lines += ['', f"I八来源{source_successes}/{len(sources)}。六个有E对照的来源中，"
              f"I为{sum(r['I_success'] for r in common_sources)}/{len(common_sources)}，"
              f"E为{sum(r['E_success'] for r in common_sources)}/{len(common_sources)}。"
              '教师恢复的完整成功率与这些自主成绩分别记录。', '',
              '## 颜色、位置与布局', '', '| 集合 | 分类 | I | H | E | B |', '|---|---|---:|---:|---:|---:|']
    for group in GROUPS:
        for category in ('by_color', 'by_slot'):
            for value in tables[group]['I'][category]:
                lines.append('| ' + group + ' | ' + value + ' | ' + ' | '.join(
                    score(tables[group][label][category][value]) for label in MODEL_ORDER) + ' |')
    lines += ['', '绿色×前左按布局细分如下；完整颜色×位置×布局及逐组配对结果见color_position_layout_results.json。'
              '颜色、位置和布局耦合，分组变化不能直接证明颜色识别或视觉遗忘。', '',
              '| 集合 | layout | I | H | E | B | I/H修复/丢失 |', '|---|---:|---:|---:|---:|---:|---|']
    for group in GROUPS:
        for item in fine[group]['by_color_slot_layout']:
            if item['target'] == 'green' and item['slot'] == 'front_left':
                lines.append('| ' + group + ' | ' + str(item['layout']) + ' | ' +
                    ' | '.join(score(item['models'][label]) for label in MODEL_ORDER) +
                    f" | {item['paired']['H']['repaired_count']}/{item['paired']['H']['lost_count']} |")
    lines += ['', '## I失败的已记录时序', '',
        '帧号为0基动作前记录；连续双侧接触区间起点不等于在线确认时刻，到箱不等于入箱/释放/稳定。'
        '原failure_stage保持，下面增加时序解释。', '']
    if not failures:
        lines.append('本轮125项没有失败回合。')
    for row in failures:
        lines += [f"- **{row['report_group']} {identity(row['task'])}**（原{row['original_failure_stage']}）："
                  + row['explanation_zh'], '']
    lines += ['', '## 指定训练批次的实际日志', '',
              '| 更新 | I loss | H loss | E loss | I裁剪前grad norm |', '|---:|---:|---:|---:|---:|']
    metric_map = {label: {item['local_update']: item for item in batch_comparison[label]}
                  for label in ('I','H','E')}
    for update in (19,33,48,93,150,416):
        lines.append(f"| {update} | " + ' | '.join(f"{metric_map[label][update]['loss']:.9g}" for label in ('I','H','E')) +
                     f" | {metric_map['I'][update]['grad_norm']:.9g} |")
    lines += ['', '日志loss为实际批均值，grad_norm为原全局裁剪前数值；模型轨迹不同。'
              '损失下降不等于自主完整任务改善；416原有跨实验尖峰未被归罪113尾窗。'
              '更新93和150分别含115相对15和25的新窗口，其归一化动作最大值升至91.089和36.988；平滑只是分散姿态回正，不等于消除所有大尺度监督。全部27个改变窗口的实际批次日志均保留。', '',
              '## 实际耗时与结果范围', '',
              f"教师三例正式再采：{timing['collection_seconds']:.2f}秒；"
              f"I正式训练：{timing['training_seconds']:.2f}秒；125项并行评测：{timing['evaluation_seconds']:.2f}秒。"
              f"I流水线从启动至评测完成的墙钟为{timing['pipeline_execution_seconds']:.2f}秒，"
              f"采集＋训练＋评测阶段相加为{timing['collection_training_evaluation_sum_seconds']:.2f}秒；"
              '这不是从用户发出指令算起的总耗时，阶段和流水线口径分开记录。', '',
              '两路独立服务/worker复用已实现流程，原种子、420/40、20Hz、horizon10、replan5、batch1推理和flow10保持。'
              'B/E/H仅复用历史结果；未重跑基线，未使用3000–3009。', '',
              decision['reason'] + ' 验证已多轮参与选择，72/75为工程选择线，不称新独立泛化。'
              '本轮不自动I1000、H1000、扩评或配方搜索。', '',
              '代码、配置、采样、日志、全部紧凑回合JSON和本报告入Git。大检查点、optimizer、原始数组、完整视频留服务器供用户备份；'
              '不新增大文件队列、不在电脑下载归档、不自动删除研究资料。', '']
    (CAMPAIGN / 'final_report_zh.md').write_text('\n'.join(lines))
    return decision
