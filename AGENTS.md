# π0 / π0.5 项目执行约定

远端：https://github.com/kaiwen123-yang/-0--0.5 。本仓库保存 fy-5080 历史工作和 D57 后续复现准备。

- 默认计算机 autodl-d57，工作区 /root/autodl-tmp/robot-repro/pi-reproduction。fy-5080 原目录仅作历史来源，不修改其已完成结果或其他人的任务。
- 先读 README.md、ARTIFACT_INDEX.json、docs/AUTODL_D57.md 和直接相关任务源码。历史文档中的“当前/下一步”只属于其记录日期。
- π0 和 π0.5 使用各自隔离环境；不得修改 Conda base、MPC-RL、SuperMimic 的包或正在运行的作业。GPU 仍共享，执行前核对实际占用。
- 本次任务仅发布、迁移和准备，没有授权开始新训练、重评或实机动作。以后按用户具体任务执行。
- LIBERO 183/200 与 196/200 是每任务 5 初态 pilot；Piper H 32/75 与 47/75 是更换机器人后的迁移仿真，不混为一套基准。
- 颜色入盒是 π0.5 实验：165 条合成示范；LoRA 1500 updates 后完整任务验证 0/15。保留失败，不以抬升替代入盒、松爪与稳定成功。
- LoRA 1499 本地只有推理参数和资产，没有优化器状态。全参 1000 本地备份不完整，不作为可恢复训练检查点。不得根据云端旧 inventory 声称本地文件完整。
- 原 120/15/30 布局划分、数据动作语义和原始记录保留；从臂反馈是 observation，实际发送的目标是 action。
- 不新增通用 fallback、无限重试、单元/mock/冒烟/导入/形状测试套件或流水报告。用实际完整任务和必要的发布完整性检查推进。
- 原 2026-10-25 Git 归档不覆盖、不 force-push。新增大文件使用 Release，索引记录真实大小、摘要和位置；源码/配置/紧凑结果用 Git。
- 凭据、SSH 私钥、认证配置、安装缓存和环境包二进制不发布。官方基础/任务权重保留原来源及校验清单，避免重复镜像。
- 所有新计算与大文件发布在服务器完成；不在用户电脑再次下载、压缩或归档。

## 2026-10-31 后续指令与状态
- 用户已授权 D57 入口适配、旧 LoRA 完整闭环复评、失败诊断和及时提交 GitHub；本轮没有启动新训练或硬件动作。
- 当前路线按用户倾向先专注 π0，再进入实机数据和闭环，最后推进 π0.5。具体下一轮方案见 docs/PI0_FIRST_PLAN.md；这是方案，不是已经执行的训练。
- D57 旧 LoRA 两次完整验证为 3/15 和 0/15，不能只保留较好一次。教师回放/前缀介入不计入自主成功率。运行索引 results/piper-color-v1/d57-recovery-20261031/index.json。
- 新仿真入口 scripts/run_piper_color_d57.sh；独立环境 runtime/d57-color-sim。保留旧仿真与模型配置，历史路径脚本不直接整套重跑。

## 2026-10-31 π0 六示范运行
- 用户已授权执行第一步 π0 六示范 LoRA；固定 2,010 updates，不自动扩大到全部数据、π0.5 或硬件。
- 使用 tmux `pi0-six-demo-20261031`；稳定后退出前台。独立目录 `outputs/pi0-six-demo-20261031`，执行与结果状态读 `run.json`，不要重复启动同一任务。
- 用户要求每次更新详细记录，且每 500 次更新推送日志到 GitHub。当前发布分支 `codex/pi0-six-demo-20261031`，500/1000/1500/2000/2010 与评测完成时自动提交。不要在后台运行时切换其工作区分支。
- 入口、完整检查点、固定采样顺序与评测约定见 `docs/PI0_SIX_DEMO_RUN.md`。完整模型及视频仍在 D57，Git 日志推送不等于大文件已上传。

- 2026-10-31 23:17：本轮 2,010 updates 与 36 次完整评测已结束，tmux exit=0。最终两个种子均 2/6，开发门槛未通过；失败诊断见 results/piper-color-v1/pi0-six-demo-20261031/ANALYSIS_zh.md。禁止将已结束会话当作卡住而重复启动；没有新的训练预算授权。

## 2026-11-01 诊断与下一轮方案
- 用户授权四项失败任务诊断、仿真对照和及时发布；本轮无训练更新或实机动作。诊断输出 `outputs/pi0-failure-diagnosis-20261101`，发布分支 `codex/pi0-failure-diagnosis-20261101`。
- 原设置自主结果仍为 2/6、2/6。教师前缀和改接触参数的结果是诊断介入，不改写原成绩。
- 发现原软接触配置的长时间滑移；impratio=10 是经教师静态/完整回放核验的候选，尚未永久修改原 sim.py 或重生成训练数据。
- 下一轮方案见 `docs/PI0_120_DEMO_NEXT_PLAN_20261101.md`。用户问 120 条是否合适是方案讨论，不是启动新训练授权。后续按新指令执行，不自动续训旧 2010。


## 2026-11-01 用户授权执行 120 条 v2 下一阶段
- 当前用户明确授权按仓库计划启动下一步、tmux 训练、稳定后前台退出、逐次日志和每 500 次推送。上文旧日期的“未授权新训练”不适用于本次范围。
- 分支 `codex/pi0-120-demo-v2-20261101`，运行 `outputs/pi0-120-demo-v2-20261101`；不要切分支或重复启动。
- 先固定 v2 场景、六项教师完整回放及十秒持物、新 120 条训练数据和独立归一化；旧策略在同环境验证后才从 pi0_base 新初始化。
- 自动执行 2010/4020/8040 分段，每段训练六项和验证十五项各两种子；完整 schedule 固定 24120，8040 后先分析闭环证据，不自动把后两轮预算消耗完。
- 日志 Git 发布不等于大模型或视频已上传。完整检查点保留最近两个和评测节点，原始逐次日志全部保留。详见 docs/PI0_120_DEMO_RUN_20261101.md。


## 2026-11-01 120 条首轮完成后的退化诊断
- 用户授权分析 120 条退化原因、逐阶段轨迹对比及发布下一步方案。本轮冻结模型推理和教师前缀诊断已经完成，优化器新增更新为 0，独立测试集未使用。
- 原运行在 8040 正常完成并停在决策点，最终验证 1/15、1/15；不得因 tmux 仅剩 tail 日志窗口而误判为训练仍在运行。
- 主因的行为证据是初始指令条件弱化、接近/对准错误；十个旧成功新失败试验在 30/60/85 步教师前缀后为 8/10、10/10、10/10，均属于介入，不改写自主成绩。
- 完整分析 docs/PI0_120_REGRESSION_ANALYSIS_20261101.md；下一步 docs/PI0_120_REGRESSION_NEXT_PLAN_20261101.md。旧五轮与新一轮、不同 schedule 和归一化不能当作只改变数据量的实验。
- 新方案提出从旧 2010 状态 fork 两个有限预算、同学习率但不同前段采样的实验，尚未启动；当前指令只要求分析与方案发布。
- 诊断原始数组的 Release 与校验见 results/piper-color-v1/pi0-120-regression-diagnosis-20261101/raw_artifact_release.json；模型权重和视频仍在 D57。


## 2026-11-01 用户授权从旧 2010 执行 A/B
- 当前用户明确授权按最新方案运行 A/B，两组各新增 2010、tmux 顺序执行、逐次日志、每 500 次推送，稳定后前台结束。前文“新方案尚未启动/没有授权”仅描述旧任务。
- 分支 `codex/pi0-ab-old2010-20261101`，tmux `pi0-ab-old2010-20261101`，目录 `outputs/pi0-ab-old2010-20261101`。不要切换运行中的分支、重复启动或覆盖原实验。
- A 均匀采样，B 帧 0–9 / 10–61 / 62–267 以 40/30/30 概率采样；同一旧完整模型/优化器/RNG/归一化、同一 v2 120 条数据与固定 3e-6，局部更新和累计优化器计数分开记录。
- 500/1000/2010 节点完整评测和冻结输入诊断，保留方案的连续下降停止规则。A 因行为退化停止时 B 仍独立从原旧检查点开始；执行错误停止流水线。
- 详细约定见 docs/PI0_AB_OLD2010_RUN_20261101.md。每组最近两个完整检查点加验证候选，新增检查点总量不超过 60 GiB；所有更新和评测轨迹保留。不自动加预算、使用独立测试集或执行硬件动作。


## 2026-11-01 A/B 完成后的合并任务交接
- 原 A/B 已正常完成：两组各新增 2010，B 验证 15/15、15/15，训练六项 3/6、4/6；旧 tmux 的 dead=1、exit=0 是正常结束，不重新启动。
- 当前用户要求合并前三步并推送，由新对话完成。本次仅编写交接资料，没有新增训练/评测。任务入口 `docs/PI0_B_COVERAGE_CORRECTION_TEST_TASK_20261101.md`，合同 `experiments/piper-color-v1/pi0-b-coverage-correction-test-20261101.json`。
- 本任务分支 `codex/pi0-b-coverage-correction-test-20261101`。新对话接到执行指令后，覆盖评测→条件纠偏 C/D（各最多1000新更新）→候选冻结→一次60试验独立测试，属于一个完整任务，不为正常阶段转换重复询问。
- 指定起点是 B 的 ab_old2010/2010，累计优化器4020，不是最早六示教2010。新训练局部/累计更新、样本偏移和RNG单列。
- 纠偏只用训练布局；测试开始前冻结并推送候选，不用测试成绩换模型或再训练。实机与π0.5不在范围内。保存所有失败，发布待补传按实际状态报告。


## 2026-11-01 条件性存储清理请求
- 用户要求“如果 π 系列数据已经全部推到 GitHub，则删除 AutoDL 相关存储”。核对结果尚未全备份，未执行删除。详情 docs/PI0_STORAGE_BACKUP_STATUS_20261101.md 与 publication/pi0-storage-audit-20261101.json。
- 后三轮 π0 完整检查点、v2 数据及原始视频/轨迹仍有未备份部分；日志 push 和历史 Release 不等于这些文件全部已上传。下一任务继续依赖 B 完整状态与冻结数据，清理/迁移后必须重新验证实际路径。


## 2026-11-01 明确授权完整备份、验证恢复后清理
- 最新用户指令已明确要求先把未备份 π 数据完整上传 GitHub Release，核对大小/SHA256、确认可恢复后删除对应服务器数据；其他项目不动。此授权覆盖本轮白名单内经验证的数据清理，不需要再次询问。
- 恢复说明 docs/PI0_RELEASE_RESTORE_20261101.md，索引 publication/pi-complete-backup-20261101/index.json。只有全部组完成远端摘要、回下载、解包逐文件校验且索引已推送后，才删除原始数据。
- 本轮完整恢复副本包含两套官方基础权重并附原许可。认证信息、已安装环境二进制和其他项目不发布；代码、Git 与隔离环境保留。
- 新合并任务仍未启动，若来源数据已归档清理，必须先按恢复说明恢复最小 B 集合并核对实际路径，不能从 base 新初始化代替 B 完整状态。


## 最新用户取消：停止 GitHub 备份和自动数据清理
- 用户已明确取消继续推送 GitHub；pi-complete-backup-20261101 已停止，自动源数据清理禁用，不得按此前授权自行重启。
- 核对6548个源文件仍在且大小/时间/身份未变；pi0、pi05、d57-color-sim环境均保留。仅清除了本次产生的临时压缩包与回下载副本，保留清单及日志。
- 新任务可使用现存原始B检查点与v2数据，无需因已取消的备份流程等待恢复。本条仅本地记录，不再推送GitHub。


## 2026-11-01 最新授权：三阶段实验与渐进上传
- 本次用户授权在独立 tmux 执行 B 完整覆盖→训练失败诊断/条件 C、D 各1000→冻结候选后一次60测试，正常阶段衔接无需再询问；稳定后允许前台结束。
- 旧备份已取消，现存 B/v2/环境直接使用；不等待备份完成，不运行 pi_release_backup.py，不做恢复验证、全库备份、清理或删除。上文取消指令历史保留；本次仅重新授权本段的渐进上传与实验 Git 发布。
- 本次独立单并发低优先级上传此前完成成果及新任务大文件，复用现有 Release 资产；现有服务器 VPN 仅作用于 GitHub 子进程。上传不能影响计算，不回下载，不全量扫描哈希，不重复镜像官方权重。
- 保留全部失败、原始数据、旧/新检查点及环境。两节点全保留，无删除保留策略。run.json 与独立 transfer progress 分别判断实验和上传状态。


## 2026-11-01 22:20 后用户调整网络方案
- 因用户 VPN 流量消耗，π 项目的 GitHub 传输改为仅使用官方 /etc/network_turbo 学术加速；已实测 API、git ls-remote 和实际 Release 上传。此条覆盖前文“只用 VPN、不用学术加速”的历史网络限制。
- 仅为 GitHub 子进程设置代理，不改全局配置或其他项目；官方代理失败则有界重试后待传，禁止自动回退用户 VPN。实验协议、预算和结果保留规则不变。


## 2026-11-02 latest network authorization
- User now permits the existing D57 server-local VPN after another academic acceleration interruption. This overrides earlier academic-only/VPN-prohibited transfer instructions for this project.
- Keep the current academic batch running. On its next transport failure, resume the existing queue using D57 Mihomo at 127.0.0.1:7890 in GitHub child processes only. Do not use the PC reverse tunnel or alter other projects/global proxy settings.
- Preserve receipts and failed attempts, reconcile remote name/state/size, and keep bounded retries. No new experiments or training are authorized by this network change.


## 2026-11-03 latest network instruction: VPN revoked
- User explicitly revoked all VPN use for this project. This overrides the 2026-11-02 server VPN fallback authorization.
- Only official AutoDL academic acceleration may be used for uploads, metadata queries, and Git pushes. Slow transfer is acceptable. Both server VPN and PC VPN/tunnel are prohibited; automatic VPN fallback is disabled.
- The VPN transfer batch was stopped. Resume the same queue through academic acceleration after reconciling remote names/states/sizes. Network failure leaves pending items and preserves originals. Do not restart experiments.
