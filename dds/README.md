# 📡 Z-MAX 三端消息中间件（DDS）

老倪 2026-09-25：「ecs 4060 mac 消息中间件用DDS技术实现」

## 技术选型
**Eclipse Cyclone DDS**（OMG DDS 标准实现）· pip 可装 · Linux/Mac/Windows 通用。
```bash
python3 -m venv ~/dds-venv && ~/dds-venv/bin/pip install cyclonedds
```

## 四话题（QoS 按用途区分）
| 话题 | 类型 | QoS | 用途 |
|---|---|---|---|
| `zmax/hw_state` | HardwareState | RELIABLE · KEEP_LAST(1) · **TRANSIENT_LOCAL** | 硬件实际值（新订阅者立刻拿到最新）|
| `zmax/train_prog` | TrainProgress | 同上 | 训练进度（真实步数）|
| `zmax/deploy_cmd` | DeployCommand | RELIABLE · **KEEP_ALL** | 部署/回滚指令（不许丢）|
| `zmax/heartbeat` | Heartbeat | BEST_EFFORT · KEEP_LAST(1) | 节点存活（丢了无所谓）|

**约定**：未测到的量 = `-1.0`（**不用 0 冒充**，0 是合法实测值）。

## 三端角色
| 端 | 发布 | 订阅 |
|---|---|---|
| **4060**（静静/工作端）| hw_state（CUDA）· train_prog · heartbeat | deploy_cmd |
| **Mac**（小芳/备份端）| hw_state（**MPS**）· heartbeat | deploy_cmd |
| **ECS**（公网中转）| deploy_cmd | 全部 |

## 用法
```bash
# 4060 端（持续发布）
/home/ubuntu/dds-venv/bin/python tools/dds_node_4060.py --interval 5

# Mac 端（小芳）
python3 tools/mac_hw_report.py --dds            # 用 DDS 上报（含 MPS 实际值）
python3 tools/mac_hw_report.py --dds --watch 30 # 每 30s 持续

# 跨网（公网 ECS）加配置
--cfg dds/cyclonedds_unicast.xml
# 或 export CYCLONEDDS_URI=file://<repo>/dds/cyclonedds_unicast.xml
```

## 跨网关键（实测踩坑，勿回退）
```
✅ 可用: <General><AllowMulticast>false</AllowMulticast></General> + <Discovery><Peers>单播列表</Peers>
❌ 不可用（该版本会 DDS_RETCODE_ERROR）:
   · <Interfaces><NetworkInterface name="auto"/></Interfaces>
   · <General><Ports><Base>..</Base><Max>..</Max></Ports></General>
告警修正: <LeaseDuration> 必须放 <Discovery> 下（放 Internal 会告警）
防火墙: 未固定端口 → 需放行 UDP 动态端口段; 若只能开固定端口, 该版本 Ports 语法不可用（需换 Fast DDS）
```
