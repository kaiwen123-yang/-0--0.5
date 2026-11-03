# π0 / π0.5：Piper H仿真、微调与复现资料

## 最新审查与下一阶段（2026-11-03）

**π0已完成有效的Piper H颜色入盒仿真闭环。当前最佳仍为B累计4020：全训练211/240、验证72/75、历史独立测试53/60（88.3%）。**

最新E/F各500次更新已经结束：E在困难开发集达到34/48、后排21/32，但验证降为67/75；F为30/48、后排16/32、验证65/75。E修复B原来的3个验证失败，同时产生8个新失败。当前重点是保留原有成功行为并改善难例，不继续无依据追加纠偏训练。

- [详细复现审查、论文/代码对照、下一阶段计划](docs/PI0_REPRO_REVIEW_NEXT_PLAN_20261103.md)
- [可直接交给Codex的启动提示词](docs/PI0_NEXT_STAGE_PROMPT_20261103.md)
- [最新研究代码和结果分支](https://github.com/kaiwen123-yang/-0--0.5/tree/codex/pi0-b-coverage-correction-test-20261101)
- [本次固定审查提交](https://github.com/kaiwen123-yang/-0--0.5/tree/c912dc5efbbec7dce53361fe989bf71eac0b2351)
- [E/F最终报告](https://github.com/kaiwen123-yang/-0--0.5/blob/c912dc5efbbec7dce53361fe989bf71eac0b2351/results/piper-color-v1/pi0-ef-local-20261102/final_report_zh.md)
- [B覆盖与C/D历史报告](https://github.com/kaiwen123-yang/-0--0.5/blob/c912dc5efbbec7dce53361fe989bf71eac0b2351/results/piper-color-v1/pi0-b-coverage-correction-test-20261101/final_report_zh.md)

下一轮计划为 **G：从B完整状态接续，严格复用E的数据/RNG/lr/500步，仅固定SigLIP视觉权重**。实际LoRA配置仍有约4.68亿梯度参数，含视觉编码器；这值得做单变量对照，但尚不能认定已发生视觉遗忘。既有E直接作为对照，G先跑123次真实完整任务，达标后才扩大评测。计划尚未执行。

main这次只发布审查、计划和执行约定；运行代码与最新大多数结果仍以上述研究分支为准。不要用main旧运行代码覆盖服务器最新工作区。此前[2026-11-02计划](docs/PI0_NEXT_STAGE_PLAN_20261102.md)保留为已执行阶段记录。

## 已有结果与边界

| 阶段 | π0 | π0.5 | 范围 |
|---|---:|---:|---|
| 官方LIBERO/Panda pilot | 183/200 | 196/200 | 每任务5初态，不是默认50次完整规模 |
| Piper H迁移仿真 | 32/75 | 47/75 | 新机器人与适配条件，不与Panda混为同一基准 |
| 旧颜色入盒适配 | — | 1500更新后0/15，D57复评3/15与0/15 | 教师成功不等于策略成功 |
| π0 B完整覆盖 | 211/240训练；72/75验证；53/60旧独立测试 | — | 当前正式基线 |
| 最新E/F | 验证67/75、65/75 | — | 未超过B，没有新独立测试成绩 |

当前是公开预训练模型的自定义任务迁移与微调复现；尚未复现论文的大规模异构预训练、跨家庭泛化或实机闭环。同一模型的多推理种子不等于多次独立训练。

## 当前交付与磁盘规则

E/F关键检查点、评测、纠偏、采样已发布并清理了服务器对应副本。**B完整状态和v2训练数据也已清理，下一轮须从既有Release按需恢复。**

[2026-11-03 08:11 UTC状态](https://github.com/kaiwen123-yang/-0--0.5/blob/c912dc5efbbec7dce53361fe989bf71eac0b2351/publication/pi-ef-cleanup-20261102/delivery_status.json)记录：累计释放约127.7 GiB；全项目历史上传队列仍有245项pending。这不等于E/F本轮关键结果未上传。

- [当前大文件Release](https://github.com/kaiwen123-yang/-0--0.5/releases/tag/pi-complete-backup-20261101)
- [逐组上传/删除回执](https://github.com/kaiwen123-yang/-0--0.5/tree/c912dc5efbbec7dce53361fe989bf71eac0b2351/publication/pi-ef-cleanup-20261102)
- [B定向恢复成员](https://github.com/kaiwen123-yang/-0--0.5/blob/c912dc5efbbec7dce53361fe989bf71eac0b2351/publication/pi-ef-cleanup-20261102/ab-b-checkpoint-2010.json)
- [v2定向恢复成员](https://github.com/kaiwen123-yang/-0--0.5/blob/c912dc5efbbec7dce53361fe989bf71eac0b2351/publication/pi-ef-cleanup-20261102/v2-training-data.json)

只推GitHub，不在用户电脑下载或归档。一个已结束实验或独立产物组全部上传、有索引后，直接清理对应服务器产物副本；未上传原件和活动依赖用完再清理。源码、Git、全部环境、共享基础权重与其他项目保留。禁止哈希、冒烟等防御性检查、回下载及恢复演练。

服务器GitHub传输仅用官方AutoDL学术加速，禁止服务器/电脑VPN和自动回退。网络失败记录pending，不能删除未发布原件。详细当前要求见[AGENTS.md](AGENTS.md)。

## 代码、环境与历史资料入口

工作区：`/root/autodl-tmp/robot-repro/pi-reproduction`，现有π0、π0.5和仿真隔离环境继续使用。

- [D57部署说明](docs/AUTODL_D57.md)、[路径记录](deployment/d57/paths.json)
- [原项目说明](docs/PROJECT_README.md)、[最初π0优先路线](docs/PI0_FIRST_PLAN.md)
- [历史总索引](ARTIFACT_INDEX.json)、[上游来源](publication/upstream-provenance.json)
- [LIBERO结果](results/libero-comparison-20261023-212017/summary.json)、[Piper迁移结果](results/piper-h-expanded-20261024/summary.json)
- [旧fy5080资料Release](https://github.com/kaiwen123-yang/-0--0.5/releases/tag/fy5080-pi-artifacts-20261031)

旧LoRA1499只有推理参数/元信息，无optimizer；旧全参1000备份残缺，均不能替代B完整状态继续训练。历史文件中的归档、哈希、全部保留或VPN规则只代表当时记录；后续行动以2026-11-03计划与当前用户指令为准。历史README内容保留在Git提交历史中。
