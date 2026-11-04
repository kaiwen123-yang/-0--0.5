# π0 / π0.5：Piper H仿真、微调与复现资料

## 当前状态：H500已完成，B继续作为正式模型

**H完成500更新与125次自主完整任务：开发37/48、验证65/75，两个补充来源2/2；八个恢复来源自主成功5/8。H没有达到候选保留条件，B验证72/75仍是正式基线。**

- **当前唯一入口：[H完成审查、下一轮计划与启动提示词](docs/PI0_H500_REVIEW_NEXT_PLAN_20261104.md)。**
- [H最终报告](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/final_report_zh.md)、[逐回合JSON](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/node_H_500.json)、[配对变化](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/paired_comparison.json)、[实际训练日志](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-h500-recovery-20261103/H/lora_metrics.jsonl)。
- 实际运行代码位于研究分支`codex/pi0-h500-recovery-20261103`，审查提交`3dd547a`（北京时间2026-11-03 23:26）。main维护当前计划，不用main旧代码覆盖服务器工作区。
- [AGENTS当前规则](AGENTS.md)、[发布与人工备份规则](docs/RESEARCH_PUBLISH_POLICY.md)。

## 结果与下一步的关系

| 对象 | 原48开发 | 原75验证 | 状态 |
|---|---:|---:|---|
| B累计4020 | 25/48 | 72/75 | 正式最佳；历史全训练211/240、旧独立测试53/60 |
| E500原数据续训 | 34/48 | 67/75 | 已完成；H同预算比较对象 |
| F500早期纠偏 | 30/48 | 65/75 | 已完成 |
| G500固定视觉更新 | 29/48 | 64/75 | 已完成 |
| H500持物恢复混合 | **37/48** | **65/75** | 完整完成，保留B |

H/E共同123项净多1成功，但开发+3、验证−2；H相对B验证修复2、丢失9。8来源中有E对照的六项为E2/6、H3/6，不能把H5/8全部归因于新增恢复数据。教师8/8是上一阶段数据采集结果，不是自主成功率。

## 本次审查新增的关键发现

1. **三个接管批次需要追查数值来源。** H更新19/33/48含107蓝、115绿、105红的相对0窗口，loss为1.223、140.411、0.162，E同一步明显较低。实际batch loss不能直接归因于某一条样本，下一步限定读取现存state/action、delta与原norm后数值。
2. **第416次尖峰是共有现象。** E/G/H该步loss约3.106/2.994/3.092，不能归罪H的113尾窗。
3. **恢复阶段与更新顺序强相关。** 八条真实接管帧仅在前56更新各出现一次；后段恢复起点集中于释放/退开。其影响尚待对照，优先级低于已有数值异常。
4. **粗失败标签不等于原因。** 107有双侧接触但未抬高；105到箱412帧只余8步。下一步按实际抓持、抬起、到箱与剩余稳定预算解释，避免修错阶段。

B第四关节state/action std约0.001662；教师位置平滑但IK保持reset姿态，是具体待查线索，尚未由服务器原始数组证实。下一轮先定位并修正监督；按计划7.2最多执行一个有明确改动的I500，不直接续H或增加恢复比例。

## 并行已经落实

H实际以两套独立服务/RNG/worker执行63/62分片，125项评测约12分46秒；训练约4分02秒。后续继续使用两路评测，CPU数据读取与结果解释并行。保持原种子、420/40、20Hz、horizon10、replan5。现场资源和任务状态由服务器读取，不抢占已有活动任务。

本次ChatGPT只读审查并发布计划，没有访问服务器原始NPY/NPZ、启动I或删除资料。旧“H尚未启动”的提示词已失效。

## 交付与保留

服务器完成计算 → 代码、实际配置、完整紧凑JSON与结论先推GitHub → 继续研究。大检查点、optimizer、视频、原始数组留服务器供用户导出备份，不在电脑下载或归档，不新增大文件发布队列。

H的运行记录明确大文件仍在服务器；小结果pushed不代表大文件已有远端副本。保留全部当前及后续训练/复现依赖，不自动删除研究资料，不停止活动训练、推理或上传。环境、共享OpenPI、基础权重、缓存、Git和其他项目保持原状。禁止哈希、冒烟、shape/mock/单元测试、回下载验证、恢复演练和全库重构。

## 复现范围与历史入口

当前是公开预训练π0的Piper颜色任务适配与闭环仿真，尚未完成论文规模预训练、完整基准或实机闭环。π0.5自定义任务尚未形成同等稳定结果。

| 历史工作 | π0 | π0.5 | 口径 |
|---|---:|---:|---|
| LIBERO/Panda pilot | 183/200 | 196/200 | 每任务5初态 |
| Piper迁移仿真 | 32/75 | 47/75 | 不同机器人与适配条件 |
| 旧颜色入盒 | — | 1500更新后0/15；D57复评3/15、0/15 | 历史失败保留 |

- [H原计划（完成）](docs/PI0_H500_PLAN_20261103.md)、[G历史审查](docs/PI0_G_COMPLETED_NEXT_REVIEW_20261103.md)、[E/F审查与论文对照](docs/PI0_REPRO_REVIEW_NEXT_PLAN_20261103.md)。
- [8条最终恢复数据](https://github.com/kaiwen123-yang/-0--0.5/blob/3dd547a169c7a821fabd278af3b86a1f3d099b95/results/piper-color-v1/pi0-held-recovery-20261103/final_report_zh.md)。
- [D57部署](docs/AUTODL_D57.md)、[路径](deployment/d57/paths.json)、[原项目说明](docs/PROJECT_README.md)、[上游来源](publication/upstream-provenance.json)。
- [总索引](ARTIFACT_INDEX.json)、[历史Release](https://github.com/kaiwen123-yang/-0--0.5/releases/tag/pi-complete-backup-20261101)。

旧LoRA1499缺optimizer、旧全参1000不完整，均不能替代B完整状态。历史上传/清理记录不改写，也不作为本轮自动执行指令。
