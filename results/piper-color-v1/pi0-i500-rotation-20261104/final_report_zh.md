# I500教师姿态衔接修正结果

本次教师姿态衔接修正的I500未达到候选保留条件；B继续正式，本轮结束。

本轮仅改变任务教师的接管旋转衔接：Only the existing lift phase uses SO(3) shortest-path SLERP with the same smoothstep as position, from measured takeover rotation to original reset orientation over 30 frames. No policy/controller changes.。实际measured state、执行绝对命令、起点state对应的10步delta和B norm数值见本轮定点来源表；导出与完整NPZ对应，实际修改针对固定姿态突然回正。原B输入state的尺度偏移仍然存在，不能把教师动作更平滑写成state分布已被修复。

重新生成3条完整教师后缀，共450帧作为新版本；另外750帧恢复数据复用。原H采样顺序和位置保持，1932个原起点＋68个恢复起点中，27个恢复窗口对应三条新版轨迹。原版均保留。这是教师衔接修正对照，不是采样重排消融，也未删除高loss样本。

正式教师采集3/3条被接受，实际新增版本共450教师帧。原每条阶段帧数{'lift': 30, 'transfer': 40, 'lower': 26, 'release': 20, 'retreat': 30, 'settle': 4}保持；前缀物理状态/command比较和真实接管时刻逐条见data_change.json及采集manifest。教师成功不计入自主成绩。

I从B累计4020的完整状态分叉，完成500次更新、累计4520；batch 4、学习率1e-06，沿用原optimizer/RNG/norm、E/upstream更新范围。未续H，未改norm、梯度clip、关节监督或自主执行器。

| 集合 | I | H复用 | E复用 | B复用 |
|---|---:|---:|---:|---:|
| development | 39/48 | 37/48 | 34/48 | 25/48 |
| validation | 69/75 | 65/75 | 67/75 | 72/75 |
| additional_sources | 1/2 | 2/2 | 未评 | 0/2 |

48开发、75验证和2个补充来源分组报告；E仅有原123项，未补造其两项来源结果。八来源从本轮同一125项提取，没有另加回合。

## 配对变化

| 对照 | 集合 | 共同项 | 修复 | 丢失 | 净变化 |
|---|---|---:|---:|---:|---:|
| I/H | development | 48 | 4 | 2 | +2 |
| I/H | validation | 75 | 6 | 2 | +4 |
| I/H | additional_sources | 2 | 0 | 1 | -1 |
| I/E | development | 48 | 7 | 2 | +5 |
| I/E | validation | 75 | 6 | 4 | +2 |
| I/E | additional_sources | 0 | 0 | 0 | +0 |
| I/B | development | 48 | 17 | 3 | +14 |
| I/B | validation | 75 | 2 | 5 | -3 |
| I/B | additional_sources | 2 | 1 | 0 | +1 |

### I相对H的具体任务

- development：修复102/blue/43、122/red/42、134/blue/42、107/blue/43；丢失100/blue/43、101/red/43。
- validation：修复1000/green/42、1003/red/42、1004/green/43、1002/green/44、1000/green/45、1002/green/45；丢失1003/red/43、1001/blue/46。
- additional_sources：修复无；丢失120/blue/43。

### I相对E的具体任务

- development：修复103/red/42、122/red/42、122/red/43、134/blue/42、110/green/43、107/blue/43、113/red/42；丢失100/blue/43、100/green/43。
- validation：修复1001/green/42、1003/red/42、1004/green/43、1001/blue/44、1002/green/44、1001/red/46；丢失1003/red/43、1003/green/43、1003/blue/44、1001/blue/46。
- additional_sources：修复无；丢失无。

### I相对B的具体任务

- development：修复100/blue/42、101/red/42、102/blue/43、103/red/42、122/red/43、123/red/42、123/red/43、124/red/42、131/red/43、134/blue/42、134/blue/43、110/green/43、115/green/43、100/green/42、109/red/42、113/red/42、101/green/43；丢失101/red/43、103/red/43、100/green/43。
- validation：修复1001/red/44、1001/blue/45；丢失1000/red/43、1003/red/43、1003/green/43、1000/red/46、1001/blue/46。
- additional_sources：修复139/red/42；丢失无。

## 八个恢复来源

| 任务 | I | H | E | B | I接触/持物/到箱帧 |
|---|---|---|---|---|---|
| 113/red/42 | 成功 | 成功 | 失败 | 失败 | 79/110/170 |
| 120/blue/43 | 失败 | 成功 | 未评 | 失败 | 83/100/337 |
| 109/red/42 | 成功 | 成功 | 成功 | 失败 | 97/127/186 |
| 139/red/42 | 成功 | 成功 | 未评 | 失败 | 91/105/172 |
| 107/blue/42 | 失败 | 失败 | 失败 | 失败 | 75/307/371 |
| 115/green/43 | 成功 | 成功 | 成功 | 失败 | 82/119/161 |
| 105/red/43 | 失败 | 失败 | 失败 | 失败 | 150/253/未记录 |
| 126/blue/43 | 失败 | 失败 | 失败 | 失败 | 172/210/未记录 |

I八来源4/8。六个有E对照的来源中，I为3/6，E为2/6。教师恢复的完整成功率与这些自主成绩分别记录。

## 颜色、位置与布局

| 集合 | 分类 | I | H | E | B |
|---|---|---:|---:|---:|---:|
| development | red | 17/22 | 17/22 | 13/22 | 10/22 |
| development | green | 15/16 | 15/16 | 15/16 | 12/16 |
| development | blue | 7/10 | 5/10 | 6/10 | 3/10 |
| development | back | 25/32 | 24/32 | 21/32 | 14/32 |
| development | front_left | 6/8 | 5/8 | 5/8 | 4/8 |
| development | front_right | 8/8 | 8/8 | 8/8 | 7/8 |
| validation | red | 22/25 | 22/25 | 21/25 | 24/25 |
| validation | green | 24/25 | 19/25 | 22/25 | 25/25 |
| validation | blue | 23/25 | 24/25 | 24/25 | 23/25 |
| validation | back | 22/25 | 22/25 | 22/25 | 23/25 |
| validation | front_left | 23/25 | 19/25 | 21/25 | 24/25 |
| validation | front_right | 24/25 | 24/25 | 24/25 | 25/25 |
| additional_sources | red | 1/1 | 1/1 | 未评 | 0/1 |
| additional_sources | green | 未评 | 未评 | 未评 | 未评 |
| additional_sources | blue | 0/1 | 1/1 | 未评 | 0/1 |
| additional_sources | back | 未评 | 未评 | 未评 | 未评 |
| additional_sources | front_left | 1/2 | 2/2 | 未评 | 0/2 |
| additional_sources | front_right | 未评 | 未评 | 未评 | 未评 |

绿色×前左按布局细分如下；完整颜色×位置×布局及逐组配对结果见color_position_layout_results.json。颜色、位置和布局耦合，分组变化不能直接证明颜色识别或视觉遗忘。

| 集合 | layout | I | H | E | B | I/H修复/丢失 |
|---|---:|---:|---:|---:|---:|---|
| development | 100 | 1/2 | 1/2 | 2/2 | 1/2 | 0/0 |
| validation | 1000 | 5/5 | 3/5 | 5/5 | 5/5 | 2/0 |
| validation | 1002 | 5/5 | 3/5 | 4/5 | 5/5 | 2/0 |
| validation | 1004 | 5/5 | 4/5 | 4/5 | 5/5 | 1/0 |

## I失败的已记录时序

帧号为0基动作前记录；连续双侧接触区间起点不等于在线确认时刻，到箱不等于入箱/释放/稳定。原failure_stage保持，下面增加时序解释。

- **validation 1000/red/43**（原approach_or_grasp）：接触区间起点284，抬高未记录，双侧持物未记录，到箱未记录，到箱余步未记录。已有连续双侧接触，旧approach_or_grasp不能解释为从未抓到。

- **validation 1003/red/43**（原lift_or_transfer）：接触区间起点88，抬高111，双侧持物111，到箱未记录，到箱余步未记录。既有诊断掉落帧124；掉落前大开爪命令0帧；箱前首次执行大开爪262。该次大开爪晚于掉落，不能把这次开爪写成先行原因。

- **validation 1003/green/43**（原lift_or_transfer）：接触区间起点70，抬高97，双侧持物97，到箱未记录，到箱余步未记录。既有诊断掉落帧106；掉落前大开爪命令0帧；箱前首次执行大开爪264。该次大开爪晚于掉落，不能把这次开爪写成先行原因。

- **validation 1003/blue/44**（原approach_or_grasp）：接触区间起点259，抬高未记录，双侧持物未记录，到箱未记录，到箱余步未记录。已有连续双侧接触，旧approach_or_grasp不能解释为从未抓到。

- **validation 1000/red/46**（原lift_or_transfer）：接触区间起点144，抬高223，双侧持物223，到箱未记录，到箱余步未记录。

- **validation 1001/blue/46**（原stability_or_distractor）：接触区间起点81，抬高194，双侧持物194，到箱313，到箱余步107。终态入箱且开爪，但未累计40步连续成功；JSON无最终连续计数，不推断具体缺几帧。

- **development 100/blue/43**（原stability_or_distractor）：接触区间起点169，抬高321，双侧持物321，到箱359，到箱余步61。终态入箱且开爪，但未累计40步连续成功；JSON无最终连续计数，不推断具体缺几帧。

- **development 101/red/43**（原lower_or_release）：接触区间起点287，抬高312，双侧持物312，到箱389，到箱余步31。首次到箱已不足40步稳定计时预算，不能仅凭旧标签归因为释放控制。

- **development 103/red/43**（原approach_or_grasp）：接触区间起点194，抬高未记录，双侧持物未记录，到箱未记录，到箱余步未记录。已有连续双侧接触，旧approach_or_grasp不能解释为从未抓到。

- **development 105/red/43**（原lift_or_transfer）：接触区间起点150，抬高253，双侧持物253，到箱未记录，到箱余步未记录。

- **development 114/red/43**（原stability_or_distractor）：接触区间起点264，抬高280，双侧持物280，到箱345，到箱余步75。终态入箱且开爪，但未累计40步连续成功；JSON无最终连续计数，不推断具体缺几帧。

- **development 124/red/43**（原approach_or_grasp）：接触区间起点411，抬高未记录，双侧持物未记录，到箱未记录，到箱余步未记录。已有连续双侧接触，旧approach_or_grasp不能解释为从未抓到。

- **development 126/blue/43**（原lift_or_transfer）：接触区间起点172，抬高210，双侧持物210，到箱未记录，到箱余步未记录。

- **development 100/green/43**（原lift_or_transfer）：接触区间起点76，抬高349，双侧持物349，到箱未记录，到箱余步未记录。

- **development 107/blue/42**（原lower_or_release）：接触区间起点75，抬高307，双侧持物307，到箱371，到箱余步49。

- **additional_sources 120/blue/43**（原stability_or_distractor）：接触区间起点83，抬高100，双侧持物100，到箱337，到箱余步83。终态入箱且开爪，但未累计40步连续成功；JSON无最终连续计数，不推断具体缺几帧。


## 指定训练批次的实际日志

| 更新 | I loss | H loss | E loss | I裁剪前grad norm |
|---:|---:|---:|---:|---:|
| 19 | 0.0460034348 | 1.22302675 | 0.00419109315 | 0.636016309 |
| 33 | 3.95037913 | 140.41127 | 0.00267788512 | 11.5972338 |
| 48 | 0.0248569194 | 0.162274152 | 0.00834007841 | 0.882832468 |
| 416 | 3.07676435 | 3.09158969 | 3.10571027 | 210.747864 |

日志loss为实际批均值，grad_norm为原全局裁剪前数值；模型轨迹不同。损失下降不等于自主完整任务改善；416原有跨实验尖峰未被归罪113尾窗。

## 实际耗时与结果范围

教师三例正式再采：16.04秒；I正式训练：204.66秒；125项并行评测：710.93秒。I流水线从启动至评测完成的墙钟为959.81秒，采集＋训练＋评测阶段相加为931.64秒；这不是从用户发出指令算起的总耗时，阶段和流水线口径分开记录。

两路独立服务/worker复用已实现流程，原种子、420/40、20Hz、horizon10、replan5、batch1推理和flow10保持。B/E/H仅复用历史结果；未重跑基线，未使用3000–3009。

本次教师姿态衔接修正的I500未达到候选保留条件；B继续正式，本轮结束。 验证已多轮参与选择，72/75为工程选择线，不称新独立泛化。本轮不自动I1000、H1000、扩评或配方搜索。

代码、配置、采样、日志、全部紧凑回合JSON和本报告入Git。大检查点、optimizer、原始数组、完整视频留服务器供用户备份；不新增大文件队列、不在电脑下载归档、不自动删除研究资料。
