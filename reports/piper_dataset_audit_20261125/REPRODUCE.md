# 在 AutoDL 复核

脚本只读第三方原件和已有自采示教，派生结果写入独立审计目录。首次运行要有可用空间容纳约 19.25 GB 原件及少量检查表与预览。使用本轮现有 Python 3.11 环境中的 requests、NumPy、SciPy、PyArrow、PyAV、Pillow、h5py 和 OpenCV。完整解码使用 CPU，每个视频解码器仅一个编解码线程。Git LFS 远端目录可以用普通 Git 读取指针，无需拉取 HDF5 大库。

将本目录的 `scripts/` 和 `review_issues.json` 放入独立审计根目录。D57 本轮根目录为 `/root/autodl-tmp/robot-repro/piper-dataset-audit-20261125`。命令在该目录运行。

```bash
audit_root="$PWD"
py=/root/autodl-tmp/robot-repro/pi0/openpi/.venv/bin/python
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
mkdir -p raw sources checks tables previews logs
"$py" scripts/acquire.py "$audit_root" --endpoint https://hf-mirror.com --workers 32
"$py" scripts/robomind.py "$audit_root"
"$py" scripts/video.py "$audit_root" --workers 10
"$py" scripts/arrays.py "$audit_root" --workers 4
"$py" scripts/hdf.py "$audit_root"
"$py" scripts/synchrony.py "$audit_root" --workers 7
"$py" scripts/reference.py ../piper-real-single-v1/data/blue_red_direct_20261124_50_v1 checks/reference.json
"$py" scripts/metadata.py "$audit_root"
"$py" scripts/representation.py "$audit_root"
"$py" scripts/phases.py "$audit_root"
"$py" scripts/catalog.py "$audit_root"
"$py" scripts/publisher_notes.py "$audit_root"
"$py" scripts/tables.py "$audit_root"
"$py" scripts/finish.py "$audit_root"
"$py" scripts/registry.py "$audit_root"
"$py" scripts/previews.py "$audit_root" --full A/152 stack-bowls/260 stack-bowls/319 hang-cup/105 hang-cup/187 fold-towel/41 fold-towel/213 fold-towel/393 press-button/217 press-button/360 C/22 C/31 D/77
```

可在下载期间并行运行 `video.py --watch`。完整文件在大小及远端摘要通过后才从暂存名改为正式名。中断后重跑相同命令，HTTP 请求从现有前缀继续，服务器返回全量响应时从头重写临时文件。数组、解码和同步检查按回合或视频保存结果。对于尚未取得完整相机组的回合，下载完成后再跑一次 synchrony 和 previews。若要用不同算法重新计算某项统计，给新计算选用独立的 checks 目录。修改审计代码后需要重新生成该项派生结果。

本轮还使用了反向文件顺序的 HTTP 路径和 `fill.py` 补齐慢文件。后者只请求缺项并优先取得待视觉审阅的文件，已有预览选择清单时可用 `"$py" scripts/fill.py "$audit_root" https://hf-mirror.com 64`。可选 `hub_relay.py` 从标准输入接收本轮 Hub 锁清单的 JSON 数组，只向本机回环地址提供固定 SHA、固定路径的公开 Hub 文件，以内存缓冲转发。Xet 试用脚本接受来源键并逐个核对 LFS SHA-256。复核者用单条可用 HTTP 路径即可完成。最终核对独立重读所有原件。

现场原始 CAN 与导出的比对可只读执行以下命令。标准输出是每个来源的行数、误差和发送记录计数。

```bash
python3 scripts/field_feedback.py /home/kaiwen/research/pi-q12-data
```

## 表格和定位

- `files.csv.gz` 给出来源相对路径、D57 绝对路径、字节数、远端 LFS SHA-256 或 Git blob、实测 SHA-256、写入与核验时间。Git 的普通 blob 校验包含标准对象头。
- `episodes.csv.gz` 包含全部回合。每维分布按最小、P1、P50、P99、最大排列，变化量是相邻记录的绝对差。恒定段长度以相邻间隔数计，帧号从 0 开始。详细时序与相应帧号保存在 `checks/arrays/<来源>/episode_XXXXXX.json`。
- `lags.csv.gz` 逐任务、维度和偏移保存计数、精确相等次数和平均绝对误差。正偏移 k 比较 action[t] 与 state[t+k]。为给所有统计提供同一“下一步是否运动”定义，分相位表不使用回合末行作锚点。每个偏移只用回合内合法交集，分母随偏移变化。同帧全行统计另含末行。在该维 state[t+1] 与 state[t] 精确不同的样本记为 moving，其余记作 still。
- `arm_phases.csv.gz` 和 `arm_phase_lags.csv.gz` 给出一整侧机械臂的分段及对照。六轴任一每步绝对差大于 0.001，或夹爪大于 0.0005，算为该侧运动。阈值使用原始数值，仅辅助排除低幅抖动。大跳定位另用 0.2 与 0.025，均为人工检查触发条件。
- `videos.csv.gz` 给出视频原始时基、首末 PTS、解码帧数和间隔范围。所有不同间隔及次数、非众数间隔位置、错误位置在 D57 的 `checks/video/<原相对路径>.json`。有规律的非均匀 PTS 保留为时序特征。HDF5 内的 JPEG/PNG 按相机和模态各计一条流。
- `synchrony.csv.gz` 逐视频比较从各自首帧起算的 PTS、表内时间和同回合其他相机。32×24 灰度相邻帧的平均绝对像素变化用来筛查哪一路腕图在动，压缩、曝光和运动物体也能产生变化。E 的逐流原始类型、时钟、统计量和图像解码明细见 `hdf/`。
- `duplicates.csv.gz` 同时检查文件 SHA-256 和状态动作串联的完整轨迹 SHA-256。疑似重复筛查在相同维度上比较 24 个均匀选取的实有观测行，各关节差不超过 0.01、夹爪差不超过 0.001。该方法可能漏掉变速、截短、换视角或重标注的重复示教。仓库同名搜索见 `public_documents.json`。
- `fields.json`、`sidecars.json`、`tasks.csv`、`action_semantics.csv`、`visual_review.csv`、`issues.csv.gz` 与 `candidates.csv` 可分别按来源或回合查询。HDF 原件定位采用文件路径加内部数据集键。D 的附加标注可用 episode_index 和 frame_index 关联回主表。
- `completion.json` 由最后一次文件重读、逐回合及逐相机覆盖检查生成。`robomind_remote_catalog.csv.gz` 中除五条取样外均为远端指针信息，不能计为已下载轨迹。人工视觉结论作为文字保存，重新生成联系表不等于重新审阅。
