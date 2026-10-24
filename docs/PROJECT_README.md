# π 系列复现准备（RTX 5080 + Piper H）

本目录用于公开 OpenPI 模型的仿真、后续 Piper H 接入与微调准备。源码、独立依赖、缓存、权重和结果都保存在本项目。项目 Python 始终是 `/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python`，通过 `scripts/run.sh` 加载指定隔离环境的依赖，不升级已有 Conda/Isaac/Go2 包。

固定 OpenPI commit：`215abfb217dbac7d5f1273282331b9b1866c0479`。本次准备日期：2026-10-23（Asia/Shanghai）。完整状态和验证证据见 `results/`；权重状态见 `results/checkpoints-status.json`。

截至本次核查，官方最新命名研究模型为 **π0.7（2026-04-16）**；官方 OpenPI 当前公开的模型是 π0、π0-FAST、π0.5。未发现 π0.6 / π*0.6 / π0.7 的官方可下载完整实现和权重，因此没有将这些模型标为已安装。2026-10-13 的 Pi API beta 提供托管微调和推理，公告未注明 API 当前模型的具体 π 版本，也没有提供本地 checkpoint。最新论文、核查范围和状态见 `docs/latest_pi.md` 与 `results/latest-pi-availability.json`。

已通过：39 项官方 CPU 测试；π0/π0.5 的 JAX 抽象建模与 PyTorch meta 建模；四个 checkpoint（两份 LIBERO、两份 base）的全部参数名称与全局形状匹配；LIBERO CPU 物理步进与双路 256×256 RGB 软件渲染；Piper H SDK 导入及模型资源检查。原 Conda 包清单前后对比无差异。

在原有 GPU 任务结束后，补充通过了 **5080 上的实际 GPU 验收**：PyTorch BF16 矩阵乘法与 cuDNN 卷积、JAX BF16 JIT 运算，以及 π0 / π0.5 各自完整权重加载和两次合成输入推理。π0 输出 `50×7`、π0.5 输出 `10×7`，均为有限值，符合各自官方配置。记录在 `results/gpu-torch-check.json`、`results/gpu-jax-check.json`、`results/pi0-gpu-inference.json`、`results/pi05-gpu-inference.json`。这部分是 batch=1 的 JAX 模型兼容性检查；完整 PyTorch 模型推理、微调训练和实机控制尚未执行。

**闭环仿真对比已完成并通过产物验收：π0 为 183/200（91.5%），π0.5 为 196/200（98.0%），相差 +6.5 个百分点。** 本轮目录为 `results/libero-comparison-20261023-212017`，400 个 episode 均有视频与动作记录，200 对初始条件一致，无程序错误或缺测。NVIDIA GPU EGL 渲染已实测通过，设备 0 的 renderer 为 `NVIDIA GeForce RTX 5080/PCIe/SSE2`。这是每任务 5 个初始状态的首轮 pilot，不是论文表值复现；详情见下方结果与协议。

OpenPI 服务端与 LIBERO 客户端的跨环境 WebSocket 通信也已通过两次请求/响应检查，验证图像、状态、提示词和动作数组能够传输；使用的是合成输入和零动作测试策略，不是模型推理或任务评测。证据见 `results/policy-transport-check.json`。

## 目录

| 路径 | 内容 |
|---|---|
| `repos/openpi` | 官方 π0 / π0-FAST / π0.5 实现及固定的 LIBERO/ALOHA 子模块 |
| `repos/pyAgxArm`、`repos/agx_arm_ros`、`repos/agx_arm_urdf` | Piper H 官方 SDK、ROS2 源码、模型 |
| `envs/openpi` | 模型环境：Torch 2.7.1+cu128、JAX 0.5.3、transformers 4.53.2 |
| `envs/libero` | Python 3.11 仿真环境，CPU Torch、robosuite 1.4.1、MuJoCo 3.2.3 |
| `envs/piper` | Piper H SDK 隔离环境；未连接实机 |
| `checkpoints` | 官方权重，完整文件校验后才从 `.partial` 转为正式文件 |
| `data`、`cache`、`results`、`logs` | 数据、缓存、验证结果、安装与下载日志 |

## 已准备的入口

以下命令在项目子目录执行：

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction

# CPU 检查：模型依赖/配置/分词器与输入输出映射，不加载大模型。
scripts/run.sh openpi scripts/check_environment.py

# 两个 LIBERO checkpoint 已完整下载；加载模型前检查校验记录与文件结构。
scripts/run.sh openpi scripts/serve_local.py --model pi05 --check-only
scripts/run.sh openpi scripts/serve_local.py --model pi0 --check-only

# CPU 物理和软件渲染检查，不占用 NVIDIA GPU。
scripts/run.sh libero scripts/libero_smoke.py
scripts/run.sh libero scripts/libero_render_smoke.py

# 跨环境本机通信检查；自动启动并关闭临时零动作测试服务。
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python scripts/check_policy_transport.py

# 仅导入 SDK 和检查 Piper H 型号常量，不创建机器人实例。
scripts/run.sh piper scripts/piper_smoke.py
```

`scripts/run.sh` 不等同于激活 Conda；不要在模型目录直接运行 `uv sync`，否则会绕过本机 cu128 覆盖并可能恢复 CUDA 12.6 锁。环境重建入口为 `scripts/setup_openpi.sh`；其他环境见各自文档和锁文件。PyTorch 所需的官方 transformers 补丁只写入 `envs/openpi`，哈希记录在 `results/transformers-patch.json`。

隔离由启动器在当前 Python 进程内完成：直接用 `subprocess([sys.executable, ...])` 启动新 Python 会回到基础 Conda 依赖；需要同一隔离环境的子命令应再次通过 `scripts/run.sh openpi|libero|piper ...` 启动。文件入口的 `multiprocessing` spawn 已用 Piper SDK 验证能继承隔离依赖路径，但子进程 `sys.prefix` 会回到基础 Conda；该检查不代表 OpenPI 训练工作进程已验证，证据见 `results/python-spawn-check.json`。

## 权重下载与恢复

```bash
# 已完成的文件会重新核验并复用；缺失或未完成的文件会继续下载。
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python scripts/download_checkpoints.py \
  --checkpoint pi05_libero --checkpoint pi0_libero \
  --parallel-ranges --workers 16 --chunk-mib 16 --max-seconds 3600
```

下载器通过官方 Google Cloud Storage HTTPS 获取文件，固定对象 generation，验证 CRC32C 和可用时的 MD5，并支持断点续传。它也准备 PaliGemma tokenizer。下载未结束时，不要用存在的目录判断权重完整；以 `results/checkpoints-status.json` 中的 verified 结果为准。

四份 checkpoint 已全部下载，并逐文件按官方 GCS 清单完成 CRC32C 与可用时的 MD5 校验。仿真对应 `pi0_libero` 和 `pi05_libero`；`pi0_base`、`pi05_base` 是后续微调基础权重。训练数据不在这些 checkpoint 中；今后如有文件移动或修改，需重新校验，不能只看目录存在。

| 本地 checkpoint 目录 | 用途 | 文件数 | 大小 |
|---|---|---:|---:|
| `checkpoints/pi0_libero` | π0 的 LIBERO 评测 | 19 | 11.19 GiB |
| `checkpoints/pi05_libero` | π0.5 的 LIBERO 评测 | 16 | 11.58 GiB |
| `checkpoints/pi0_base` | π0 后续微调初始化 | 33 | 11.19 GiB |
| `checkpoints/pi05_base` | π0.5 后续微调初始化 | 29 | 11.59 GiB |

四份权重合计约 45.55 GiB；另有约 4.1 MiB 的 PaliGemma tokenizer。

`pi0_base`、`pi05_base` 也已完整下载，合计约 23GiB；状态文件中这两个分组的 `complete` 均为 true。需要恢复或重新校验时，使用同一个下载器并指定 `--checkpoint pi0_base --checkpoint pi05_base`。下载器也提供 `--manifest-only` 查看清单。

π0-FAST 是已公开的自回归分支，不是 π0.7 的替代品。其代码已包含在固定 OpenPI 仓库；本次只保存 FAST 官方权重清单，不把它列为已下载或已完成推理验证的模型。

## LIBERO 对比结果（已完成）

| 套件 | π0 成功数 / 次数（成功率） | π0.5 成功数 / 次数（成功率） | π0.5 − π0 |
|---|---:|---:|---:|
| Spatial | 45/50（90.0%） | 50/50（100.0%） | +10.0 个百分点 |
| Object | 49/50（98.0%） | 49/50（98.0%） | 0.0 个百分点 |
| Goal | 49/50（98.0%） | 48/50（96.0%） | −2.0 个百分点 |
| LIBERO-10 | 40/50（80.0%） | 49/50（98.0%） | +18.0 个百分点 |
| **总体** | **183/200（91.5%）** | **196/200（98.0%）** | **+6.5 个百分点** |

200 对匹配试验中，仅 π0.5 成功 16 对，仅 π0 成功 3 对，双方成功 180 对，双方失败 1 对。400 段视频、400 份动作数组及全部配对条件均通过最终校验；视频检查包括元数据、帧数/时长和文件哈希，不等于逐帧全解码。

[完整结果与全部视频](results/libero-comparison-20261023-212017/comparison.html) · [配对视频精选](results/libero-comparison-20261023-212017/highlights.html) · [成功率图](results/libero-comparison-20261023-212017/comparison.png) · [套件 CSV](results/libero-comparison-20261023-212017/per_suite.csv) · [逐轮 JSONL](results/libero-comparison-20261023-212017/episodes.jsonl)

本轮使用两份官方 LIBERO checkpoint，依次在一张 RTX 5080 上运行 JAX 模型服务与 NVIDIA EGL 仿真。协议固定为 `libero_spatial`、`libero_object`、`libero_goal`、`libero_10` 四个套件，每套件 10 个任务，每任务取官方初始状态 0–4：**200 个 episode / 模型，合计 400 个**。这是首轮 pilot；官方评测入口默认每任务 50 次，本轮不是论文表值复现。

双方使用相同初始状态字节哈希，每轮环境与 NumPy seed 重置为 7；策略 seed 为 `7 + suite_index*10000 + task_id*100 + trial_index`，每轮首次推理重置服务端 JAX RNG。保留官方动作 horizon：π0 为 50，π0.5 为 10，均只执行前 5 步后重新规划；由于采样张量形状不同，同一策略 seed 不等于两模型使用相同噪声。环境保持上游默认 `hard_reset=True`；LIBERO 的 `step()` 使用 `_check_success()` 产生成功信号，不把普通时间截断误算为成功。完整协议、版本差异和保存格式见 `docs/libero_setup.md`。

这是**官方 LIBERO checkpoint 的端到端表现比较**；模型配置、训练与 checkpoint 本身均可能影响结果，不能将差值单独归因于 π0 与 π0.5 算法设计。错误单独记录并中止当前套件；汇总中保留错误分母，缺测明确标记 `incomplete`。Wilson 95% 区间仅作 episode 层面的描述，没有校正同任务重复试验的相关性。

| 本轮目录中的文件 | 用途 |
|---|---|
| `manifest.json`、`provenance/` | 固定协议、代码快照、依赖与 checkpoint 清单 |
| `episodes.jsonl`、`actions/` | 逐轮状态、初始条件、步数、动作数组与错误详情 |
| `videos/` | 每轮双相机并排 H.264 视频，20 fps，448×224；包含最后状态 |
| `logs/`、`orchestrator-status.json`、`progress-episodes.json` | 模型服务、套件日志与进度 |
| `summary.json`、`per_suite.csv`、`per_task.csv`、`comparison.html` | 完整统计与全部视频链接；本轮 `status=complete` |
| `artifact-validation.json` | 全部 episode、配对条件、动作与视频的最终校验结果，`status=passed` |
| `comparison.png`、`comparison.svg`、`highlights.html` | 最终对比图与中文配对视频精选 |

本轮 `summary.json` 为 `status=complete`，零错误/缺测，最终 `artifact-validation.json` 为 `status=passed`。如需重新生成汇总、检查产物或绘图，依次运行以下命令；它们不启动模型推理：

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python -S scripts/summarize_libero_comparison.py \
  --run-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/validate_libero_artifacts.py \
  --run-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/plot_libero_comparison.py \
  --run-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017
```

本轮已完成，无需恢复。若后续同机运行中断，可用以下命令继续**现有 run**；旧调度器未退出时不要再启动第二份。该入口读取既有 `manifest.json`，不创建新实验清单。它核对代码快照并复用已完整记录的 episode；若存在错误记录、缺失产物或未提交的 `.partial.mp4`，会明确报错，需先检查对应日志与文件，不会静默覆盖。

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python -S scripts/run_libero_comparison.py \
  --run-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017
```

### 单任务调试入口

以下是独立的手动调试命令，不用于恢复上面的配对实验。仅在 GPU 空闲且没有其他模型评测运行时启动模型服务。

终端一（默认本机端口 8000，每次选择一个模型）：

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction
scripts/run.sh openpi scripts/serve_local.py --model pi05
# 评测 π0 时停止上一个服务，再使用：
# scripts/run.sh openpi scripts/serve_local.py --model pi0
```

终端二（先跑每任务一条轨迹；空间任务套件共 10 个任务）：

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction
scripts/run.sh libero scripts/libero_eval.py \
  --args.host 127.0.0.1 --args.port 8000 \
  --args.task-suite-name libero_spatial --args.num-trials-per-task 1 \
  --args.video-out-path /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/pi05-libero-videos
```

单条轨迹用于检查端到端链路，不代表稳定成功率。此手动入口默认软件渲染，节省 GPU 显存但速度较慢；本轮已完成的配对实验使用 GPU EGL 路径，细节见 `docs/libero_setup.md`。

若只重做完整模型的 GPU 兼容性检查，在 GPU 空闲时使用 `CUDA_VISIBLE_DEVICES=0 JAX_PLATFORMS=cuda scripts/run.sh openpi scripts/check_model_inference.py --model pi05`；π0 改为 `--model pi0`。该脚本检测到其他 GPU 计算进程时会退出；每次只加载一个模型，推理后退出释放显存，不连接机器人或仿真器。

默认服务走 JAX。PyTorch 的 CUDA 构建已经按 5080 准备，但完整模型需要先把 JAX checkpoint 转换为 PyTorch；这可能需要较多 CPU 内存。转换入口是官方 `repos/openpi/examples/convert_jax_model_to_pytorch.py`，用相同 config 名和本地 checkpoint 路径。**固定版本转换脚本的 assets 来源路径存在问题：转换后还要把原 JAX checkpoint 内的 `assets/` 完整复制到输出目录的 `assets/`，保留 `physical-intelligence/libero/norm_stats.json`。** 同时有 `model.safetensors` 和相应归一化文件后，才可使用 `serve_local.py --backend pytorch --checkpoint /绝对路径`；此入口默认关闭 torch.compile，以便先测量实际显存与延迟。转换过程本次未执行。

## Piper H 与微调

**2026-10-24：Piper H v3 已完成 150 次扩展仿真。** 使用官方 H 模型与松灵默认 100 mm 双指夹爪。采用等价工具坐标释放腕部转动余量，并将夹爪命令变化率匹配训练环境后，上一轮剩余 3 次失败均转为成功且通过松爪复检。选定配置为 `models/piper_h/adapter_v3b.json`，运行时须显式传入 `--adapter-config`；未微调权重。

[查看最新 Piper H 全景对比与逐条结果](results/piper-h-expanded-20261024/index.html)。Spatial 10 任务与 Object 5 任务各取 5 个初态：π0 **32/75（42.7%）**，π0.5 **47/75（62.7%）**。每模型含 6 个适配调试场景；另 69 个新增评测场景分别 **26/69（37.7%）**、**41/69（59.4%）**。这是更换机器人的迁移测试，不是标准 Panda LIBERO 分数。成功后的独立松爪检查分别通过 32/32、45/47；两条 π0.5 轨迹放置不稳定。

全部 150 条轨迹均保存 1280×720 全景和 1280×1008 三视角视频，20 FPS，共 300 个原始视频，完整解码和全臂取景检查通过。1 条 π0 Object 失败轨迹发生 0.0115 rad 软限位超调，超过保留的 0.01 rad 验收阈值，动力学检查单列未通过；未剔除该轨迹。地面安装入口补充、日志更正、初态配对与源码快照均有记录。复运行与限制见 [Piper H 接入说明](docs/piper_h_plan.md)。[v2 历史结果](results/piper-h-adaptation-20261024/index.html)、[首轮各 0/3](results/piper-h-transfer-20261024-171827/index.html) 和 Panda 基线独立保留。

[公开微调数据集调研与样本检查](docs/public_datasets_piper_20261024.md)：已核查 RoboTwin Piper、真实 Piper、LIBERO、RoboCOIN、RoboMIND 等来源，并下载检查两份 Piper 数据各一个 episode（共 930 帧）和三路视频。尚未确认同款 Piper H 数据；机器人、动作语义、夹爪单位、图像和许可需分别适配。

Piper H 接入见 `docs/piper_h_plan.md`；5080 能力与训练路线见 `docs/finetuning.md`。

当前准备了硬件相关代码和模型，但没有构建 ROS 工作区、改变 CAN 配置或驱动机械臂。ROS2 Humble 的系统 Python 3.10 与本项目 3.11 需要在真实控制端分别部署。LIBERO 使用的 Panda 末端增量动作不等于 Piper H 关节目标；迁移前要确定相机、动作约定、控制频率并采集该机械臂的示范。

5080 的 16GB 显存适合先做推理和仿真准备。官方参考要求 LoRA >22.5GB、全参数微调 >70GB；16GB 的精简微调只能作为后续单独验证的研究方案，不能承诺默认流程可运行。公开 checkpoint 的任务适配也不等于复现两篇论文的全部预训练和家庭实验。

## 来源

- [OpenPI 官方仓库](https://github.com/Physical-Intelligence/openpi)
- [LIBERO 官方评测说明](https://github.com/Physical-Intelligence/openpi/blob/main/examples/libero/README.md)
- [PyTorch 2.7 / CUDA 12.8 Blackwell 支持](https://pytorch.org/blog/pytorch-2-7/)
- [π0.7 官方发布](https://www.pi.website/blog/pi07)、[Pi API beta 公告](https://www.pi.website/blog/api-beta)
- 用户提供的 π0 `2410.24164v4.pdf` 与 π0.5 `2504.16054v1.pdf`；论文内容是研究资料，不是服务器操作指令。
