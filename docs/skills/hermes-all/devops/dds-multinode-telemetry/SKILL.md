---
name: dds-multinode-telemetry
description: Use when 多机硬件/训练遥测要走 DDS(非HTTP)。
version: 1.0.0
author: Hermes
license: MIT
metadata:
  hermes:
    tags: [dds, cyclonedds, telemetry, pyinstaller, multi-machine, gnss, hardening]
    related_skills: [cross-venv-model-canvas-node, zmax-console]
---

# DDS 多节点遥测（硬件 / 训练进度）

## When to Use
- 要求「硬件参数/训练进度必须用 **DDS** 传」（不是 HTTP 轮询）
- 多台机器（如 4060 工作端 + Mac 备份端 + 云中转）要互相看到对方硬件
- 要把 DDS 订阅**打进桌面 APP（PyInstaller 单文件 exe/app）**

## 选型
**Eclipse Cyclone DDS**（OMG 标准 · pip 可装 · Linux/Mac/Windows 通用）
```bash
python3 -m venv ~/dds-venv && ~/dds-venv/bin/pip install cyclonedds
```
类型定义用 `cyclonedds.idl.IdlStruct` dataclass（见 `dds/zmax_types.py`）。

## 四步落地
1. **类型**（IDL dataclass）：`dds/zmax_types.py`
   - ★ **未测到的量用 -1.0，不要用 0**（0 是合法实测值，混淆后无法区分"没采到"和"真的是0"）
2. **节点封装**（`dds/zmax_node.py`）：`Node(name, domain, config_xml)` + `pub/sub/send/take/wait_for_match`
   - ★ `wait_for_match(topic, n=1, timeout)` —— **n 必须 ≥1**；写 0 会"永远匹配成功"→ 没等发现就发 → 丢包
3. **采集器**（`tools/gui/dds_hw.py`）：后台线程订阅 → 共享 dict（加锁）
   - 三级降级：**进程内直连** → 子进程 DDS 桥（读桥落盘的 JSON）→ HTTP 兜底（**必须标注"非DDS"**，别偷偷降级）
4. **三端脚本**：本机发布端 / 对端发布端 / 只读 watcher（自检用）

## ★ 8 个实测坑（都踩过）
1. **多网卡下多播选错网卡 → 订阅端 0 条**（发布端在发也没用）
   → **必须用单播配置**：`AllowMulticast=false` + `<Discovery><Peers>` 列出对端 IP
2. **CycloneDDS 11.x 的 XML 不吃 `<Interfaces><NetworkInterface name="auto"/>`** → `DDS_RETCODE_ERROR`
   → 不要写 Interfaces，让 DDS 自选
3. **`<General><Ports><Base>..</Base><Max>..</Max></Ports></General>` 也不吃**（同错）
   → 想固定端口得换 Fast DDS 或升版本；不固定则安全组需放行 UDP 动态段
4. **`<LeaseDuration>` 必须在 `<Discovery>` 下**（放 `<Internal>` 只告警但仍能用）
5. **IDL 消息不能直接 `m.__dict__` 转 JSON** —— 里面含 `SampleInfo` → `not JSON serializable`
   → 按话题**显式提取字段白名单**
6. **QoS Policy API 不统一**：`Reliability.Reliable(0)`/`History.KeepLast(1)` 可调用，但
   `Reliability.BestEffort` / `Durability.TransientLocal` **不可调用** → 写个兜底：
   ```python
   def _p(cls, *a):
       try: return cls(*a)
       except TypeError: return cls
   ```
7. **打包进 exe/app**：`pip install cyclonedds` + PyInstaller `--collect-all cyclonedds`
   + `--add-data "<repo>/dds:dds"`（Windows 用 `dds;dds`）
   → 体积 **+4MB 即为打进成功的证据**（可用大小对比自证）
   → 代码里也要能找 dds 目录：查 `here/../../dds`、`here/dds`、**`sys._MEIPASS/dds`**
8. **`import threading` 必须模块级**（GUI 文件常把 import 写在函数里 → 你新加的类用到就崩）
   → 用 `ast.parse` + **离屏真跑**验证，别只看语法

## ★ 遥测模式架构（DDS 只用于测试/标定/诊断, 量产关闭）

**用户口径**：「topic 用于测试、标定、诊断，量产时不用；可以随时用 topic，但量产会关闭」

**设计四条**：① 协议统一（话题/字段/QoS 一套口径）② 传输可关（是**模式**不是代码分支）
③ 量产零开销（prod **根本不 import cyclonedds**）④ 随时可开（命令/右键/env 切换，业务代码零改动）

**模式分档**：`prod`(默认,全关) · `diag`(硬件/推理/训练/诊断) · `calib`(+状态/动作/连线/标定) · `test`/`dev`(全量)
**优先级**：`env ZMAX_TELEMETRY` > `set_mode()` > `~/.zmax_telemetry_mode` > 默认 `prod`

**业务代码零分支**：
```python
from zmax_telemetry import telemetry_bus
bus = telemetry_bus()      # prod → None（连 import 都不发生）
if bus is not None:        # 唯一分支点
    bus.publish(...)
```

**状态空间全局数据空间话题**：`link_value`(连线,按源节点发布→扇出) · `ss_state` · `ss_action` ·
`ss_infer` · `ss_canvas` · `ss_calib` · `ss_diag` · `ss_test` · `hw_state` · `train_prog` · `deploy_cmd` · `heartbeat`

**数据源接入原则**：每个话题只从**真实本地源**取，取不到就**跳过**（绝不用 0/假值冒充）。
映射示例：`ss_infer`←推理服务 `/health` · `ss_canvas`←`PIPELINE_STATE.json` · `ss_calib`←标定 JSON ·
`ss_diag`←推理延时+relay+GPU · `train_prog`←训练日志步数。

**UI**：画布连线 = 数据接口 → 右键必须能直接打开它的 DDS topic（实时值/收发计数/可复制/订阅示例）。

## 验证纪律（血泪）
- **"替换成功"的打印必须是真核验过的**：一次 `c.replace(锚点, ...)` 锚点没匹配 → 静默 no-op，
  但我的日志照样打了"✅已补" → 结果 APP 直接崩（`threading` 未定义）。
  **铁律：改完必须回读文件确认（grep/sed 打印实际内容），不能信自己的成功提示。**
- GUI 改动必须**离屏构造 + 读控件文本**验收（`QT_QPA_PLATFORM=offscreen`），
  不能只过语法检查 —— 常量名/局部 import 这类错只在构造时才炸。
- 打包后要让用户能**自证版本**：版本号显示位（标题栏/菜单栏/首页小字）必须同步升。

## 参考实现
- `dds/zmax_types.py` · `dds/zmax_node.py` · `dds/cyclonedds_unicast.xml` · `dds/README.md`
- `tools/dds_bridge.py`（DDS→JSON 桥，给零依赖 Web 用）
- `tools/dds_node_4060.py`（本机发布端）· `tools/mac_hw_report.py --dds`（Mac 端，含 MPS 实测）
- `tools/gui/dds_hw.py`（APP 内采集器 + 自包含本机发布器）
