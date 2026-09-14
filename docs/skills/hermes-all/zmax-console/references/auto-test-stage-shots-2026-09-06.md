# 自动测试 阶段截图 + 功能块顺序用例 + 3D 视频 (2026-09-06 实测)

触发: 老倪要求"接近/对位/下降/插入等所有步骤都要自动测试"、"自动测试的完整3D视频发给我"。
相关: pyqt-gui-auto-verification SKILL.md + references/remote-desktop-x11vnc-novnc.md (交付通道)。

## TC08 阶段截图: xwd → QWidget.grab() 修复 (8 阶段全成功)
- **症状**: auto_test_suite.py TC08 用 `_xwd_shot` 截 3D 窗口 → 本机 xwd (x11-apps) 未装 → FileNotFoundError → 全阶段 `@0KB` 假成功。日志 "xwd 截图失败"。
- **修法**: 改 `_shot_widget(w3, f"{nm}.png")` (QWidget.grab / viewport().grab 兜底)。3D GL 窗口 grab **照常出真实渲染** (241-257KB/张) — TC07 早就证明 (265KB), 旧注释 "GL 窗口 grab 截不到 → xwd" 是**错的**。
- **阶段遍历逻辑**: `tr["stage"]` 每阶段取首个下标 → `w3.set_frame(i)` (或 `_idx=i; _update_frame(i)`) → processEvents + sleep 0.5 → grab。实测 8 阶段 (接近/对位/下降/抓取/抬起/转移/插入/完成) 各 241-257KB 全 PASS。

## TC09-TC12: 按状态空间功能块顺序的用例 (老倪: "按照状态空间的功能块, 按顺序测试")
追加到 `_build_plan()` (TC01-TC08 之后), 断言**画布节点名**而非内部对象 (诚实可读):
- TC09 S1感知层: 名字含 传感器/感知 + 43D/obs/状态向量
- TC10 S2并行层: 前馈/加速器 + 估计器 + 预测/动力学 + 校正/残差 (≥3/4)
- TC11 S3认知层: 调制/调度/状态机 + 安全/限幅/边界
- TC12 执行闭环: 执行/机器 + 物理/世界 + 反馈/z_k/传感
验证: 12/12 PASS (TC01-08 原套件 + 新 4)。扩展用例模式: fn 返回 (ok, note) 或 (ok, note, shot_widget)。

## 3D 完整操作视频生成 (330 帧 mp4, 老倪: "完整3D视频发给我")
工作流 (独立脚本, gui-venv311 + DISPLAY):
1. `StudioMainWindow()` 构造后 **SimulinkModule 是延迟创建** (studio 5s+ 定时器) → 轮询 `win.simulink` 非 None (每 0.5s × 16) 再驱动, 别假设构造即就绪
2. `sim.open_state_space()` → `chk_engine_demo.setChecked(True)` → `sim.start_sim()` → 轮询 `sim._ss_tr` 有 `x` 且 len>50 (最多 60s)
3. `sim.open_ss_3d(on_top=False)` → 取 `_ss_3d_windows` 中 isVisible 的窗口 → 逐帧 `w3.set_frame(i)` + processEvents + `w3.grab().save(f_%04d.png)`; 抽稀 `max(1, n//200)` 控帧数
4. **ffmpeg 合成坑**: `-pix_fmt yuv420p` 要求宽高偶数 — grab 尺寸 1180x937 (奇数高) → 报 "width or height" 失败。先 PIL 全部帧 `resize((1160,920), LANCZOS)` 再 `ffmpeg -framerate 15 -i f_%04d.png -c:v libx264 -preset fast -pix_fmt yuv420p -movflags +faststart out.mp4`
5. 330 帧 → 2.3MB mp4; MEDIA:/path.mp4 发飞书交付

## 测试驱动注意
- 阶段截图在 TC03 仿真后执行 (需 `_ss_tr`) — `_build_plan` 顺序 TC01→02→03→TC08→04→05→06→07→09-12 保持依赖
- QTimer 链式 `_tick` (1.2s/用例) 主线程跑, 不卡 UI; report.json 汇总 {total, pass, results[{tc,desc,pass,note,shot,shot_kb}]}
- 跑完整套件: `ZMAX_AUTO_TEST=1 python studio.py` (5s 后自动起), 截图落 /tmp/zmax_auto_test/TC*.png — 逐张 MEDIA 发群即交付 (老倪偏好: 看控制台实际操作截屏, 非桌面 scrot)
