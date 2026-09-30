# 按钮「反应很慢」= 主线程在跑 IO; 命令类按钮必须回读证据 (2026-09-16 实测)

同一控制台, 同一天的两个用户反馈: 「点红色应该变红」/「按钮为什么感觉反应很慢」。
崩因(qFatal/槽异常)见 `references/slot-exception-qfatal-2026-09-16.md`, 本篇是不崩但"卡"和"假成功"那一半。

## 1. 「反应很慢」先量, 别猜

用户原话: 「硬件工具箱的按钮，为什么感觉反映很慢?」—— 实测是**槽函数里同步跑 ssh/HTTP** 堵住事件循环,
不是渲染/定时器的锅。量法 (offscreen, 逐按钮):

```python
t0 = time.perf_counter(); hw._tower_cmd("green"); print(time.perf_counter() - t0)
```

| 调用 | 阻塞主线程 |
|---|---|
| `_tower_cmd("green")` (ssh + ros2 pub + 回读 status) | **5.48 s** |
| `_gripper_cmd(0.0)` (ssh service call) | 0.39 s |
| `_refresh()` (100ms 定时刷新 5 张表, QTableWidgetItem 全量重建) | 0.10 ms — **无辜, 别去改它** |

**规程**: ①逐按钮量, 定时器/重绘最容易被冤枉(本项目那 100ms 刷新只 0.1ms);
②阻塞体丢子线程, 结果经本仓库既有的 `_oneshot(self, 0, lambda: apply(res))`
(纯 Python 队列 + 主线程 20Hz 轮询消费, 见 `_OneshotPoller`) 回主线程 —— 模板就是同文件的 `_cam_apply_later`;
③**子线程零 Qt 接触** (曾因 worker 线程 emit/QTimer 触发 killTimer 跨线程 → SIGSEGV);
④改完复量: 点击应在 <50 ms 返回, 日志/表格由信号回填。
遗留: 塔灯/夹爪/拍照/读传感器在 v5.6.14 仍是同步版。

## 2. 命令类按钮: "已下发"不算证据, 要回读目标端真实状态

塔灯「点红色不变红」根因 = 旧 `_tower_cmd` **只有一条通道** relay→Mac 守护→ssh Orin→ros2 topic pub;
Mac 守护不在线时指令石沉大海, 界面却照样写「🟡 指令已下发」= 假成功。改成
**直连优先 + 发完回读 status 当证据 + 中间件兜底**:

```bash
ssh tashan@192.168.23.66 'export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash && \
  ros2 topic pub --once /tower_light/command std_msgs/msg/String "{data: red}" && \
  timeout 5 ros2 topic echo /tower_light/status --once | head -1'
# → {"state": "red", "desired_state": "red", "port": "/dev/serial/by-id/usb-Artery_LED_..."}
```
规律: **任何"下发指令"类按钮, 日志里必须出现目标端的真实回读值** (用户要看"点到变色"有据可查);
"已下发/成功"三个字不算证据。同理"设备层 vs 驱动层"别混为一谈: RealSense D405 插上后
`lsusb` + `/dev/video0-5` 都在(设备层 OK), 但没装 `realsense2_camera` 时 `/realsense/*` 话题 Publisher 仍是 0
(驱动层缺) —— 判据要分别看。

## 3. 改码后重启控制台: systemd 用户单元 (关终端不死) + pkill 新形态

```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
systemd-run --user --unit=zmax-studio --collect \
  --setenv=DISPLAY=:0 --setenv=XAUTHORITY=/run/user/1000/gdm/Xauthority --setenv=XDG_RUNTIME_DIR=/run/user/1000 \
  /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python /home/ubuntu/lerobot-smolvla-lew/tools/gui/studio.py
```
- DISPLAY/XAUTHORITY 真值从桌面进程取:
  `tr '\0' '\n' < /proc/$(pgrep -f gnome-terminal-server|head -1)/environ | grep -E 'DISPLAY|XAUTHORITY'`
- 汇报证据三连 (用户会质疑"你没重启"): 新 Main PID + 启动时间 + 窗口已映射
  (`DISPLAY=:0 XAUTHORITY=… xdotool search --name "Z-MAX"`)。
- ⚠️ **pkill 自杀新形态**: 把 `pkill -f "[s]tudio\.py"` 和**紧随其后的启动命令**写进同一条命令行 →
  整条 cmdline 含明文 `studio.py` → pkill 匹配到自己, shell 收 SIGTERM(exit -15), 后面的启动/提交全不执行。
  (旧形态是 pkill 撞上自己的 grep; 这条是"同一条命令行里带着启动路径"。)
  **kill 与 start 必须分两次调用**; git commit/push 也要另起一条。
