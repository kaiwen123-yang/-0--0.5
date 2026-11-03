# H500恢复数据对照结果

这套68/2000恢复混合、500更新配方未达到保留候选条件，本轮结束并保留B。

H从B累计4020的完整模型、optimizer与RNG分叉，沿用B原norm、E的可训练范围和upstream训练步骤。完成500更新，累计4520；batch4、常数1e-6、无新warmup，未使用G视觉置零。

E前2000项中固定替换68项，1932项原位保留；替换来自68个不同原episode，三个区间为26/22/20，全部120个原episode保持覆盖。8条恢复后缀均含相对0与25，指定四条另含15。

| 集合 | B复用 | E500复用 | H500 |
|---|---:|---:|---:|
| development | 25/48 | 34/48 | 37/48 |
| validation | 72/75 | 67/75 | 65/75 |
| additional_sources | 0/2 | 未评测 | 2/2 |

48开发、75验证和2个补充来源分别报告；H/E配对仅123个共同任务，H/B为125个已匹配任务。8来源结果直接从本轮125项提取，未增加回合。

## 配对修复与丢失

| 配对 | 集合 | 修复 | 丢失 |
|---|---|---|---|
| H_vs_B | development | 16：100/blue/42、100/blue/43、101/red/42、103/red/42、122/red/43、123/red/42、123/red/43、124/red/42、131/red/43、134/blue/43、110/green/43、115/green/43、100/green/42、109/red/42、113/red/42、101/green/43 | 4：103/red/43(approach_or_grasp)、122/red/42(lift_or_transfer)、100/green/43(lift_or_transfer)、107/blue/43(approach_or_grasp) |
| H_vs_B | validation | 2：1001/red/44、1001/blue/45 | 9：1000/green/42(lift_or_transfer)、1003/red/42(lower_or_release)、1000/red/43(approach_or_grasp)、1003/green/43(lift_or_transfer)、1004/green/43(approach_or_grasp)、1002/green/44(lower_or_release)、1000/green/45(lift_or_transfer)、1002/green/45(lift_or_transfer)、1000/red/46(lift_or_transfer) |
| H_vs_B | additional_sources | 2：120/blue/43、139/red/42 | 0：无 |
| H_vs_E | development | 5：101/red/43、103/red/42、122/red/43、110/green/43、113/red/42 | 2：102/blue/43(stability_or_distractor)、100/green/43(lift_or_transfer) |
| H_vs_E | validation | 3：1001/green/42、1001/blue/44、1001/red/46 | 5：1000/green/42(lift_or_transfer)、1003/green/43(lift_or_transfer)、1003/blue/44(lower_or_release)、1000/green/45(lift_or_transfer)、1002/green/45(lift_or_transfer) |

## 八个训练来源

| 任务 | 原位置 | B | E500 | H500 | H失败阶段 |
|---|---|---|---|---|---|
| 113/red/42 | front_left | 失败 | 失败 | 成功 | success |
| 120/blue/43 | front_left | 失败 | 未评测 | 成功 | success |
| 109/red/42 | front_left | 失败 | 成功 | 成功 | success |
| 139/red/42 | front_left | 失败 | 未评测 | 成功 | success |
| 107/blue/42 | front_left | 失败 | 失败 | 失败 | approach_or_grasp |
| 115/green/43 | back | 失败 | 成功 | 成功 | success |
| 105/red/43 | back | 失败 | 失败 | 失败 | lower_or_release |
| 126/blue/43 | back | 失败 | 失败 | 失败 | lift_or_transfer |

## 颜色与位置分项

| 集合 | 分类 | B | E500 | H500 |
|---|---|---:|---:|---:|
| development | red | 10/22 | 13/22 | 17/22 |
| development | green | 12/16 | 15/16 | 15/16 |
| development | blue | 3/10 | 6/10 | 5/10 |
| development | back | 14/32 | 21/32 | 24/32 |
| development | front_left | 4/8 | 5/8 | 5/8 |
| development | front_right | 7/8 | 8/8 | 8/8 |
| validation | red | 24/25 | 21/25 | 22/25 |
| validation | green | 25/25 | 22/25 | 19/25 |
| validation | blue | 23/25 | 24/25 | 24/25 |
| validation | back | 23/25 | 22/25 | 22/25 |
| validation | front_left | 24/25 | 21/25 | 19/25 |
| validation | front_right | 25/25 | 24/25 | 24/25 |
| additional_sources | red | 0/1 | 未评测 | 1/1 |
| additional_sources | green | 未评测 | 未评测 | 未评测 |
| additional_sources | blue | 0/1 | 未评测 | 1/1 |
| additional_sources | back | 未评测 | 未评测 | 未评测 |
| additional_sources | front_left | 0/2 | 未评测 | 2/2 |
| additional_sources | front_right | 未评测 | 未评测 | 未评测 |

## 完整任务中记录的动作进程

抓稳定义为连续5帧双侧接触力均大于0.05 N；抬起定义为目标高于半块高度5 cm；时间来自20 Hz仿真帧。预测/执行开度超过0.04 m与失去双侧接触分别记录，事件本身不证明失败原因。逐任务帧号、到箱剩余步数和完整任务成败见紧凑JSON。

| 集合 | 抓稳→抬起中位秒/有效数 | 持物→到箱中位秒/有效数 | 到箱剩余步数中位/有效数 | 箱前预测开爪/执行开爪/失去双侧接触 |
|---|---|---|---|---|
| development | 1.3/45 | 2.95/41 | 228/41 | 0/0/0 |
| validation | 1.6/73 | 2.55/68 | 254.0/68 | 1/1/1 |
| additional_sources | 0.775/2 | 4.325/2 | 228.5/2 | 0/0/0 |

## 运行与结论范围

两路独立服务和worker按原名册偶/奇编号完成63/62项，总评测墙钟766.0秒；逐路时间见evaluation_timing.json。每回合使用原身份种子，worker编号未参与seed。
协议保持420步上限、连续40步成功、horizon10、replan5、20Hz、batch1推理与10次flow采样。无教师介入。
H/E用于观察本次恢复数据混合相对同预算续训的变化；H/B用于判断候选完整能力。验证集已多轮参与选择，72/75是工程选择线；本轮不是新的独立泛化测试，单次阴性结果也不否定所有恢复数据方法。
未重跑B/E/F/G，未使用3000–3009，未续训或扩评。所有大检查点、optimizer、完整视频与原始数组保留服务器，用户自行备份；本流程只推代码和小结果，不建立H大文件发布队列、不删除研究资料。
