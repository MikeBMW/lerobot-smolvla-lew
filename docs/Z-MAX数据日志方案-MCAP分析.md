# Z-MAX 数据日志方案：Rosbag vs MCAP 对比分析

> 决策文档 | 2026-07-07 | 智蜂创元(ZFCY)

---

## 一、两种格式概述

| 特性 | Rosbag (.db3) | MCAP (.mcap) |
|------|---------------|-------------|
| 底层存储 | SQLite3 数据库 | 扁平化二进制 buffer |
| 索引方式 | 内置 B-tree 索引 | 自描述 chunk + 外部索引 |
| 随机访问 | ✅ 支持（需索引） | ✅ 支持（chunk header） |
| 压缩 | Zstd（rosbag2） | Zstd/LZ4（内置） |
| 多机传输 | 需要完整文件 | 支持流式传输 |
| 跨语言 | C++/Python | C++/Python/Rust/Go/JS |
| 规范标准 | ROS2 社区 | OSRF 官方标准 |
| 单文件大小 | 受 SQLite 限制（~140TB 理论） | 无上限 |
| 损坏恢复 | 困难（数据库损坏） | 容易（chunk 级恢复） |

---

## 二、Z-MAX 场景分析

### 2.1 数据负载

Z700 F 在正常工序中产生的数据：

| 数据源 | 类型 | 频率 | 单条大小 | 1小时数据量 |
|--------|------|------|---------|------------|
| RGB 相机 (2路) | `sensor_msgs/Image` | 30fps | ~1.5MB | ~324GB |
| 深度图 (2路) | `sensor_msgs/Image` | 30fps | ~0.5MB | ~108GB |
| 力传感器 | `WrenchStamped` | 1kHz | ~200B | ~720MB |
| 关节状态 | `JointState` | 100Hz | ~500B | ~180MB |
| 夹爪位置 | `Float32` | 50Hz | ~50B | ~9MB |
| 触觉传感器 | `TactileSensor` | 事件驱动 | ~200B | ~10MB |
| Robot Status | `String` | 10Hz | ~200B | ~7MB |
| **总计** | | | | **~433GB/h** |

### 2.2 关键需求

1. **传输到上位机**：WSL/XSpace Studio 需要从 Orin 拉取日志做离线分析
2. **随机访问**：快速跳转到特定时间点查看数据
3. **存储效率**：433GB/h 的数据量需要高效压缩
4. **容错性**：录制中断不应导致整个文件损坏
5. **跨平台**：Orin (Linux ARM64) → WSL (Linux x64) → Windows 上位机

---

## 三、决策：选择 MCAP

### 推荐方案：rosbag2 + MCAP 存储后端

```bash
# 录制命令（在 Orin 上）
ros2 bag record -s mcap -o session_name \
  /realsense/color/image_raw \
  /realsense/depth/image_rect_raw \
  /robot/force_torque \
  /robot/joint_states \
  /gripper_pos \
  /tactile_sensor \
  /robot_status \
  --compression-mode file \
  --compression-format zstd
```

### 选择理由

| 理由 | 说明 |
|------|------|
| **传输友好** | MCAP 是扁平文件，单个 `.mcap` 直接 scp/ftp/http 传输，不需要索引文件 |
| **流式读取** | MCAP 支持边传边读，上位机可以在录制进行中就拉取分析 |
| **容错强** | chunk 级自描述，网络中断/磁盘满不会损坏已录制的 chunk |
| **压缩更好** | Zstd 压缩比通常比 rosbag2 SQLite 压缩高 20-30% |
| **跨语言** | Python 直接 `pip install mcap` 读取，Windows 上位机无需 ROS2 |
| **未来兼容** | MCAP 是 ROS2 官方推荐的长期格式（已纳入 REP-2006） |

### 上位机读取方案

```python
# 在 Windows/XSpace Studio 上读取 MCAP（无需 ROS2）
from mcap.reader import make_reader

with open("session.mcap", "rb") as f:
    reader = make_reader(f)
    for schema, channel, message in reader.iter_messages():
        # 直接解析 message.data
        pass
```

**保持 rosbag2 兼容**：Orin 端仍用 `ros2 bag record -s mcap` 录制，API 不变，只改存储后端。

---

## 四、迁移路径

### 当前（Phase 0）→ 目标（L2 投产）

```
当前:  ros2 bag record (默认 SQLite .db3)
        ↓  仅改一个参数
目标:  ros2 bag record -s mcap (MCAP .mcap)
```

### XSpace Studio 集成

1. 硬件总线 → 增加「录制」按钮
2. SSH 通道自动拉取 MCAP 文件到 WSL
3. Python `mcap` 库解析 → Rerun .rrd 可视化
4. Windows 上位机直接读取 MCAP 文件

---

## 五、结论

**Z-MAX 选择 MCAP 作为数据日志格式。**

- 录制：`ros2 bag record -s mcap`
- 存储：单个 `.mcap` 文件，Zstd 压缩
- 传输：SSH scp 到上位机，支持流式边录边传
- 上位机：Python `mcap` 库直接读取，无需 ROS2
- 兼容：rosbag2 API 完全兼容，仅改存储后端参数

**风险**：MCAP 生态相比 rosbag2 SQLite 略新，但已是 ROS2 Humble 默认支持，且 OSRF 官方主推。

**附录**：当前 Orin 已安装 ros-humble-rosbag2 0.15.16，原生支持 `-s mcap`。
