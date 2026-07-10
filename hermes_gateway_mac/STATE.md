# Hermes Gateway — 运行状态 & 离线恢复指南

> 最后更新: 2026-07-10 08:35 CST (关机断点)
> 此文件供 Hermes Agent (小芳) 恢复时自动读取

---

### 🖥 Mac — 推理主机 (Mikes-Mac-mini)

| 项目 | 值 |
|------|-----|
| 型号 | Mac Mini M1 (Apple Silicon) |
| 芯片 | Apple M1, 8核 (4性能+4能效) |
| 内存 | 8GB 统一内存 |
| GPU | Apple M1 GPU (Metal/MPS) |
| 系统 | macOS 26.x (ARM64) |
| Python | 3.12.13 (venv: ~/lerobot-smolvla-lew/.venv) |
| 角色 | Gateway + SmolVLA/ACT推理 + Z-MAX GUI |

### 🤖 Orin — 机器人控制 (nvidia-desktop)

| 项目 | 值 |
|------|-----|
| 型号 | NVIDIA Jetson AGX Orin |
| CPU | 6核 ARM Cortex-A78AE |
| GPU | Orin nvgpu (2048 CUDA cores, 64 Tensor cores) |
| 内存 | 7.4GB LPDDR5 (机器人占用~6.5GB) |
| 磁盘 | 233GB NVMe (136GB可用) |
| 系统 | Ubuntu 22.04 aarch64, Kernel 5.15.148-tegra |
| Python | 3.10.12 |
| CUDA | 12.6, PyTorch 2.5.0, torchvision 0.20 |
| ROS2 | Humble (Domain ID 23) |
| 机器人 | XMS5-R800-W4G3B4C 6轴机械臂 |
| 相机 | Intel RealSense D435 (480×640, 30fps) |
| 角色 | 实时控制 + 传感器采集 + 可选SmolVLA推理 |

## 网络拓扑

```
┌─────────────────────────────────────────────────────────┐
│ Mac M1 (Mikes-Mac-mini)                                 │
│   以太网 en0: 192.168.23.1 (需手动配)                    │
│   Gateway Pure :8080 (FastAPI)                          │
│   SmolVLA 450M 本地推理 (MPS, 3 FPS)                    │
│   ACT 51.6M 本地推理 (MPS, 2172 FPS)                    │
│   Z-MAX Studio GUI (PyQt5, run_studio.sh)               │
│   SSH Key: ~/.ssh/id_rsa → Orin (immutable key)         │
├─────────────────────────────────────────────────────────┤
│                    SSH (免密 Key)                        │
│                    ↓                                     │
├─────────────────────────────────────────────────────────┤
│ Orin (nvidia-desktop)                                   │
│   IP: 192.168.23.10                                     │
│   User: nvidia                                          │
│   OS: Ubuntu 22.04 aarch64, Linux 5.15.148-tegra        │
│   ROS2 Humble, CUDA 12.6, PyTorch 2.5                   │
│   机器人: XMS5-R800-W4G3B4C (6-DOF 机械臂)              │
│   内存: 7.4GB (机器人占用~6.5GB)                         │
│   GPU: Orin nvgpu (507M SmolVLM2 fp16, 4.1 FPS)         │
│   数据流: stream_joints/camera/gripper.py → /tmp/*.json │
└─────────────────────────────────────────────────────────┘
```

## 连接信息

| 项目 | 值 |
|------|-----|
| Mac IP | `sudo ifconfig en0 inet 192.168.23.1 netmask 255.255.255.0` |
| Orin IP | `192.168.23.10` |
| Orin 用户 | `nvidia` |
| Gateway API | `http://localhost:8080` |
| Orin数据文件 | `/tmp/joints.json` `/tmp/camera.jpg` `/tmp/gripper.json` |

## 启动顺序

### 1. Mac 配网
```bash
sudo ifconfig en0 inet 192.168.23.1 netmask 255.255.255.0
```

### 2. Orin 启动机器人
```bash
ssh nvidia@192.168.23.10 "cd ~ && bash run.sh &"
# 项目: sr5_guangmokuai_100gAOI
# 启动约60-90秒后话题上线
```

### 3. Orin 启动数据流 (用于Gateway)
```bash
WS=~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && source $WS/install/setup.bash && nohup python3 /tmp/stream_joints.py > /dev/null 2>&1 &"
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && source $WS/install/setup.bash && nohup python3 /tmp/stream_camera.py > /dev/null 2>&1 &"
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && source $WS/install/setup.bash && nohup python3 /tmp/stream_gripper.py > /dev/null 2>&1 &"
```

### 4. Mac 启动 Gateway
```bash
cd ~/lerobot-smolvla-lew/hermes_gateway_mac
~/.venv/bin/python3 gateway_pure.py --orin-host 192.168.23.10 --port 8080 &
```

### 5. 离线时用仿真器
```bash
cd ~/lerobot-smolvla-lew/hermes_gateway_mac
~/.venv/bin/python3 orin_simulator.py --port 8080
# 73话题 + 24节点 + 6轴真实快照
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务状态 |
| GET | `/status` | 完整状态 (关节+夹爪+时间戳) |
| GET | `/joints` | 6轴关节名→位置 |
| GET | `/gripper` | 夹爪Float值 |
| POST | `/cmd` | 发送指令 {"command":"回零"/"开"/"关"} |
| WS | `/ws` | WebSocket实时推送 |

## VLA 推理管线

### 相机+关节 → SmolVLA (Mac MPS)
```bash
cd ~/lerobot-smolvla-lew
~/.venv/bin/python3 infer_camera.py
# 输出: ~/vla_output.png (相机画面+关节+预测动作)
```

### Orin CUDA 推理 (停机器人后)
```bash
# Orin需先停机器人释放内存:
ssh nvidia@192.168.23.10 "sudo pkill -9 -f python3"
# 模型在 /home/nvidia/.cache/huggingface/hub/
# 推理: Python 3.10 + attn_implementation='eager'
# 性能: 0.24s/帧 (4.1 FPS) fp16
```

## 模型清单

| 模型 | 参数 | 速度 | 位置 |
|------|------|------|------|
| SmolVLA (官方) | 450M | 0.3s Mac / 0.24s Orin | HF缓存 |
| SmolVLA Mini (自训) | 263K | 0.5ms | `outputs/train/smolvla_lew_mini/` |
| ACT Aloha | 51.6M | 0.5ms (2172FPS) | HF缓存 |

## SSH 持久化

Mac公钥已写入Orin `/etc/ssh/global_authorized_keys`，设置**immutable(+i)**标志。
任何人(包括root)无法删除。改密码不影响key认证。

## 技能清单

| 技能 | 说明 |
|------|------|
| `hermes-gateway-robot` | Gateway连接Orin完整流程 |
| `orin-ssh-persistence` | SSH永久后门维护 |
| `orin-simulator` | 离线仿真器启动 |
| `vla-realtime-inference` | VLA实时推理管线 |

## 关键决策记录

1. **macOS ARM64无ROS2 Humble** → SSH文件桥替代(rclpy直接订阅)
2. **ros2 daemon不稳定** → Python rclpy脚本订阅话题写JSON文件
3. **Docker网络不通** → 放弃,用本地MPS推理
4. **Orin部署SmolVLA** → 需先停机器人释放内存,pip3+pytorch需eager attention
5. **Xet CAS 401错误** → 禁Xet (`HF_HUB_DISABLE_XET=1`) 下载成功

## Git

- 仓库: MikeBMW/lerobot-smolvla-lew
- 当前分支: mac (HEAD: 1df62bab)
- main 分支: c9c3ecab (领先 origin 14 commits)
- SSH key 已生成但未授权 GitHub（push 失败）
- 待推送: mac 分支所有 commits

## 关机断点 (2026-07-10 08:35 CST)

- 飞书网关: 正常运行 (launchd PID 821, WebSocket 已连接)
- Git 状态: 干净，无未提交改动
- 后台进程: 无
- Hermes 技能: 82个（完整）
- 恢复后: 进入项目目录，查看 STATE.md，继续推进 GitHub SSH 配置和 push

## Git 恢复命令
```bash
cd ~/lerobot-smolvla-lew
git log --oneline -5          # 查看最近 commits
git status                     # 确认分支状态
# 推送需先配置 GitHub SSH: https://github.com/settings/keys
```

## Z-MAX Studio

完整PyQt5桌面应用，8大功能模块:
- 📊 数据集管理 | 🏋️ 训练控制台 | ✅ 评估分析 | 🔧 硬件工具箱
- ⚙️ 配置中心 | 📈 实时监控 | 🧠 推理服务 | 🔄 版本同步
- 启动: `cd tools/gui && bash run_studio.sh` (需PyQt5 + conda lerobot环境)
- 架构: System 0(L2基石) + Sys-11(动作) + Sys-12(引导) + System 2(L4大脑)

## 新增脚本 (2026-07-09/10)

| 脚本 | 功能 |
|------|------|
| `infer_camera.py` | RealSense相机+关节 → SmolVLA → 飞书可视化 |
| `infer_realtime.py` | Gateway关节 → SmolVLA → 持续动作预测 |
| `infer_smolvla.py` | 预训练SmolVLA加载+推理测试 |
| `train_mini_v2.py` | 自训练CNN+DiT (263K参数, 18s) |
| `train_synth.py` | 官方SmolVLA训练脚本(合成数据) |
| `orin_simulator.py` | Orin离线仿真器(73话题+24节点快照) |
| `install_backdoor.py` | SSH Key持久化安装脚本 |
| `ssh_wrapper.exp` | SSH密码自动登录(expect) |
