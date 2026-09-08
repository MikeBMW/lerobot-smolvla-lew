# 状态空间 GUI 呈现升级 + 崩溃排查 (2026-08-18 晚)

## 用户铁律: 画布节点 = 标准 node 大小, 双击 = 独立大窗口
老倪对状态空间画布两个"视频类"节点的明确要求:
- **「📊 仿真波形」节点 (ssvideo)**: 画布上标准节点 (150 x DH=50), 双击弹大窗口显示波形
- **「🎥 操作视频」节点 (ssvideo2)**: 画布上标准节点 (150 x 50), 双击弹独立大窗口播放视频
- 窗口要求: 初始大 (1280x820), 可自由调整 (setSizeGripEnabled + WindowMaximizeButtonHint), 不卡, 看得清
- ⚠️ **改节点前先确认是哪个节点** (查 flows/*.json 的 id/name): 老倪说"仿真波形"我改成了 ssvideo,
  实际他要的是操作视频 ssvideo2 — 用户原话"你也没改啊"。两个节点别搞混。

## StateSpaceScopeDialog 大窗口 + 不卡 (simulink_module.py ~1015)
- setMinimumSize(820,560) → (1024,700); 加 resize(1280,820) (原无初始尺寸 → QDialog 默认小窗)
- setSizeGripEnabled(True) + setWindowFlags(| Qt.WindowMaximizeButtonHint)
- **曲线绘制: 逐点 drawLine (500点x4子图=2000次, resize 重绘卡死) → QPainterPath 批量 lineTo + 一次 drawPath (<5ms)**
- 线宽 2→2.5, 标题字号 12→14 (放大后清晰)

## MLPRolloutDialog — 独立大窗口视频播放模板 (~1102)
画布内嵌播放 (节点 paint 画帧, VcXsrv 下小/卡) → 废弃, 改独立 QDialog:
- 结构: 标题 QLabel + 视频 QLabel (AlignCenter, 黑底) + 控制条 (⏮⏸⏭🔄)
- 100ms PreciseTimer (_tq 挂 parent) 轮播; 播完一圈自动暂停, 双击画面重播
- **渲染: 存原始 QPixmap (_pm), _render() 按 label 当前尺寸 scaled(KeepAspectRatio) + 旋转; resizeEvent → _render() (resize 不卡不重载)**
- 后台线程 ffmpeg 抽帧 (缓存秒开) + pyqtSignal 回主线程 (帧列表/目录放 dialog 自包含)
- closeEvent 必须停 timer (防 activateTimers 崩溃铁律)
- 主窗口 play_mlp_rollout → 弹窗 (已有窗口则 raise_/activateWindow 不重复开);
  _mlp_rot180/_mlp_next/_mlp_prev/_mlp_toggle 改为转发 dialog (右键菜单不改)

## 崩溃排查进行中: 「运行」卡死 + Segfault (未定位, 用 gdb 抓)
现象: 点「▶ 运行」→ 状态空间仿真 → 卡死 → Fatal Python error: Segmentation fault
报错前置: `QObject::killTimer: Timers cannot be stopped from another thread` +
`QObject::~QObject: Timers cannot be stopped from another thread`, 栈停在 studio.py main (app.exec_)
已知线索:
- _start_video_export (仿真完成自动触发, ~8910) 注释记载同类崩溃: 后台线程首次 import PyQt5 模块
  → SIGSEGV (QObject::killTimer)。已修: gen_state_space_video 改纯 Pillow 渲染 + 主线程预加载 import。
- 本次仍崩: 后台线程 _worker 只调 make_video (Pillow) + _safe_log (QMetaObject 队列, 安全), 无直接 Qt 操作。
- 排查工具: scripts/gdb_studio_crash.sh — gdb 监控启动 studio, SIGSEGV 自动 bt 30 + info threads 到 /tmp/gdb_crash.log
  (用法: bash 该脚本后台跑, 让用户复现崩溃, 再读 /tmp/gdb_crash.log)
