# VcXsrv 渲染 bug + PyQt5 深坑 (2026-08-18 深夜全实测)

## VcXsrv (HC-Consult 12014000, 2021 版) 渲染 bug — 代码侧无法根治
症状: 拖动滚动条/分割条时 **"上半部分动, 下半部分不动"** / 大窗口黑屏。
证据链 (全部实测):
- faulthandler 证明主线程正常 (无死锁) — 问题在显示层不在 Qt 逻辑
- 窗口移动 (xdotool windowmove) 后内容完整 = 服务器端合成正常
- 增量更新 (滚动/局部重绘) 部分失效: XCopyArea 位块移动只移一半、
  大 XPutImage (窗口 ~5MB 单请求, max request 16MB 支持 BIG-REQUESTS) 只画顶部一点
- **QT_XCB_NO_XDAMAGE=1 会让视频弹窗整体黑屏** (禁用增量上传 → 全量大请求 → bug) — 不要加!
- QT_XCB_NO_MITSHM=1 无效 (VcXsrv 无 MIT-SHM 扩展, 本来就走 XPutImage)
- xdotool 注入事件 Qt 收不到 (VcXsrv XTEST 走 core 事件, Qt xcb 用 XInput2) — 别指望自动化模拟

结论: 滚动/大窗口重绘在 VcXsrv 老版本下必踩 bug。Qt 侧最优 = 默认 MinimalViewportUpdate
(滚动走 XCopyArea + 小条重绘, 尽量少触发大上传)。根治 = 升级 VcXsrv 或换显示方案
(Xvfb+VNC / 新版本)。

## PyQt5 5.15 sip 枚举错位 (ViewportUpdateMode)
实测值: NoViewport=3, Minimal=1, **Full=0**, Bounding=4, Smart=2
- 传 QGraphicsView.FullViewportUpdate (PyQt5 值 0) → C++ 收到 0 = NoViewportUpdate (滚动不重绘!)
- 要 C++ FullViewportUpdate 必须传整数值 2 (= PyQt5 的 SmartViewportUpdate)
- MinimalViewportUpdate=1 是唯一与 C++ 一致的枚举 — 排查滚动问题时先打印 viewportUpdateMode() 确认

## 排查方法论 (卡死/黑屏/滚动异常)
1. faulthandler (studio.py main): enable() + dump_traceback_later(20, repeat=True) — 卡死时
   信号照常触发, dump 全部线程 Python 栈, 先分主线程阻塞 vs 显示层问题
2. 主线程正常 → 显示层: 用 QScreen.grabWindow(0) 截图 (ffmpeg x11grab 对 TCP X 不可靠),
   PIL 分条带对比差异定位"哪部分没刷新"
3. 窗口移动测试: xdotool windowmove → 服务器端全量合成 → 若完整则增量更新路径有 bug
4. gdb attach 崩溃进程: bt + thread apply all bt (抓全部线程, 别只看主线程)

## 操作视频播放器 (MLPRolloutDialog) 语义 — 老倪明确
- 操作视频 = **机械臂动作视频** (MLP rollout: mlp_insert_success_final 等), 不含
  state_space_sim.mp4 (仿真波形动画, 属「📊 仿真波形」节点) — 别把仿真动画混进播放列表
- 选片排除 rot180/rot 变体 + 伪装副本「发送_MLP插拔成功.mp4」
  (字节数与 mlp_insert_success_rot180.mp4 完全相同 = rot180 副本, HUD 文字倒)
- MLP 视频默认 rot180 (老倪实测图像才正); 用 QPixmap.fromImage(pm.toImage().mirrored) 快转
- 播放器要点: 初始 1280x820 可调大小, 循环播放 (播完自动暂停会被误认"卡住"),
  QLabel setPixmap 缩放适配 (resizeEvent try 保护), 标题栏/按钮禁 emoji (VcXsrv wqy 无字形 → ??)

## 渲染子进程化 (Pillow GIL)
gen_state_space_video.py (Pillow 渲染 240 帧持 GIL) 线程内跑会卡主线程 →
改 `subprocess.run([sys.executable, "gen_state_space_video.py", out], cwd=gui_dir)` 子进程渲染,
主线程零阻塞 (sys.executable = gui-venv311, 有 numpy+PIL)。
