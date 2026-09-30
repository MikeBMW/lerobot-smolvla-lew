# 硬件工具箱 (VEH.3) · 真机(Orin)链路 4 个真根因 — 2026-09-16 实测

老倪当天连问: 「点红色应该变红」→「发现硬件怎么崩了」→「按钮为什么反应很慢」, 并纠正过一次
「是 VEH.0.86 硬件工具箱」。**四个问题四个独立根因**, 全部实测定位, 全部已修 (v5.6.14)。

速查:
- 页面 = `HardwareModule` (studio.py, `setObjectName("hardware")` → VEH.3.xx); 首页卡片标签 VEH.0.86 = 「硬件工具箱」
- 发现硬件 = VEH.3.04 按钮 → `HardwareDiscoveryThread` (定义在 `hardware_simulator.py`, **不在** studio.py)
- 真机栈: 18 ROS 节点 / 46 话题, **ROS_DOMAIN_ID=0**(不是 23), 服务 `/gripper_driver [interfaces/srv/GripperSrv]`

## 1. 点「发现硬件」弹「无法连接 192.168.23.66」= 账号写死旧值
- `HardwareDiscoveryThread.ORIN_USER = "nvidia"` (nvidia@.10 时代遗留) → `ssh nvidia@.66` = Permission denied → rc!=0
  → 直接报 `无法连接 Orin (192.168.23.66)`。studio.py 其它路径早已改用 `tashan`, 只有这个发现线程漏改。
- 配套两条: ① GUI 所有 ssh 路径靠**免密**(弹窗自己写着"请确认 SSH 免密已配置"); 本机无密钥时一律连不上 →
  `ssh-keygen -t ed25519 -N ''` + 公钥写入 `tashan@.66:~/.ssh/authorized_keys`。② ros2 命令前必须
  `export ROS_DOMAIN_ID=0`, 否则只看到 `/rosout`, 会被误判成"Orin 上 ROS2 没跑"。
- `/tmp/orin-ssh.sock` (ControlMaster=auto, ControlPersist=120) 是 GUI 多处硬用的复用通道, **别指望它常驻**
  (闲置即消失, `ssh -O check` 报 No such file) — 但 ssh 会回退直连, 所以免密配好就不影响功能。
- 改完实测: `success=True · 18 节点 · 46 话题 · 10 条详情 · 8765 listening=True`。

## 2. 点一下就「崩」(进程直接消失, 没有报错弹窗) = Qt 槽里未捕获异常
- 真 traceback: `studio.py:7372  Z700_ROS2_NODES.get("real", {}).get(n, "")` —
  `Z700_ROS2_NODES["real"]` 是 **list[(节点名, 说明)]** 不是 dict → `AttributeError: 'list' object has no attribute 'get'`
  → **PyQt 槽函数里未捕获异常 = qFatal → 整个进程中止**。
- 为什么以前不炸: 发现必失败(账号错)根本走不到这行; 账号修好后立刻撞上潜伏 bug ——
  **修好一层会暴露下一层, 要有心理准备连续收口**。
- 修 3 处: ① 列表/字典兼容转 dict + `topic_details` 优先; ② `device_tree.topLevelItem(i)` 判 None;
  ③ **渲染总闸**: 把槽函数拆成 `_on_discovery_result` (try/except → 只记日志) + `_render_discovery_result` (真身)。
- 通用铁律: **页面按钮类功能一律加"总闸"** — 槽里异常不会弹窗, 只会静默杀进程, 用户看到的就是"崩了"。

## 3. 点🔴不变红 = 只走 relay→Mac 一条链路
- 旧 `_tower_cmd`: ECS relay `/command` → Mac 守护 → ssh Orin → `ros2 topic pub`。Mac 守护不在线时指令石沉大海,
  而界面照样写"🟡 指令已下发" = **静默失效** (用户观感"以前能用现在不好使")。
- 改「**直连优先 + 回读验证** + relay 兜底」:
  `ros2 topic pub --once /tower_light/command std_msgs/msg/String "{data: <color>}"`
  → `ros2 topic echo /tower_light/status --once` 读回 `state`, 打进 GUI 日志 (点到变色可证)。
  实测: 点 red → `state=red`; 点 green → `state=green` (口 `/dev/serial/by-id/usb-Artery_LED_*`, 115200, dry_run=False)。
- 塔灯状态词: `red/green/yellow/off` + 语义态 `idle/running/complete/error/busy`。
- 教训: **凡是"命令通道"都要有回读**, 否则"已下发"三个字会掩盖整条链路死掉。

## 4. 「按钮反应很慢」= 命令在主线程做 ssh (有实测数字, 别猜)
计时(offscreen + 真跑, gui-venv311):
```
_refresh()  单次 0.1 ms (20 次合计 3 ms)     ← 100ms 定时刷表是无辜的, 不要优化它
_tower_cmd("green")   阻塞主线程 5.48 s      ← ssh + ros2 pub + echo 回读
_gripper_cmd(0.0)     阻塞主线程 0.39 s      ← ssh(失败快)
```
- 结论: 慢 = 点击后在**主线程**等 ssh/HTTP 往返; GUI 事件循环被冻住 → 观感"反应很慢"。
- 修法(下次做): 阻塞段丢子线程 + 既有 `_oneshot(self, 0, lambda: apply(res))` 桥回主线程
  (studio.py 已有范式 `_cam_apply_later(fn, apply)`; 建议统一成 `_hw_async(work, label)` 包装)。
  涉及: `_tower_cmd / _gripper_cmd / _check_camera / _read_sensor / _read_tactile / _read_robot_joints / _robot_stop`。
- ⚠️ 这些老命令还带 `ROS_DOMAIN_ID=23` + `~/0615/...setup.bash` 的失配(机器人在 domain 0, 现行 install 在 `~/0810/`) — 顺手一起改。

## 5. 判断"相机坏没坏"要分三层量 (本轮示例)
1) 设备层: `lsusb | grep -iE "intel|realsense"` + `ls /dev/video*` + `ls /dev/v4l/by-id/` → D405 插上就是 6 个 video 节点
2) SDK 层: `python3 -c "import pyrealsense2"` (Orin 有 2.58.2) + 真抓一帧
3) ROS 层: `ros2 topic info -v /realsense/color/image_raw` 的 **Publisher count**
   (本轮 = 0, 但有 2 个订阅者在等 → 设备层 OK、驱动层缺: Orin 未装 `realsense2_camera`, 且 launch 配置里
   realsense 话题被注释掉)。**层与层不能互相代替下结论。**

## 6. 控制台重启 / 长驻 (本轮定型)
GUI 改码必须重启; 用 systemd 用户单元长驻, 关终端/退出会话不死:
```bash
systemd-run --user --unit=zmax-studio --collect \
  --setenv=DISPLAY=:0 --setenv=XAUTHORITY=/run/user/1000/gdm/Xauthority --setenv=XDG_RUNTIME_DIR=/run/user/1000 \
  <repo>/gui-venv311/bin/python <repo>/tools/gui/studio.py
systemctl --user status zmax-studio          # Main PID + 启动时间 = 汇报证据
DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority xdotool search --name "Z-MAX"   # 窗口真映射了
```
DISPLAY/XAUTHORITY 的正确值从桌面进程取: `tr '\0' '\n' < /proc/$(pgrep -f gnome-terminal-server|head -1)/environ | grep -E 'DISPLAY|XAUTHORITY'`
(`--collect` 的 transient 单元退出后自动消失, 所以崩了会 `Unit could not be found`)。

## 7. ⚠️ pkill 自杀(本轮又踩 2 次, 新增场景)
除已知的 `pkill -f "studio.py"` 会匹配自身命令行外, **启动命令里含明文进程名也会让同一条命令里的 pkill 自杀**:
`pkill -f "[s]tudio\.py"; ... systemd-run ... studio.py` ← 后半段把明文写进了同一命令行 → pkill 匹配到自己的 shell
→ `exit -15`, 后续命令全不执行(看起来像"什么都没干")。
**铁律: kill 与 start 永远分两条 terminal 调用**; 且命令行里绝不出现明文目标进程名。

## 8. 收尾留档坑: `git add <dir>/` 会一口气吞掉上千文件
`git status --short` 对未跟踪目录是**折叠**显示(63 条) → `git add reports/` 展开成 **1862 files / 29MB** 一次提交。
先补 `.gitignore` 规则再 add:
```
reports/**/*.mp4
reports/**/*.avi
reports/**/*.zip
reports/**/*.tar.gz
```
提交后 `git show --shortstat HEAD` 复核体量; 大文件(证据视频)只写进清单
`reports/EVIDENCE_MANIFEST_<date>.md`(路径+体积), 不入库 (遵循"大文件不进代码库"纪律)。
