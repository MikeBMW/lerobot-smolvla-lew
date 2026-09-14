# Mac/Orin 硬件控制链路 — ECS relay 中转 (2026-08-09 会话沉淀)

## ⚠️ 网段铁律: 本地 WSL 永远连不上 Orin (192.168.23.x)
- 本地 WSL 网络是 `172.18.80.x` (eth0), Orin/Mac 在 `192.168.23.x` 局域网 — **不同网段, ssh 直连 `No route to host` 是常态不是异常**
- 因此所有"控制 Orin 硬件"的按钮**不能走本地 ssh 直连**, 必须经: 本地 → ECS relay (`https://datadrive.world/api/relay/command`) → **Mac 守护轮询执行** → Mac ssh Orin
- 排查顺序: 点按钮没反应 → 先 `ping 192.168.23.10` 确认网段可达性; 不通就别修 ssh 参数, 直接改走 relay 链路
- 错误示范: 早期 `_tower_cmd` 用 `ssh nvidia@192.168.23.10` 直连, WSL 下必然失败且异常被 except 吞 → 按钮看似无反应

## Orin 地址变更 (小芳 2026-08-09 修复)
- ❌ 旧: `nvidia@192.168.23.10` (废弃配置)
- ✅ 新: `tashan@192.168.23.66` (当前 Orin, 密码已从代码删除)
- 小芳修复涉及 6 文件 22 处 (studio.py/hardware_simulator.py/zmax_auto_collector.py/tcp_bridge/*), 推在 mac 分支

## 塔灯控制 (VEH.3.16 红灯/绿灯) — 双通道定稿
```python
# ① 本地直连 (同网段才可达, WSL 下必然失败 → 自动走 ②)
# ② ECS relay 下发 → Mac 守护执行:
r2 = requests.post("https://datadrive.world/api/relay/command",
                   json={"cmd": f"tower_light {color}"}, timeout=15)
```
- 颜色值: `green / red / yellow / off`; 话题 `/tower_light/command` (std_msgs/String)
- Orin 上直接执行: `ros2 topic pub --once /tower_light/command std_msgs/msg/String "{data: green}"` (ROS_DOMAIN_ID=23)
- 状态话题: `/tower_light/status` 返回 `{"state": "green", ...}`; 塔灯 = Artery LED 串口 `/dev/serial/by-id/usb-Artery_LED_13EE1C342566-if00`, 由 tower_light_node 管理
- 日志形态: 先打"本地直连失败 (exit 255) — 走 ECS relay", 再打"📡 已下发 Mac 塔灯指令" — **失败原因要可见, 别被 except 吞**

## ⚠️ Mac 守护 (zmax_auto_collector.py) 三个坑
1. **只认 `cmd == "collect"`**: 原 while 循环 `if cmd == "collect": do_cycle(...)` — 其他指令被静默忽略。必须加 elif 分支:
   ```python
   elif cmd.startswith("tower_light"):
       color = cmd.split()[-1]
       run_ssh(f"source /opt/ros/humble/setup.bash && "
               f"ROS_DOMAIN_ID=23 ros2 topic pub --once /tower_light/command "
               f"std_msgs/msg/String '{{\"data\":\"{color}\"}}'", timeout=10)
   elif cmd.startswith("deploy_model"):
       # 拉取 act_latest.safetensors → /tmp/
   ```
2. **BACKEND 旧地址**: `http://106.75.239.80:50053` 已废 → `https://datadrive.world/api/relay`。**改后端地址时必须 grep 所有客户端读点** (Mac 守护 / 控制台 / web 页面)
3. **Mac 守护更新需要小芳操作**: 代码推 mac 分支后, Mac 上要 `git pull` + 重启守护才生效 — 本地验证 relay 指令落盘 ≠ Mac 已执行, 要跟小芳确认

## 摄像头连接功能 (参考 https://datadrive.world/cicd.html)
- 方案: 轮询快照端点 `https://datadrive.world/api/snapshot/latest?t=<ts>` → QLabel 显示 JPEG (cicd.html 用 100ms setInterval, GUI 用 1.5s QTimer 足够)
- 链路: nginx `/api/snapshot/` → relay 39053 → `/root/zmax-relay/archive/snap_*.jpg` (24 万张, 10s 间隔更新)
- **⚠️ ECS relay 快照端点卡死根因**: 原实现 `sorted(os.listdir(archive))` 对 24 万张全量排序 → 每请求卡死 (curl 挂住无响应)。改为 `max(glob.glob(...), key=os.path.basename)` 取文件名最大 (snap_<ts>_xxx.jpg 时间戳递增) → 0.4s 返回
- GUI 实现: `btn_cam_connect` (🔌 连接摄像头) + `cam_view` QLabel (fixedHeight 240) + `_cam_timer` (1500ms) + `_cam_poll`/`_show_cam_frame` (QPixmap.loadFromData + KeepAspectRatio)
- 连接按钮探测: GET snapshot → 200 + Content-Type image/* → 显示首帧 + 启动轮询; 失败显示 HTTP 码
- 验证: `curl -s https://datadrive.world/api/snapshot/latest?t=$(date +%s)` → JPEG 480x360

## 📡 中间件消息通道 relay_middleware.py (2026-08-09 封装定稿)
- 背景: 散落 5 处 `requests.post("https://datadrive.world/api/relay/command")` 直调 → 用户要求"封装一个中间件消息通道"。文件 `tools/gui/relay_middleware.py`:
  - `RelayMiddleware` (单例 `get_middleware()`): `send(cmd)` 下发 / `peek()` 读指令 / `status()` / `orin_status()` / `snapshot_bytes()` (快照 JPEG) / `health()` (全链路 ECS+Orin+快照) — 全部抛 `RelayError` (不静默)
  - `WSClient` (后台线程): 连 `wss://datadrive.world/ws` 实时推送, `on_status`/`on_event` 回调, **断线 5s 自动重连**, `connected`/`last_status` 属性
- **WebSocket 通道是现成的**: ECS 上 `ws_relay.py` 监听 :8765 (nginx `/ws` 反代到 :8765), 控制台订阅 `ws://datadrive.world/ws` 收 `orin_status`/`data_arrived` 事件 (Orin 推理服务 WS 长连接发心跳 → ECS 广播)。**实时状态走 WS, 指令下发走 HTTP /command — 双通道**。
- 用户选型时明确: 接通 ws/orin WebSocket 实时推送 (非纯 HTTP 轮询)。
- **⚠️ WS 回调线程安全 (铁律)**: WSClient 回调在后台线程, 不能直接改 UI — 用 `QTimer.singleShot(0, lambda: self._apply_ws_status(evt))` 抛回主线程 (子线程日志队列同款铁律)。HardwareModule `_on_ws_status` → `_apply_ws_status` 更新 status_label/hw_table。
- 本地依赖: 系统 python 有 `websocket-client 1.9.0` (无 `websockets` 库); relay 侧 ECS 有 `websockets 16.1.1`
- 验证: WSClient 连接 → 12s 内收到 orin_status 即通 (HTTP orin_status online=True 与 WS 推送 online 可能不一致 — WS 是 Orin 长连接实时真值)

## git worktree 推修复到 mac 分支 (cherry-pick 冲突时)
- 场景: main 与 mac 分支分叉大 (mac 缺 studio.py 大量改动), `git checkout mac` 被工作区未提交产物 (reports/*.mp4, config_*.yaml, rollout 帧) 阻碍, cherry-pick 必冲突
- **正解 (worktree, 不动当前工作区)**:
  ```bash
  git worktree add /tmp/mac_wt origin/mac      # 干净检出远程 mac
  cp tools/zmax_auto_collector.py /tmp/mac_wt/tools/  # 应用修复
  cd /tmp/mac_wt && git add ... && git commit -m "..."
  git push origin HEAD:mac                      # 推送到 mac 分支
  cd ~/repo && git worktree remove /tmp/mac_wt --force
  ```
- **绝不 `git add -A`/`git add .`** — 工作区被 rollout 产物污染 (reports/*.mp4, frames/*.png, config_*.yaml 几十个), 永远选择性 add 本版文件

## 端侧部署链路 (VEH.2.26/2.31, 模型推送到 Mac/Orin)
- 链路: 本地模型 → scp/分块上传 → ECS `/www/wwwroot/datadrive.world/models/` → `act_latest.safetensors` 覆盖即部署 → Mac 拉取
- **chmod 644 铁律**: scp 保留本地 600 权限 → nginx www 用户读不了 → 403。上传后必须 `chmod 644` (记忆里有, 本次又踩)
- **分块上传带百分比**: scp 87MB 静默 2 分钟 = "没反应" (用户强烈不满)。改 8MB 分块 `sshpass ssh 'cat >> file'`, 每 5% 打日志 (百分比+速率+大小); **cat >> 前先 `rm -f` 远程同名** (防残留重复追加)
- 详细反馈要求: ECS 连通性探测 (relay /status + SSH_OK) → 上传 → chmod → URL HEAD 验证 → Mac 指令 → Orin 状态 — 用户明确说"没有详细反馈啊, 到底部署成功没有"
- 上传两个名: 版本化 `act_<ts>.safetensors` + `act_latest.safetensors` (覆盖即部署)
- 验证: `curl -I https://datadrive.world/models/act_latest.safetensors` → 200; `sha256sum` 本地 vs 远程一致才是真部署 (HEAD 200 但文件不存在 = nginx 缓存/幻影, 小芳曾抓到)

## Model Zoo 队列推进 (VEH.2.18 插拔结果"训练中")
- ZOO_POLICIES 7 模型串行: act → smolvla → smolvla_lew → vla_touch → awe_zflow → expert_mlp → expert_policy
- 队列完成判定 = 远程 `docker ps -q --filter name=zmax_train` 容器退出即推进 — **不验证 checkpoint 是否真保存** → 8月8日 cuDNN 崩溃时代的失败训练 (awe/vla_touch 目录 checkpoints=0) 会被队列跳过
- VEH.2.18 "除了 ACT 都是训练中" = 正常串行逻辑, 但要注意远程 `outputs/train/` 里无目录的模型可能是**被跳过的失败轮次**, 需要补跑
- 排查: 远程 `ls outputs/train/*smolvla*` 无目录 = 从没训过/失败未重跑
