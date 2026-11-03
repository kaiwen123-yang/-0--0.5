# G500 固定视觉最终更新对照

G从B累计4020完整状态接续500次真实更新，最终累计4520。原filter、dtype、梯度裁剪、optimizer buffer、学习率schedule与数据/RNG规则沿用E。仅在tx.update之后、apply_updates之前将PaliGemma/img/.*最终update置零。

| 指标 | B（复用） | E500（复用） | F500（复用） | G500（本轮） |
|---|---:|---:|---:|---:|
| 困难开发 | 25/48 | 34/48 | 30/48 | 29/48 |
| 开发后排 | 14/32 | 21/32 | 16/32 | 15/32 |
| 验证 | 72/75 | 67/75 | 65/75 | 64/75 |
| 验证后排 | 23/25 | 22/25 | 18/25 | 20/25 |

开发48项与验证75项独立报告；推理种子不是独立训练种子。

| 配对 | 集合 | 修复 | 丢失 |
|---|---|---:|---:|
| G对B | train | 11 | 7 |
| G对B | validation | 2 | 10 |
| G对E | train | 4 | 9 |
| G对E | validation | 2 | 5 |

## 逐任务修复与丢失

任务记法为layout/target/seed；train与validation分别比较，不合并评分。

| 配对 | 集合 | 修复任务 | 丢失任务及G失败阶段 |
|---|---|---|---|
| G对B | train | 100/green/s42、100/blue/s42、101/red/s42、100/blue/s43、101/green/s43、107/blue/s42、113/red/s42、105/red/s43、115/green/s43、131/red/s43、134/blue/s43 | 101/green/s42(approach_or_grasp)、101/red/s43(approach_no_closure)、106/green/s42(lift_or_transfer)、114/red/s42(lower_or_release)、122/red/s42(approach_or_grasp)、131/red/s42(approach_no_closure)、103/red/s43(approach_or_grasp) |
| G对B | validation | 1001/red/s44、1001/blue/s45 | 1003/red/s42(lower_or_release)、1000/red/s43(approach_or_grasp)、1001/blue/s43(lift_or_transfer)、1002/green/s43(lift_or_transfer)、1004/red/s43(approach_no_closure)、1001/blue/s44(lift_or_transfer)、1002/green/s44(stability_or_distractor)、1000/red/s46(approach_or_grasp)、1001/red/s46(approach_or_grasp)、1003/red/s46(lift_or_transfer) |
| G对E | train | 105/red/s43、107/blue/s42、107/blue/s43、113/red/s42 | 102/blue/s43(approach_or_grasp)、114/red/s42(lower_or_release)、123/red/s42(stability_or_distractor)、123/red/s43(stability_or_distractor)、124/red/s42(approach_no_closure)、131/red/s42(approach_no_closure)、106/green/s42(lift_or_transfer)、109/red/s42(approach_or_grasp)、101/green/s42(approach_or_grasp) |
| G对E | validation | 1001/green/s42、1004/green/s43 | 1001/blue/s43(lift_or_transfer)、1002/green/s43(lift_or_transfer)、1004/red/s43(approach_no_closure)、1003/blue/s44(approach_or_grasp)、1003/red/s46(lift_or_transfer) |

G恢复E丢失的B验证成功2/8项；保留E修复的B训练难例8/13项。
完整任务身份与失败阶段见paired_comparison.json；逐任务结果见node_G_500.json。

## 选择与证据边界

当前选择：B。G开发门槛未通过，保留B并停止本轮路线
本轮新布局测试未执行：G开发门槛未通过。
旧独立测试53/60仅为B历史成绩，不能改称本轮成绩。
该对照检验限制视觉权重移动对本次适配收益与退化的影响。单次训练对照不能证明SigLIP灾难性遗忘；验证布局已反复用于开发。

## G失败阶段

train：{'approach_no_closure': 5, 'approach_or_grasp': 8, 'lower_or_release': 2, 'stability_or_distractor': 3, 'lift_or_transfer': 1}
validation：{'lower_or_release': 1, 'approach_or_grasp': 4, 'lift_or_transfer': 4, 'approach_no_closure': 1, 'stability_or_distractor': 1}

## 任务与交付

真实训练500次；新增自主完整任务123次；E/F训练与B/E/F开发评测未重复。
源码、配置、正常日志、紧凑结果与本报告入Git；完整检查点及新轨迹/视频入Release。发布、保留与pending范围见publication/pi0-g-fixed-vision-20261103/delivery_status.json。
按用户最新更正，B/v2恢复副本、G完整检查点、optimizer/RNG/norm/采样与训练数据、轨迹视频和相关记录全部保留；只清理无活动依赖的传输临时副本。B/v2已有Release资产不重复上传。
