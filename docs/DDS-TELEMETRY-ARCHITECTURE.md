# Z-MAX 遥测架构：DDS topic 只用于 测试 / 标定 / 诊断，量产关闭

> 老倪 2026-09-25：「topic用于测试，标定，诊断，量产时不用，你来设计架构，
> 即我可以随时用topic，但量产会关闭」

## 一、设计原则（四条）

| 原则 | 含义 | 落地方式 |
|---|---|---|
| **协议统一** | 全局数据空间统一用 DDS 话题语义（话题名/字段/QoS 一套口径） | `dds/zmax_types.py` + `ss_types.py` 单一类型源 |
| **传输可关** | 「是否真的起 DDS 发布/订阅」是**模式**，不是代码分支 | `zmax_telemetry.py` 单一开关 |
| **量产零开销** | prod 模式**根本不 import cyclonedds**、不起线程、不开端口 | `telemetry_bus()` 在 prod 直接 `return None` |
| **随时可开** | 一条命令/一个右键/一个环境变量切换，**业务代码零改动** | CLI + 画布右键 + env + 模式文件 |

## 二、模式定义（按用途分档，每档只开需要的话题子集）

| 模式 | 用途 | 开启话题 | 典型场景 |
|---|---|---|---|
| `prod` | **量产（默认）** | **无（全关）** | 出厂/现场生产运行 |
| `diag` | 诊断 | hw_state · heartbeat · ss_infer · train_prog | 现场排查硬件/性能/延时 |
| `calib` | 标定 | 上面 + ss_state · ss_action · link_value | 手眼标定、几何/力校准 |
| `test` | 测试 | 全量 11 个话题（含画布节点/宏观层/部署指令） | 功能测试、回归、整链验证 |
| `dev` | 开发 | = test | 日常开发 |

## 三、开关优先级（从高到低）

```
① 环境变量  ZMAX_TELEMETRY=diag      ← 进程级，最高优先（CI/脚本用）
② 运行时    set_mode("diag")         ← GUI 右键 / 外部 agent 调用
③ 模式文件  ~/.zmax_telemetry_mode   ← 跨进程共享，随时改（现场最常用）
④ 缺省      prod                     ← 不配置就是量产安全态
```

## 四、两条通道必须分开（重要）

```
┌─ 通道 A：内网遥测（测试/标定/诊断）
│   用途: 观测连线数据、标定量、性能诊断
│   开关: **遥测模式**（prod = 关）
│   影响面: 仅本机/局域网内部, 关掉不影响业务
│
└─ 通道 B：对外上报（硬件 → 手机 APP / 网页）
    用途: 老倪明确要求的「APP 显示 4060 硬件/显存」交付功能
    开关: **独立**（服务 zmax-dds-agg / zmax-hw-upload）
    影响面: 关掉 = APP 看不到硬件数据
```
> ⇒ **量产关闭的是通道 A（内网遥测）**；通道 B 是否跟随关闭，由交付口径决定
> （若要"量产也保证 APP 可见硬件"，则 B 单列一个开关，不随遥测模式走）

## 五、业务代码怎么用（零分支）

```python
from zmax_telemetry import telemetry_bus

bus = telemetry_bus()          # prod → None（零开销）；其他模式 → DDS 总线
if bus is not None:            # 唯一的分支点
    bus.publish(node_id, name, port, value)
```
- `bus is None` ⇒ 走本进程内存（`_sim_signals`）—— **原链路完全不变**（零回退）
- `bus` 可用 ⇒ 同一份数据**同时**是可被跨进程/跨机消费的 DDS topic

## 六、怎么用（三种入口）

```bash
# ① 命令行（脚本/外部 agent）
python3 tools/gui/zmax_telemetry.py --status          # 看当前
python3 tools/gui/zmax_telemetry.py --mode diag       # 切诊断
python3 tools/gui/zmax_telemetry.py --toggle          # 量产 ⇄ 诊断 一键切

# ② 画布空白处右键 → 遥测模式菜单（勾选当前模式 + 一键切换）

# ③ 环境变量（单进程覆盖）
ZMAX_TELEMETRY=calib python3 tools/gui/studio.py
```

## 七、安全护栏

| 护栏 | 说明 |
|---|---|
| **默认安全态** | 不配置 = prod（全关）→ 量产环境不会因为漏配置而误开 |
| **误调不出网** | prod 下 `telemetry_bus()` 返回 None → 连 import 都不发生，**不可能**意外发包 |
| **DDS 缺失不崩** | 非 prod 但没装 cyclonedds → 打印提示并返回 None，业务继续跑 |
| **QoS 分档** | 信号=BEST_EFFORT·KL(3) · 状态=RELIABLE·KL(1)·TRANSIENT_LOCAL · 指令=RELIABLE·KEEP_ALL |
| **帧龄拒收** | 每条消息带 ts+seq，消费端拒收过期帧 |
| **单播配置** | 多网卡环境必须（默认多播会选错网卡→静默收不到） |

## 八、实测验证（不是设计稿）

```
prod  → 总线=None(全关) | 🔴 量产关闭（无 DDS, 零开销）      ← 零 import ✓
diag  → 总线=DDS | 4 话题(heartbeat,hw_state,ss_infer,train_prog) | 读到值 ✓
calib → 总线=DDS | 5 话题(+link_value,ss_state,ss_action)         | 读到值 ✓
test  → 总线=DDS | 11 话题(全量)                                  | 读到值 ✓

画布连线: 写点发布 → 订阅端 recv=1 → 读到值 ✓
连线右键「📡 打开 DDS Topic」: 显示实时值/发布接收计数/可复制 ✓
```

## 九、文件清单

| 文件 | 作用 |
|---|---|
| `tools/gui/zmax_telemetry.py` | ★ 模式开关（单一事实源）+ 受控总线工厂 + CLI |
| `tools/gui/dds_link_bus.py` | 连线 DDS 总线（发布/订阅缓存 + stats） |
| `tools/gui/simulink_module.py` | 画布接入（写点发布 / 读点优先DDS / 空白右键菜单 / 连线右键 Topic 窗） |
| `dds/zmax_types.py` · `zmax_dds/ss_types.py` | 类型契约（硬件/训练/部署/状态空间/连线） |
| `dds/zmax_node.py` | DDS 节点封装（TOPICS + QoS 分档） |
| `dds/cyclonedds_unicast.xml` | 跨网单播配置（多网卡必需） |
