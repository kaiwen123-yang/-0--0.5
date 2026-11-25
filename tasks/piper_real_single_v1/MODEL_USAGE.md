# 单相机 π0 / π0.5 模型接口与正式训练入口

**2026-11-25当前状态：π0.5全参10,000步及V01完成，候选9999；3060 Laptop6GiB已用原始Orbax/JAX统一内存完成本地推理与模型引导、SDK辅助抓放。完整策略自主抓放待接续。** 详见[部署计划与执行提示词](../../docs/PI05_FIRST_REAL_DEPLOYMENT_20261125.md)及[09:58现场回执](../../results/piper-real-single-v1/20261124_blue_red50_full/pi05_blue_sdk_field_20261125.json)。

先保留第二平台已跑的入口、环境与本地资产路径，不把旧PREPARATION_ONLY模板当当前实验状态。下文通用格式保留为接口说明；本批冻结数据为kinesthetic_manual_gripper_v1，六轴与夹爪监督来自未来50ms实测位置，不冒称主动CAN命令或力监督。当前实际配置为wrist；π0与π0.5各用自己的norm。

接口以OpenPI `215abfb217dbac7d5f1273282331b9b1866c0479`为依据，独立于旧`tasks/piper_color_v1`和B资产。ONNX／量化不是当前实机接续前置条件。

## 1. 模型输入、动作与时间约定

| 项目 | 契约 |
| --- | --- |
| `camera_rgb` | 一台真实相机的 RGB、HWC、uint8；不要传 BGR |
| `state` | 7 维：六个实测关节角 rad，随后为实测夹爪总开口 m |
| `prompt` | 当前任务的字符串指令 |
| `actions` | 七维监督目标，六关节rad＋SDK宽度m；本批kinesthetic合同取未来50ms实测值，其他来源须保留真实动作语义；观测/推理不要求此字段 |
| `camera_mount=external_fixed` | 真实图映射 `base_0_rgb` |
| `camera_mount=wrist` | 真实图映射 `left_wrist_0_rgb` |
| 其余图像槽 | 零占位且 `image_mask=False`，不构造第二视角 |
| `policy_hz=20` | 名义训练行与动作目标时间网格，间隔 50 ms；不是相机、推理循环或机械臂已实测达到的频率 |
| `action_horizon=10` | 示例沿用 10 个目标的 chunk；按名义网格为 0.5 s 的动作序列，不规定阻塞推理的重规划时钟 |

两份早期模板使用 `external_fixed`。11 月 20 日实际部署的两份配置均指定 `wrist`，来源为现场安装照。[D57 两模型目录和实际配置](../../results/piper-real-single-v1/20261120_194402/report_zh.md)

训练输入把每个 chunk 的前六维绝对关节目标减去该 chunk 起点的实测关节角。夹爪保持绝对开口。输出反归一化后加回同一起点关节角一次，再截取七维。模型内部保留预训练 `action_dim=32`，补维由 OpenPI 完成。

| 模型 | 状态输入 | 归一化 | 参数结构 |
| --- | --- | --- | --- |
| π0 | 连续状态 | mean/std | `gemma_2b` + `gemma_300m`，`freeze_filter=nnx.Nothing` |
| π0.5 | 保留离散状态进入提示词 | quantile | `gemma_2b` + `gemma_300m`，`freeze_filter=nnx.Nothing` |

两个模型分别使用自己的基础权重、norm、资产和 checkpoint。单相机屏蔽输入槽不等于上游图像编码自动减少至三分之一；本轮没有据此估算双任务显存。

## 2. 配置文件与必需字段

复制对应的 `pi0_full.example.json` 或 `pi05_full.example.json` 为实际配置。示例中的路径和训练决策为 `null`，没有填入未经确定的预算。`status=PREPARATION_ONLY` 是准备状态说明；入口按当前阶段实际所需字段和真实文件判断是否能够执行，不额外要求批准字段。

| 顶层字段 | 填写规则 | 使用阶段 |
| --- | --- | --- |
| `model_family` | `pi0` 或 `pi05` | 全部 |
| `camera_mount` | `external_fixed` 或 `wrist` | 全部 |
| `policy_hz` | 当前接口固定为 20 | 全部 |
| `action_horizon` | 当前示例为 10；必须与所用 checkpoint 和数据统计一致 | 全部 |
| `openpi_root` | 现有固定版本 OpenPI checkout 的绝对路径 | 全部 |
| `experiment_name` | 本次真实数据实验名，模型/安装变化时使用独立实验名 | 统计、训练 |
| `run_root` | 本次输出的上级绝对目录 | 统计、训练 |
| `dataset_root` | 本节所定义、已完成实际时间对齐的真实示范目录 | 统计、训练 |
| `base_params` | 对应模型的本地基础权重 `params` 目录；π0 与 π0.5 各填各自来源 | 训练 |

`training` 字段仅在正式训练时需要。保存样本推理不要求已决定训练预算，也不需要训练数据目录。

| `training` 字段 | 含义与空值规则 |
| --- | --- |
| `ema_enabled` | 明确填 JSON `true` 或 `false`；示例 `null` 表示尚未决定 |
| `ema_decay` | `ema_enabled=true` 时必须填具体衰减值；关闭 EMA 时可以为 `null` |
| `batch_size` | 正式任务的 batch，不据 96GB 规格自动推定双任务可用值 |
| `num_workers` | 当前任务的数据加载进程数 |
| `num_train_steps` | 本次正式训练的总目标更新步数 |
| `seed` | 本次实验随机种子 |
| `log_interval` | 训练指标记录步间隔 |
| `save_interval` | checkpoint 保存步间隔 |
| `keep_period` | 交给 OpenPI 的周期保留间隔；允许 `null` 表示不设置额外周期保留 |
| `resume` | 明确填 JSON 布尔值，决定是否恢复该实验已有 checkpoint |
| `warmup_steps` | 余弦学习率计划的 warmup 步数 |
| `peak_lr` | 该计划的峰值学习率 |
| `decay_steps` | 该计划的衰减步数 |
| `decay_lr` | 该计划的衰减终点学习率 |

入口遇到未填必需字段，打印 `NOT_RUN` 与字段名后返回，不会先对 `null` 做 `Path()` / `int()` 转换。准备统计阶段不要求训练预算或基础权重。统计和训练都要求真实示范及时间来源；训练还要求自己的 norm 已经存在。

## 3. 真实数据格式与 20 Hz 时间网格

这部分定义将来的训练文件接口，不在本轮决定遥操作/示教方案。当前 `observation_only` 记录若没有实际动作标签，保持其原有用途。

数据目录包含：

```text
dataset.json
index.json
alignment_manifest.json
episode_0001/state.npy
episode_0001/actions.npy
episode_0001/camera_rgb.npy
episode_0001/policy_timestamps_ns.npy
```

`dataset.json` 的实际文件必须明确声明：

```json
{
  "data_kind": "real_demonstrations",
  "camera_mount": "external_fixed",
  "action_representation": "absolute_joint_targets_and_total_opening",
  "policy_hz": 20,
  "timestamp_alignment_source": "alignment_manifest.json"
}
```

`timestamp_alignment_source` 指向存在的实际对齐记录，可以是相对 `dataset_root` 的路径或本机绝对路径。其内容应定位原采集会话及源文件，并记录时间域、原始相机/关节/夹爪/实际指令时间戳、各策略行取用了哪些源样本、对齐方法、实际时间差与缺帧处理。若清单只包含索引，必须继续指向这些实际逐行记录。这里的文件名只是格式说明，不创建空报告代替实测来源。

`index.json` 是 episode 列表，每项包含：

```json
{
  "directory": "episode_0001",
  "frames": 120,
  "split": "train",
  "prompt": "实际任务指令"
}
```

以上项中的目录、帧数和指令在真实数据生成时填写。`split` 按完整 episode 划分；统计只读取 `train`。

每个 episode 的 `state.npy`、`actions.npy` 均为 `[N,7] float32`，`camera_rgb.npy` 为 `[N,H,W,3] uint8`；同一行代表同一名义策略时刻关联的真实观测和实际目标。`policy_timestamps_ns.npy` 为 `[N]` 整数 ns，使用对齐报告声明的同一时间域，相邻行严格相隔 `50_000_000 ns`。它记录对齐后的策略网格，原始传感器和指令时间戳仍由来源记录保留；不能改写成“传感器曝光已同步”。

训练 reader 不接收未说明频率的任意数组，不在读取时隐式重采样。它要求 manifest 的 `policy_hz=20`、实际对齐来源文件，以及上述逐行网格。真实原始记录频率不等于 20 Hz 时，未来数据整理步骤须先按实际时间戳形成网格和来源记录，再交给训练。当前未实现该数据整理步骤，也没有把 H0 测量值复制成动作标签。

采样时从当前行取连续 `action_horizon` 个目标，限定在同一 episode 内；尾部不足时延用该 episode 最后一条实际目标。统计使用相同尾部规则和相同起点关节差分，避免统计与训练动作定义不同。

## 4. 正式执行入口

以下命令供真实数据与相应路径齐备后的现场执行，本轮不运行。使用已有 OpenPI Python 环境，在 π 仓库根目录执行；不重装共享环境。`--spec` 指向填写后的实际配置。

### 4.1 生成各自的真实训练统计

```bash
python -m tasks.piper_real_single_v1.train --spec /absolute/path/pi0_real.json --stage prepare-stats
python -m tasks.piper_real_single_v1.train --spec /absolute/path/pi05_real.json --stage prepare-stats
```

仅读取真实 `train` episode，计算 state 和变换后的 actions 统计。保存 mean、std、q01、q99；两个模型根据各自变换使用对应统计。写入各自资产及 `normalization.json`，不启动训练，不使用 heldout，不套用 B 的窄分布 norm。

### 4.2 启动一个明确的全参任务

```bash
python -m tasks.piper_real_single_v1.train --spec /absolute/path/pi0_real.json --stage train
```

π0.5 使用对应实际 spec 运行同一入口。该入口不创建第二个后台任务，不修改 JAX 显存分配设置，不自动切换为 LoRA。用户希望两者并行；是否能在单张 96GB 卡上同时正式运行，仍由后续对应配置的实际资源证据决定，不能从配置已准备推定并发容量已证实。

缺数据、自己的 norm 或基础权重时，输出 `NOT_RUN`。正式执行时写出 `run_spec.json` 和参数数量记录，然后调用现有 OpenPI 训练实现。参数数量记录能说明该任务实际参数结构是否全参，不能替代设备内存峰值测量。

输出目录：

```text
<run_root>/<model_family>/<experiment_name>/
  assets/piper_h_<camera_mount>_<model_family>_single_v1/norm_stats.json
  normalization.json
  run_spec.json
  parameter_counts.json
  checkpoints/<model_family>_piper_real_single_full/<experiment_name>/<step>/
```

`run_spec.json.resolved_paths.checkpoint_directory` 给出 OpenPI 实际 checkpoint 根目录。推理应选择其中一个已有 `<step>` 目录，而非外层 `checkpoints/`。

### 4.3 对一个保存的真实观测做只读推理

观测 NPZ 需要 `camera_rgb`、`state`、标量字符串 `prompt`，不要求 actions。使用单相机真实任务对应的已训练 checkpoint 及它随附的 norm：

```bash
python -m tasks.piper_real_single_v1.infer --spec /absolute/path/pi0_real.json --checkpoint /absolute/path/step --observation /absolute/path/actual_observation.npz --output /absolute/path/prediction.npz
```

缺必要模型字段、checkpoint、其自有资产或观测文件时输出 `NOT_RUN`。该入口不要求训练预算已经填写，不使用旧 B checkpoint 冒充完成单相机适配。

成功执行后写 `prediction.npz` 及同名 JSON，动作是七维绝对目标，`sent=false`。记录的单次 `inference_ms` 包括可能发生的首次编译，不能写作稳态端到端延迟或实测 20 Hz。此入口不打开相机、不发送 CAN，不构成实时自主控制器。

`infer.create_policy(spec, checkpoint)` 可被未来只读在线循环复用；直接调用方须已经在现有 OpenPI 环境设置导入路径，并提供完整模型字段。当前 CLI 根据 `openpi_root` 完成路径设置。

## 5. 本轮交付范围

已准备两模型共用的单相机接口、两份全参配置模板、真实数据 reader、显式统计/训练入口和保存样本推理入口。现场采集、时间关联和标定工具见本模块其他文件及当前项目计划。标定不阻塞上述接口准备；没有真实数据、norm、checkpoint 或模型运行记录时，各对应结果维持 `NOT_RUN`。
