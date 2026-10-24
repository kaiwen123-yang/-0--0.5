# π0 / π0.5 · Piper H 仿真与微调实验归档

**状态：上传完成（2026-10-25）。130 个分卷已全部上传，文件数量与大小核对通过。** 按用户最终决定，仅保留源码、环境配置、日志、评测结果和全景视频；不上传权重、优化器或训练示范数据。完整归档约 1.08 GB。完成状态见 `ARCHIVE_STATUS.json`。

## 已核实结果（2026-10-24）

| 实验 | π0 | π0.5 |
|---|---:|---:|
| 原版 LIBERO / Panda | 183/200（91.5%） | 196/200（98%） |
| Piper H 适配扩展仿真 | 32/75（42.7%） | 47/75（62.7%） |

两行使用不同机械臂和实验条件，不能当作同一基准的直接比较。

颜色物体入盒任务：LoRA 完成 1500 步，验证完整任务 **0/15**；全参数执行至 1456 步被平台定时关机中断，最后已保存 checkpoint 1000。没有续训、没有全参数最终评测，不将抓起物体计为完整任务成功。教师示范 165/165 的通过率也不是学习策略成功率。

尚未连接或部署实机。计划硬件：Piper H、松灵官方夹爪（仿真默认 100 mm）、DaBai DC1 腕部相机、D435i 外部相机。未完成相机实物标定与真实机器人验收。

## 文件

- `scripts/`、`tasks/`、`models/`：适配、训练、评测代码。
- `docs/`：实验说明、公开数据调研、原项目说明；历史文档可能记载已取消的续训计划，以本页最终范围为准。
- `results/`：可直接查看的统计、环境锁定信息与恢复记录。
- `archives/source.tar.gz.part-*`：完整工作源码快照、上游源码及资源、论文、云端代码与配置。
- `archives/results.tar.gz.part-*`：全部本轮保留的实验日志、结构化结果、轨迹及视频。
- `cloud/`：补取的云端启动检查视频、教师检查结果和归一化配置。
- `docs/ARCHIVE_HANDOFF.md`：最终交接、失败结果含义和 AutoDL 中断记录。
- `archives/manifest.json`：逐文件清单、大小与明确排除项。没有重新计算校验哈希。
- `archives/piper-color-original-source-v1.tar.gz`：训练启动时的原始任务源码包。

## 恢复源码和结果

`ARCHIVE_STATUS.json` 已标记 `complete: true`。下载或克隆整个仓库，分卷须全部下载。

```bash
git clone https://github.com/kaiwen123-yang/-0--0.5.git pi-reproduction-archive
cd pi-reproduction-archive
mkdir -p restored/pi-reproduction
cat archives/source.tar.gz.part-* | tar -xz -C restored/pi-reproduction
cat archives/results.tar.gz.part-* | tar -xz -C restored/pi-reproduction
```

完整视频及 HTML 报告在 `restored/pi-reproduction/results/`。原版比较入口为 `libero-comparison-20261023-212017/comparison.html`；Piper H 扩展实验入口为 `piper-h-expanded-20261024/index.html`。保留对应子目录后，本地打开 HTML 即可查看视频。

云端代码另位于解压目录中的 `archive-upload/cloud-source-config.tar.gz`，内部保留 `pi05/` 与 `piper-color-v1/` 路径。环境可根据版本锁定文件、云端 `python_packages.txt`、`blackwell_environment.patch` 和安装脚本重新构建。旧脚本含原机器绝对路径，换机器前需要修改；运行入口原用 Python 3.11。

## 本次没有归档的内容

模型检查点及优化器、训练数据数组及数据 tar、可重新下载的安装缓存和完整已安装环境、Git 对象库、账户凭据不在本仓库。官方权重的来源与版本记录保留在文档和清单中。LoRA 推理参数此前已完整保存于 fy-5080 本地，**不在 GitHub**；全参数检查点没有完整本地副本，释放云端原存储后不能从该断点继续训练。

第三方源码和模型资源保留原许可证及来源；没有为未提供许可证的上游资源另行声明开源许可。
