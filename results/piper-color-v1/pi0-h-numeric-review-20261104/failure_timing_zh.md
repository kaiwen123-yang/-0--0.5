# H500已有失败时序复核

H原125项中21项失败：开发11、验证10。以下复用已保存JSON，原success与粗failure_stage保持；新增时序解释不改成绩。

帧号为0起始的动作前记录，n帧时间为n/20秒；420是已执行动作数，最后动作前帧为419。抓稳帧是首个连续5帧双侧接触区间的起点，不是在线判据在起点已获知未来4帧。到箱仅是XY范围满足，不等于入箱、释放或开始稳定计时。

| 时序观察 | 数量 |
|---|---:|
| 已记录连续双侧接触，未抬高5cm | 5 |
| 已抬起，始终未到箱上 | 9 |
| 到箱上余步少于40 | 3 |
| 到箱上恰剩40步 | 2 |
| 到箱上余步超过40，仍未完整成功 | 2 |

## 21例逐项事实

| 集合/任务 | 原标签 | 接触区间起点 | 抬高/持物 | 到箱 | 余步 | 双侧接触累计 | 终态入箱/开爪/稳定 |
|---|---|---:|---|---:|---:|---:|---|
| validation 1000/green/42 | lift_or_transfer | 89 | 148/148 | 未记录 | 未记录 | 335 | False/False/False |
| validation 1003/red/42 | lower_or_release | 82 | 328/328 | 380 | 40 | 338 | False/False/False |
| validation 1000/red/43 | approach_or_grasp | 309 | 未记录/未记录 | 未记录 | 未记录 | 12 | False/True/False |
| validation 1003/green/43 | lift_or_transfer | 70 | 98/98 | 未记录 | 未记录 | 35 | False/True/False |
| validation 1004/green/43 | approach_or_grasp | 86 | 未记录/未记录 | 未记录 | 未记录 | 334 | False/False/False |
| validation 1002/green/44 | lower_or_release | 81 | 374/374 | 415 | 5 | 339 | False/False/False |
| validation 1003/blue/44 | lower_or_release | 260 | 278/278 | 348 | 72 | 99 | False/False/False |
| validation 1000/green/45 | lift_or_transfer | 85 | 375/375 | 未记录 | 未记录 | 335 | False/False/False |
| validation 1002/green/45 | lift_or_transfer | 83 | 386/386 | 未记录 | 未记录 | 337 | False/False/False |
| validation 1000/red/46 | lift_or_transfer | 144 | 223/223 | 未记录 | 未记录 | 276 | False/False/False |
| development 102/blue/43 | stability_or_distractor | 178 | 200/200 | 337 | 83 | 206 | True/True/False |
| development 103/red/43 | approach_or_grasp | 155 | 未记录/未记录 | 未记录 | 未记录 | 58 | False/False/False |
| development 105/red/43 | lower_or_release | 134 | 212/212 | 412 | 8 | 286 | False/False/False |
| development 114/red/43 | lift_or_transfer | 247 | 304/304 | 未记录 | 未记录 | 173 | False/False/False |
| development 122/red/42 | lift_or_transfer | 179 | 268/268 | 未记录 | 未记录 | 241 | False/False/False |
| development 124/red/43 | lower_or_release | 326 | 344/344 | 396 | 24 | 94 | False/False/False |
| development 126/blue/43 | lift_or_transfer | 168 | 209/209 | 未记录 | 未记录 | 245 | False/False/False |
| development 134/blue/42 | lower_or_release | 159 | 335/335 | 380 | 40 | 261 | False/False/False |
| development 100/green/43 | lift_or_transfer | 76 | 419/419 | 未记录 | 未记录 | 344 | False/False/False |
| development 107/blue/42 | approach_or_grasp | 76 | 未记录/未记录 | 未记录 | 未记录 | 344 | False/False/False |
| development 107/blue/43 | approach_or_grasp | 87 | 未记录/未记录 | 未记录 | 未记录 | 333 | False/False/False |

## 与旧宽标签不同的具体解释

- **validation 1000/green/42**：第148帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为2.95秒。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01000_green_seed42/attempt000_seed42/layout_01000_green.json)

- **validation 1003/red/42**：第328帧持物，第380帧首次到箱上，剩40步；持物至到箱耗时2.6秒。到箱只留下40步，无额外下降/释放余量；最终仍未入箱或开爪。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01003_red_seed42/attempt000_seed42/layout_01003_red.json)

- **validation 1000/red/43**：第309帧为首个连续5帧双侧接触区间起点；累计12帧双侧接触，但目标未高于半块高度5cm。旧标签不能被解释为从未接触或从未抓到。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01000_red_seed43/attempt000_seed43/layout_01000_red.json)

- **validation 1003/green/43**：第98帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为1.4秒。第105帧首次失去双侧接触，第107帧记录目标回落至低于半块高度1cm；第292帧才出现超过0.04m的预测/执行开爪，掉落前大开爪命令为0帧。这排除了“该次已记录的大开爪先于掉落”的解释，未确定最初失去接触的原因。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01003_green_seed43/attempt000_seed43/layout_01003_green.json)

- **validation 1004/green/43**：第86帧为首个连续5帧双侧接触区间起点；累计334帧双侧接触，但目标未高于半块高度5cm。旧标签不能被解释为从未接触或从未抓到。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01004_green_seed43/attempt000_seed43/layout_01004_green.json)

- **validation 1002/green/44**：第374帧持物，第415帧首次到箱上，剩5步；持物至到箱耗时2.05秒。到箱已不足连续40步的稳定计时预算，不能仅凭旧标签归因为释放控制。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01002_green_seed44/attempt000_seed44/layout_01002_green.json)

- **validation 1003/blue/44**：第278帧持物，第348帧首次到箱上，剩72步；持物至到箱耗时3.5秒。首次到箱时理论余步超过40，但到箱不是完整成功条件。虽然首次到箱余72步，累计到箱仅13帧；终态仍未入箱、未开爪。不能把72步余量误作72帧持续在箱上或稳定成功。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01003_blue_seed44/attempt000_seed44/layout_01003_blue.json)

- **validation 1000/green/45**：第375帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为14.5秒。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01000_green_seed45/attempt000_seed45/layout_01000_green.json)

- **validation 1002/green/45**：第386帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为15.15秒。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01002_green_seed45/attempt000_seed45/layout_01002_green.json)

- **validation 1000/red/46**：第223帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为3.95秒。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/validation_01000_red_seed46/attempt000_seed46/layout_01000_red.json)

- **development 102/blue/43**：第200帧持物，第337帧首次到箱上，剩83步；持物至到箱耗时6.85秒。首次到箱时理论余步超过40，但到箱不是完整成功条件。终态correct_in_box=true、gripper_open=true、wrong_in_box=false，红/绿扰动物位移均为0、最大关节越界0，但stable_2s=false。因此旧stability_or_distractor标签不能写成碰撞扰动物；未累计40步稳定成功。紧凑JSON未保存最终连续成功计数，不能据此给出缺少的确切帧数。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00102_blue_seed43/attempt000_seed43/layout_00102_blue.json)

- **development 103/red/43**：第155帧为首个连续5帧双侧接触区间起点；累计58帧双侧接触，但目标未高于半块高度5cm。旧标签不能被解释为从未接触或从未抓到。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00103_red_seed43/attempt000_seed43/layout_00103_red.json)

- **development 105/red/43**：第212帧持物，第412帧首次到箱上，剩8步；持物至到箱耗时10秒。到箱已不足连续40步的稳定计时预算，不能仅凭旧标签归因为释放控制。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00105_red_seed43/attempt000_seed43/layout_00105_red.json)

- **development 114/red/43**：第304帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为2.85秒。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00114_red_seed43/attempt000_seed43/layout_00114_red.json)

- **development 122/red/42**：第268帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为4.45秒。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00122_red_seed42/attempt000_seed42/layout_00122_red.json)

- **development 124/red/43**：第344帧持物，第396帧首次到箱上，剩24步；持物至到箱耗时2.6秒。到箱已不足连续40步的稳定计时预算，不能仅凭旧标签归因为释放控制。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00124_red_seed43/attempt000_seed43/layout_00124_red.json)

- **development 126/blue/43**：第209帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为2.05秒。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00126_blue_seed43/attempt000_seed43/layout_00126_blue.json)

- **development 134/blue/42**：第335帧持物，第380帧首次到箱上，剩40步；持物至到箱耗时2.25秒。到箱只留下40步，无额外下降/释放余量；最终仍未入箱或开爪。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00134_blue_seed42/attempt000_seed42/layout_00134_blue.json)

- **development 100/green/43**：第419帧已同时满足抬高与双侧接触，到420步结束始终未记录到箱上；接触区间起点至首次抬起为17.15秒。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00100_green_seed43/attempt000_seed43/layout_00100_green.json)

- **development 107/blue/42**：第76帧为首个连续5帧双侧接触区间起点；累计344帧双侧接触，但目标未高于半块高度5cm。旧标签不能被解释为从未接触或从未抓到。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00107_blue_seed42/attempt000_seed42/layout_00107_blue.json)

- **development 107/blue/43**：第87帧为首个连续5帧双侧接触区间起点；累计333帧双侧接触，但目标未高于半块高度5cm。旧标签不能被解释为从未接触或从未抓到。 [原回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/evaluations/H_500/train_00107_blue_seed43/attempt000_seed43/layout_00107_blue.json)

## 八个恢复来源

| 任务 | B | E | H | H接触/持物/到箱帧 |
|---|---|---|---|---|
| 113/red/42 | 失败 | 失败 | 成功 | 78/171/250 |
| 120/blue/43 | 失败 | 未评 | 成功 | 83/99/202 |
| 109/red/42 | 失败 | 成功 | 成功 | 101/171/241 |
| 139/red/42 | 失败 | 未评 | 成功 | 96/111/181 |
| 107/blue/42 | 失败 | 失败 | 失败 | 76/未记录/未记录 |
| 115/green/43 | 失败 | 成功 | 成功 | 86/165/196 |
| 105/red/43 | 失败 | 失败 | 失败 | 134/212/412 |
| 126/blue/43 | 失败 | 失败 | 失败 | 168/209/未记录 |

H为5/8；有E对照的六例是E2/6、H3/6，只有113/red/42是H相对E新增成功。109/red/42与115/green/43在E已成功，120/blue/43与139/red/42没有E结果。教师恢复8/8不计入这些自主成绩。

本表只解释已记录事件，不把训练监督异常直接写成这些失败的已证原因；未新增回合、训练、VLA前向、NPZ扫描或测试。102/blue/43的具体连续成功帧数不在紧凑JSON中，保留为未知。
