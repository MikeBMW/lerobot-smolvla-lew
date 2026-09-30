# WSL 显示/打开/PDF 三坑 (2026-08-12 实测)

## 1. cmd.exe /c start 从 WSL 启动必须指定 Windows cwd (重大)
从 WSL 直接 `cmd.exe /c start "" url` 时,cmd 当前目录是 `\\wsl.localhost\Ubuntu\...`(UNC),
报 "UNC 路径不受支持" 且 **start 静默失败** —— 网页/文件根本没打开,无报错。

修复:所有 `subprocess.Popen(["cmd.exe","/c","start","",x])` 必须加 `cwd="/mnt/c/Windows"`。
已修调用点(2026-08-12):simulink `open_solution_web` / `open_scene_link` / `open_node_source`,studio `_export_doc_pdf`。
验证:cd /mnt/c/Windows 后 cmd start 干净 rc=0 且真实打开。

## 2. 窗口在 X server 但 Windows 桌面看不到
- WSLg 下窗口可能跑到屏幕外(负坐标 -32692,-32650),且 WSLg wayland 下 xdotool windowmove 管不动。
- 改用 VcXsrv (XLaunch) 显示:VcXsrv 是 X11,xdotool 可控制窗口位置。
- 恢复可见: `xdotool windowmap <wid>; windowsize <wid> 1400 900; windowmove <wid> 60 40; windowactivate <wid>`
- VcXsrv 进程假死:tasklist 显示 vcxsrv.exe 在跑但窗口全不显示 → 杀重启:
  `powershell.exe -NoProfile -Command "Stop-Process -Name vcxsrv -Force; Start-Process 'C:\Program Files\VcXsrv\vcxsrv.exe' -ArgumentList ':0','-ac','-multiwindow','-clipboard','-wgl'"`
  (-ac 关访问控制,multiwindow 每个 X 窗口独立 Windows 窗口)

## 3. 源码/文件打开 (WSL 路径 Windows 打不开)
- `\\wsl$\` UNC 被拒 → 一律复制到 Windows 可见 C 盘再打开:
  - 源码目录: C:\zmax_src_view\ (右键节点"📂 打开源代码"用,排除 __pycache__)
  - 文档: C:\Users\Public\ZMAX_docs\ (帮助文档菜单用)
- 复制后 `cmd start` 打开(注意坑 1 的 cwd)。

## 4. 改 GUI 代码必须重启 GUI 用户才看到 (老倪"没看到"教训)
改 simulink_module.py / studio.py / 生成脚本后,不重启 GUI 用户永远看到旧界面/旧按钮。
流程: pkill -9 -f "studio\.py" → 重启 (DISPLAY=172.18.80.1:0 /usr/bin/python3 studio.py) → xdotool 拉到 (60,40) 1400x900。

## 5. PDF 导出 (reportlab 中文字体 + GUI 解释器)
- **reportlab 不支持 CFF/PostScript outlines 字体**: `TTFont('NotoSansCJK-Regular.ttc')` 抛
  "postscript outlines are not supported"。系统 Noto CJK 全是 CFF (.ttc) → 装 TrueType 中文字体:
  `sudo apt-get install -y fonts-wqy-microhei` → `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc` (subfontIndex=0)
- emoji 在 WQY 无字形 → 渲染 \u0000/方块 → 剥离 `[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]`
- fitz 1.28: `fitz.Story` 渲染 0KB 无效; `insert_htmlbox` 返回高度≈矩形高度不可用分页 → 用 reportlab SimpleDocTemplate 自动分页
- **GUI 用系统 python3 (/usr/bin/python3, 无 reportlab)** → 转换必须走 .venv 子进程:
  `.venv/bin/python tools/gui/docs_pdf.py <md> <pdf>` (docs_pdf.py 自带 __main__)
- 工具: tools/gui/docs_pdf.py (轻量 md 解析: 标题/列表/表格/代码块/段落)
