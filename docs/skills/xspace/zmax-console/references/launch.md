# 启动 Studio 控制台 (2026-08-09 实测)

## 最快启动命令

```bash
cd /home/xspace/lerobot-smolvla-lew/tools/gui
QT_QPA_PLATFORM=wayland DISPLAY=:0 /usr/bin/python3 studio.py   # 用 terminal(background=true)
```

## python 选择

- `run_studio.sh` 首选 `~/miniconda3/envs/lerobot/bin/python` (conda lerobot 环境)
- 若该环境不存在: 系统 `/usr/bin/python3` 自带 PyQt5, 可直接启动 — 不要卡在找 conda 上, 直接 fallback
- 验证 python 可用: `<python> -c "import PyQt5"`

## 关键点

- 必须 `QT_QPA_PLATFORM=wayland` (xcb 飞屏问题, 见 SKILL.md refs/wsl-display-links)
- 不要用 `nohup ... &` 前台后台化 — Hermes terminal 工具会拒绝 (报错要求用 background=true); 直接 `terminal(background=true)`
- 日志里的 EGL/MESA/ZINK `failed to choose pdev`、`Unknown property cursor`、`qt.qpa.wayland: Wayland does not support QWindow::requestActivate()` 全是噪音, 可忽略

## 验证窗口已起

```bash
pgrep -fa studio.py   # ⚠️ 会匹配到自己的 bash 包装行, 认 `python3 studio.py` 那条子进程
```

- 启动后 sleep ~8s 再查; 进程名是 `python3 studio.py` (PID 是子进程, 不是 bash 包装); 正常态 = Sl 状态
- 然后 process(action=poll) 确认 status=running 且无 Traceback。窗口显示在 WSLg 里, 用户直接操作即可
- 已有实例在跑时不用重启: 先 pgrep 看有没有, 窗口在 WSLg 里直接可见

## python 选择补充

- `.venv/bin/python` (torch 训练环境) 无 PyQt5, 用它起 GUI → `ModuleNotFoundError: No module named 'PyQt5'` 秒退; GUI 必须用带 PyQt5 的 python (系统 python3)

## 已失效的路径

- `~/miniconda3/envs/lerobot/bin/python` 曾不存在 (2026-08-09) → `No such file or directory`, exit 127
- miniconda3 整体不存在 (`~/miniconda3/bin/python` 也没有)
