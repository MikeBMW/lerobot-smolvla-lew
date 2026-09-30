---
name: dds-messaging
description: Use when 多端改用 DDS 消息中间件. 含 Cyclone DDS 实测坑。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [dds, cyclonedds, pubsub, middleware, multicast, unicast, cross-network, rtps]
    related_skills: [http-relay-service, system-replication-twin, zmax-console, layered-capability-stack]
---

# DDS 消息中间件（多端实时状态/指令分发）

## When to Use
- 用户要求**「消息中间件改用 DDS」**，或要**多端（工作端 / 备份端 / 公网中转）实时互传**状态与指令
- 现有 HTTP 轮询/relay 方案**延迟高、要轮询、无 QoS**，想要 pub/sub + 可靠/丢弃语义分级
- 需要 **latch 语义**：新加入的订阅者要**立刻**拿到最新一帧状态（不用等下一次发布）
- 要**跨公网**在两台内网机器之间传数据，但没有可用的中继（见「跨公网」章节）

> DDS = OMG 标准的发布/订阅中间件（RTPS 协议），不是"某个库"。Python 侧选
> **Eclipse Cyclone DDS**（`pip install cyclonedds`，Linux/macOS/Windows 通用）。

## 安装（独立 venv，别污染主环境）
```bash
python3 -m venv ~/dds-venv && ~/dds-venv/bin/pip install cyclonedds
```
主应用**不必**装 cyclonedds：用「DDS→JSON 桥」解耦（见下）。

## 数据模型：IDL dataclass，字段带单位
```python
from dataclasses import dataclass
from cyclonedds.idl import IdlStruct
from cyclonedds.idl.types import float64, int32, sequence   # ⚠️ 该版本无 string 类型

@dataclass
class HardwareState(IdlStruct, typename="zmax::HardwareState"):
    node: str = ""          # ★ IDL string 直接用 Python 内置 str
    util_pct: float = -1.0  # ★ 缺测项 = -1.0（**不要用 0 冒充**，0 是合法实测值）
```
`from cyclonedds.idl.types import string` → **ImportError**（该版本没有 `string`）。

## QoS：按用途分级，不要一刀切
| 用途 | QoS | 为什么 |
|---|---|---|
| 状态快照（硬件/进度）| RELIABLE · KEEP_LAST(1) · **TRANSIENT_LOCAL** | 新订阅者**立刻**拿到最新值（latch），只留最新不积压 |
| 控制指令（部署/回滚）| RELIABLE · **KEEP_ALL** | 指令**一条都不许丢** |
| 心跳 | BEST_EFFORT · KEEP_LAST(1) | 丢几个无所谓，别占带宽 |

```python
def _p(cls, *a):
    """CycloneDDS 11 的 Policy **API 不一致**:
       Reliability.Reliable(n)/History.KeepLast(n) 是可调用类,
       而 Reliability.BestEffort / Durability.TransientLocal 是**普通类**（调用会 TypeError）
    → 能调就调, 不能就原样用"""
    try:
        return cls(*a)
    except TypeError:
        return cls

Qos(_p(Policy.Reliability.Reliable, 0), _p(Policy.History.KeepLast, 1),
    _p(Policy.Durability.TransientLocal))
```

## ★ 头号坑：多网卡主机的多播发现会选错网卡 → 收不到任何消息

**症状**：发布端日志显示正常 `write()`，订阅端 `matched_publications = 0`，收到 0 条。
**原因**：DDS 默认靠**多播**做 discovery；本机有多个网卡（`lo` / 以太 / WiFi / `docker0`）时
可能挑中不通的那个（常是 `docker0`）。**在 localhost 自测也会中招。**

**修**：**默认就用单播配置**（`AllowMulticast=false` + 显式 `<Peers>`），不要依赖多播。

```xml
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain id="any">
    <General><AllowMulticast>false</AllowMulticast></General>
    <Discovery>
      <ParticipantIndex>auto</ParticipantIndex>
      <LeaseDuration>30s</LeaseDuration>   <!-- ★ 必须在 Discovery 下 -->
      <Peers>
        <Peer address="127.0.0.1"/>        <!-- 本机自测也要写 -->
        <Peer address="<对端1真实IP>"/>
      </Peers>
    </Discovery>
    <Internal><HeartbeatInterval>2s</HeartbeatInterval><WriterLingerDuration>2s</WriterLingerDuration></Internal>
  </Domain>
</CycloneDDS>
```
用 `--cfg` 或 `export CYCLONEDDS_URI=file://<abs路径>` 加载。

### 该版本实测**不可用**的 XML 元素（会 `DDS_RETCODE_ERROR`，别加回来）
```
❌ <Interfaces><NetworkInterface name="auto"/></Interfaces>      ← 指定网卡也不行
❌ <General><Ports><Base>7400</Base><Max>7410</Max></Ports></General>
❌ <Internal><LeaseDuration>  ← 位置错会告警, 必须放 <Discovery>
✅ 可用 = <AllowMulticast>false</AllowMulticast> + <Discovery><Peers>单播列表</Peers>
```
调试法：从**最小 XML** 开始逐个加元素，一次只加一个，立刻测
`DomainParticipant(0)` 能否创建 —— 能定位到具体是哪个元素不被接受。

**代价**：没固定端口 ⇒ 防火墙要放行 UDP 动态端口段。现场若只能开固定端口，
该版本的 `Ports` 语法用不了 → 换 **Fast DDS**（eProsima）或升级 CycloneDDS。

## 发现是异步的：发之前先等配对
```python
def wait_for_match(self, topic, n=1, timeout=15.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = (self._w[topic].get_matched_subscriptions() if topic in self._w
              else self._r[topic].get_matched_publications())
        if len(st) >= n: return True
        time.sleep(0.2)
    return False
```
不等配对就发 → 首帧丢给"还没发现你"的读者。

## DDS → JSON 桥：让零依赖的主应用也能用 DDS
把 cyclonedds 隔离在一个常驻小进程里：它订阅所有话题 → 按节点聚合 → 写一个 JSON；
主应用（如标准库 `http.server` 控制台）只读 JSON。两边不互相污染依赖。

```python
# ★ 坑: IDL 消息对象 m.__dict__ 里含 DDS 的 SampleInfo → json.dump 报
#    "Object of type SampleInfo is not JSON serializable"
# 修: 按话题**显式白名单**提取字段, 丢弃 DDS 元数据
KEYS = {"hw_state": ("node","role","backend","util_pct",...), "train_prog": (...)}
d = {k: getattr(m, k, None) for k in KEYS[topic]}
# 每节点只留最新一帧 + recv_ts + age_s + stale(超时标记)
```

## 跨公网（服务器在公网、两端在内网）
1. 三端都写进 `<Peers>`（含服务器公网 IP），全部 `AllowMulticast=false`
2. 服务器安全组/防火墙放行 **UDP**（动态端口段；或换 Fast DDS 固定端口）
3. 跨公网延迟高 → 放松 `<HeartbeatInterval>` / `<LeaseDuration>`（实测 2s / 30s）
4. 若只有一端能出网（NAT 严格），DDS 直连不通 → 用 **DDS Router**，或退化为
   「一端 HTTP 上报 + 那端桥接进 DDS」，别硬凑 P2P

## 总线可观测/分析（对标 CANoe 的 Trace·Statistics·Restbus）—— 三条铁律
1. **观察者读取端必须深历史**：`BEST_EFFORT + KEEP_LAST(200)`。发布端若是 `KEEP_LAST(1)`，
   读取端照抄 ⇒ 一轮 182 条只看得到 1~3 条；读端 RELIABLE 配写端 BEST_EFFORT 属于
   **QoS 不兼容**(根本不匹配)。History 不参与 RxO 匹配 ⇒ 读端可自己加深，不改发布端语义。
2. **一条报文承载多条信号**：N 条连线/N 个节点值不开 N 个 topic(发现/内存/可读性一起崩)。
   新话题**必须先进注册表**，否则订阅端 `TOPICS[key]` KeyError；`Node.pub/send` 传**短键**
   (封装自带 `zmax/` 前缀，传全名 = 双重前缀 KeyError)。
3. **突发要节流 + 配置要防呆**：一口气灌 N 条会被写端 `KEEP_LAST(1)` 覆盖(80/182 → 加 1ms/条
   后零丢失)；`CYCLONEDDS_URI=file://<0 字节>` 会让参与者掉出发现网，表现为“发了配对=0”
   —— 空/缺配置一律当未配置处理并告警，且发布端与守护端要同一套防呆。

深度: `references/bus-observability.md`(深历史/节流/短键/档位跟随/防呆/回灌口径)；
四色状态灯(绿正常·红故障·黄报警·黑无信号)的唯一口径与取值坑: `references/status-lamp-four-colors.md`。

## 验证顺序（每步都要真跑，别跳）
```
① 纯模型自检: 4 个 dataclass 能否构造
② 本机 pub→sub 往返（同进程）: 证明 DDS 栈通
③ 跨进程 + 单播配置: 证明发现通 ← 这一步才是"多网卡坑"的照妖镜
④ 三端真实数据: watcher 打印收到的**实际字段值**（不是"应该收到了"）
```

## 反例：别用 DDS 的场景
```
✗ 只有两个进程在同一台机器上通信 → 用队列/Unix socket, 杀鸡用牛刀
✗ 只需要"请求-应答"(RPC 语义) → DDS 是数据分发, 用它的 RR 模式或直接 HTTP
✗ 现场网络只允许 80/443 且拿不到固定端口 → 别硬上
✗ 端侧(NPU/DSP/裸 MCU) → 先确认有没有 RTPS 栈, 别默认能跑
```
