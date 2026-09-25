# DDS 三端消息中间件（Cyclone DDS 实测）

场景：ECS(公网) / 4060(内网) / Mac(另一网络) 三端互相交换**实时状态**
（硬件资源、训练进度、部署指令、心跳）。用户原话：「ecs 4060 mac 消息中间件用 DDS 技术实现」。

相对 HTTP relay 的定位：
- **HTTP relay / WS**（本技能 §1-§11）：文件传输、队列、通知事件 —— 仍保留。
- **DDS**：多端**实时状态分发**（每端既是发布者又是订阅者，无中心，QoS 可控）。
  选它的理由：OMG 标准、类型化话题、QoS 分级（状态 vs 指令 vs 心跳）、跨语言。
  不选它的理由（如实说）：跨公网需要单播配置 + 放行动态 UDP 端口，比 HTTP 麻烦。

---

## 1. 安装（一次性）

```bash
python3 -m venv ~/dds-venv
~/dds-venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ cyclonedds
```
装完**独立 venv**：cyclonedds 不进主环境，DDS 侧脚本用它跑；零依赖的 HTTP 控制台读 JSON 即可（见 §6 桥接）。
实测版本：`cyclonedds 11.0.1`（Python 3.11）。

---

## 2. Cyclone DDS 11 的 API 不一致（写在最前，否则 import 就挂）

**(a) `cyclonedds.idl.types` 里没有 `string`**
```python
from cyclonedds.idl.types import float64, int32, sequence   # ✅
from cyclonedds.idl.types import ... string                # ❌ ImportError
```
IDL 的 string 直接用 Python 内置 `str` 标注。

**(b) Policy 有的可调用、有的不可 —— 用兜底 helper**
```python
def _p(cls, *a):
    """Reliable(n)/KeepLast(n) 可调用; BestEffort / Durability.TransientLocal 不可调用"""
    try:
        return cls(*a)
    except TypeError:
        return cls

qos = Qos(_p(Policy.Reliability.Reliable, 0), _p(Policy.History.KeepLast, 1),
          _p(Policy.Durability.TransientLocal))
```
实测：`Policy.Reliability.Reliable(0)` ✅ / `Policy.Reliability.BestEffort(0)` ❌ TypeError /
`Policy.History.KeepLast(1)` ✅ / `Policy.Durability.TransientLocal` ✅（不带括号）。

---

## 3. 跨网 XML 配置 —— 只有一种组合可用（实测排除法）

可用（**唯一**验证通过的最小组合）：
```xml
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain id="any">
    <General>
      <AllowMulticast>false</AllowMulticast>
    </General>
    <Discovery>
      <ParticipantIndex>auto</ParticipantIndex>
      <LeaseDuration>30s</LeaseDuration>   <!-- ★ 必须在 Discovery 下 -->
      <Peers>
        <Peer address="127.0.0.1"/>          <!-- 本机自测 -->
        <Peer address="<内网IP>"/>
        <Peer address="<对端IP>"/>
        <Peer address="<ECS 公网IP>"/>
      </Peers>
    </Discovery>
    <Internal>
      <HeartbeatInterval>2s</HeartbeatInterval>
      <WriterLingerDuration>2s</WriterLingerDuration>
    </Internal>
  </Domain>
</CycloneDDS>
```

❌ **会 `DDSException: [DDS_RETCODE_ERROR]` 初始化失败**（实测逐个排除）：
| 写法 | 结果 |
|---|---|
| `<General><Interfaces><NetworkInterface name="auto"/></Interfaces></General>` | ❌ 失败 |
| `<General><Ports><Base>7400</Base><Max>7410</Max></Ports></General>` | ❌ 失败 |
| `<General><Ports><Base>7400</Base></Ports></General>` | ❌ 失败 |
| `<General><Ports><Base>7400</Base><ParticipantGain>2</ParticipantGain></Ports></General>` | ❌ 失败 |
| 只 <AllowMulticast>false</AllowMulticast> + <Peers> | ✅ 可用 |
| `<LeaseDuration>` 放 `<Internal>` 下 | ⚠️ 仅告警 "setting moved"，但仍可用 |

**排查手法（值得复用）**：不要猜，写 4-6 个变体各存一个 XML，循环 `DomainParticipant(0)` 看哪个过 ——
30 秒定位到具体非法元素。比读文档快，且结论可复现。

**未固定端口的代价（如实标注）**：该版本不支持固定端口 → 防火墙必须放行 UDP 动态端口段。
若现场只允许开固定端口，需换 Fast DDS 或升级版本（未验证，勿当结论）。

---

## 4. ★ 多网卡陷阱：默认多播会选错网卡，消息一条都收不到

**症状**：发布端日志正常刷 `📤 ...`，订阅端/桥 **收到 0 条**，`matched_publications = 0`，
两个进程都活着，无任何报错。

**根因**：本机有 4 个网卡（`lo` / `enx00e04c0c32a0` / `wlp0s20f3` / `docker0`）。
DDS 默认多播发现（`AllowMulticast` 默认开）可能挑中 docker0 或某个没有对端的网卡 →
两端发现消息走不到一起。**这是"看起来在发、实际收不到"的头号原因。**

**修法**：**永远用 §3 的单播配置**（`AllowMulticast=false` + `<Peers>` 明确列 127.0.0.1 与对端 IP），
并把它设为脚本的**默认 `--cfg`**，不要指望调用方记得加。

**判别**：先跑自检（pub→sub 同进程往返）。同进程能收到、跨进程收不到 → 100% 是发现/网卡问题。
`reader.get_matched_publications()` 为 0 即坐实。

---

## 5. 其他三个必踩的坑

**(a) 发现是异步的 —— 先等配对再发**
新参与者刚建就 `write()`，样本会丢给"还没发现"的读者。发前等配对：
```python
for _ in range(N):
    if len(writer.get_matched_subscriptions()) >= 1: break
    time.sleep(0.2)
```

**(b) IDL 消息 `__dict__` 含 `SampleInfo`，不能直接 JSON 化**
```
TypeError: Object of type SampleInfo is not JSON serializable
```
按话题**白名单提取字段**，丢弃 DDS 元数据：
```python
keys = {"hw_state": ("node","role","backend","device_name","ts","util_pct", ...)}
d = {k: getattr(m, k, None) for k in keys[topic]}
```

**(c) 未测到的量 = `-1.0`，不用 `0` 冒充**
`0%` 利用率、`0W` 功耗都是**合法实测值**；"取不到"必须能与"真的是 0"区分。
默认值全给 `-1.0`，前端把 `< 0` 渲染成 `—`。这条在跨端展示时尤其重要（Mac 没有统一的
GPU 利用率接口 → 明确 `-1.0`，而不是填 0 让人以为 GPU 闲着）。

---

## 6. 话题 / QoS 设计（按用途分层，不要一刀切）

| 话题 | 类型 | QoS | 理由 |
|---|---|---|---|
| `zmax/hw_state` | HardwareState | RELIABLE · KEEP_LAST(1) · **TRANSIENT_LOCAL** | 状态类：新订阅者**立刻**拿到最新值（latch 语义），不用干等下一个周期 |
| `zmax/train_prog` | TrainProgress | 同上 | 同上 |
| `zmax/deploy_cmd` | DeployCommand | RELIABLE · **KEEP_ALL** | 指令**不许丢**，与状态类的取舍相反 |
| `zmax/heartbeat` | Heartbeat | BEST_EFFORT · KEEP_LAST(1) | 心跳丢了无所谓，不值得重传 |

**桥接模式（本会话最实用的架构决定）**：
零依赖的 HTTP 控制台跑在**系统 python**，cyclonedds 在**dds-venv** → 不要硬把两者塞进一个进程。
```
dds-venv:  dds_bridge.py   订阅 DDS → 写 reports/dds_latest.json（按节点名索引 + recv_ts/age_s/stale）
系统python: 控制台 /api/hardware 读该 JSON → 面板每节点一张卡
```
两侧解耦：控制台保持零依赖、DDS 侧可独立重启，任一侧挂掉另一侧不崩。

---

## 7. 验收清单（缺一不算通）

1. 同进程 pub→sub 往返收到 1 条（证明栈通）。
2. **跨进程**：发布端 + 订阅端各一个进程 → 收到 ≥1 条（证明发现通）。
3. 带跨网 XML 再跑一遍 2（证明单播配置有效）。
4. `matched_publications > 0`。
5. 把收到的字段逐个打印（node/role/device_name/数值），确认**不是空壳**。
6. 桥 JSON 落盘后，控制台端点能读到同样数值（端到端闭环）。

## 8. 本会话踩坑账单（供未来对照）

| 现象 | 根因 | 修法 |
|---|---|---|
| `ImportError: cannot import name 'string'` | 该版本无 `string` 类型 | 用内置 `str` |
| `'Durability.TransientLocal' object is not callable` | Policy API 不一致 | `_p()` 兜底 helper |
| `'Reliability.BestEffort' object is not callable` | 同上 | 同上 |
| XML 初始化 `DDS_RETCODE_ERROR` | `<Interfaces>` / `<Ports>` 不被接受 | 只用 AllowMulticast=false + Peers |
| 发布正常但订阅 0 条 | 多网卡下多播选错网卡 | 默认单播配置（Peers 列全） |
| `Object of type SampleInfo is not JSON serializable` | `m.__dict__` 含 DDS 元数据 | 按字段白名单提取 |
| 首次 write 后订阅端收不到 | 发现是异步的 | `wait_for_match` 后再发 |
