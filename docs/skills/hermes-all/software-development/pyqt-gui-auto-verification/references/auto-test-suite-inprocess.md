# auto_test_suite.py 进程内自动测试 + 3D 视频生成 (2026-09-06 实测)

仓库: /home/ubuntu/lerobot-smolvla-lew · GUI venv: gui-venv311
补 zmax-studio-automation.md 的进程内套件细节。

## 入口与机制
`ZMAX_AUTO_TEST=1 gui-venv311/bin/python studio.py` → studio 5s 后 `_start_auto_test_suite()`
→ `auto_test_suite.StateSpaceAutoTest(self, self.simulink)` QTimer 链式逐用例 (~1.2s/步),
每用例 `QWidget.grab()` 截图存 /tmp/zmax_auto_test/ + report.json (total/pass/results[])。
**窗口 X 层不 map (Mutter bug) 不影响 — grab 照常出真实渲染** (见 mutter-window-map-debug.md)。

## 用例清单 (12 个, 2026-09-06)
- TC01 打开状态空间画布 (节点数>10 含 S1感知) / TC02 引擎快演 (start_sim) / TC03 仿真结果
  (330步 done=True 距离~0.066 接触1.00) / TC04 节点逻辑 (38/42) / TC05 数据总线 /
  TC06 3D 打开 / TC07 3D 图层 (13层) / TC08 阶段动作截图
- **TC09 S1感知层 / TC10 S2并行层 / TC11 S3认知层 / TC12 执行物理闭环** — 2026-09-06 按状态空间
  功能块顺序新增: 断言画布节点名含 传感器融合/43D obs/前馈/估计/预测/校正/调制/安全/执行/物理世界/反馈

## 单用例过滤 (遥控"打开状态空间画布"这类单指令用)
`ZMAX_AUTO_TEST_ONLY=TC01` env → _build_plan 按前缀过滤 → 起 studio + 两 env → ~40s →
收 /tmp/zmax_auto_test/TC01_*.png → MEDIA 发飞书 = 交付该步实际操作画面。

## 踩过的坑
- **TC08 原用 `_xwd_shot` (xwd 命令截 GL 窗口)** — 本机 xwd 不存在 → 每阶段 0KB
  (`阶段截图(3D): 接近@0KB, 对位@0KB...`)。改 **QWidget.grab() 截 w3 (DreamView3D)** →
  241-257KB/张全成功。3D 窗口 grab 有效 (TC07 早有 265KB 佐证), 无需 xwd。
- **外部无法给运行中 Qt 进程注入 QTimer/指令** — 想换场景只能重启 studio 带对应 env
  (ZMAX_AUTO_SS=1 自动开画布 / ZMAX_AUTO_SS_RUN=1 再自动▶运行 / ZMAX_AUTO_RUN=1 五模型对比)。
  跨进程调 StudioMainWindow 方法不可行, 别试 debugpy attach 之类绕路。

## 3D 全流程视频生成 (接近→对位→下降→抓取→抬起→转移→插入→完成)
单实例脚本流程 (gen_3d_video.sh 模式):
1. 构造 StudioMainWindow → **等 simulink 延迟创建** (轮询 `getattr(win,'simulink',None)` 至多
   8s — 勿假设构造完就有, SimulinkModule 是 QTimer 延迟建的)
2. `sim.open_state_space()` → 勾 chk_engine_demo + `sim.start_sim()` → 等 `_ss_tr` 步数>50
3. `sim.open_ss_3d(on_top=False)` → 找 `_ss_3d_windows` 中 isVisible 的 w3
4. 逐帧 `w3.set_frame(i)` + `w3.grab()` 存 /tmp/ss3d_frames/f_%04d.png
   (抽稀 `step_skip = max(1, n//200)` → ≤200 帧; 每帧间 processEvents + ~30ms sleep)
5. ffmpeg 合成
**ffmpeg 坑: yuv420p 需偶数宽高** — grab 尺寸含奇数 (如 1180x937) 报错
"width or height not divisible by 2" → 先 PIL `resize((1160, 920), LANCZOS)` 再合成:
`ffmpeg -y -framerate 15 -i f_%04d.png -c:v libx264 -preset fast -pix_fmt yuv420p -movflags +faststart out.mp4`

## 遥控"实际操作"交付模式 (老倪偏好)
用户发指令 (如"打开状态空间画布") → 重启 studio 带对应 env 钩子/单用例 → 收 QWidget.grab 截图
→ MEDIA 发飞书。桌面 scrot 不是交付物; 要控制台/画布控件本身的 grab 图 (见
remote-desktop-x11vnc-novnc.md 用户偏好节)。
