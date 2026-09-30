# 硬件工具箱真机链路修通 (2026-09-16, v5.6.14)

老倪三连反馈: 「点红色应该变红」→「发现硬件怎么崩了」→「按钮为什么感觉反映很慢」。
三个症状三个不同根因, 全部实测定位。**这条链的上游前提**: 本机已直连 Orin 局域网
(见技能 `orin-lan-direct-access`), 旧「本地到不了 192.168.23.x, 必绕 ECS/Mac」作废。

## 一、表层配置先错 (不修它后面两个 bug 都暴露不出来)

| 位置 | 旧值(错) | 现值 | 后果 |
|---|---|---|---|
| `hardware_simulator.py::HardwareDiscoveryThread.ORIN_USER` | `nvidia` (nvidia@.10 时代) | `tashan` | ssh Permission denied → 弹「无法连接 192.168.23.66」 |
| 同文件三条 ros2 命令 | 无 domain | `export ROS_DOMAIN_ID=0` | 机器人在 **domain 0**; 用 23 查只看到 /rosout, 误判"ROS2 未运行/驱动没起" |
| studio.py 多处 ssh 命令 | `ROS_DOMAIN_ID=23` + `~/0615/*/install` | domain 0 + `~/0810/*/install` | 读到空数据 or 服务类型找不到 |
| 本机 SSH | 无任何密钥 (`~/.ssh` 只有 known_hosts) | ed25519 + 公钥进 Orin `tashan` authorized_keys | GUI 全部 ssh 路径都靠**免密**, 没密钥一律连不上 |
| TCP bridge 探测 | `pgrep orin_forwarder` | `pgrep 'orin_gateway\|orin_forwarder'` | 现役网关是 `orin_gateway.py`, 旧名匹配不到 |

**铁律: 配置层(账号/域/端口/免密)修好后必须重走完整链路** — 修完账号第一次真跑通"发现硬件",
立刻撞上潜伏的 `list.get()` 崩溃 (下面第二节)。别假定配置修好后面就没坑。

## 二、点一下整个控制台消失 = Qt 槽未捕获异常 → qFatal

真 traceback (offscreen 直接调 handler 拿到的, 不是猜的):
```
File "studio.py", line 7372, in _on_discovery_result
    [(n, Z700_ROS2_NODES.get("real", {}).get(n, "")) for n in nodes]
AttributeError: 'list' object has no attribute 'get'
```
`Z700_ROS2_NODES["real"]` 是 `[(名, 说明)]` **list** (同文件 108 行定义), 代码却当 dict 调 `.get()`。
PyQt5 里槽函数抛未捕获异常 → `qFatal` → **整个进程中止**: 用户看到的是"崩了", 没有任何报错弹窗,
journal 里也**没有** Python traceback (只有 `Consumed ... CPU time` 一行)。

**判据**: 进程凭空消失 + 日志无 traceback ⇒ 怀疑 C 级 abort / qFatal, 不要去翻业务逻辑。
**取证法**: offscreen 里构造**真类**(`studio.StudioMainWindow` → `findChildren(studio.HardwareModule)`)
+ **真数据**(现场跑 `HardwareDiscoveryThread` 拿 result), 然后直接 `hw._on_discovery_result(res)` ——
直接调用时异常抛给自己而不是进 qFatal, traceback 就到手了。

**根治套路 (每个页面槽都该有)**:
1. 槽体拆两层: 总闸 `_on_X(self, ...)` = `try: self._render_X(...) except Exception: 只记日志`;
   `_render_X` 才是原逻辑。渲染异常永不冒泡。
2. 表格/树索引前判 None: `it = self.device_tree.topLevelItem(i)` 可能为 None → `if it is not None`。
3. 模块级常量表 (Z700_ROS2_NODES 这类) 列表/字典都兼容, 别假设 `.get()`:
   ```python
   _known = Z700_ROS2_NODES.get("real", [])
   _known_map = dict(_known) if isinstance(_known, dict) else {str(k): v for k, v in _known}
   ```

## 三、按钮"反应很慢" = 命令在主线程跑 ssh (实测数字)

| 调用 | 阻塞主线程 |
|---|---|
| `_tower_cmd("green")` (ssh + ros2 pub + 回读 status) | **5.48 s** |
| `_gripper_cmd(0.0)` | 0.39 s |
| `_refresh()` (100ms 定时, 5 张表重建) | 0.1 ms — **无辜** |

量法: `t0=time.perf_counter(); fn(); time.perf_counter()-t0` 逐按钮量, 先测量再改 (别怀疑定时器)。

**修法 (本仓库既有设施, 别自造)**: 阻塞体丢子线程, 结果经 `_oneshot(self, 0, lambda: apply(res))`
回主线程 (纯 Python 队列 + 主线程 20Hz 轮询消费, 见 `_OneshotPoller`); 模板 = 同文件 `_cam_apply_later`。
子线程**零 Qt 接触** (本仓库 2026-08-19 的 segfault 根因就是 worker 线程碰 Qt)。
改完复量: 点击应在 <50 ms 返回, 日志/表格更新由信号回填。

## 四、塔灯「点红色不变红」= 单通道中间件 + 静默失败

旧 `_tower_cmd` 只走 `ECS relay /command → Mac 守护 → ssh Orin → ros2 topic pub`; Mac 守护不在线时
指令石沉大海, 界面还照写「🟡 指令已下发」。直连可用后应改**直连优先 + 回读验证 + 中间件兜底**:

```bash
ssh tashan@192.168.23.66 'export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash && \
  ros2 topic pub --once /tower_light/command std_msgs/msg/String "{data: red}" && \
  timeout 5 ros2 topic echo /tower_light/status --once | head -1'
# 回读: {"state": "red", "desired_state": "red", "port": "/dev/serial/by-id/usb-Artery_LED_..."}
```
话题是 `std_msgs/msg/String`, 值可 `red/green/yellow/off` (也认 idle/running/complete/error/waiting/busy);
`dry_run=False`、波特率 115200。**发完必须回读 status 当证据** (老倪要"点到变色"可证)。

## 五、控制台重启纪律 (2026-09-16 起挂 systemd 用户单元)

```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
systemd-run --user --unit=zmax-studio --collect \
  --setenv=DISPLAY=:0 --setenv=XAUTHORITY=/run/user/1000/gdm/Xauthority --setenv=XDG_RUNTIME_DIR=/run/user/1000 \
  /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python /home/ubuntu/lerobot-smolvla-lew/tools/gui/studio.py
```
- 好处: 终端关掉它也不死 (`systemctl --user status/stop zmax-studio`)。
- DISPLAY/XAUTHORITY 真值从桌面进程取: `tr '\0' '\n' < /proc/$(pgrep -f gnome-terminal-server|head -1)/environ | grep -E 'DISPLAY|XAUTHORITY'`
  (本机 = `:0` / `/run/user/1000/gdm/Xauthority`)。
- 汇报证据三连: 新 Main PID + 启动时间(`systemctl --user status` 里的 since) + 窗口已映射
  (`DISPLAY=:0 XAUTHORITY=... xdotool search --name "Z-MAX"`)。改码必须重启, 否则用户看到旧行为。
- ⚠️ **pkill 自杀新形态**: 把 `pkill -f "[s]tudio\.py"` 和紧随其后的**启动命令**写进同一条命令行 →
  整条 cmdline 含明文 `studio.py` → pkill 匹配到自己, shell 被 SIGTERM, 后面的启动/提交全不执行
  (老形态是 pkill 撞上自己的 grep; 这条是"同一条命令行里有启动路径")。
  **kill 与 start 必须分两次调用。**

## 六、关机前收尾 (老倪口径: 保存数据 / 记忆 / 技能 / 小版本 / 推送)

1. **Git 折叠坑**: `git status --short` 把未跟踪**目录**折叠成一行 (`?? reports/evidence_ab10_f0_r1/`),
   直接 `git add reports/` 会一次吞进 **1862 个文件**。正解: 先补 `.gitignore`
   (`reports/**/*.mp4|avi|zip|tar.gz`) + 生成 `reports/EVIDENCE_MANIFEST_<date>.md` (大文件只记
   路径/体积, 不入库), 再选择性 add。
2. 小版本五处同步 + tag + push 见 `references/version-bump-checklist.md`; 直连 GitHub 可用时
   `git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push origin main` 即可 (无需 ghproxy)。
3. 停服务顺序: `systemctl --user stop zmax-studio` → `pkill -f "[a]uto_loop\.py"` (重启后 @reboot cron 拉起)
   → 复核无 lerobot_train/gui-venv311/lerobot-venv 进程 + `sync` 刷盘。
