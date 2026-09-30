# 遥控执行 + 单用例过滤 + studio env 钩子 (2026-09-06 实测)

触发: 老倪在飞书发指令 ("打开状态空间画布" / "点运行仿真" / "打开3D视图") → agent 操作控制台 → 截图回传。

## 核心约束: 外部进程截不了运行中 Qt 窗口
- `QWidget.grab()` 必须**进程内**执行 — 无法对"已在跑的 studio.py 进程"发指令或截它当前画面。
- **⚠️ 别构造第二个被测窗口去 grab**: 独立新 `StudioMainWindow()` 无布局激活 → canvas 只有
  126x79、主窗口 grab 内容空泛 (非运行中实例的真实页面)。实测踩过。
- 正确模式 = **杀旧实例 → 带 env 钩子重启 → 等截图落盘 → MEDIA 发群**。

## studio.py 启动 env 钩子 (无 IPC 遥控 Qt 应用的主通道)
| env | 动作 | 时机 |
|---|---|---|
| ZMAX_AUTO_TEST=1 | 自动启动 auto_test_suite (TC01-TC12 全跑, QTimer 1.2s/用例) | 5s |
| ZMAX_AUTO_TEST_ONLY=TC01 | **单用例过滤** (auto_test_suite `_build_plan()` 末尾按前缀过滤, "完成: 1/1 PASS") | 与上合用 |
| ZMAX_AUTO_SS=1 | 自动打开状态空间画布 | 3s |
| ZMAX_AUTO_SS_RUN=1 | 再自动点 ▶运行 (引擎快演) | 5.5s |
| ZMAX_AUTO_RUN=1 | 切 Simulink 页 + 五模型对比 + ▶运行 | 2.5s |
| ZMAX_NO_SPLASH=1 | 跳过 splash (诊断窗口问题时) | 启动 |
| ZMAX_FAULTHANDLER=1 | faulthandler 20s 周期 dump 主线程栈到 stderr | 启动 |
| ZMAX_DIAG_UNMIN=1 | _unminimize_loop 每次探测写 /tmp/studio_show_diag.log | 启动 |

启动时必须从 gnome-shell 进程取会话 env (DBUS/XDG_RUNTIME/XAUTHORITY 见 mutter-window-map-debug.md),
不要 nohup 裸启; 完整环境用 `gio launch <Desktop/*.desktop>` 或逐项 export 自 /proc/<gnome-shell-pid>/environ。

## 遥控工作流 (验证过)
1. 杀旧: `for pid in $(pgrep -f "gui-venv311/bin/python studio.py"); do kill -9 $pid; done` (写脚本文件跑, 防自杀)
2. 重启带钩子: `ZMAX_AUTO_TEST=1 ZMAX_AUTO_TEST_ONLY=TC01` → 单用例截图 → /tmp/zmax_auto_test/TC01_*.png
3. 或 `ZMAX_AUTO_SS=1` → 画布自动开 → 用独立脚本 open_state_space+win.grab 已弃用 (见上坑), 走套件截图
4. 收图 → 逐张 MEDIA: 发飞书 — 每图即"该指令的实际操作结果" (老倪: 看控制台截屏, 非桌面 scrot)

## TC08 阶段截图用 grab 而非 xwd (2026-09-06 修复)
- auto_test_suite TC08 原用 `_xwd_shot` 截 3D 窗口 — 本机 xwd 未装 → FileNotFoundError → 全阶段 @0KB。
- 修: `_shot_widget(w3, f"{nm}.png")` (QWidget.grab / viewport().grab) — 3D GL 窗口 grab 照常出真实渲染
  (每阶段 241-257KB, 8 阶段 接近/对位/下降/抓取/抬起/转移/插入/完成 全 PASS)。
- 旧注释 "GL 窗口 grab 截不到 → xwd" 是错的 (TC07 早已 265KB 证明)。

## 3D 完整操作视频 (330 帧 mp4)
- 流程: 构造 studio (SimulinkModule 延迟创建, 轮询 win.simulink 非 None) → open_state_space →
  chk_engine_demo.setChecked(True) + start_sim → 轮询 _ss_tr 就绪 → open_ss_3d(on_top=False) →
  逐帧 `w3.set_frame(i)` + processEvents + `w3.grab().save(f_%04d.png)` → ffmpeg 合成。
- **ffmpeg 偶数尺寸坑**: `-pix_fmt yuv420p` 要求宽高偶数; grab 1180x937 (奇数高) → "width or height" 失败。
  先 PIL 全帧 `resize((1160,920), LANCZOS)` 再合成 (`-framerate 15 -c:v libx264 -preset fast -movflags +faststart`)。
- 330 帧 → ~2.3MB; MEDIA: 发 mp4 交付。
