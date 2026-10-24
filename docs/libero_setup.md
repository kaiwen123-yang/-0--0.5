# LIBERO 仿真环境准备

核验日期：2026-10-23。目录：`/home/fanyuan/projects/kaiwen-learning/pi-reproduction`。

## 已验证到哪一步

- 五个官方评测套件的任务定义均可读取：`libero_spatial` 10 个、`libero_object` 10 个、`libero_goal` 10 个、`libero_90` 90 个、`libero_10` 10 个。
- `libero_spatial` 第 0 个任务：加载官方初始状态、reset、恢复初始状态、执行 10 个零位移/张开夹爪控制步，关节位置和速度为有限值；不创建渲染器。
- 同一任务另行完成 CPU 离屏渲染：Mesa `llvmpipe (LLVM 15.0.7, 256 bits)`，两路 RGB 相机均为 256×256，与上游评测的环境分辨率一致。图像已检查，能看到机械臂、桌面、碗、盘子等场景，非空白帧。
- 软件 EGL 明确选择带 `EGL_MESA_device_software` 扩展的设备。本机是编号 2；脚本动态识别，不把硬件设备编号 0 当作 CPU。先验证 GL_RENDERER 含 llvmpipe/softpipe，再创建 LIBERO 环境。
- NVIDIA GPU EGL 已在本轮闭环评测中实际验证：设备编号 0，vendor 为 `NVIDIA Corporation`，renderer 为 `NVIDIA GeForce RTX 5080/PCIe/SSE2`。该设备枚举与软件 EGL 不同；本轮双相机视频使用 GPU 渲染。
- `openpi-client` 已在本环境安装，用于后续连接独立运行的策略服务。仿真进程使用 PyTorch CPU 构建，模型进程使用独立 openpi 环境。

最初的 smoke 检查验证了环境、物理步进和 RGB 渲染。另行模型验收已在 5080 上加载 π₀/π₀.₅ 完整权重并各执行两次合成输入推理，见 `results/pi0-gpu-inference.json` 和 `results/pi05-gpu-inference.json`。**本轮真实模型闭环评测已完成：400 个 episode、400 段视频、400 份动作数组及 200 对初始条件均通过最终验收，零程序错误、零缺测。** 本轮目录为 `results/libero-comparison-20261023-212017`；训练和实机控制未执行。

证据：`results/libero_cpu_smoke.json`、`results/libero_render_smoke.json`、`results/libero_agentview_image.png`、`results/libero_robot0_eye_in_hand_image.png`，对应完整日志在 `logs/libero_*smoke.log`。

## 版本和与官方环境的差异

LIBERO 来源是 openpi 的官方子模块，提交 `f78abd68ee283de9f9be3c8f7e2a9ad60246e95c`。来源目录 `repos/openpi/third_party/libero`；没有修改算法或上游任务源码。

| 组件 | 本机版本 | 说明 |
|---|---|---|
| Python | 3.11.16 | 按本项目要求使用 kaiwen-learn 的解释器 |
| robosuite | 1.4.1 | 保留 openpi 官方仿真版本 |
| MuJoCo | 3.2.3 | 保留 openpi 官方锁定版本 |
| bddl | 1.0.1 | 保留 LIBERO 官方版本 |
| gym | 0.25.2 | 保留 LIBERO 官方版本 |
| NumPy | 1.26.4 | 官方 1.22.4 没有对应 Python 3.11 的常规 wheel |
| Numba / llvmlite | 0.61.2 / 0.44.0 | 替代 Python 3.8 锁中的 0.53.1 / 0.36.0 |
| PyTorch / torchvision | 2.7.1+cpu / 0.22.1+cpu | 替代官方 Python 3.8 的 torch 1.11+cu113；仿真不需 GPU tensor |
| SciPy / matplotlib | 1.14.1 / 3.9.4 | 使用 Python 3.11 wheel |

上游文档推荐 Docker / Python 3.8；本机适配版不能称为逐依赖一致的论文复现环境。`requirements.in` 是适配清单，`requirements.lock` 固定含哈希的完整依赖，`installed.freeze.txt` 记录实际安装结果。这里只安装仿真和策略客户端依赖，没有安装 LIBERO 旧有 lifelong-learning 训练栈。

兼容处理均在 `scripts/libero_bootstrap.py`：

1. 在项目目录生成 LIBERO 配置，避免首次导入交互提示或写入共享 `~/.libero`。
2. 为 PyTorch 2.6+ 默认的 `weights_only=True` 添加官方初始状态需要的 NumPy 数据类型白名单，不全局关闭受限加载器。
3. 软件渲染只使用系统已有 Mesa 库，没有安装或更换系统驱动/包。
4. 原版 Gym 和 robosuite 的维护提示保留在日志中；已通过实际物理步进。源码还注册了不在官方评测列表中的 `libero_100`，其任务表不完整；脚本只检查官方提供的五个套件。

## 重建与检查

所有运行入口通过 `scripts/run.sh libero`，实际执行文件仍是 `/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python`，依赖来自隔离目录 `envs/libero`。不要直接在基础 Conda 环境安装这些包。

```bash
/home/fanyuan/projects/kaiwen-learning/pi-reproduction/scripts/libero_setup.sh

/home/fanyuan/projects/kaiwen-learning/pi-reproduction/scripts/run.sh libero   /home/fanyuan/projects/kaiwen-learning/pi-reproduction/scripts/libero_smoke.py

/home/fanyuan/projects/kaiwen-learning/pi-reproduction/scripts/run.sh libero   /home/fanyuan/projects/kaiwen-learning/pi-reproduction/scripts/libero_render_smoke.py
```

这两个 smoke 脚本仅运行 CPU，不加载 VLA 模型。第二个脚本会覆盖上述示例 PNG 和 JSON 结果。配置在 `envs/libero/config/config.yaml`；示范数据集尚未下载。

## 本轮结果与闭环对比协议（已完成）

本轮记录目录：`/home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017`。完整协议保存在该目录 `manifest.json`，代码快照、环境冻结清单和 checkpoint 文件清单保存在 `provenance/`。本次不连接机械臂。

| 套件 | π0 成功数 / 次数（成功率） | π0.5 成功数 / 次数（成功率） | π0.5 − π0 |
|---|---:|---:|---:|
| Spatial | 45/50（90.0%） | 50/50（100.0%） | +10.0 个百分点 |
| Object | 49/50（98.0%） | 49/50（98.0%） | 0.0 个百分点 |
| Goal | 49/50（98.0%） | 48/50（96.0%） | −2.0 个百分点 |
| LIBERO-10 | 40/50（80.0%） | 49/50（98.0%） | +18.0 个百分点 |
| **总体** | **183/200（91.5%）** | **196/200（98.0%）** | **+6.5 个百分点** |

200 对匹配试验中，仅 π0.5 成功 16 对，仅 π0 成功 3 对，双方成功 180 对，双方失败 1 对。总体 Wilson 95% 区间分别为 π0 的 86.8%–94.6% 和 π0.5 的 95.0%–99.2%，仅作 episode 层面的描述；本轮小样本与任务内相关性的限制见下文。

[完整结果与全部视频](../results/libero-comparison-20261023-212017/comparison.html) · [配对视频精选](../results/libero-comparison-20261023-212017/highlights.html) · [成功率图](../results/libero-comparison-20261023-212017/comparison.png) · [套件 CSV](../results/libero-comparison-20261023-212017/per_suite.csv) · [逐轮 JSONL](../results/libero-comparison-20261023-212017/episodes.jsonl)

| 项目 | 固定设置 |
|---|---|
| 模型与权重 | 官方 `pi0_libero`、`pi05_libero`；JAX、BF16；同机依次运行 |
| 任务范围 | Spatial、Object、Goal、LIBERO-10 四套件，每套件任务 0–9 |
| 试验次数 | 每任务官方初始状态 0–4，共 4×10×5=200 次/模型、400 次总计 |
| 环境随机性 | 每个 episode 的 NumPy 与环境 seed 均重置为 7，支持跳过已完成 episode 后继续 |
| 策略随机性 | `7 + suite_index*10000 + task_id*100 + trial_index`，套件顺序取 `manifest.suites`；每轮首个请求重置服务端 JAX RNG |
| 配对依据 | suite、task、trial、初始状态 index/SHA-256、环境 seed、策略 seed 均一致 |
| 模型动作 horizon | π0 为 50；π0.5 为 10；保留各自官方配置 |
| 执行动作与采样 | 每次推理只执行前 5 步后重新规划；flow 去噪 10 步；控制频率 20 Hz |
| 初始等待与步数上限 | 先执行 10 个等待步；策略动作上限 Spatial 220、Object 280、Goal 300、LIBERO-10 520 |
| 图像与渲染 | NVIDIA EGL device 0；双相机原始 256×256，按官方处理旋转 180°、resize/pad 至 224×224 |
| 视频 | agentview 与 wrist 并排，448×224、H.264、20 fps；策略执行段加最后状态，帧数=动作步数+1 |

每项任务只取 5 个初始状态，属于首轮 **pilot**，没有使用官方入口默认的每任务 50 次。原样保留 LIBERO 环境默认 `hard_reset=True`；每轮 reset 后恢复对应官方初始状态并执行等待步。LIBERO 底层 `step()` 将 `done` 设置为 `_check_success()`，因此评测中的成功来自任务目标判定；达到本轮动作步数上限仍未成功则记为 failure，不把时间截断当作成功。

两模型的动作 horizon 和采样张量形状不同；虽然每对 episode 的策略 seed 相同，也**不代表两模型抽到了相同噪声**。本轮比较两份官方 LIBERO checkpoint 在各自配置下的端到端表现，差异还受训练与 checkpoint 选择影响，不能作为只有算法设计不同的受控消融。所有依赖差异仍适用前述说明；本轮不宣称复现论文表值。

`episodes.jsonl` 逐轮写入结果、初始状态哈希、两类 seed、执行步数、推理次数、视频/动作路径与异常。模型服务、套件日志在 `logs/`；进度看 `orchestrator-status.json` 和 `progress-episodes.json`。动作数组在 `actions/`，双相机视频在 `videos/`。程序错误记为 `status=error` 并停止当前套件，错误不会被静默当作普通策略失败；汇总仍将错误保留在成功率分母中，并单列错误数量。未运行 episode 另列缺测，状态为 `incomplete`。

统计包括各任务、各套件与总体成功数/分母，Wilson 95% 区间，以及相同初始条件下 π0.5 单独成功、π0 单独成功、双方成功、双方失败的配对计数。区间只是 episode 层面的描述，未校正同任务重复试验的相关性；不根据本轮小样本区间宣称统计显著优越。

## 同机恢复与最终结果检查

本轮已完成，不需要恢复。若后续中断运行需要同机继续，先确认旧调度进程已退出，避免两个进程写同一 run；恢复入口读取**已存在的 manifest**，不创建新实验。启动时核对保存的脚本快照，依次启停模型服务，跳过已完成且产物齐全的 episode。错误记录、残留 `.partial.mp4`、缺失视频/动作或脚本变化都会报错，需要先查明原因；恢复不会擅自覆盖这些记录。

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python -S scripts/run_libero_comparison.py \
  --run-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017
```

下列命令用于重新生成汇总、检查产物与出图，不启动模型推理。最终验收与绘图只接受完整且无错误的结果，本轮已满足这一条件：

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python -S scripts/summarize_libero_comparison.py \
  --run-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/validate_libero_artifacts.py \
  --run-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/plot_libero_comparison.py \
  --run-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero-comparison-20261023-212017
```

`summary.json`、`per_task.csv`、`per_suite.csv` 和 `comparison.html` 保存统计与全部视频链接。`artifact-validation.json` 核对完整试验网格、配对条件、有限动作数组、视频唯一性、H.264/分辨率/帧率/帧数/时长及文件 SHA-256；视频检查采用 ffprobe 元数据，不等于逐帧全解码。`comparison.png` / `comparison.svg` 为可分享图，`highlights.html` 为中文双视频页面，每个胜负类别最多选一对，按套件/任务/试验顺序取样。这些精选仅作示例，不能代表整体成功率；不会自动播放。

本轮 `summary.json` 的 `status=complete`，无错误/缺测、200 对配对完整；最终 `artifact-validation.json` 为 `status=passed`，记录了全部 400 段视频和 400 份动作数组的检查结果。

## 独立单任务调试

模型权重已准备并通过独立 GPU 推理检查；按 README 启动模型服务后，客户端可连接本机 8000 端口。以下旧入口用于单独调试，不用于恢复上面的配对实验；仅在 GPU 空闲且无其他模型评测运行时使用：

```bash
/home/fanyuan/projects/kaiwen-learning/pi-reproduction/scripts/run.sh libero   /home/fanyuan/projects/kaiwen-learning/pi-reproduction/scripts/libero_eval.py   --args.host 127.0.0.1 --args.port 8000   --args.task-suite-name libero_spatial --args.num-trials-per-task 1   --args.video-out-path /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/libero_videos
```

`libero_eval.py` 默认用 CPU 软件渲染，把显存留给模型服务。CPU 渲染吞吐较低；显式设置 `LIBERO_RENDER_BACKEND=gpu` 可选择 GPU EGL。GPU EGL 已在本轮配对评测入口中实测通过并投入使用，本机 NVIDIA 设备为 0；`MUJOCO_EGL_DEVICE_ID` 仍需按实际渲染后端的设备枚举设置，软件后端的编号 2 不能照搬给 NVIDIA 后端。

上游 openpi README 报告 π₀.₅@30k 的 Spatial/Object/Goal/Libero10 成功率为 98.8% / 98.2% / 98.0% / 92.4%，平均 96.85%；**这是官方参考结果，与本轮每任务 5 个初始状态的实测值不可混同**。本轮结果不表示已复现官方评测规模或论文表值。

来源：[openpi LIBERO 说明](https://github.com/Physical-Intelligence/openpi/tree/main/examples/libero)、[官方仿真依赖锁](https://github.com/Physical-Intelligence/openpi/blob/main/examples/libero/requirements.txt)、[LIBERO 项目](https://github.com/Lifelong-Robot-Learning/LIBERO)。
