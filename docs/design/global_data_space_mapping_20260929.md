# 🌐 全局数据空间 (Global Data Space) —— 映射关系 · 数据闭环 · 质量管理 · 全链路可视化

- 作者: 静静 (总架构师) · 日期: **2026-09-29** · 状态: 映射表已落地并**真跑通**(DDS 实测取证见 §5)
- 机器可读真源: `src/lerobot/dataspace/topics.py`(映射表) + `quality.py`(质量规则) + `probe.py`(全链路探针)
- 对标: 百度 Apollo Cloud / DreamView —— 节点+频道清单 · 实时频率与帧龄 · 数据质量告警 · 闭环环节状态

---

## 0. 一句话定义

**全局数据空间 = 一台机器上所有真实数据源/消费者的统一命名空间 + 统一的 QoS 与质量口径 + 一条能被看见的闭环。**
在这里: 命名空间 = DDS 域 0 的 `zmax/*` 话题; 口径 = `-1.0 表示未测(不许 0 冒充)`; 闭环 = 采集→上传→入库→训练→评测→发布→部署→推理→**回采**。

三层映射(老倪的分层口径, 不许越层):

| 层 | 映射什么 | 真源 |
|---|---|---|
| ① 物理层 | 话题 ↔ IDL 类型 ↔ QoS ↔ 频率 | `topics.py::TOPICS` |
| ② 语义层 | 话题 ↔ 生产者/消费者(进程/服务/网页/画布节点) | `topics.py::TOPICS[*].producer/consumers` + `PRODUCERS` |
| ③ 闭环层 | 环节 ↔ 入口/产物/质量门/证据 | `topics.py::CLOSED_LOOP` |

---

## 1. ① 物理层: 话题清单 (14 个, 全部在 DDS 域 0)

QoS 三档(按用途分级, 不一刀切): `state` = RELIABLE·KEEP_LAST(1)·TRANSIENT_LOCAL(新订阅者立刻拿到最新) ·
`beat` = BEST_EFFORT·KEEP_LAST(1)(丢帧无妨, 要低延迟) · `cmd` = RELIABLE·KEEP_ALL(一条都不许丢)。

| 话题 | 类型 | 设计Hz | QoS | 生产者 | 主要消费者 | 允许模式 |
|---|---|---|---|---|---|---|
| zmax/hw_state | HardwareState | 0.33 | state | 4060 硬件发布端 | 汇聚器→ECS / 控制台 / 网页 | diag·calib·test |
| zmax/train_prog | TrainProgress | 0.33 | state | 训练脚本→发布端 | 控制台训练页 | diag·test |
| zmax/deploy_cmd | DeployCommand | 事件 | cmd | ECS/控制台(人工晋级) | 4060 / Orin 部署 | test |
| zmax/heartbeat | Heartbeat | 0.2 | beat | 各端守护 | 汇聚器 / 控制台节点灯 | diag·calib·test |
| zmax/ss_state | SSState | 10 | beat | 数据空间守护 ← 真机只读 tap | 控制台/备份端 | calib·test |
| zmax/ss_action | SSAction | 10 | beat | 守护 ← 本机推理 8790 输出 | 控制台 / 审计 | calib·test |
| zmax/ss_infer | SSInfer | 0.5 | beat | 守护 ← 8790 /health | 控制台推理页 | diag·test |
| zmax/ss_canvas | SSCanvasNode | 0.5 | state | 画布节点执行上报 | 控制台画布页 | test |
| zmax/ss_macro | SSMacro | 0.2 | state | 五层记忆/宏观层 | 控制台记忆页 | test |
| zmax/ss_nodes | SSNodes | 0.2 | state | 数据空间自描述 | 控制台节点清单 | test |
| zmax/ss_calib | SSCalib | 0.2 | state | 守护 ← 标定真源文件 | 控制台标定页/现场核对 | calib·test |
| zmax/ss_diag | SSDiag | 0.5 | beat | 守护(延时/帧龄/吞吐/健康度) | 控制台监控页/告警 | diag·calib·test |
| zmax/ss_test | SSTest | 事件 | state | 取证/回归脚本 | 控制台评估页 | test |
| zmax/link_value | LinkValue | 5 | beat | 画布连线总线 | 控制台画布页 | calib·test |

遥测模式(env `ZMAX_TELEMETRY` > 运行时 > 文件 `~/.zmax_telemetry_mode` > prod)决定**允许发哪些话题**:
`prod` 零开销(不建参与者、不 import cyclonedds) · `diag` 5 个 · `calib` 7 个 · `test` 全部 14 个。
> ★ 这不是"开关话术": 模式白名单是**执行期真裁剪**(守护每轮 `allow(topic)` 判定), 度量方式见 §5。

## 2. ② 语义层: 谁发 / 谁收 (数据空间里的"节点")

```
4060 硬件发布端(zmax-dds-pub)      ──hw_state, train_prog, heartbeat──┐
数据空间守护(zmax-dds-ss)           ──ss_* 9 类────────────────────┼──► DDS 域0 (zmax/*)
画布连线总线(dds_link_bus)          ──link_value───────────────────┘
                                                                    │
   汇聚器(zmax-dds-agg) ◄── hw_state/train_prog/heartbeat ─────────┘ ──► ECS relay (公网/异地)
   全链路探针(dataspace.probe) ◄── 当前模式允许的全部话题 ──► live.json ──► 控制台「数据空间」页
   控制台/网页 ◄── 读 live.json(不直接依赖 cyclonedds)
```
**规矩**: 控制台/主应用**不许**直接 import cyclonedds(依赖污染) ⇒ 一律走 `probe` 的
「DDS → JSON 桥」(`/home/ubuntu/zmax_data/dataspace/live.json`)。

## 3. ③ 闭环层: 数据闭环流程 (9 环节, 每环都有门)

| 环节 | 入口 | 产物 | **质量门(判据)** | 证据来源 |
|---|---|---|---|---|
| S0 采数前自检 | 现场核对 | — | 手眼 rms≤2mm · TCP 非全 0 · 相机帧龄 0<龄<1s | ss_calib 话题 / tcp_out/latest.json / 8793 横幅 |
| S1 真机采集 | Orin 采集(20s MCAP+打标) | 数据包(state6+action6+图+label) | 帧数≥20 · 维度 6D · 图像有效帧率>0 · **action≠state** | 包内 meta |
| S2 上传中转 | POST /api/relay/upload | ECS 队列(≤100M/包) | 回执 + 帧数/维度一致 + 校验和 | /api/relay/status · peek |
| S3 入库质量门 | build_orin6d_dataset.py | LeRobot 数据集(parquet+mp4) | 帧数=视频帧数 · 时间戳单调 · float32 定长 · 索引 int64 | meta/info.json + 对账 |
| S4 训练 | ACT 三阶段(S1冻结→S2零样本→S3真机微调) | ckpt + 进度文件 | GPU 负载达标 · loss 有限 · 每 N 步落进度 | train_prog 话题 / 日志 |
| S5 评测 | 同口径评测(同源预处理+留出集+平凡基线) | 评测 JSON | **有提升才放行**(非仅不回退) | ss_test 话题 / reports/*.json |
| S6 发布 | 静态 URL + sha256 + 版本号 | datadrive.world/models/<name> | sha256 一致 · HTTP 200 · 可匿名拉 | curl -sI |
| S7 部署 | DeployCommand over DDS | Orin 在役权重 | issuer 可追 · artifact 存在且 sha 匹配 · 可回滚 | deploy_cmd 话题 + 审计 jsonl |
| S8 真实推理与回采 | Orin 真机推理 | 推理计数 + 成功率 + 失败样本 | infer_count>0 · 失败帧归档 | ss_infer 话题 / relay/orin/status |

**为什么是闭环**: S8 的失败样本回到 S1 —— 没有回采就是开环, 失败样本是下一轮数据的主料。

## 4. 全面数据质量管理

- 规则库: `quality.py::TH`(阈值集中) + `topics.py::QUALITY_RULES`(23 条判据定义), 每条话题**声明**适用规则。
- 三级裁决: `ok` / `warn`(记录显示不拦) / `veto`(**拒用**: 标定无效、动作无闸门、负帧龄、NaN)。
- 关键判据: 帧龄(>5s 只报 diag) · **负帧龄拒用**(本机 NTP 曾回拨 8h) · 缺测 -1.0 / **假 0 检测** ·
  维度一致 · 闸门审计(gate_pass≠-1) · 手眼残差 ≤2mm · 计数自洽(total=passed+failed) · 频率偏差 ≤35% ·
  单位命名 · 自述 vs 实测对账(ss_nodes) · 产物存在性(deploy artifact)。
- 质量分: 通过率(veto 再打半折), 每话题与全局各一份 —— 控制台看板直接用。

## 5. 本轮实测取证 (全是真跑的输出)

```
① 全链路探针 mode=diag 实测(24s 窗):
   zmax/heartbeat  0.21Hz(设计0.2)  5 条  配对1  ok
   zmax/hw_state   0.26Hz(设计0.33) 6 条  配对1  ok   真实值: util=3% mem=2644/8188MB 43°C 9.75W 盘可用60.8GB backend=cuda
   zmax/ss_diag    0.50Hz(设计0.5) 12 条  配对1  ok
   zmax/ss_infer   0.50Hz(设计0.5) 12 条  配对1  ok
   zmax/train_prog 0.26Hz(设计0.33) 6 条  配对1  ok
   ⇒ 落盘 /home/ubuntu/zmax_data/dataspace/live.json (控制台/网页读这一份)
② 质量管理**抓到的真缺陷 3 个**(都已在本次修掉, 附根因):
   (a) 硬件话题整条链断了: 发布端 `--cfg` 指向 **0 字节**配置 ⇒ CYCLONEDDS_URI 解析失败、参与者掉出发现网
       (实测 配对=0、帧龄=None)。守护端早就有空文件保护, 发布端漏了 ⇒ 已按同口径修 + 空文件告警。
   (b) hw_state/train_prog **每轮发不出去**: 发布端用 `dirname(dirname(__file__))` 反推仓库根, 脚本在
       /home/ubuntu 下算出 REPO=/home ⇒ sys.path 指 /home/tools(不存在) ⇒ `import hardware_view`
       抛 ModuleNotFoundError。只有不依赖它的 heartbeat 在发。⇒ 改为指 main 工作树(/home/ubuntu/zmax)。
   (c) 注册表频率与实现不符(ss_infer/ss_diag 写 1.0Hz 实为 0.5Hz、train_prog 写 0.5 实为 0.33):
       质量引擎的 hz_tol 当场报出来 ⇒ 已按**实现**更正为真值。
③ 探针自身也修了两处口径错: 低速率话题在 5s 滑窗里 hz 被系统性低估(改按整观测窗平均);
   loss=-1.0(未训练)被误判为"loss 不合理"(改为 running=0 时不算违规)。
```

## 6. 全链路 topic 可视化 (控制台要做成的样子, 对标 DreamView)

一页三栏 + 一底条, 数据全部来自 `live.json`(不猜、不缓存假值):

```
┌ 顶栏: 模式[prod|diag|calib|test] · 允许/注册话题数 · 注册表版本 · 观测时刻 · 质量总分 ┐
│ 左: 节点清单        中: 频道(topic)清单                    右: 闭环 9 环节条       │
│  进程/服务/灯        名字·类型·实测Hz/设计Hz·帧龄·条数·配对   门是否通过·证据链接   │
│                     ·裁决·质量规则明细(点开看字段真值)                            │
└ 底: 质量告警流 (时间 · 话题 · 规则 · 值 · 级别) + [导出 JSON] [导出 CSV]           ┘
```
必须能: ①看频率与帧龄是否在规格内 ②点话题看**最新字段真值** ③按规则列告警 ④**可复制/可导出**(老倪要求)
⑤切换遥测模式(写运行时开关, 与守护口径一致)。

## 7. 收口计划 (老倪的"一个 CICD 路径"红线, 必须做)

现状: DDS 的类型/节点/守护/汇聚器在**仓库外** —— `/home/ubuntu/zmax/dds/{ss_types,zmax_types,zmax_node}.py`、
`/home/ubuntu/zmax/dds{,_ss_daemon,_aggregator,_ss_verify}.py`。本轮的 (a)(b) 两个缺陷**根因都是这个**
(脚本位置与仓库根假设不一致; 两处手工同步的模式白名单)。
计划(每步都要能回滚, 服务 unit 先改后重启, 逐台验证):
1. 类型与 Node → `src/lerobot/dataspacedds/`(与 `dataspace/` 同门) 或直接并入 `src/lerobot/dataspacedds` 命名;
   守护/汇聚器/发布端 → `tools/dds/*.py`, 一律 `REPO=zmax_rel` 相对定位。
2. 模式白名单**只留一份**(现在 `zmax_dds_ss_daemon.py:51` 与 `tools/gui/zmax_telemetry.py` 各一份) ⇒ 并入
   `src/lerobot/dataspacedds/topics.py::MODE_TOPICS`。
3. 真实单播配置: 现在 `zmax_dds/cyclonedds_unicast.xml` 是 **0 字节**(空文件), 大家实际走默认多播(日志里还能看到
   往 10.163.146.78 / 10.163.147.55 写失败的噪声)。现场网络恢复后按 `dds-messaging` 技能写真配置
   (`AllowMulticast=false` + 显式 peers: 127.0.0.1 + Orin + Mac + ECS), 三端一致后再切。

## 8. 需要现场/老倪配合的事 (走通闭环的物理前提)

| 需要 | 为什么 | 现在状态 |
|---|---|---|
| Orin 上电 + 产线网卡插回(192.168.23.66) | S1 采集/S8 推理都在 Orin 侧 | ✗ 不可达 |
| 深度容器/相机(:8791 arm 流) | 3D 真值 + 掩膜贴合复测 | ✗ arm=503 |
| 珞石位姿真值(rokae_tcp_sampler) | S0 自检与动作闸门 | ✗ 全 0(会话陈旧) |
| 遥测模式选择 | 量产 `prod` / 现场诊断 `diag` / 标定 `calib` | 现暂置 `diag`(为了可视化有数据) |
| ECS 反向隧道(zmax-ecs-ov/station) | 公网看板/异地中转 | ✗ activating 反复重启 |

## 9. 下一步 (按序, 不再请示)

1. 控制台「🌐 全局数据空间」页按 §6 改造(读 live.json + 注册表; 加模式切换与导出)。
2. `probe --watch` 做成常驻服务(`zmax-dataspaces-probe.service`), 让 live.json 是活的。
3. 闭环九环节的**证据采集器**: 每环节读一个真实来源(文件/端点), 汇成 `loop.json`, 页面直接显示"这一环过没过门"。
4. 收口(§7) —— 让 DDS 代码进仓库, 消灭"两个地方"。

---

# 8. 🚌 DDS 总线层 (对标 Vector CANoe) —— 2026-09-29 老倪追加要求

> 「所有的数据都要有 topic; 从状态空间工程开始, 所有节点之间的数据要可视化, 能够被检测、被观察;
>  量产期间我可以不序列化为 topic, 但是工程上我可以随时探测系统, 保证系统的数据质量;
>  参考 Vector 公司的 CANoe 做一个 DDS 总线, 全面检查系统数据; 根据状态空间工程导出的 json 数据,
>  可以加载到 DDS 总线上, 实现全局数据可视化。」

## 8.1 CANoe 概念 ↔ 本系统映射

| CANoe | 本系统 | 落点 |
|---|---|---|
| DBC / 数据库 | 总线数据库 busdb | `src/lerobot/dataspace/busdb.py` → `busdb.json` |
| Message(报文) | DDS topic | 13 个类型化话题 + `zmax/link_value`(连线报文) |
| Signal(信号) | 画布上的一条连线 | 182 条: 信号身份 = (源节点, 源端口) |
| ECU / Node | 画布节点 / 发布者进程 | 74 个数据节点(89 减 15 个 row_bg 背景行) |
| Measurement | 探针 | `probe.py` → `live.json` + `trace.jsonl` |
| Trace 窗口 | 📋 报文追踪 | 逐条报文: 时刻/报文/类型/序号/字节/载荷摘要 |
| Statistics 窗口 | 📊 统计 | 实测Hz · 抖动(相邻间隔σ) · 丢包估算 · 载荷B · 配对 · 裁决 |
| Symbol 视图 | 🔌 信号 | 报文→层→节点→端口 + 实时值 |
| Error frame | ⚠ 质量告警 | 规则不过 + 闭环门不过 |
| Restbus / 回灌 | 📥 回灌 | `tools/dds_bus.py --simulate`: 把工程 json 发到总线 |
| Measurement bar | 🚌 总线状态条 | 档位 · 活报文/总报文 · 错误数 · 累计报文 · 刷新龄 |

## 8.2 全链路 topic 化的口径(与老倪要求逐条对应)

1. **所有节点之间的数据都要有 topic**: 画布 182 条连线全部上车 —— 一条报文 `zmax/link_value`
   (CANoe 口径: 一条 Message 承载多条 Signal, 信号身份 = 源节点 + 源端口), 层(L2/L3/L4/L5/meta)
   由总线数据库查得。**不为每条连线开一个话题**: 182 个话题会把发现/内存/可读性一起拖垮。
2. **可被检测、可被观察**: 观察者(探针)用 **BEST_EFFORT + KEEP_LAST(200) 深历史**读取端 ——
   只观察, 不改变发布端语义。实测: 若照抄发布端的 `KEEP_LAST(1)`, 一轮 182 条只能看到 **1 条**;
   换深历史后同口径看到 **80→182 条**。这是 CANoe 分析仪的做法。
3. **量产不序列化, 工程随时探测**: 档位(prod/diag/calib/test)白名单是**唯一开关**;
   prod = 0 话题(预期, 零开销), 探针**跟随档位切换**(2s 内跟上, 不重启进程)。要探测就切 calib/test。
4. **工程 json 加载到总线**: `tools/dds_bus.py --simulate` 读画布 json → 182 信号发到总线;
   口径见 8.3。

## 8.3 诚实口径(不许含糊)

* 回灌报文: `kind='bus-sim'`, `text='from canvas json (工程回灌·非实测)'` —— UI 上必须与真机实测区分。
* 闭环证据三态: pass / fail / **unknown(没证据就写 unknown, 不猜不美化)**。
* 观察者读到 0 条 ≠ 系统坏了: 要先看档位白名单与配对(prod 档为 0 是设计预期)。

## 8.4 实测踩到的坑(都已修, 记下来免得重犯)

| 现象 | 根因 | 修法 |
|---|---|---|
| 回灌 182 条, 探针只看到 1~3 条 | 探针读取端照抄发布端 QoS `beat=KEEP_LAST(1)` | 观察者用 RELIABLE 不兼容 → 用 BEST_EFFORT + KEEP_LAST(200) |
| 节流前 80/182, 节流后 182/182 | 发布端 KEEP_LAST(1), 一口气灌 182 条会被覆盖 | 默认 1ms/条节流(物理性质, 不是丢包 bug) |
| `Node.pub/send` KeyError | `Node` 自己会加 `zmax/` 前缀, 传全名等于双重前缀 | 传短键 |
| 总线库造出 5 个话题却订阅不到 | `zmax/ss/link_l2` 等未在注册表登记 | 收敛到已注册的 `zmax/link_value` |
| main 树上没有 `link_value` 类型 | `tools/gui/dds_link_bus.py` **只在 mac-hw 分支**, 从未并入 main | 已带入 main 工作树(收口: 类型应搬进 `src/lerobot/dataspace/`) |
| 档位切换后探针看不到新话题 | 探针只在启动时定订阅集 | `follow_mode()`: 每轮对账档位白名单, 补订新话题 |
| UI 整页被一条数据异常打死 | 刷新无保护 | `refresh()` 包 try/except, 异常写进质量窗口 |

---

# 9. 🚦 状态灯规范 (四色语义) —— 2026-09-29 老倪追加要求

> 「所有 topic 数据, 都是一种系统状态的反馈或输入/输出信号; 每个模块要有个状态灯, 这个 DDS 总线上,
>  绿色表示正常, 红色表示故障, 黄色表示报警, 黑色表示无信号。」

## 9.1 唯一口径

实现在 `src/lerobot/dataspace/lamps.py`(纯函数, 无依赖)。**UI 不许自己另判颜色**, 只读:

* 探针把每条话题的灯算好写进 `live.json`: `topics.<key>.lamp` / `.lamp_reason`, 外加总览 `lamp_tally`
* 控制台按 `lamps.module_state()` 聚合出模块灯

| 灯 | 含义 | 判据(按此顺序, 先命中先返回) |
|---|---|---|
| ⚫ 黑 | 无信号 | ① 本档位白名单外(量产 prod 属**预期**) ② 探针无记录 ③ 窗口内 0 条 ④ **最后一条数据龄 > max(5s, 3/设计周期)** —— 数据停了就是无信号, 不能一直挂黄灯 |
| 🔴 红 | 故障 | 规则 violation/veto(值域越界/NaN/维度错/闸门否决), 或裁决 violation/veto |
| 🟡 黄 | 报警 | 告警级规则不过 · 裁决 warn · 实测 Hz < 设计 ×60% · 配对 0(有样点) |
| 🟢 绿 | 正常 | 以上都不命中 |

**模块灯** = 该模块**输出信号**所在话题的灯聚合:
任一红→红; 否则任一黄→黄; 否则全黑→黑; 否则有黑有绿→黄(部分信号无); 否则绿。
(模块无任何输入/输出信号 → 黑「无输入/输出信号」)

## 9.2 实测(2026-09-29 18:12, calib 档)

| 场景 | 报文灯 | 模块灯 |
|---|---|---|
| 平时(无节点间数据流) | 绿2/黄1/红1/黑3 | 全黑 74(输出信号无数据) |
| 工程回灌运行中 | 绿3/黄1/红1/黑2 | **绿 74**(全图点亮) |
| 回灌刚停 | 同上 | 黄 74(数据变稀=报警) → 120s 窗口过期后转黑 |

真故障灯实例(不是模拟): `ss_calib` = 🔴 `valid_flag: valid=0(0=无效 不许用, -1=未知)` —— 标定文件当前无效。
真报警灯实例: `hw_state` = 🟡 `hz_tol: 实测 0.21Hz vs 设计 0.33Hz(允许 -35%)`。

## 9.3 界面落点(UI)

* 「🚦 状态灯」Tab(总线组第 1 个): 14 盏报文灯 + 74 盏模块灯, 按 L5/L4/L3/L2/meta 分组; 顶部总览条 + 分层灯计数 + 「只看非绿灯」过滤
* 「🚌 总线架构」: 报文方框右上角一盏灯; 每个节点小方框左侧层色条 + 一盏模块灯
* 「📊 统计」: 首列状态灯(● 文字 + 颜色)
* 顶部总线状态条: `🚦 报文灯 绿x/黄x/红x/黑x · 模块灯 绿x/黄x/红x/黑x · 档位 · 累计报文 · 刷新龄`

# 10. 界面复核驱动整改 (2026-09-29, 像素级目检 8 条)

| # | 复核发现 | 改法 |
|---|---|---|
| 1 | 表格白底 62~79%, 字色还是深色主题的浅灰/蓝 ⇒ "老板看就是没字" | 全 Tab 套 `DARK_QSS` 深色主题(表/树/文本/输入/表头); 实测纯白像素 **0.0%** |
| 2 | 报文列一律 100px ⇒ 14 行全显示 `zmax/...` | 追踪表 选项/报文/类型/序号/字节 = 92/210/110/70/70, 摘要列 Stretch |
| 3 | 统计表 12 列死板 104px ⇒ 左侧截断 + 右侧 483px 空列 | 逐列定宽 + 末列 Stretch |
| 4 | 空表体/大白块无法判断"是没数据还是坏了" | 每张表加计数行与空态提示(如"暂无报文 —— 先看状态灯是哪一盏黑/红") |
| 5 | 界面残留 Markdown 星号 `**预期**` | 改中文书名号/直述 |
| 6 | 总线图只有报文方框有挂线, 节点像"悬在下面" | 加左侧立管(busY→各层)+ 各层节点母线 + 接头圆点 |
| 7 | 图上标题文字压在第一个报文方框上 | 标题移到 y=11, 方框下移到 y=20 起 |
| 8 | 节点文字越框/硬切 | 名称截 14 字 + 框宽 150 + 字号 7 |
| 附 | 截图文件名与内容错位(bus_topology 装了数据空间页) | 截图脚本改为**按 Tab 文本映射文件名**, 7 张一一对应 |
| 附 | 「⚠ 质量告警」Tab 消失 | 去重逻辑按文本匹配删掉了全部副本 ⇒ 改为保留最早那个, 只删后续重复 |
