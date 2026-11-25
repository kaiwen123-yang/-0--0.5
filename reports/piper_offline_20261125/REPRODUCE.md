# 从冻结原件复现

实际工作目录为 D57 的 `/root/autodl-tmp/robot-repro/piper-offline-20261125-v1`。code/ 是本分支 tasks/piper_external_v1/ 的运行副本。原始文件继续放在相邻的 piper-dataset-audit-20261125/raw/，原 PTS 复核缓存来自 checks/video/。以下命令在 D57 Bash 执行；为独立重算，将 work 设为新的同级目录，并从本分支取同一份代码。

```bash
base=/root/autodl-tmp/robot-repro
audit="$base/piper-dataset-audit-20261125"
local50="$base/piper-real-single-v1/data/blue_red_direct_20261124_50_v1"
work="$base/piper-offline-20261125-v1"
code="$work/code"
py="$base/pi0/openpi/.venv/bin/python"
py05="$base/pi05/openpi/.venv/bin/python"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export CUDA_VISIBLE_DEVICES="" JAX_PLATFORMS=cpu
export PYTHONPATH="$base/pi-blue50-source-7850136"
mkdir -p "$work/reports" "$work/review"
"$py" "$code/derive.py" "$audit" "$work/grid" --pilot
"$py" "$code/derive.py" "$audit" "$work/grid"
"$py" "$code/local_windows.py" "$local50" "$work/reports"
"$py" "$code/review_frames.py" "$audit" "$work/review"
"$py" "$code/recheck.py" "$audit" "$work"
"$py" "$code/bowl_frames.py" "$audit" "$work"
"$py" "$code/catalog.py" "$audit" "$work"
"$py" "$code/timing_summary.py" "$work"
"$py" "$code/quantization.py" "$audit" "$work"
"$py" "$code/split_check.py" "$local50" "$work"
"$py" "$code/prepare_eval.py" "$local50" "$work/reports"
"$py05" "$code/verify.py" "$audit" "$work" "$local50"
"$py" "$code/package_reports.py" "$work" "$work/publication"
```

数值与审阅脚本实跑于 Python 3.11.18、NumPy 1.26.4、PyArrow 20.0.0、PyAV 17.0.0 和 Pillow 11.2.1。

verify.py 使用真正参加训练的任务快照 `7850136cb28da98ec5e1a5e661eca256e6b17aac` 和 π0.5 的既有 OpenPI 环境。它调用 reader、图像槽打包和 delta 变换。脚本没有创建模型、读取模型参数或接触硬件。prepare_eval.py 生成评价键与未来的试验顺序，表格中的计划行不是执行回执。

## 查一个窗口

```bash
"$py" - "$work/grid/stack-bowls/000371" <<'PY'
import json, sys
from pathlib import Path
import numpy as np
episode = Path(sys.argv[1])
print(json.loads((episode/"source.json").read_text()))
with np.load(episode/"grid.npz") as grid:
    print("valid starts", grid["starts"])
    start = 16
    for key in ("query_ns","image_frame","image_pts","obs_row","obs_age_ns","target_query_ns",
                "target_row","target_age_ns","span_ns","segment","gap","missing","padded"):
        print(key, grid[key][start:start+10])
    print("source state", grid["state"][start])
    print("original action", grid["original_action"][start])
    print("absolute future source states", grid["future_state"][start:start+10])
PY
```

所有区间字符串均为包含两端的零基索引。grid_episodes.csv.gz 的 start_ranges 表示 20 Hz **网格**起点，gap_after_source_rows 表示**源**行号；源行与对应全局数据索引可通过固定 Parquet 的 frame_index 和 index 复查。缺失行保存最后可查行的指针，训练选择必须使用 starts、valid 及来源资格。相机路径、原始 action、原始时间列与原始状态列均由固定源 revision 和回合 ID 限定。A 的双视角补查图在 review/recheck_0.jpg 至 recheck_3.jpg，每组从上到下依次为 (2,12,18)、(34,65,73)、(104,136,152)、(160,197,198)；图中源帧号可直接定位。B 的额外正面帧和 A 全部六帧检查表也在 review/。

decisions.json 固定了本次人眼审阅结论。重新生成关键帧会复现取样和清单，新的审阅判断应另行版本化。C 的完整 examples、帧图和派生数组仅在 D57。现有 Git 只发布少量 A/B 对照图和回合/时间索引。生成的表格及预览可直接和 publication/ 中的实跑产物对照。
