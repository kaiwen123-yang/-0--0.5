# 最新 π 系列的公开可用性（核查日期：2026-10-23）

目前官方已命名的最新研究模型是 **π0.7**，2026-04-16 发布；官方最新产品公告则是 **2026-10-13 的 Pi API beta**。二者都不能当作已提供本地源码和权重的 OpenPI 新版本。现有官方 OpenPI 可准备的模型家族仍为 **π0、π0-FAST、π0.5**。[π0.7 官方介绍](https://www.pi.website/blog/pi07)、[API beta 公告](https://www.pi.website/blog/api-beta)、[OpenPI README](https://github.com/Physical-Intelligence/openpi/blob/215abfb217dbac7d5f1273282331b9b1866c0479/README.md)。

| 项目 | 官方公开内容 | 本机复现状态 |
| --- | --- | --- |
| π0 / π0-FAST / π0.5 | OpenPI 源码、训练配置及 GCS 权重；π0.5 公开实现只支持 flow-matching head | 沿用项目内的 OpenPI 环境；各权重是否下载完成以 `results/checkpoints-status.json` 为准 |
| π0.6 / π*0.6 | 基础模型 model card；π*0.6 的 RECAP 论文与演示 | 本次核查未发现官方可下载源码/config/checkpoint；论文已保存，不能宣称已配好该模型运行环境 |
| π0.7 | 论文、技术介绍与演示 | 本次核查未发现官方可下载源码/config/checkpoint；论文已保存 |
| Pi API beta | 官方托管微调与推理流程，可向官方申请 beta | 公告未说明 API 当前模型的精确 π 版本；本次没有申请服务、安装客户端或上传数据 |

π*0.6 是 π0.6 加入 RECAP 强化学习后的模型。RECAP 利用示范、机器人自主执行、人工纠正和奖励反馈更新策略；它不是 π0.5 的普通 LoRA 配置。π0.6 官方 model card 使用 Gemma3 4B 主干和约 860M 参数动作专家，图像最高 448×448，所以现有 π0.5 环境和权重不能改个名字充当 π0.6。[π*0.6 官方介绍](https://www.pi.website/blog/pistar06)、[π0.6 model card](https://website.pi-asset.com/pi06star/PI06_model_card.pdf)。

π0.7 通过语言、执行质量/速度等元数据、控制模式及视觉子目标构造更丰富的条件，研究跨任务、跨场景和跨机器人的泛化。这里保存的是官方作者上传的论文，尚无经核实的本地权重下载地址，也不能据此承诺 RTX 5080 的显存足够运行或微调它。[π0.7 论文版本记录](https://arxiv.org/abs/2604.15483)。

本地新增资料：

- `docs/papers/2604.15483v2-pi07.pdf`：arXiv v2，2026-04-24，25 页；[固定版本下载地址](https://arxiv.org/pdf/2604.15483v2)。
- `docs/papers/2511.14759v2-pistar06.pdf`：arXiv v2，2025-11-19，18 页；[固定版本下载地址](https://arxiv.org/pdf/2511.14759v2)。
- `results/latest-pi-availability.json`：文件字节数、SHA-256、官方下载来源、版本信息及完整核查范围。

核查覆盖官方 GitHub 组织返回的 10 个公开仓库、OpenPI 的 6 个公开分支和 releases、README/模型文件/训练配置，以及官方 Hugging Face 组织模型列表和公开 GCS checkpoint 目录。官方 HF 当前只返回 `physical-intelligence/fast`，它是动作 tokenizer。OpenPI `main` 为 `215abfb217dbac7d5f1273282331b9b1866c0479`；未发现 π0.6/π0.7 的配置或下载项。这个结论只针对本次能公开访问的官方渠道，不能排除私有、需授权、其他名称或未来发布的资产。第三方复现与 LeRobot 移植不会被标成 PI 官方发布。[官方 GitHub](https://github.com/Physical-Intelligence)、[官方 HF](https://huggingface.co/physical-intelligence/models)。

π0-FAST 的代码和依赖已包含于现有 OpenPI 环境，但模型权重和 FAST tokenizer 是两种资产。静态核查发现 tokenizer 默认从 HF 动态加载代码，且未锁定 revision；正式准备时应保存并审查 `ec4d7aa71691cac0b8bed6942be45684db2110f4` 版本的 tokenizer 到本地，再指定本地路径。本次未实例化 FAST 模型或 tokenizer；该项不能视作推理验证通过。[官方 FAST tokenizer](https://huggingface.co/physical-intelligence/fast/tree/ec4d7aa71691cac0b8bed6942be45684db2110f4)。
