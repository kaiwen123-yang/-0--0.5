# 蓝红 50 条实机示范：在 Chat 中独立复核

本批次使用 Piper H、单腕 DC1 和固定浅盘。每个布局抓蓝、抓红各一次。训练集有 20 个布局、40 条示范，独立验证集有 5 个布局、10 条示范。本页对应标签 `pi-real-blue-red-50-20261124`。审查数据只需要 Python 3.10 或更新版本和 NumPy，无需连接机械臂、安装 OpenPI 或启动训练。[Release 附件](https://github.com/kaiwen123-yang/-0--0.5/releases/tag/pi-real-blue-red-50-20261124)

## 给 Chat 的最小输入

1. 在 Release 下载 **reviewer-numeric.zip**。将该附件交给可执行 Python 的 Chat，即可复核数值、任务配对和采样窗口。包中包含 Stage A 的 3 份顶层 JSON，以及每条的状态、动作、网格时间、有效起点、行级来源和质量记录。夹爪单位是 SDK 开口米值。两指接触时的真实夹持力无法由宽度直接推算。
2. 若要检查实际拿的是哪种颜色、是否从盘外起抓、是否释放和空爪抬离，提供对应布局的腕图。按布局排列的 25 张图共包含 250 个观察时刻，图下注明原始帧号和相对任务起点时间。验证时同时查看该布局的蓝、红两条。抽查画面可以确认这些时刻的可见事实，画面外的接触和真实夹持力仍未知。[逐布局腕图索引](../results/pi-readiness/20261124/blue_red_50_review_frames/README.md)
3. 若需复核任意导出行的腕图，从完整数据 Release 中选取这一条 UUID 对应的附件及元数据附件。完整包中的 `camera_rgb.npy` 是 20 Hz 对齐后的 RGB 数组。选定原图受到时间网格采样约束，帧号可从 `row_sources.jsonl` 对应行的 `image` 字段追溯。完整数据包以 Release 列出的 UUID、文件名和字节数为准。查看 50 条全部数组时，将完整分卷解入同一个空目录。

可以把下面这段话连同附件发给 Chat：

> 解压 reviewer-numeric.zip，在含 dataset.json 的目录运行包里的 check_released_dataset.py。请显示实际输出，分别说明 train 和 validation 的 episode 数、蓝红配对布局数、20 Hz 网格行、有效行和十步窗口。解释完成十步依赖的真实来源、哪些窗口末尾需要补齐。用 T02-RB05 蓝块说明为什么操作者确认成功但 O 标记处可能没有完整有效窗口；再指出仅用这个数值附件无法检查哪些视觉事实。若收到对应腕图，请同时检查 C、O、E，并区分操作者确认与图中观察。

## 启动检查

从解压目录运行（此处 `.` 是含 `dataset.json` 的目录）：

```bash
python check_released_dataset.py .
```

完整包可使用仓库中的同一脚本：

```bash
python tasks/piper_real_single_v1/check_released_dataset.py /path/to/extracted-stage-a --require-rgb
```

完整性校验与内容检查分开进行。下载完整分卷后，先按 Release 清单核对每个文件的字节数和 SHA-256，再解压。检查脚本验证全体 ID、任务、split 和来源合同，通过元数据和数组形状区分纯数值包和完整图像包。完整模式要求每条的 RGB 形状为 `[N,480,640,3]`、类型为 `uint8`。含 RGB 的报告只代表这些结构检查通过，识别方块需查看像素。[独立检查脚本](../tasks/piper_real_single_v1/check_released_dataset.py)

## 可复算的预期结果

| 项目 | 训练 | 独立验证 |
|---|---:|---:|
| 正式示范（蓝 / 红） | 40（20 / 20） | 10（5 / 5） |
| 配对布局 | 20 | 5 |
| 20 Hz 网格行 | 26,572 | 6,788 |
| 有效行 | 22,032 | 5,582 |
| 可采样十步窗口 | 21,163 | 5,406 |
| 全部十步都来自实际连续行的窗口 | 20,893 | 5,352 |
| 在本条末尾重复最后一行的窗口 | 270 | 54 |

每行 `state.npy` 和 `actions.npy` 都有 7 列，顺序为六轴关节角（rad）和夹爪 SDK 开口（m）。动作是下一格时刻之前最近的六轴及夹爪实测值，两种来源都按行保存。校验器对相邻行验证上一步动作与下一步实测状态完全一致，并核对相应的关节与夹爪来源时间和样本 ID。它逐行读取 `training_row_valid` 和 `excluded_reasons`，将触及被排除行的十步窗口剔除，独立重算得到的起点须与 `valid_action_starts.npy` 完全相同。要独立重建**两个网格时刻之间瞬时发生的越限**，还需现场保存的高频原始 CAN 反馈。[质量报告](../results/pi-readiness/20261124/blue_red_50_quality_report_zh.md) · [逐条数值](../results/pi-readiness/20261124/blue_red_50_quality.csv)

两条示范共用布局编号，表示操作者在同一桌面摆放下分别完成蓝红任务。腕部相机随手臂移动；同一布局的两条首帧可以不同。C/O 标记来自操作者确认抓住和释放时的按键，运动可能先于按键发生。验证集的配对、session 和轨迹来源独立；实际泛化性能须由后续模型评估测量。

## 可追溯的例子

- **T02-RB05 蓝块。** O 标记开口 101.5 mm，超出本批 0–100 mm 的有效范围。O 标记自身没有有效十步窗口覆盖。该条仍有 539 个可用起点，C 到 O 之间可以观察到正确方向的开合变化。先看 `partial_mark_coverage` 输出，再用逐条 CSV、腕图索引和原始图编号核对。[逐条审查数据](../results/pi-readiness/20261124/blue_red_50_quality.json)
- **V01-FOUR01 蓝块。** 操作者 E、原始事件、任务尾帧均已保存，采集器在任务结束后的回零前置检查因 −0.1 mm 读数而拒绝封存。按原始 E 恢复，保留原始失败回执、更正的回执及出处。该条有 605 个有效起点，任务末尾约 11.66 s 无完整可用窗口。[验证配对回执](../results/pi-readiness/20261124/V01_FOUR01_passive_pair.json)
- **排除项。** T01-RB05 首轮两条抓反颜色；后续实际重录正确才纳入。T02-FOUR04 红块抓起之前已在目的浅盘，原蓝块成功保留为补充数据，后续另摆 FOUR04b 才形成正式配对。[抓反颜色的腕图](../results/pi-readiness/20261124/T01_RB05_color_review.jpg) · [起始布局核对](../results/pi-readiness/20261124/T02_FOUR04_layout_review.jpg)
