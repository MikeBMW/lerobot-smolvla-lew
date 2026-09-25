# 硬件工具箱接 Orin 真机 — 「无法连接 192.168.23.66」根因 + VEH-ID 定位 + 重启姿势 (2026-09-16)

本次会话: 本机与 Orin 局域网已打通(直连, 见技能 `orin-lan-direct-access`), 但老倪点硬件工具箱
连 Orin 报「无法连接 192.168.23.66」。查证结论: **网络没问题, 是 GUI 侧三个陈旧配置**。

## 1. 根因: 旧账号 nvidia(不是网络)

`tools/gui/hardware_simulator.py` → `class HardwareDiscoveryThread`:
```python
ORIN_HOST = "192.168.23.66"
ORIN_USER = "nvidia"      # ← 废弃账号(nvidia@.10 时代); 当前 Orin 账号 = tashan
```
`run()` 第一步 `self._ssh("echo OK")` → rc≠0 即 `results["error"] = f"无法连接 Orin ({HOST}): {out}"`,
`_on_discovery_result` 弹窗「硬件发现失败 / 无法连接到 Orin 或发现硬件」。实测:
`ssh nvidia@192.168.23.66` → `Permission denied (publickey,password)`。
**改 `ORIN_USER = "tashan"` 即通** (commit 09fe1125)。仓库内同类残留(未改, 参考):
`hermes_gateway_mac/update_robot_status.py`、`hermes_gateway_mac/collect_full_status.py`、
`hermes_gateway_mac/install_backdoor.py`、`experiments/infer/infer_camera.py`(都是 nvidia@192.168.23.10)。

## 2. 配套三条(不修则"改了账号还是连不上")

**① GUI 全部 ssh 路径靠免密, 本机没密钥 = 所有硬件按钮都连不上。**
`HardwareDiscoveryThread._ssh_opts` 只有 StrictHostKeyChecking/ConnectTimeout, `studio.py` 的
_tower_cmd / _gripper_cmd / 拍照 / cam_cap 也全是裸 `ssh`/`scp` — 都不带口令(发现硬件弹窗自己也写
"请确认 SSH 免密已配置")。本机 `~/.ssh` 原本只有 known_hosts → 必失败。
修:
```bash
ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub | sshpass -p ts123 ssh tashan@192.168.23.66 \
  'cat >> ~/.ssh/authorized_keys && sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys'
ssh -o BatchMode=yes tashan@192.168.23.66 'echo 免密OK'
# studio 的所有硬件命令都走这个复用 socket, 预建可省每次重连:
ssh -o ControlMaster=auto -o ControlPath=/tmp/orin-ssh.sock -o ControlPersist=120 -fN tashan@192.168.23.66
```

**② ros2 命令必须 `export ROS_DOMAIN_ID=0`。** 机器人在域 0; 域 23 只看到 `/rosout` →
会被误报成「Orin 上 ROS2 未运行。请先启动机器人系统。」。已给发现线程的三条 ros2 命令都加上。

**③ TCP bridge 探测模式要跟现役进程名。** 原 `pgrep -f 'orin_forwarder'` 永远是 STOPPED
(现役网关 = `~/.zmax/orin_gateway.py`, 监听 8765) → 改 `pgrep -f 'orin_gateway|orin_forwarder'`。

## 3. 验证姿势: 直接跑线程, 别开 GUI

```python
# gui-venv311/bin/python (系统 python3 无 PyQt5)
os.environ["QT_QPA_PLATFORM"]="offscreen"; sys.path.insert(0, "tools/gui")
app = QApplication([])
from hardware_simulator import HardwareDiscoveryThread
t = HardwareDiscoveryThread(); t.progress.connect(print); res = {}
t.result_ready.connect(lambda r: res.update(r)); t.start()
while not res: app.processEvents(); time.sleep(0.05)
```
修复后实测: `success=True` · 18 节点 · 46 Topic · 10 条 topic 详情 · 系统资源(CPU/DISK/UPTIME) ·
`TCP bridge running=True, 8765 listening=True`。修复前: `error=无法连接 Orin (192.168.23.66)`。

## 4. 「VEH.x.y 是什么」——编号是运行时的, grep 不到

老倪报 **VEH.0.86 = 首页 System 0 卡「硬件工具箱」**。要点:
- 编号器 `_holo_apply_all` / `_veh0_apply` 定义在 **TrainingModule** 里(studio.py), 由主窗口调用
  `self.model_engine._holo_apply_all(self)` — 所以复现脚本必须走 `w.model_engine`, 不能在 StudioMainWindow 上找。
- **必须 `w.show()`**: 同一份代码, 不 show → VEH.0.86 落到「模型引擎」; show → VEH.0.86 =「硬件工具箱」,
  差 7 个控件(编号按布局 y→x, 且依赖可见性)。验证 VEH-ID 时先 show 再编号。
- 硬件页 VEH.3 实测 28 控件: 01 仿真档下拉 / 02 ▶启动仿真 / 03 ↺重置 / 04 🔍发现硬件 / 05 硬件表 /
  06 🔴触发急停 / 07 🟢释放急停 / 08 关节表 / 09 表格 / 10 参数输入 / 11 应用 / 12 分组框 /
  13 表格 / 14-17 塔灯四色 / 18 力传感📡 / 19 🛑 / 20 🖐️开 / 21 ✊关 / 22-26 📡 / 27 分组框 / 28 🔌连接摄像头。
- 画布版见 `references/hardware-toolbox-flow.md`(42 节点 = 14 关节 + 执行器4 + 感知6 + 相机7 + 安全IO6)。

## 5. 改 GUI 码后重启控制台 —— pkill 自杀升级版 + 分离启动

⚠️ **方括号技巧不够**: 本轮 `pkill -f "[s]tudio.py"; sleep 3; pgrep …; systemd-run … studio.py …`
**自杀**(exit -15) —— 因为同一条命令行里的 systemd-run 段含明文 `studio.py`, pkill 匹配到 shell 自身,
后面 sleep/pgrep/systemd-run 全没执行。**正解: kill 与 start 分成两条 terminal 调用**, 且 kill 那条整行
不得出现明文目标名。判定: 命令返回 exit_code=-15 且输出被截断 = 自杀, 不是被测进程的问题。

分离启动(关终端不死, 推荐):
```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
systemd-run --user --unit=zmax-studio --collect \
  --setenv=DISPLAY=:0 --setenv=XAUTHORITY=/run/user/1000/gdm/Xauthority --setenv=XDG_RUNTIME_DIR=/run/user/1000 \
  /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python /home/ubuntu/lerobot-smolvla-lew/tools/gui/studio.py
systemctl --user status zmax-studio --no-pager     # Main PID / Active since
```
XAUTHORITY 取法(本机 = /run/user/1000/gdm/Xauthority):
`tr '\0' '\n' < /proc/$(pgrep -f gnome-terminal-server | head -1)/environ | grep -iE '^(DISPLAY|XAUTHORITY)'`。
汇报三连 = 新 pid + `ps -o lstart= -p <pid>` + **窗口映射实证** `DISPLAY=:0 xdotool search --name "Z-MAX"`
(只断言进程活着不算证据, 老倪会问"真的起来了么")。

## 6. Orin 侧硬件基线(同批次体检, 域 0)

18 节点在跑: robot_driver / gripper_driver / honeywell_scanner / tactile_force_node / tower_light / motion /
vision / vision_tag / vision_pointcloud / pointcloud_receiver / obstacle_marker / external_comm /
hmi_v1_tashan_bridge / orin_shadow / ss_collector / robot_state_publisher / sim_joint_state_publisher / scene_mesh_marker。
速率: `/real_joint_states` 100.8Hz(珞石 XMS5-R800) · `/robot/joint_states` 49.5 · `/robot/force_torque` 50.5 ·
`/gripper_pos` 12.1 · `/barcode_scanner/status` 1.0 · `/tower_light/status` 1.0(state=complete) · `/robot_status` 2.2。
服务 `/gripper_driver [interfaces/srv/GripperSrv]` 在线(**别随手调, 会真动夹爪**)。
串口: ttyACM0 Honeywell 3320g / ttyACM1 Artery LED 塔灯 / ttyUSB0 FTDI FT232R。

**体检判据(哪些"无数据"是正常的)**: 急停 `/usb_estop`、`/physical_estop` 是事件型 → 静默正常, 验证要现场按一下;
`/motion/active_states` 静默 = 装配状态机没在跑(与"闭环数据全 IDLE/臂一直没动"同一条因果链)。

**相机(2026-09-16 未结案, 不要当结论用)**: 老倪说"相机连着呢", 但 Orin 侧 `lsusb` 无任何相机
(只有 FT232R / Artery LED / CH341 / Metrologic 3320g / VIA+Genesys 集线器)、无 `/dev/video*`、
`/realsense/color/image_raw` **Publisher=0 但 Subscription=2**(vision_tag 以 RELIABLE 在等) → 该域内没有发布者。
线索两条待确认: ① 机器人 launch 配置(sr5_guangmokuai_*AOI/start.launch.yaml)注释写着
"RealSense is not required for this project; keep only the Mech-Mind backend"(`camera_backend: mechmind_realsense`,
realsense_source 走 /realsense/points|color/image_raw|depth/image_rect_raw) → 可能是配置如此;
② 本机(ThinkBook)`lsusb` 有一条 `Microdia Dual Mode Camera (0c45:8006)` + `/dev/video0~3` → 相机可能接在
**本机或工控机(192.168.23.23, 仅 22 端口通)/Mac(192.168.23.1)** 上。**下次先问清接在哪台再去那台查**,
别只在 Orin 上反复翻。

**「Publisher=0 而有订阅者」就是这个域的"上游没起"信号** —— 用它区分"没数据因为节点没起" vs
"节点起了但设备没接": 有订阅者说明消费者在等, 缺发布者就是设备/驱动侧问题。
