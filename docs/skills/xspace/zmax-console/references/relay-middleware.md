# relay_middleware.py — 控制台中间件消息通道 (2026-08-09 老倪: 封装统一消息通道)

## 为什么存在
本地 WSL (172.18.x) 与 Orin (192.168.23.x) **不同网段, ssh 直连永远不通** — 一切远程硬件操作 (塔灯/部署/摄像头/Orin状态) 统一经 ECS relay 中转。老倪明确要求封装中间件, 不散落直连调用。

## 通道模型
```
[控制台] --POST /api/relay/command--> [ECS relay] --GET /command 轮询--> [Mac 守护]
    ^                                                            | ssh tashan@.66
    └------ WS wss://datadrive.world/ws (实时推送 orin_status) <-- [Orin 执行]
```
- HTTP: `RelayMiddleware` — send/peek/status/orin_status/snapshot_bytes/health (统一超时+RelayError)
- WS: `WSClient` — 订阅 `wss://datadrive.world/ws` 实时推送 (orin_status/data_arrived), **断线 5s 自动重连**, 后台线程
- 单例: `get_middleware()`
- 端点: `RELAY_BASE=https://datadrive.world/api/relay` (nginx→39053); 旧 `106.75.239.80:50053` 已废 (Mac 守护曾轮询旧地址收不到指令 — 统一地址是塔灯链路修复一环)

## ⚠️ WS 回调跨线程铁律
WSClient 回调在后台线程 → **不能直接改 UI** — 用 `QTimer.singleShot(0, lambda: self._apply_ws_status(evt))` 抛回主线程 (同子线程日志队列铁律)。
```python
def _on_ws_status(self, evt):
    from PyQt5.QtCore import QTimer as _QTM
    _QTM.singleShot(0, lambda: self._apply_ws_status(evt))
```
HardwareModule `__init__` 里 `self._ws = WSClient(on_status=self._on_ws_status)` (try/except 包裹, 中间件不可用不影响页面)。

## 塔灯控制最终链路 (VEH.3.16 红灯修复定稿)
- 老倪: "我点绿灯了还是不好使" → 完整根因链:
  1. 本地 ssh 直连 Orin 不同网段必然失败 (WSL 172.18.x ≠ 192.168.23.x)
  2. relay /command 下发 `tower_light green` 落盘 ✅ 但 **Mac 守护只认 `cmd=="collect"`**, 其他指令忽略 → 塔灯不动
  3. Mac 守护轮询旧地址 `http://106.75.239.80:50053` (已废) → 收不到新指令
- 修复 (三端):
  - **本地** `_tower_cmd`: `mw.send(f"tower_light {color}")` 走中间件 (不再本地 ssh, 不再裸 requests)
  - **Mac 守护** `tools/zmax_auto_collector.py`: `BACKEND = "https://datadrive.world/api/relay"` + 新增 `elif cmd.startswith("tower_light"): run_ssh("...ros2 topic pub --once /tower_light/command std_msgs/msg/String '{data: green}'")` + `deploy_model` 分支 (拉 act_latest.safetensors)
  - **推送到 mac 分支**: 用 `git worktree add /tmp/mac_wt origin/mac` → 改 → commit → `git push origin HEAD:mac` (工作区有大量未提交产物时, checkout -B 会失败, worktree 最干净)
- 小芳确认的 Orin 塔灯: topic `/tower_light/command` (std_msgs/String), 颜色 green/red/yellow/off, 串口 `/dev/serial/by-id/usb-Artery_LED_13EE1C342566-if00`, Orin 地址 **tashan@192.168.23.66** (不是旧 nvidia@.10)

## ⚠️ ECS 快照端点性能 (24万文件卡死)
- `os.listdir(archive)` + sorted 全量排序 24万 jpg → 每请求卡死 (本机 curl 无响应)
- 修复: `max(glob.glob(os.path.join(dir, "snap_*.jpg")), key=lambda f: os.path.basename(f))` — 文件名带时间戳, max 字符串即可取最新, 0.4s 返回
- 验证: 本机 `curl 127.0.0.1:39053/api/snapshot/latest` 应 <1s 返回 JPEG; 公网 `https://datadrive.world/api/snapshot/latest` HTTP 200 + `image/jpeg`

## ⚠️ 部署上传要分块+百分比 (老倪: "我要详细反馈", 静默卡 2 分钟被骂)
- scp 87MB 静默执行 ~2min 无反馈 = "没反应" → 老倪要详细反馈
- 分块上传: 8MB 块 `ssh 'cat >> models/xxx.safetensors'` (先 `rm -f` 防 cat>> 追加残留) + 每 5% 打日志 `{pct}% ({sent}KB/{size}KB) · {spd}KB/s`
- 上传后 **chmod 644 铁律** (scp 保留 600 → nginx 403); 版本化 `act_<ts>.safetensors` + `act_latest.safetensors` 双写
- ECS models 目录: `/www/wwwroot/datadrive.world/models/` (nginx 静态, URL `https://datadrive.world/models/act_latest.safetensors`), 不是 /root/zmax-relay/models

## ⚠️ 本地直连永远不通的地址不要反复尝试
WSL 与 Orin 不同网段 → `ssh tashan@192.168.23.66` / `nvidia@192.168.23.10` 本地都 No route to host。判断"本地直连 vs 中间件": 先 `ping` 目标, 不通就直接走 relay, 别在 GUI 里留直连分支假装可用。
