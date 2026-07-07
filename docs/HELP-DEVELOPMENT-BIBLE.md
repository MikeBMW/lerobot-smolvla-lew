# Z-MAX 操作手册 · User Manual

> **Z-MAX 多模态动作专家 — XSpace Studio 完整操作指南**
> 
> 版本: v1.0.3+ | 编制: 智蜂创元(ZFCY) | 更新: 2026-07-06
> 
> 本文档是 Z-MAX 的唯一权威操作手册。无论是否有 Orin 连接，均可按本文档完成所有功能的验证和操作。

---

## 一、快速开始

### 1.1 启动 Z-MAX

```bash
cd ~/lerobot-smolvla-lew
bash start.sh
```

或 VSCode 里: `Ctrl+Shift+B`

### 1.2 界面总览

```
┌──────────────────────────────────────────────────────────┐
│  [📁文件] [👁视图] [📖帮助文档] [ℹ关于]   菜单栏          │
├────────┬─────────────────────────────────────────────────┤
│ 侧边栏  │  主内容区（9个功能模块）                         │
│        │                                                 │
│ System2│  🏠首页 · 📊数据集 · 🏋️训练 · ✅评估             │
│ Sys-12 │  🔧硬件 · ⚙️配置 · 📈监控 · 🤖插拔 · 🔄版本     │
│ Sys-11 │                                                 │
│ Sys-0  │                                                 │
├────────┴─────────────────────────────────────────────────┤
│  ● 状态栏                                                │
└──────────────────────────────────────────────────────────┘
```

主页顶部按钮: `● smolvla_lew` `🔄同步到GitHub` `📦版本同步` `📋解决方案` `📊PPT汇报` `📱分享`

---

## 二、核心功能: 实时监控（5 种信号源）

实时监控是 Z-MAX 的核心数据可视化模块，支持 5 种信号源 + 2 种可视化引擎。

### 2.1 界面布局

```
┌─ 信号源 ───────────────┐ ┌─ 可视化引擎 ───────┐
│ ○ 回放数据 [session ▼] │ │ [📊 Rerun Web]     │
│ ○ 仿真数据              │ │ [🤖 RViz ROS2]     │
│ ○ 演示动画              │ │ 端口: 9877         │
│ ○ 实时数据              │ │                    │
│ ○ 离线仿真              │ │                    │
│ 状态: xxx               │ └────────────────────┘
├────────────────────────────────────────────────┤
│  [▶ 启动]  [⏹ 停止]                   ● 就绪   │
├──────────────┬─────────────────────────────────┤
│ Topics [刷新]│ Nodes                          │
│ 30个topic    │ 18个节点                       │
├──────────────┴─────────────────────────────────┤
│ ── 实时信号追踪 ──                             │
│ joint_states  J1:+0.41 J2:+0.49 ...          │
│ gripper_pos   180.0                           │
│ force_torque  Fx:+4.81 Fy:-5.58 Fz:+1.56     │
├────────────────────────────────────────────────┤
│ [日志]                                         │
└────────────────────────────────────────────────┘
```

### 2.2 5 种信号源详解

#### 信号源 1: 回放数据
**用途**: 回放历史采集的机器人数据
**数据来源**: CSV文件 (replay_001) 或 .rrd 文件
**操作流程**:
1. 选 ○ 回放数据
2. 下拉框选 `replay_001`
3. 会话自动加载（33帧珞石真机数据）
4. 点 ▶ 启动 → 生成 replay.rrd → 自动打开 Rerun Web Viewer
**离线可用**: ✅（数据已保存在本地）

#### 信号源 2: 仿真数据
**用途**: Z700 14-DOF 正弦波仿真
**数据来源**: hardware_simulator.py (本地仿真引擎)
**操作流程**:
1. 选 ○ 仿真数据
2. 自动启动仿真引擎
3. 点 ▶ 启动 → 生成 sim.rrd → 打开 Rerun
**离线可用**: ✅

#### 信号源 3: 演示动画
**用途**: 6-DOF 彩色机器人动画演示
**数据来源**: 本地生成的 robot_demo.rrd (60帧)
**操作流程**:
1. 选 ○ 演示动画
2. 自动生成 .rrd 文件 (65KB)
3. 点 ▶ 启动 → 打开 Rerun, 浏览器访问 http://127.0.0.1:9090
**离线可用**: ✅

#### 信号源 4: 实时数据
**用途**: SSH 连接 Orin (192.168.23.10) 拉取真实 ROS2 数据
**数据来源**: Orin ROS2 Domain 23 (需要 Orin 在线 + 机器人运行)
**操作流程**:
1. 选 ○ 实时数据
2. 自动 SSH 获取 topic/node 列表
3. Topic/Node 面板 显示完整列表
4. 信号追踪面板 每1.5秒刷新7个关键topic
5. 点 ▶ 启动 → 采集5秒 → live.rrd → Rerun
**离线可用**: ❌（需要 Orin 在线）
**Orin 端要求**: `ROS_DOMAIN_ID=23 ros2 daemon start`

#### 信号源 5: 离线仿真
**用途**: 完全本地模拟（无需 Orin）
**数据来源**: hardware_simulator.py 本地假数据
**操作流程**:
1. 选 ○ 离线仿真
2. 自动启动本地仿真引擎
3. 假 topic/node 列表 + 正弦波信号数据
4. 信号追踪实时更新（0.5秒间隔）
5. 点 🔄 刷新 可更新 Topic/Node 列表
**离线可用**: ✅

### 2.3 2 种可视化引擎

| 引擎 | 说明 | 离线 |
|------|------|------|
| 📊 Rerun (Web) | 本地 Web Viewer · port 9877 · 浏览器打开 | ✅ |
| 🤖 RViz (ROS2) | ROS2 原生 3D 可视化 · 需 source 环境 | 需 ROS2 |

### 2.4 离线验证清单

以下功能 **不需要 Orin 连接**，可离线完整验证:

| 功能 | 操作 | 预期结果 |
|------|------|---------|
| 演示动画 → Rerun | 选○演示→点▶启动→浏览器 | 3D彩色机器人动画 |
| 仿真数据 → Rerun | 选○仿真→点▶启动→浏览器 | 14-DOF关节动画 |
| 回放数据 → Rerun | 选○回放→选replay_001→点▶启动 | 珞石真机33帧回放 |
| 离线仿真面板 | 选○离线仿真→观察面板 | 7个topic实时刷新 |
| 分享二维码 | 首页点📱分享 | 弹出GitHub二维码 |

---

## 三、硬件工具箱

### 3.1 硬件总线面板 (CANoe 风格)
12 路真实硬件一行一个，支持状态读取和控制操作。

| 硬件 | 控制方式 | 经验 |
|------|---------|------|
| 🚦 三色塔灯 | `/tower_light/command` pub "green"/"yellow"/"red"/"off" | ✅ 实测三色全通，0.3秒响应 |
| 🖐️ 电动夹爪 | `/gripper_driver` GripperSrv (target_pos 0-200) | ✅ 开/关两个按钮最实用 |
| 🤖 珞石机械臂 | 📡读取关节 + 🛑急停 | idle时不发关节数据 |
| 📷 RealSense D405 | 📸拍照弹窗显示 | ✅ 实测39KB JPEG |
| 🖐️ 触觉传感器 | TS-F-L, BEST_EFFORT模式 | 有接触才发数据 |

### 3.2 仿真模式 (System 0)
- **启动仿真**: 14-DOF 正弦波 + 7路相机测试图案 + 六维力传感器
- **设备树**: 左侧层级设备列表，点击联动右侧详情
- **详情面板**: 关节状态表 / 相机状态 / 六维力 / IO状态
- **急停控制**: IO面板可触发/释放急停

### 3.2 Real 模式 (Orin 真机)
- **发现硬件**: SSH 到 Orin 发现全部 ROS2 节点和 Topic
- **拓扑表**: 节点数/Topic数/系统资源/GPU/内存/TCP Bridge
- **真机节点列表**: 显示真实 ROS2 节点

### 3.3 数据回放面板
- **会话选择**: replay_001 等已采集数据
- **播放控制**: ▶播放 ⏸暂停 ⏹停止
- **进度条**: 紫色进度条实时更新
- **关节显示**: J1~J6 实时位置 + 夹爪开度

---

## 四、其他功能模块

### 4.1 数据集管理 (System 2)
- 浏览 HuggingFace LeRobot 数据集
- 下载指定数据集到本地
- 查看数据内容（图像/视频/state）

### 4.2 训练控制台 (Sys-11)
- SmolVLA-LEW 端到端训练
- 训练参数可视化配置
- 实时训练曲线监控

### 4.3 评估分析 (Sys-12)
- LeWorldModel 验证
- 动作回放分析
- 成功率统计

### 4.4 配置中心
- 架构模式选择 (Sys-11纯动作 / Sys-11+Sys-12混合)
- VLM骨干网络配置
- Action Head (DiT-B) 参数
- LeWorldModel 参数
- 优化器 & 调度器
- 配置导出 YAML

### 4.5 插拔场景
- Z700 轮式双臂机器人概述
- 8步插拔流程可视化
- ROI 投资回报计算器

### 4.6 版本同步
- LeRobot 上游更新检查
- 安全同步 (git merge)
- 冲突检测

---

## 五、程序架构原理

### 5.1 技术栈

```
前端: PyQt5 (暗色主题)
后端: Python 3.12 (conda lerobot)
仿真: hardware_simulator.py (独立线程, 1ms周期)
可视化: Rerun SDK 0.33.1 + CLI (--web-viewer)
ROS2: Humble (Domain 23, SSH远程)
数据: CSV + rosbag (.db3) + Rerun (.rrd)
```

### 5.2 数据流

```
┌──────────┐    SSH     ┌──────────┐    QThread   ┌──────────┐
│  Orin    │───────────→│  WSL     │────────────→│  GUI     │
│ ROS2 D23 │  topic echo │  Monitor │  signal    │  Display │
└──────────┘            └──────────┘             └──────────┘
                              │
                              ├──→ .rrd 生成 → rerun --web-viewer
                              ├──→ CSV 回放   → ReplayEngine
                              └──→ 仿真引擎   → HardwareSimulator
```

### 5.3 关键文件

| 文件 | 功能 |
|------|------|
| `tools/gui/studio.py` | 主界面 (5850+行) |
| `tools/gui/hardware_simulator.py` | 仿真引擎 + 回放引擎 + 发现线程 |
| `tools/gui/version_sync.py` | 版本管理 |
| `tools/gui/training_backend.py` | 训练后台 |
| `tools/tcp_bridge/` | Orin-PC 数据桥 |
| `docs/HELP-DEVELOPMENT-BIBLE.md` | 开发宝典 |
| `docs/VERSION.md` | 版本规范 |

---

## 六、Rerun 可视化

### 6.1 启动方式

1. 选信号源 → 点 ▶ 启动 → 自动生成 .rrd
2. 自动执行 `rerun <.rrd> --web-viewer`
3. 浏览器打开 `http://127.0.0.1:9090`

### 6.2 查看内容

- **3D 视图**: 彩色关节球 + 连线 + 轨迹
- **RGB 坐标轴**: 红色X · 绿色Y · 蓝色Z
- **时间轴**: 底部拖动播放/暂停
- **时间序列**: 右侧面板可查看各关节数值

### 6.3 已生成的 .rrd 文件

| 文件 | 大小 | 内容 |
|------|------|------|
| `robot_demo.rrd` | 65KB | 6-DOF演示动画 |
| `replay.rrd` | 5KB | 珞石真机33帧 |
| `zmax_bag_001.rrd` | 3.3MB | rosbag 328秒真机数据 |
| `live.rrd` | 47KB | 实时采集5秒 |
| `sim.rrd` | 首次生成 | 14-DOF仿真 |

---

## 七、分享功能

### 7.1 操作

首页点击 `📱 分享` → 弹出二维码对话框 → 手机扫码 → 打开 GitHub 项目页

### 7.2 二维码内容

```
https://github.com/MikeBMW/lerobot-smolvla-lew
Z-MAX 多模态动作专家
Z700 轮式双臂机器人
精度±0.02mm | 成功率>99%
```

---

## 八、实战经验与 Know-How

> ⚠️ 本章是 2026-07-06 全天实战的结晶。每一个条目背后都是踩过的坑。

### 8.1 SSH 连接 Orin — 核心加速技巧

**问题**: 每次 hardware bus 点击按钮要等 3 秒以上，因为每次新建 SSH 连接。

**解决**: SSH ControlMaster 连接复用
```bash
# 建立持久连接 (在GUI自动执行)
ssh -o ControlMaster=auto -o ControlPath=/tmp/orin-ssh.sock \
    -o ControlPersist=120 -fN nvidia@192.168.23.10

# 后续命令加这个参数，3秒 → 0.3秒
ssh -o ControlPath=/tmp/orin-ssh.sock nvidia@192.168.23.10 "..."
```

**教训**: 高频远程命令必须复用连接。Z-MAX 在 HardwareModule 初始化时自动建立复用。

### 8.2 ROS2 daemon 故障 — 头号坑

**症状**: `ros2 topic list` 报 `!rclpy.ok()` 错误

**原因**: 有两个 daemon 在跑——Domain 0（默认）和 Domain 23（机器人）。`ros2` 命令没有 `ROS_DOMAIN_ID=23` 前缀时自动创建 Domain 0 daemon，它看不到机器人的 topic。

**解决**:
```bash
# 彻底清理
pkill -9 -f ros2-daemon

# 重启正确的 daemon
ROS_DOMAIN_ID=23 ros2 daemon start

# 验证
ROS_DOMAIN_ID=23 ros2 topic list  # 应该显示 51 个 topic
```

**教训**: 
- 所有 ros2 命令必须加 `ROS_DOMAIN_ID=23`
- GUI 的 SSH 轮询命令用了 `source /opt/ros/humble/setup.bash` 未加 domain 也会触发此问题
- 不要让 Domain 0 daemon 存在

### 8.3 Rerun 可视化 — WSL 里的血泪史

**迭代过程**:
1. `rr.init("app", spawn=True)` — WSL GPU 不支持，失败
2. `rr.serve_web_viewer()` — API 变更，阻塞 GUI
3. Python API `rr.serve_grpc()` + `rr.serve_web_viewer()` — 复杂且卡顿
4. **最终方案**: `subprocess.Popen(["rerun", file, "--web-viewer"])` — 最简单、最可靠

**教训**:
- WSL 不能用原生 GPU 渲染，必须用 `--web-viewer`
- **不要在 GUI 主线程里执行 Rerun API** — 全部用 subprocess 后台启动
- Rerun 0.33.1 API 频繁变更: `rr.Scalar(v)` → `rrc.Scalar(v)`, `set_time_seconds` → `set_time`
- 端口冲突: 每次启动前 `pkill -f "rerun.*web-viewer"`

### 8.4 触觉传感器 — "为什么没数据？"

**现象**: 第一次读到数据（通用小拇指 TS-F-L），之后一直无数据

**原因**: 
- QoS: BEST_EFFORT + VOLATILE — 消息不保证送达
- **事件驱动**: 只在真正有物理接触时发布
- robot idle 状态时完全不发

**教训**: 传感器分"持续发布"和"事件驱动"两类。不能因为无数据就认为坏了。

### 8.5 夹爪控制 — 设计迭代

**三个版本**:
1. 滑块拖动 (QSlider) — 手感差，难以精确定位
2. ◀▶ 步进按钮 (-1cm/+1cm) — 操作反馈慢，不知道当前状态
3. **最终版**: 🖐️开(200) / ✊关(0) 两个按钮 — 简单粗暴，最实用

**教训**: **简单就是最好的设计**。不要过度设计控制精度，实际使用中只需要全开/全关。

### 8.6 相机拍照 — 避坑指南

**问题**: `ros2 topic echo --once` 返回图像数据很大（4MB），终端无法处理

**解决**: 用 Python 脚本在 Orin 端用 cv_bridge 直接转 JPEG
```python
# Orin 端脚本 capture_cam.py
os.environ["ROS_DOMAIN_ID"] = "23"  # 必须在 init 前设置!
rclpy.init(args=[])
bridge = CvBridge()
# 订阅 /realsense/color/image_raw
# cv2.imwrite("/tmp/cam.jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
```

**教训**:
- `ROS_DOMAIN_ID` 必须在 `rclpy.init()` 之前设置
- 相机在 idle 状态不推流，需要拍摄时先确认机器人状态
- 图像数据必须压缩后传输（4MB raw → 39KB JPEG）

### 8.7 网络问题 — GitHub / HuggingFace

**常见故障**:
- GitHub push 超时: 通常 DNS 解析失败或国际出口拥堵
- HuggingFace `Connection reset by peer`: 直连被墙
- `hf-mirror.com` 镜像: 有模型不分发数据集

**应对**:
- GitHub: 重试或等待网络恢复，代码已本地提交
- HuggingFace: 优先用 `hf-mirror.com` 下载模型，数据集尽量一次下载缓存
- 数据集名不能拼错: `metaworld_mt50` 不是 `meta_wool_mt50`

### 8.8 信号源选择 — 什么时候用什么

| 场景 | 推荐信号源 | 原因 |
|------|-----------|------|
| 离线开发/调试 | 离线仿真 | 零依赖，本地14-DOF正弦波 |
| 演示/培训 | 演示动画 | 漂亮的3D动画，无需数据 |
| 查看历史数据 | 回放数据 | 328秒真机rosbag回放 |
| 连Orin调试 | 实时数据 | 看topic/node列表+信号 |
| 对比算法 | 仿真数据 | 可控的14-DOF参数仿真 |

### 8.9 实时数据轮询 — 性能权衡

**问题**: 1.5 秒轮询 7 个 topic 太慢，降低间隔会加重 SSH 负担

**经验**:
- 配合 SSH ControlMaster，0.3 秒响应已经够快
- 不要轮询 `ros2 topic echo --once`（等消息到达），改用 `timeout 3` 限制等待
- 机器人 idle 时所有 topic 都无数据，这是正常的
- 信号追踪面板的"余晖效果"就是为了区分"有数据"和"无数据"

### 8.10 文档路径 — 经典 Bug

**问题**: 所有帮助文档打不开，路径多了一层 `tools/`

**原因**: `studio.py` 在 `tools/gui/` 下，`os.path.dirname` 需要 3 层才到项目根目录，不是 2 层。

```python
# ❌ 错误: 2层 → /home/.../tools/
self.repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ✅ 正确: 3层 → /home/.../lerobot-smolvla-lew/
self.repo_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

### 8.11 ROS2 topic 数据采集 — 最佳实践

**录制 rosbag** (推荐用于回放):
```bash
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && \
  ROS_DOMAIN_ID=23 ros2 bag record \
  /robot/joint_states /gripper_pos /robot/force_torque \
  /robot/tcp_pose /robot_status /emergency_stop /tower_light/status \
  -o session_name"
```

**rosbag → Rerun**:
```python
# 用 rosbag2_py 读取 .db3 → rr.log() → rr.save(".rrd")
# 338MB rosbag → 3.3MB .rrd
```

**rosbag → 终端回放**:
- WSL 不能 `ros2 bag play`（DDS 不通）
- 用 `_start_replay_display` QTimer 逐帧读取 → 信号面板显示

#### 8.11b. MCAP 数据日志方案（推荐）

Z-MAX 数据量大（433GB/h），推荐使用 **MCAP** 格式替代传统的 SQLite rosbag。

| 特性 | Rosbag (.db3) | MCAP (.mcap) |
|------|---------------|-------------|
| 底层 | SQLite3 数据库 | 扁平化二进制 buffer |
| 传输 | 需要完整文件 | 支持流式边录边传 |
| 容错 | 数据库损坏难恢复 | chunk 级自恢复 |
| 压缩 | Zstd | Zstd（高20-30%） |
| 上位机读取 | 需 ROS2 环境 | `pip install mcap` 即可 |

**录制命令**:
```bash
# Orin 端 MCAP 录制
ros2 bag record -s mcap -o session_name \
  /realsense/color/image_raw /realsense/depth/image_rect_raw \
  /robot/force_torque /robot/joint_states /gripper_pos \
  /tactile_sensor /robot_status \
  --compression-mode file --compression-format zstd
```

**Windows 上位机读取**（无需 ROS2）:
```python
from mcap.reader import make_reader
with open("session.mcap", "rb") as f:
    for schema, channel, message in make_reader(f).iter_messages():
        pass  # 直接解析 message.data
```

**决策**: Z-MAX 选 MCAP。详细分析见 `docs/Z-MAX数据日志方案-MCAP分析.md`。

### 8.12 PyQt5 暗坑

1. **`QThread` 必须 import**: `from PyQt5.QtCore import QThread`
2. **`QScrollBar` 样式**: `QScrollArea` 内的 `<pre>` 字体不会自动继承 QFont
3. **`QTableWidget.setCellWidget`**: 删除行后 widget 不会自动析构
4. **SSH subprocess 不要用 `shell=True`**: 引号转义地狱
5. **`QTextEdit.setHtml`** 不支持 CSS `{{}}` 双花括号（f-string 冲突）

### 8.13 数据源设计哲学

经过一天的实战，信号源设计遵循以下原则：

1. **一个信号源 = 一种数据来源**，不混淆
2. **离线优先**: 4/5 信号源离线可用
3. **自动检测**: rosbag .rrd 存在时自动使用，不需要用户选择
4. **统一输出**: 所有源最终生成 .rrd → Rerun
5. **终端辅助**: 回放数据同步显示在信号面板

---

## 九、功能等级定义 · L1~L5 自动化标准

### 9.1 行业标准对照

| 等级 | 名称 | 定义 | 决策 | 人工角色 | Z-MAX对应 |
|------|------|------|------|----------|-----------|
| **L1** | 辅助操作 | 单一功能辅助，人做主要动作 | 人 | 全程参与 | — |
| **L2** | 分段式自动化 | 预设工序自动执行，人监控切换 | 人编排 | 编排+监控 | **Z700 F 基线** |
| **L3** | 条件自动化 | 传感器+视觉自动适应，人处理异常 | 机器+人 | 异常处理 | Z700 增强版 |
| **L4** | 高度自动化 | 全自主执行+自适应+自恢复 | 机器 | 仅在极限情况 | Z700 旗舰版 |
| **L5** | 完全自主 | 任何场景无人工干预，自我进化 | 机器 | 零参与 | 未来目标 |

### 9.2 Z-MAX 产品等级详细定义

#### L2 基线版（Z700 F · Sys-0 分段式）
- **核心能力**: 人工流程编排 + 标准原子功能库 + 分段验证
- **技术架构**: 系统 0 · 动作(标准接口) · 真实环境运行
- **操作方式**: 6步流程（人工编排→原子功能→动作执行→力控反馈→AOI验证→下料）
- **关键指标**: 关键工序良率 ≥99.2%
- **硬件**: SR5-C机械臂 + AGX Orin NX + 双3D相机 + DH夹爪 + TS-T-15触觉
- **安全**: 双路急停 + 安全光栅 + 三色塔灯
- **状态**: 已交付 · 苏州实验室 Phase 0 验收通过

#### L3 增强版（Sys-1 多模态端到端）
- **新增能力**: 多模块自主识别 · 自主闭环工作 · 换线自主换配方 · 异常诊断自恢复
- **技术升级**: 系统 1 · SmolVLA 多模态端到端模型 · 视觉引导定位
- **升级方式**: OTA 软件升级 · 现有硬件不变
- **关键指标**: 全工序良率 ≥99.5%
- **时间**: 2026 Q4

#### L4 旗舰版（Sys-11 精细感知全自主）
- **新增能力**: VLA视觉语言动作模型 · 精细感知 · 场景引导 · AI主动安全
- **技术升级**: 系统 11 · 潜空间压缩优化 · 精细感知模型 · 力控预判 · 触觉闭环
- **安全升级**: 五层主动保护（力控预判·触觉闭环·光幕联动·自诊断·AI预测）
- **升级方式**: OTA 软件升级 · 现有硬件不变
- **关键指标**: 全工序良率 ≥99.9% · 7×24无人值守
- **时间**: 2027 Q2

### 9.3 对比示例：光模块插入工序

| 场景 | L1 人工 | L2 Z700 F | L3 增强 | L4 旗舰 |
|------|---------|-----------|---------|---------|
| 模块识别 | 人眼看型号 | 人工扫码 | **自动视觉识别** | AI自动适配未知型号 |
| 夹爪切换 | 人换工装 | 人换工装 | **自动切换400G/100G** | AI决策最优工装 |
| 插入对准 | 人手对准 | 点到点预设位姿 | **视觉引导对准** | 精细感知±0.02mm |
| 力控保护 | 人手感知 | 力传感器阈值停机 | 力控自适应 | **力控预判+触觉闭环** |
| 异常处理 | 人判断 | 人工处理 | **自动诊断+重试** | AI预测+主动避让 |
| 换线转产 | 人重设全部参数 | 人重选配方 | **扫码自动加载配方** | AI零编程自适应 |

### 9.4 升级路径

```
L2 基线版 ──OTA──→ L3 增强版 ──OTA──→ L4 旗舰版
  (已交付)         (2026Q4)           (2027Q2)

硬件平台: Z700 F → Z700 (同一硬件，仅软件升级)
模型引擎: Sys-0 → Sys-1 → Sys-11
```


## 十、常见问题

**Q: 启动报错 qt.qpa.xcb?**
A: WSL里需要 X Server。运行 `export DISPLAY=:0` 或使用 `start.sh` 启动。

**Q: Rerun 打不开?**
A: 确保 rerun CLI 已安装。运行 `which rerun` 确认。

**Q: 实时数据无显示?**
A: 检查 Orin 连接和 ROS2 daemon。Orin 终端: `ROS_DOMAIN_ID=23 ros2 daemon start`

**Q: 离线能用哪些?**
A: 回放/仿真/演示/离线仿真 — 4 种信号源完全离线可用。

**Q: 如何录制 rosbag?**
A: 连上 Orin 后，终端执行: `ros2 bag record /robot/joint_states /gripper_pos ...`

---

> **📌 本文档与 Z-MAX 产品版本同步更新。离线开发、在线调试，一册通晓。**
> 
> GitHub: https://github.com/MikeBMW/lerobot-smolvla-lew
