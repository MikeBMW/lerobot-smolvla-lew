# WSL GUI 显示链路 (XLaunch/VcXsrv + WSLg) — 2026-08-12 实测

## 症状与根因
- 控制台(studio.py)窗口"没打开"但进程活着 → 窗口被 WSLg 合成器放到了**屏幕外**
  (xdotool getwindowgeometry 报 Position: -32692,-32650), xdotool windowmove 在 wayland 下**无效**
- 用户说"XLaunch 没打开" → tasklist 显示 vcxsrv.exe 在跑但**假死**(进程活着, 显示失效)
  → 必须杀掉重启, 不是没启动

## 修复流程
```bash
# 1. 杀旧 vcxsrv + 重启 (WSL bash 里 taskkill.exe //F //IM 会报参数无效 → 用 PowerShell)
powershell.exe -NoProfile -Command "Stop-Process -Name vcxsrv -Force -ErrorAction SilentlyContinue; Start-Sleep 1; Start-Process 'C:\Program Files\VcXsrv\vcxsrv.exe' -ArgumentList ':0','-ac','-multiwindow','-clipboard','-wgl'"
#    -ac = 关访问控制(X0.hosts 只有 localhost 会拒 WSL) / -multiwindow = 每窗独立显示 / -wgl = OpenGL

# 2. 验证端口 (NAT 模式: Windows 宿主 = 默认网关, nameserver 10.255.255.254 → 网关即宿主)
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/<宿主IP>/6000' && echo OK   # 宿主IP: ip route | grep default

# 3. 带 DISPLAY 启动 GUI (走 X11 而非 WSLg)
cd ~/lerobot-smolvla-lew/tools/gui && DISPLAY=172.18.80.1:0 /usr/bin/python3 studio.py

# 4. 验证窗口挂上 (xdotool 要走同一 DISPLAY)
DISPLAY=<宿主IP>:0 xdotool search --name "Z-MAX" getwindowname %@
```

## 要点
- WSL2 NAT 模式: Windows 宿主 IP = 默认网关 (`ip route | grep default` → 172.18.80.1), 不是 /etc/resolv.conf 的 nameserver(10.255.255.254 是虚拟 DNS)
- WSLg 占用 :0 的 unix socket → 想走 VcXsrv 必须显式 DISPLAY=<宿主IP>:0 (TCP 6000)
- WSLg 下窗口位置异常(xdotool windowmove 无效)时, 改走 XLaunch 显示是可靠出路
- 窗口在 VcXsrv 下 ID 复用: kill 后重启 xdotool 可能返回相同 ID, 用 getwindowpid 确认是新进程
- GUI 启动后窗口创建有延迟(8~15s), 先 poll 进程再搜窗口, 别急着判失败

## pkill/pgrep 自匹配坑 (验证时必踩)
- `pkill -9 -f "模式串"` 会匹配**自己所在 shell 的命令行**(hermes 的 bash -lic 包装含整条命令)
  → 测试命令自杀 exit -9; `pgrep -f "lerobot_train"` 报 TRAIN_STILL_RUNNING 虚惊
- 验证时: 模式串与命令隔离(用变量拼接)或结果 `grep -v` 排除自身

## 主窗口置顶挡住浏览器/文档 (2026-08-12 老倪反馈"控制台始终在前面")
- studio.py 启动尾部曾设 `win.setWindowFlag(Qt.WindowStaysOnTopHint, True)`(2026-08-07 为防 WSLg 遮挡加的)
  → 控制台永远盖在浏览器/PDF 窗口上, 点开网页看不到 → 2026-08-12 已删, 只留启动时
  `win.raise_() + win.activateWindow()` 置前一次
- 教训: WSL GUI 主窗口勿设 StaysOnTopHint; 防遮挡用启动置前一次即可

## 帮助文档/文件打不开: explorer.exe 打开 md 无关联程序没反应
- studio._mk_doc_action 曾用 `explorer.exe <C盘副本>` 打开文档 → .md 无默认关联程序时**静默没反应**
  (用户反馈"点击帮助文档不自动打开")
- 统一改 `cmd.exe /c start "" <C盘路径>` + `cwd="/mnt/c/Windows"` → Windows 默认程序自动处理
  (md→编辑器 / docx→Word / pptx→PowerPoint; WSL 侧必须先复制到 C:\Users\Public\ZMAX_docs 再开,
  UNC/\\wsl$ 路径 Windows 打不开)
- 打开网页/文件/目录在 WSL GUI 里统一走: cmd.exe start + cwd=/mnt/c/Windows (详见 SKILL.md 坑列表)
