# Cyclone DDS Python 绑定 · 实测笔记（11.0.1 / Python 3.11）

> 全部为**当场踩过并修好**的记录。版本不符时先按下面代码验一遍，再照结论用。

## 1. IDL 类型：没有 `string`
```python
# ❌ ImportError: cannot import name 'string' from 'cyclonedds.idl.types'
from cyclonedds.idl.types import float64, int32, sequence, string

# ✅ IDL string 用 Python 内置 str
from cyclonedds.idl.types import float64, int32, sequence
```
该版本 `cyclonedds.idl.types` 实际导出：`array bounded_str byte char float32 float64`
`int8..int64 sequence typedef uint8..uint64 wchar`（**无 string**）。

## 2. QoS Policy 的 API **不一致**（最坑）
```python
from cyclonedds.core import Policy
Policy.Reliability.Reliable        # 可调用: Reliable(max_blocking_time)
Policy.Reliability.BestEffort      # ❌ 不可调用: 'BestEffort' object is not callable
Policy.History.KeepLast            # 可调用: KeepLast(n)
Policy.History.KeepAll             # 可调用
Policy.Durability.TransientLocal   # ❌ 不可调用（传类本身）
```
**统一兜底写法**（一次写对，别逐个子类试）：
```python
def _p(cls, *a):
    """有的可调用有的不可 → 能调就调, 不能就原样用"""
    try:
        return cls(*a)
    except TypeError:
        return cls

def qos_for(kind):
    if kind == "cmd":      # 指令不许丢
        return Qos(_p(Policy.Reliability.Reliable, 0), _p(Policy.History.KeepAll, 0))
    if kind == "beat":     # 心跳丢了无所谓
        return Qos(_p(Policy.Reliability.BestEffort, 0), _p(Policy.History.KeepLast, 1))
    return Qos(_p(Policy.Reliability.Reliable, 0), _p(Policy.History.KeepLast, 1),
               _p(Policy.Durability.TransientLocal))   # 状态: 新订阅者立刻拿最新
```

## 3. `__dict__` 含 `SampleInfo` → 不可 JSON 序列化
```python
# ❌ TypeError: Object of type SampleInfo is not JSON serializable
json.dump(msg.__dict__, f)

# ✅ 按话题白名单提取 IDL 字段
KEYS = {"hw_state": ("node", "role", "backend", "device_name", "ts",
                     "util_pct", "mem_used_mb", "mem_total_mb", "temp_c", "power_w"),
        "heartbeat": ("node", "role", "alive", "ts", "extra")}
d = {}
for k in KEYS[topic]:
    v = getattr(m, k, None)
    if isinstance(v, list):          # sequence[str] → 保证可序列化
        v = [str(x) for x in v]
    d[k] = v
```
> 兜底也可 `dataclasses.asdict(m)`，但仍建议白名单 —— 顺便把内部字段挡在 JSON 之外。

## 4. XML 配置：这些元素该版本不接受
```xml
<!-- ❌ 初始化直接 DDS_RETCODE_ERROR -->
<General>
  <Interfaces><NetworkInterface name="auto"/></Interfaces>   <!-- 指定网卡: 不支持 -->
  <Ports><Base>7400</Base><Max>7410</Max></Ports>            <!-- Ports 元素: 不支持 -->
</General>

<!-- ⚠️ 告警(可用但会被提示搬家) -->
<Internal><LeaseDuration>30s</LeaseDuration></Internal>       <!-- 必须放 <Discovery> 下 -->
```
**最小可用组合**（实测通过）：`<General><AllowMulticast>false</AllowMulticast></General>`
＋ `<Discovery><ParticipantIndex>auto</ParticipantIndex><LeaseDuration>30s</LeaseDuration>
<Peers><Peer address="..."/></Peers></Discovery>`。

**排查手法**：把 XML 拆成最小片段逐个加，跑
`CYCLONEDDS_URI=file://x.xml python -c "from cyclonedds.domain import DomainParticipant; DomainParticipant(0)"`
—— 哪个片段一加就 error，就是它。见 `scripts/` 的用法说明。

## 5. 发现是异步的：必须等配对
```python
w = DataWriter(dp, topic, qos=qos)
while not w.get_matched_subscriptions() and time.time()-t0 < 15:
    time.sleep(0.2)            # 不等就 write → 首条消息丢给"还没发现"的 reader
w.write(msg)
```
`DataReader` 侧对应 `get_matched_publications()`。
**排查"收不到"时先看这个数**：它就是 0 说明是发现/网络问题，不是消息内容问题。

## 6. 多网卡主机（本机实测 4 个网卡）
`lo / enx* / wlp* / docker0` 共存时，默认多播发现可能挂在 docker0 →
**发布端写成功、订阅端 0 条**。改单播配置后立刻通。
⇒ 单播配置应当作**默认**，不要留给"跨公网时再加"。
