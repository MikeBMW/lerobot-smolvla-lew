# VcXsrv → Xvfb+VNC 显示通道迁移实录 (2026-08-19)

## 背景
当天 VcXsrv 崩 2 次 (Segfault):
- 第 1 次: 运行 320s, `QObject::killTimer: Timers cannot be stopped from another thread` + Segfault
  (代码路径 08-18/19 已修: _oneshot 桥/挂 parent/WS 线程零 Qt; 复查无漏网)
- 第 2 次: 几分钟, 无 killTimer 警告, 直接 `Fatal Python error: Segmentation fault`, 主线程在 Qt C++ 层
- offscreen 压测 (stress_offscreen.py 10min) 零崩溃 → **崩在 VcXsrv/X11 层, 不是代码**
- 老倪决策: 装 VNC Viewer 看 Xvfb 画面, 彻底告别 VcXsrv

## 显示通道最终形态 (默认)
```
Xvfb :99 -screen 0 1600x900x24 -nolisten tcp          # 容器内
DISPLAY=:99 x11vnc -display :99 -forever -shared -nopw -rfbport 5900
DISPLAY=:99 python studio.py                          # 控制台跑 Xvfb
```
Windows 侧: VNC Viewer 连 `172.17.0.2:5900` (容器 bridge IP; 直连不通则需
netsh portproxy 或 docker -p 5900:5900 发布 — 但容器无 docker.sock 无法自配)。
VcXsrv 只作临时显示 (崩了自动拉回 Xvfb)。

## 🐛 核心坑: TCP 端口探测 UP ≠ X 握手就绪
`timeout 2 bash -c 'echo > /dev/tcp/host.docker.internal/6000'` 返回 UP 只代表
socket 监听, VcXsrv 可能还在初始化 (或访问控制未就绪)。实测:
- 探测 UP 后立即启动 studio → `could not connect to display host.docker.internal:0`
- 正确姿势: **启动 GUI 前先 `xwininfo -root -display <disp>` 验证 X 握手真正成功**
  (返回 "Window id: 0x..." 才算就绪)

## 探测器 + watch_patterns 模式 (等用户操作 Windows 侧)
用户配合 Windows 侧操作 (双击 VcXsrv 等) 时, 挂后台循环探测:
```bash
for i in $(seq 1 180); do
  if timeout 2 bash -c 'echo > /dev/tcp/host.docker.internal/6000' 2>/dev/null; then
    echo "VcXsrv UP detected $(date +%T)"; exit 0; fi
  sleep 5; done
```
terminal(background=true) + watch_patterns=["VcXsrv UP detected"] → 通知到达后
先 xwininfo 验证, 再 kill Xvfb 实例 → DISPLAY=host.docker.internal:0 重启。

## VNC 连接检测 (确认用户已连上)
`cat /proc/net/tcp | awk '$4=="01" && $2 ~ /:170C/' | wc -l` — 5900=0x170C,
state 01=ESTABLISHED。>0 = 用户 VNC Viewer 已连上。同样用于"挂探测器等用户连"。

## 老倪偏好 (重要)
- **"别让我操作"**: 不执行 Windows 侧命令 (netsh/portproxy/命令行), 只接受双击级操作
  (双击 VcXsrv 图标、VNC Viewer 输地址)。容器无 wsl.exe interop, Windows 侧
  进程无法代劳 — 提前说明"这步只能你双击一下", 别给他贴命令。
- 切换显示通道时给选项让他选 (VNC 稳定 / VcXsrv 临时 / 只保进程), 别自作主张。
