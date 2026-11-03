# π0 / π0.5：Piper H仿真、微调与复现资料

## 当前状态：G已完成，下一步回到真实持物状态（2026-11-03）

**正式最佳仍是B累计4020：训练211/240、验证72/75、旧独立测试53/60。G500已经执行，开发29/48、后排15/32、验证64/75，未超过B。停止视觉冻结续训路线，不重跑G或自动续至1000。**

- [G完成后的详细审查、下一阶段和服务器Codex启动提示词](docs/PI0_G_COMPLETED_NEXT_REVIEW_20261103.md)
- [最新G研究分支](https://github.com/kaiwen123-yang/-0--0.5/tree/codex/pi0-g-fixed-vision-20261103)
- [固定结果报告](https://github.com/kaiwen123-yang/-0--0.5/blob/3cffdb05d8caed0696754b80ee7bfd7bc6a3f2c0/results/piper-color-v1/pi0-g-fixed-vision-20261103/final_report_zh.md)
- [E/F及论文、官方代码的历史审查](docs/PI0_REPRO_REVIEW_NEXT_PLAN_20261103.md)

B自身已有“稳定抓持却未完成转运”的具体失败记录。下一步优先从实际训练失败状态生成完整恢复后缀，最多8个指定案例；先产出真实数据，再制定H训练配方，不继续凭猜测修改学习率、冻结范围或纠偏比例。新计划尚未执行。

main本次只更新文档入口；运行代码仍以上述研究分支及服务器后续真实改动为准。不要用main旧代码覆盖工作区。[旧G提示词](docs/PI0_NEXT_STAGE_PROMPT_20261103.md)保留为已执行记录。

**保留所有训练、续训及复现资料。上传完成不自动删除B/G、数据、optimizer、RNG、norm、轨迹或视频；只清理无活动依赖的传输临时副本。** 小结果先入Git，大产物后台交付，不在用户电脑归档，不让全量上传阻塞正常训练。

## 已有结果与边界

| 阶段 | π0 | π0.5 | 范围 |
|---|---:|---:|---|
| 官方LIBERO/Panda pilot | 183/200 | 196/200 | 每任务5初态，不是默认50次完整规模 |
| Piper H迁移仿真 | 32/75 | 47/75 | 新机器人与适配条件，不与Panda混为同一基准 |
| 旧颜色入盒适配 | — | 1500更新后0/15，D57复评3/15与0/15 | 教师成功不等于策略成功 |
| π0 B完整覆盖 | 211/240训练；72/75验证；53/60旧独立测试 | — | 当前正式基线 |
| E/F | 验证67/75、65/75 | — | 未超过B |
| 最新G500 | 验证64/75 | — | 未超过B，没有新独立测试成绩 |

当前是公开预训练模型的自定义任务迁移与微调复现；尚未复现论文的大规模异构预训练、跨家庭泛化或实机闭环。同一模型的多推理种子不等于多次独立训练。

## 当前交付与磁盘规则

历史E/F阶段曾按旧授权清理已发布副本；G启动时已完成所需B/v2输入恢复。当前保留政策覆盖旧自动删除安排，不再因为一轮结束就删除后续训练所需资料。个别原始轨迹如已在旧阶段清理，仅按具体需要恢复。

[2026-11-03 13:24 UTC（北京时间21:24）状态](https://github.com/kaiwen123-yang/-0--0.5/blob/3cffdb05d8caed0696754b80ee7bfd7bc6a3f2c0/publication/pi0-g-fixed-vision-20261103/delivery_status.json)记录：G资产23/52、历史381/616已上传，共264项pending。核心G研究结果已可读取，不必等大产物传完才分析。这是Git快照，不是服务器实时状态。

- [当前大文件Release](https://github.com/kaiwen123-yang/-0--0.5/releases/tag/pi-complete-backup-20261101)
- [逐组上传/删除回执](https://github.com/kaiwen123-yang/-0--0.5/tree/c912dc5efbbec7dce53361fe989bf71eac0b2351/publication/pi-ef-cleanup-20261102)
- [B定向恢复成员](https://github.com/kaiwen123-yang/-0--0.5/blob/c912dc5efbbec7dce53361fe989bf71eac0b2351/publication/pi-ef-cleanup-20261102/ab-b-checkpoint-2010.json)
- [v2定向恢复成员](https://github.com/kaiwen123-yang/-0--0.5/blob/c912dc5efbbec7dce53361fe989bf71eac0b2351/publication/pi-ef-cleanup-20261102/v2-training-data.json)

只推GitHub，不在用户电脑下载或归档。所有训练、续训、复现资料保留，清理只限无活动依赖的传输暂存和重复临时副本。源码、Git、全部环境、共享基础权重与其他项目保留。禁止哈希、冒烟等防御性检查、回下载及恢复演练。

服务器GitHub传输仅用官方AutoDL学术加速，禁止服务器/电脑VPN和自动回退。网络失败记录pending，不能删除未发布原件。详细当前要求见[AGENTS.md](AGENTS.md)。

## 代码、环境与历史资料入口

工作区：`/root/autodl-tmp/robot-repro/pi-reproduction`，现有π0、π0.5和仿真隔离环境继续使用。

- [D57部署说明](docs/AUTODL_D57.md)、[路径记录](deployment/d57/paths.json)
- [原项目说明](docs/PROJECT_README.md)、[最初π0优先路线](docs/PI0_FIRST_PLAN.md)
- [历史总索引](ARTIFACT_INDEX.json)、[上游来源](publication/upstream-provenance.json)
- [LIBERO结果](results/libero-comparison-20261023-212017/summary.json)、[Piper迁移结果](results/piper-h-expanded-20261024/summary.json)
- [旧fy5080资料Release](https://github.com/kaiwen123-yang/-0--0.5/releases/tag/fy5080-pi-artifacts-20261031)

旧LoRA1499只有推理参数/元信息，无optimizer；旧全参1000备份残缺，均不能替代B完整状态继续训练。历史文件中的归档、哈希、全部保留或VPN规则只代表当时记录；后续行动以2026-11-03计划与当前用户指令为准。历史README内容保留在Git提交历史中。
