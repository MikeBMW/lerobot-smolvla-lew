# 启动指南 (Launch) — 本机实测正确姿势

## 新家 (2026-08-15 容器环境, Docker Desktop, 不用 WSL)

```bash
# 一次性准备 (已做):
#   ~/.hermes/bin/uv venv /root/gui-venv --python /usr/bin/python3
#   ~/.hermes/bin/uv pip install --python /root/gui-venv/bin/python PyQt5 numpy grpcio protobuf
#   apt-get install -y libxcb-xinerama0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-randr0 \
#     libxcb-render-util0 libxcb-shape0 libxcb-xkb1 libxkbcommon-x11-0 libxkbcommon0 libgl1 libegl1 \
#     libxcb-cursor0 libxcomposite1 libxdamage1 libxfixes3 libxrender1 libxtst6 libxi6

# 启动 (Windows 侧先开 VcXsrv):
#   Win+R: "C:\Program Files\VcXsrv\vcxsrv.exe" :0 -ac -multiwindow -clipboard
# ⚠️⚠️ 必须用 gui-venv311 (Python 3.11)! 不要用 /root/gui-venv (3.12+sip6.16 不稳:
#   点「运行」仿真完成 → worker 线程 → QObject::killTimer/Timers cannot be stopped
#   from another thread → activateTimers NULL receiver SIGSEGV 崩溃, 2026-08-18 实测)
cd /root/lerobot-smolvla-lew/tools/gui
DISPLAY=host.docker.internal:0 exec nice -n 10 /root/gui-venv311/bin/python studio.py
```

> ⚠️ 新家容器纯 Docker Desktop (192.168.65.x), 无 /mnt/wslg, 无 WSL interop, 无 docker.sock。
> 显示唯一通道 = Windows 宿主 VcXsrv (必须 -ac 允许远程), 容器 DISPLAY=host.docker.internal:0。
> 防火墙弹窗要允许 TCP 6000 入站。探测: `timeout 2 bash -c 'echo > /dev/tcp/host.docker.internal/6000' && echo UP`。
> 用户已明确: 以后不用 WSL (旧家 WSLg/vcxsrv_watch.sh 那套作废)。

## 旧家 (WSL, 已弃用)

```bash
cd /home/xspace/lerobot-smolvla-lew/tools/gui
exec nice -n 10 python3 studio.py   # 系统 python3 = /usr/bin/python3 (3.14, 唯一带 PyQt5 的解释器)
```

## 启动坑 (全部实测, 2026-08)

- ❌ 仓库根 .venv **没有 PyQt5** → `ModuleNotFoundError: No module named 'PyQt5'`。
  venv 在仓库根 `lerobot-smolvla-lew/.venv`, **不在** tools/gui; 在 tools/gui 下用相对
  `.venv/bin/python` 会报 "No such file or directory" (os error 2)。
- ❌ run_studio.sh 优先 conda lerobot (`~/miniconda3/envs/lerobot/bin/python`) —
  本机**无 conda** (`~/miniconda3` 不存在), 该分支自动跳过; 脚本最终回落到系统 python3。
- ✅ 校验命令: `python3 -c "import PyQt5"` 通过 = 正确解释器。

## 启动方式 (Hermes terminal 规则)

- 必须 terminal(background=true) 启动 — nohup/disown/setsid 或尾部 `&` 会被 Hermes 拦截报错。
- watch_patterns 盯 `Traceback` / `Error`; 启动后用 process(action='poll'/'wait') 确认存活。
- 日志刷 "Unknown property cursor" 是 QSS **无害警告**, 不是崩溃; 进程 running + 无 Traceback = 窗口已拉起。
- DISPLAY=:0 已是 WSLg 值, 无需 vcxsrv; WSLg 下窗口直接可见。
- nice -n 10 符合 exit134 纪律。

## 黑屏 ≠ 渲染失败 — 先查窗口坐标 (2026-08-14 实测)

用户报"控制台黑屏"时, **先别怀疑网络/渲染**, 第一步用 xdotool 查窗口坐标:

```bash
DISPLAY=:0 xdotool search --onlyvisible --class ".*" | while read w; do \
  echo "win=$w: $(DISPLAY=:0 xdotool getwindowname $w 2>/dev/null)"; done   # 窗口名
DISPLAY=:0 xdotool getwindowgeometry <win_id>   # 看 Position
```

> ⚠️ 判据升级 (2026-08-14 晚再实测): **X 层位置正常 ≠ 不黑屏**。本次坏态窗口位置
> 正常 (38,59), 但 stderr.log 报 marshaled + `XWAYLAND: Error sending request:
> Resource temporarily unavailable` (新错误变体), 用户桌面依旧空白。
> **stderr.log 的 marshaled 错误才是合成链路断的实锤判据**, 窗口坐标只是辅助:
> - 位置 -32692 = 坏态 (历史特征)
> - 位置正常 + stderr.log 有 marshaled / "Resource temporarily unavailable" = 同样坏态
> 判定顺序: 先 `tail /mnt/wslg/stderr.log | grep -i "marshaled\|temporarily"`,
> 再 xwininfo 看位置, 别只看位置就下结论。
> 坑: 坏态下 `xdotool search --onlyvisible` 可能挂起 60s+ 超时 → 用
> `timeout 15 xwininfo -root -tree 2>/dev/null | grep -i "XSpace\|studio"` 替代。

### 🐛 真正根因 (2026-08-14 实锤, 已根治)

**Weston 合成器无视 Qt 的初始位置请求**: 窗口的 WM_NORMAL_HINTS 里 Qt 请求 60,40,
但 Weston 把所有顶层窗口放到溢出坐标 **-32692,-32650** (接近 16 位坐标下限 -32768,
疑似内部溢出) → 窗口真实存在且"可见", 但位置不可见 → 看起来就是黑屏。
Qt 内部 pos() 与 X 层真实位置**不一致** (Qt 报 60,40 / 0,0, xdotool 报 -32692),
所以只看 Qt 日志会被误导。

**所有外部手段都无效** (全部实测):
- ❌ xdotool windowmove / wmctrl -r ... -e — 拉不回来 (WM 层被 Weston 接管, 请求被拒/覆盖)
- ❌ show() 前 setGeometry — 被 Weston 覆盖
- ❌ show() 后 QTimer.singleShot(500ms) setGeometry — 无效
- ❌ Qt.X11BypassWindowManagerHint (override-redirect) — **X 层位置正确 (60,40) 但用户
  依然看不到**: Xwayland 坏态下 bypass 窗口无 Wayland surface, 不合成到桌面。证伪。
- ❌ showMaximized() — _NET_WM_STATE 显示 MAXIMIZED 但位置/大小纹丝不动 (200x100),
  协议请求被 Xwayland 无视。
- ⚠️ AA_UseSoftwareOpenGL + AA_UseHighDpiPixmaps=False 组合 — 曾怀疑是根因, **已证伪**
  (去掉 dpi 仍飞屏); PyQt5 里 AA_DisableWindowManagerEffects **不存在**, 静默抛异常被吞。

### ✅ 真正根因 & 唯一解: 重启 WSLg

**根因**: WSLg 的 Xwayland 实例启动时就坏 (stderr.log 见 `XWAYLAND: request could not be
marshaled: can't send file descriptor` + `glamor: GBM Wayland interfaces not available,
falling back to sw`)。坏态下 Xwayland 与 Weston 的合成链路断: 窗口在 X 层一切正常
(存在/位置/内容都能截图), 但**从不合成到 Windows 桌面** → 用户看到"完全空白"。
任何客户端手段都救不回来, **唯一根治 = 重启 WSLg**:

```
# Windows 侧执行 (或 WSL 里执行会自杀断会话, 需用户知情):
wsl --shutdown
# 重新打开终端 → WSLg 全新启动 → 普通 Qt 窗口即恢复正常 (用户历史验证过)
```

诊断命令 (按序):
```bash
tail -30 /mnt/wslg/stderr.log            # 看 XWAYLAND marshaled 错误 (启动时故障)
DISPLAY=:0 xdotool getwindowgeometry <win>  # X 层位置 (坏态下 -32692,-32650)
ls -la /tmp/.X11-unix/                   # X0 socket 在 = WSLg 活着
```
坏态特征: 窗口 xwd -id 截图内容正常 (31852 色, 非黑屏) + xdotool 位置 -32692 +
用户桌面完全空白 = 合成链路断, 直接重启 WSLg, 别在客户端代码上浪费时间。

⚠️ **2026-08-14 傍晚实测: 重启 WSLg 并非 100% 有效!** 用户执行 wsl --shutdown 后
WSL 全新启动 (uptime 3min + /mnt/wslg/stderr.log 时间戳更新可证), 但 Xwayland
启动即报同样的 marshaled 错误, 窗口仍落 -32692,-32650, 用户桌面依旧空白。
`wsl.exe --update` 确认已是最新版 (WSL 2.7.11 / WSLg 1.0.73.2, 输出 UTF-16LE
需 decode 才能读) 也无济于事。重启无效时的下一步:
① 彻底重启 — 关掉所有 WSL 终端窗口后 PowerShell 执行 `wsl --shutdown`, 等 15s 再开;
② **vcxsrv 替代 (2026-08-14 晚实测有效, 最快路径)**: 启动 vcxsrv
(`powershell.exe -NoProfile -Command "Start-Process 'C:\Program Files\VcXsrv\vcxsrv.exe' -ArgumentList ':0','-ac','-multiwindow','-clipboard'"`,
守护 cron `vcxsrv_watch.sh` 每 2min 自动拉起), 然后 `export DISPLAY=172.18.80.1:0`
再启动 studio (必须显式 IP:0 强制走 TCP 到 vcxsrv, 不能 `:0` — 那会走 WSLg 的
坏 Unix socket)。验证: xdotool 位置回到 60,40 即成功 (坏态是 -32692,-32650);
vcxsrv 存活检查 (比 xdotool 快且不卡):
`timeout 5 bash -c 'echo > /dev/tcp/172.18.80.1/6000' 2>/dev/null && echo UP || echo DOWN`;
守护脚本实际在 `~/scripts/vcxsrv_watch.sh` (不在 ~/.hermes/scripts/);
③ Windows 事件日志查 WSLg/RDP 会话 (RDP 连接下 WSLg 合成有已知问题)。

- 🐛 黑屏排查别被误导: 进程连 ECS (39.102.211.79:443) 是正常的 relay/状态轮询 (且多在子线程),
  不是黑屏原因; 主线程阻塞只在窗口**根本没出现** (xdotool 搜不到) 时才查。

## 调试纪律 (老倪 2026-08-14)

- 排查坏窗口时, **先把当前实例关掉** (process kill) 再动代码/重启 — 别留着一个飞屏外的
  窗口同时开新实例, 用户明确要求先关。
