# 3D 视图渲染 + 播放层坑 (2026-09-10, ss_dreamview.py / GUI 播放)

本次定案: 用户报的"夹爪无缘无故转一圈 / 轨迹直上直下+螺旋 / 没夹住 / 没看到插拔" **全部在渲染与播放层**,
tr 数据层是干净的 (重放 `RealStateSpaceSim(seed=104, vision=False, demo_l4=True).run(cap='L4')`:
4704 步 done=True, hand_yaw 旋转事件仅 +91.8°(②抓前对准) 与 −93.1°(③回正), ①-⑧ 全段含 ⑤插入603帧/⑥拔出168帧)。
诊断入口见 SKILL.md 调试铁律 5。

## 坑 1 — jaw 爪瓣位置双重旋转 (commit 60646388)
- 旧代码: `jaw_lc = wrist + jaw_dir*gap` (jaw_dir = Rz(yaw)·(0,1,0), **已含 yaw**) 且
  `_box_mesh_yaw(center=jaw_lc, rot_center=_wrist, yaw)` 又把整个 box 顶点绕 wrist 转一次 yaw
  → 位置实际绕 wrist 转 **2×yaw**。
- 症状: yaw 0→90° 动画中爪瓣绕腕画 **180° 半圆弧回到对侧** (= 用户"夹爪自己转了一圈/螺旋");
  旋转结束后静止位错 (yaw=90° 时爪瓣仍在 ±y 而非应到的 ±x) → 与横放模块对不上 = "像没夹住"。
- 修复: 位置用**未旋转的 ±y 基准** `_jaw_lc = _wrist + [0, gap, 0]`, box 仍统一绕 wrist 转 yaw —
  这样位置 Rz(yaw)·(0,±1)·gap 与朝向 Rz(yaw)·x̂ 同时正确 (单次旋转)。
- **通用坑**: 任何 mesh 顶点"绕某轴旋转"时, 若其中心位置已按同角旋转过 = 双重旋转。
  验证法: 取 yaw=90° 静态帧, 检查爪瓣中心是否落在预期方位 (±x), 而不是只看动画顺不顺。

## 坑 2 — 播放速度跳帧 (commit 48707eb1)
- 并行会话为"长轨迹逐帧播太慢"加了 `step = max(1, _n/800)` 跳帧 → 4704 帧 = **每 tick 跳 5 帧 = 5× 快进**:
  90° 旋转 0.7s 一闪 (观感"无缘无故转")、伺服每 tick 跳 2-5cm (轨迹跳着走/直上直下)、
  插入段 2-3s 快闪 (用户以为没插拔)。短轨迹 (<800 帧, 如 L2/L3 的 352 步) 不跳帧 → 所以"L2/L3 平滑"。
- 修复: `step = max(1, int(round(_n / 1500.0)))` → 恒定 ≈1× 物理速度 (4704 步 ≈ 94s 播完, 每段动作可看清);
  短轨迹仍逐帧 (0.33× 慢放, 平滑)。播放 timer 间隔 60ms 不变。
- 教训: 加速播放要按**目标播放时长/恒定物理倍速**算跳帧, 不能按帧数随手除一个大数。

## 坑 3 — "3D 视图"数据源不是模型推理 (回答"渲染的是哪个模型")
- GUI 日志: `🧭 3D 视图数据源: 程序执行轨迹 (sim.run() 4631 步)` — 播的就是**这一次 ▶运行**的 tr。
- L4 档该次 tr = `RealStateSpaceSim(demo_l4=True)` → `_run_demo` → L4Demo (确定性伺服 + metaworld 真物理),
  **回路里没有学习模型**。所以"乱"永远不是权重问题; 先查 tr, 再查渲染, 最后才谈模型。

## 复用探针 (与 tr 断言同源)
```python
import os, sys, importlib.util, numpy as np
os.environ.setdefault("MUJOCO_GL", "egl"); sys.path.insert(0, "tools")
spec = importlib.util.spec_from_file_location("_l4", "tools/gen_l4_demo_video.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
demo = g.L4Demo(seed=0, record=False); demo.run_all()
tr = demo.tr; hy = np.asarray(tr["hand_yaw"], float)
# 1) 旋转事件: |Δyaw|>0.5°/帧 连续段, 累计净角 (找 >180° 异常)
# 2) peg−hand rel 恒定: (np.asarray(tr["peg"]) − np.asarray(tr["x"])) 逐帧, 应≈常量
# 3) 单帧跳: np.linalg.norm(np.diff(np.asarray(tr["peg"]), axis=0), axis=1) > 0.02 计数
# 4) 阶段分布: dict(Counter(str(s)[:8] for s in tr["stage"])) — 必须含 ⑤插入/⑥拔出
```
判据: 若 (1)(2)(3) 干净且 (4) 含插拔段 → 数据无问题, 直接转 ss_dreamview 渲染/播放排查。
