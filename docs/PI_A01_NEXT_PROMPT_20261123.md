# 下一轮 Codex：A01 之后的正式采集接续

**11/24最新增补：先执行 [四颜色采集与蓝红先训提示词](PI_COLOR_CONDITIONED_COLLECTION_20261124.md) 中第8节的完整提示词，再结合本文件控制/数据合同。用户已暂停采集，明确采蓝、红、白、绿，第一阶段只训练蓝红；先修逐episode颜色指令，按主库固定split派生蓝红视图，最后验收红蓝混摆的新位置实机抓放。此更新替代先前固定单蓝任务语言的采集范围，不覆盖现场尚未推送成果。**

日期：2026-11-23，北京时间。固定审查来源 `0ee2d2ecc6783ffcfdec115079a83db3944caeb5`。当前已有完整的采集、SDK 重放、审核、导出入口和 1 条真实成功 commissioning；本提示词要求在该实现上收敛正式采集，不重建整个采集系统。运行代码尚未因本次仓库审查修改。

复制下面整个提示词。现场需要操作时，由已有交互流程引导操作者；代码与文档先完成到可以审查、可以实际使用的程度，不因为泛泛的待确认事项停下。

```text
你只负责 π0 / π0.5 的 Piper H 单腕实机测试。继续 kaiwen123-yang/-0--0.5 的真实后续，不覆盖现场工作。先读取：
- AGENTS.md
- docs/PI_REAL_TEST_STATE.md、docs/PI_DAILY_WORK_LOG.md 最新记录
- docs/PI_A01_RECORDING_REVIEW_20261123.md
- docs/PI_LOCAL_DEMONSTRATION_GUIDE_20261123.md
- results/pi-readiness/20261123/A01_review/ 三份审查 JSON
- results/pi-readiness/20261123/local_commissioning/ 的 A01_block01.json、A01_selected_retreat.json、A01_empty.json、A01_empty_return.json、sdk_home_2207.json 和 A01_episode01/ 元数据
- tasks/piper_real_single_v1/ 现有 demo_field.py、demo_io.py、demo_path.py、demo_export.py、demo_rgb.py、pi_demo.sh、dataset.py、policy_config.py、train.py、infer.py、MODEL_USAGE.md 与 RECORDING_USAGE.md，以及真实 wrist 配置。

最新事实：
1. main@0ee2d2e 已交付 1 条 A01 真实抓放成功；11,553 原始 RGB，7,680 个 20 Hz 行，现场逐行核对已通过。它是人工示教路径的 SDK 重放，split=commissioning / training_eligible=false，不是 π 自主控制成绩。
2. 现场项目 /home/kaiwen/research/pi-single-live；入口 /home/kaiwen/research/pi-single-live/tasks/piper_real_single_v1/pi_demo.sh。
3. 原会话 /home/kaiwen/research/pi-q12-data/pickplace_20261123_211053；成功运行子目录 20261123_223453_601082_block；既有导出是同级 pickplace_20261123_211053_commissioning_01。保留原始数据和旧资格。
4. 23:27 SDK 已从 A01 抬离位直接回零，11/23 23:28:12 独立实测六轴均为 0°，6/6 使能、CAN/MOVE_J 已到位，SDK 夹爪 39.5 mm；相机与 viewer 仍运行。新会话先读取实际状态。
5. 唯一 DC1 CC16762023M，wrist，唯一有效 left_wrist_0_rgb，其余槽mask=False；沿用11/22冻结 wrist_rgb_calibration.json、received RGB与相同安装。不重跑标定、长静止或RoboMIND调研。

本轮目标：先修现有正式采集合同和正常结束/重定位接续，录下一条更紧凑且来源完整的新示范并审核导出，再按实际进度扩采。3–5条不是必须先重复旧六分钟A01的数量门禁；30–50条是首轮正式集预算，不保证学习效果。

一、查看实际环境和本轮变更范围。
先读项目分支、未提交修改、相关活动进程和实际脚本版本。复用已有环境、H0锁与pyAgxArm，不 reset/覆盖现场成果。需要时用独立工作树，只引入本轮明确文件。dog-and-arm及共享SDK/ROS/JAX/OpenPI只读复用，不更改全局环境、缓存、基础权重或其他任务。不停止既有训练、推理、相机、上传；需要复用相机时用现有单发布者检查。只维护一个主动CAN发送端。

二、贯通第七维的正式定义，不再把SDK坐标冒称物理指垫净距。
采用明确版本 piper_h_sdk_width_m_v1：state第7维为SDK反馈宽度m，action第7维为实际成功提交的绝对SDK宽度目标m。保留wire µm→m，物理指垫卡尺净距另存元数据，绑定当前夹爪/指垫安装。无需拟合全行程净距曲线，不从几个近似测点强拟合固定偏置。
同步检查setup、run、export/dataset/index/alignment、dataset.py training_data_requirements、run spec/norm资产元数据、policy metadata、离线推理及未来现场发送接口使用同一版本。消除policy_config.py中total opening的物理歧义；正式入口明确核对training_eligible及合同版本，保留旧commissioning按其split读取的能力。缺失定义不得静默推断成新合同。
前6维仍为rad，DELTA_MASK前6 true、第7false；只在模型transform里还原绝对关节一次。夹持时state约0.0247而action=0.015是正确语义，不改成相等。新建明确合同的正式setup，不翻转旧A01的flag，不删除全部formal限制。保持现场核实的开合范围和力值，少量尺读已有证据不盲目重复。

三、使任务在正常抬离位置结束，并补齐首次空场前的实际接续。
当前demo_field.teach的E、demo_path.plan和replay均有末位近起点要求；selected retreat是给旧中断源的commissioning特例。新增版本化terminal_kind=post_release_retreat，并在三处一致处理：
- start仍匹配真实保持位；start/close/open/end顺序及静止窗口、限位、时间连续性、全源路径误差检查继续保留。
- E在open之后的新鲜、静止、限内实际抬离姿态记录，保存end反馈ID、时间、姿态和图像来源。现场确认空爪抬离。任务结束不要求手拖精确回零；不得把越限尾段或人工重定位计入任务。
- 新formal源正常complete，旧A01中断源和人工selected retreat保持原样commissioning。不得补写complete或伪造end。
- 必须处理新源结束非零→首次empty前的独立重定位和模式交接。现有return-start需要同源已成功empty，不能用于这一步的循环引导。sdk_home_2207只验证过近零短路径，专用源码需到测试机核实，不能当成任意远位home命令。
- 默认最小接续：E在抬离点封存任务end后，操作者仍在被动示教模式下单独人工重定位；原始反馈继续保留并标为reposition_only，任务[start,end]不变。回到已验证的健康近起点范围后再退出示教、读新反馈、复用近零handoff/同位锚定，然后才首次empty。不要要求为凑task末位而反复手拖精确零位。若近起点还需受限短回程，先读取22:07原代码/回执，仅在新鲜状态及净空等适用条件满足时复用。当前restart-teach只支持commissioning，需针对新合同实现相应近起点锚定，不直接套旧入口。该新阶段需现场验收，不扩成通用远位自动回零框架。不得在非零示教退出后激活旧零位目标、跳过模式状态或用任意直线回零替代已核查路线。若现有接口不足，完成可完成的代码与证据核查，准确报告剩余现场条件，不假装已可运行。
- 同源新empty通过后，复用当前return-start的真实空场提交目标倒序返回、夹爪保持张开；reset是reposition_only，单独保存。
若顺手修replay E与return-start P/E的正常保持账本缺口：确认真实目标到位后记录准确stop和新hold，保留complete=false/不可训练，不放宽boot/TX/接口一致性检查，也不把故障停止改成普通暂停。

四、让下一条示范有效且紧凑。
旧A01约68.343秒抓取位等待保留原始。下一次录制前先讲清C/O/E，避免把讲解、聊天、等待操作录进任务。保留必要静止/夹持稳定/释放等待；不要删掉旧数据中间几十秒后仍声称连续50ms。现有规划每个节点保守停起会延长时长，先改善源路径与无价值等待，不先提高2.5°/s、8°/s²或5%档位。若调整时间参数化，记录依据并用实际新重放生成监督，不拿模拟轨迹当新示范。
单腕起点原图要能看清完整方块轮廓和指尖接近区域；当前源物体靠近画面下缘，先看真实原图再判断，不仅凭中心点断言裁切。保持相机安装和像素链不变。

五、现场按真实依赖执行，不把历史状态当当前状态。
先运行既有pi_demo.sh status，读取当前姿态、夹爪、使能、模式及关联账本。已有保持后不要先单独运行limits，它会发查询改变TX；动作入口自己管理读取。
如果先复用旧A01返回：核对当前会话/boot/TX/接口/保持关系，现场移走方块与工具、保留盘和胶带、确认净空，再用同S的return-start按现有现场YES交互执行。此命令真实运动，本次仓库审查没有执行。返回后才摆下一条；状态失配时诊断，不能手改hold.json或误用restart-teach远位回零。
完成新合同/终点/首次重定位后，在新会话教紧凑源，按实际新路径核一次空场及动态P/R/正常保持，再实际抓放、review、导出。旧同源同布局已通过的空场不用仅为凑数重复；实质新源/路径/布局要对应验证。一次一条，记录失败/人工介入，不用循环无人值守。
带我做时给出当前真实存在的绝对路径、命令、按键和输出位置；尚未实现的拟议参数不能冒充可用CLI。当前原A01上的block --formal会被两道门拒绝，不能直接给我这条命令说已经准备好了。

六、采集前把训练/验证会话分开。
export会分别禁止session_id、placement、source_trajectory_id跨train/validation，同一S的不同布局也不能混分。可实际建立T01、T02训练会话共40条，V01独立验证会话10条；这些名称仅是计划，生成真实目录与ID。布局、来源在现实中独立，不复用训练路径后改名当验证，不随机拆帧。
先固定蓝块、浅盘、任务语言、底座和相机，在可见可达区域变化物体起点、轻微朝向，逐步增加落点变化，每个新布局教相应新源并核查空场。同布局同源重复只提供复现，不当作多样性。数量按覆盖与问题调整，未满50不等于必定不可训练，录满50也不代表必定泛化。

七、用真实新数据验证合同，不搭额外试验框架。
保持现有因果20Hz定义：观测来自t以前，action取(t,t+50ms]末完整有效提交目标；避开半事务并保留逐行来源，当前held目标另作跟踪基准。10步chunk只在本episode内，尾部重复最后目标。失败/半提交/手拖/空场/标定/无动作观测不混入正式成功集。
对新正式episode做已有真实日志/字节对齐检查，报告图像计数与间隔、年龄、三包跨度与拒绝组、动作间隔及原因、实际提交、跟踪、开合、终态、合同和split。无需为文档或小修改添加mock、shape、导入/冒烟/单元测试流水线、容量试跑、前置试训练、全库差分或大数组回下载。
从已存在A01原图补远程证据即可：67、5531、5581、10100、10175、11551，搬运候选8680先看图确认。用原像素另附清单，保留已有展示片或关键动作原速片；展示抽帧与训练数据区分，无需重录A01或上传全量NPY。

八、正式数据合格后才衔接训练和策略测试。
两个模型共用同一冻结split，各自基础权重、全参配置、train-only norm与输出；π0 mean/std，π0.5 quantile，不套用旧双相机或external_fixed资产。新合同写进实际配置/资产，正式数据不足时不启动训练。数据完成后读D57当时实际GPU与活动任务，填实batch、步数、保存/选择规则，不假定96GB单卡双全参并行，不自动改LoRA，不停止其他作业。
以后用实际微调检查点先检查真实观测推理，再验收在线唯一发送端与时延/动作调度。20Hz网格不是20Hz推理证明，SDK路径成功不是策略成功。最终比较另留未用于选模型的场景。

九、真实记录与发布。
更新唯一docs/PI_DAILY_WORK_LOG.md、当前状态、现场指南及接续提示词，详细记录问题现象、根因证据强度、具体修法、实测数字、未完成项。任务结束时真正读取硬件模式/使能/夹爪/保持位，说明运动、相机、viewer、训练与上传是否运行；没有连接现场就明确只是历史快照。
按已授权范围提交/推送本轮明确代码、实际配置、紧凑证据和文档。大原始录制、数组、模型留原机，不新增归档或清理。不给尚未发生的现场试验、训练或成功写PASS；不伪造精确时间。没有硬件时把可审查的代码/文档做完，现场项据实NOT_RUN并提供接续。
```

## 本轮完成的验收口径

这里的“正式采集准备完成”需要代码、实际元数据和现场接续共同支持；仅改文案或 flag 不算完成。第一条新源通过后可继续现场已授权采集，无需为常规文件更新重复询问。依据新实测更新下一步，避免把本提示词的计划写成已经完成。

