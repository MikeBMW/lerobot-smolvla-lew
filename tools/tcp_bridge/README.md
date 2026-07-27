# TCP Topic Bridge — Orin ↔ PC 只读数据桥

安全的 ROS2 Topic 转发工具。Orin 端**只订阅不发布**，通过 TCP 将 topic 数据实时转发到 PC，零风险触碰电机控制。

## 文件结构

```
tools/tcp_bridge/
├── orin_forwarder.py    # Orin 端：订阅 ROS2 topic → TCP Server
├── pc_receiver.py       # PC 端：TCP Client → 显示/记录
├── run_orin.sh          # Orin 一键启动
└── run_pc.sh            # PC 一键启动
```

## 数据流

```
Orin: joint_state_pub ──→ DDS ──→ forwarder ──TCP:9999──→ PC receiver ✅ 只读
Orin: camera_pub     ──→ DDS ──→ forwarder ──TCP:9999──→ PC receiver ✅ 只读
```

## 快速开始

### Orin 端（先启动）

```bash
cd ~/xspace/tcp_bridge
bash run_orin.sh
```

### PC 端（后启动）

```bash
cd tools/tcp_bridge
bash run_pc.sh
```

## 高级用法

```bash
# Orin: 自定义端口和图片抽帧率
PORT=8888 THROTTLE=5 bash run_orin.sh

# PC: 连接指定 Orin + 保存日志
python3 pc_receiver.py --host 192.168.23.10 --port 9999 --log session.jsonl

# PC: 安静模式（仅记录不显示）
python3 pc_receiver.py --quiet --log data.jsonl
```

## 安全

- Orin 端 **仅 Subscriber**，不创建 Publisher
- 不涉及 `/arm/target_action` 或任何控制指令 topic
- 关闭 Orin 端即可断开，不影响其他 ROS2 节点

## 依赖

| 端 | 依赖 |
|----|------|
| Orin | ROS2 Humble, Python 3.10+ (stdlib) |
| PC | Python 3 (stdlib only, 无需 ROS2) |
