# 显示口径: 一档一窗 (三个 dreamview), 不要画中画 — 老倪 2026-09-13

## 用户原话
> "在3D视图里，dreamview形式的显示，不要搞成画中画了，就是两三个窗口，都用dreamview，
>  一个是L2，一个是L3，一个是L4的stable world"

以及更早的一句:
> "L4 INTACT 单独开的视频，怎么不动呢？可以像 L2 L3的dreamview一样，变成互动，可以看到任意帧的信号么"

## 结论 (照此实现/维护)
- **禁止画中画 (PiP)**: 不要再往 3D 场景右上角贴实况小窗。已删: `DreamView3D._sw_panel` 的创建、
  150ms `_sw_timer`、`_layers_def` 里的 `sw_live` 项 (2026-09-13, 相关代码注释保留说明)。
- **一档一窗, 各自独立可交互**: 3D 视图左侧一排按钮 →
  `🧭 L2 DreamView` (只开感知层 scene/traj) / `🧭 L3 DreamView` (再加 uff/latent/prior) /
  `🌍 L4·SW DreamView` (= stable-world 逐帧真渲染 + 拖帧看信号)。可同时开三个窗口。
- **档位预设贯通**: `DreamView3D(tr, module, level=...)` 与 `SimulinkModule.open_ss_3d(on_top, level=...)`
  新增 `level` 参数 → 打开即按档位开关图层 (`LEVEL_PRESETS`) + 标题标注
  `🧭 状态空间 <LEVEL> DreamView (3D 分层)`。
- **交互 = 标配 (dreamview 同款)**: 时间轴拖帧 / ◀▶ 单步 / ⏮⏭ 首尾 / ▶ 连续播放 +
  逐帧信号表 (step/回合/模型动作[0..3]/frame_std/done/累计真推理次数) + 动作曲线带游标。
  实现在 `tools/gui/intact_signal_viewer.py` (`IntactSignalViewer`, 单例 `open_signal_viewer()`)。
- **"窗口不动"的正确回应**: 只播实时流的窗口在链条停下后定格在末帧 → 不是坏了。要么给拖帧/
  单步的交互模式, 要么让窗口顶部显示数据源路径 + 状态行, 用户能自己判断"没在跑"还是"真不动"。

## 数据源约定 (互动查看器)
- 自动扫 `reports/**/frames/*.jpg` 作为"一次实况导出"; 每帧信号读同目录 `status.jsonl`。
- `status.jsonl` 由 `tools/intact_sw_bridge.py` **每步追加一行** (step/action/frame_std/done/model_calls)。
  没有该文件的旧产物: 信号列显示 "—", **不编数值** (诚实标注)。
- 窗口标题/状态行要写明当前数据源绝对路径, 避免"看的是哪次跑的"这种混淆。

## 交付前自查 (GUI 侧)
- [ ] 真显示 (`DISPLAY=:0`) 下点一遍所有新按钮 (见 `pyqt-gui-auto-verification`
      → `references/button-wiring-regression.md`; 本次就是漏了这步才让"点按钮没反应")
- [ ] 三个窗口能同时存在, 且各自 `isVisible()` + 在屏内
- [ ] 拖帧到首/中/末: 画面是真图 (像素 std>5)、信号值随帧变化
