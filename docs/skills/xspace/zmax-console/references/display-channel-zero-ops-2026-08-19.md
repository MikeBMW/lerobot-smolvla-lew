# 显示通道决策 — 零操作优先 (2026-08-19 实测)

## 用户偏好 (老倪原话: "别让我操作")
用户**拒绝做 Windows 侧任何配置** (netsh portproxy / VNC Viewer / 防火墙)。
给显示通道方案时, 优先选容器→Windows 方向的零操作通道。

## 两条通道对比
| 通道 | 方向 | 用户侧操作 | 稳定性 |
| :--- | :--- | :--- | :--- |
| VcXsrv (DISPLAY=host.docker.internal:0) | 容器→Windows (TCP 6000) | **零操作**, 窗口直接显示 | VcXsrv 不稳 (offscreen 压测 10min 零崩, 崩在 X11 层; 今天 320s 崩过) |
| Xvfb :99 + x11vnc :5900 | Windows→容器 (VNC) | 需 PowerShell portproxy + VNC Viewer 连 localhost:5900 | 稳 (根治) |

## 决策规则
1. **默认 VcXsrv 零操作通道** — 用户没明确要求 VNC/稳定时
2. Xvfb+x11vnc 只在用户愿意配置 Windows 侧时切换 (先确认再切, 别自作主张切走用户可见的窗口)
3. 切通道前先探测: `timeout 2 bash -c 'echo > /dev/tcp/host.docker.internal/6000' && echo UP`
4. VcXsrv 崩了 (watch_patterns 抓 "Segmentation fault") → 自动 kill + 重启同通道, 窗口自动回来

## 环境事实
- 容器无 wsl.exe/powershell.exe interop, 无 /mnt/c → 无法替用户执行 Windows 侧命令 (2026-08-19 复核)
- 容器 IP: 172.17.0.2 (Docker Desktop bridge)
- 崩溃根因背景: QObject::killTimer 跨线程 (代码路径 08-18/19 已修: _oneshot 桥/挂 parent),
  残余崩溃指向 VcXsrv 环境不稳 (见 segfault-timers-2026-08-19.md / qt-cross-thread-timer-segfault-2026-08-19.md)
