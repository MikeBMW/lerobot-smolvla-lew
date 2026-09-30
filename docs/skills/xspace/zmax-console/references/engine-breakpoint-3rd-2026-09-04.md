# 引擎内部断点第三次复发 + ▶运行 时序架构 (2026-09-04)

老倪第三次报"运行后进不了 yolo (detect_3d) 断点", 断点就在 fuse_sensors (perception.py:34) —
与 09-01/09-02 完全同款, py-spy 栈 `fuse_sensors ← _build_obs ← run ← _start_state_space_sim` 不变。
本次把 ▶运行 时序彻底钉死 (配套 vscode-breakpoint-engine-internal-2026-09-02.md 根因④ 的 3rd 复发记录):

```
_start_state_space_sim (simulink_module.py):
  10360  sim.run() 引擎 500 步数值闭环 (<0.1s, 纯 numpy)
         └─ 每步 _build_obs → fuse_sensors (引擎感知源码, 断点在此 = 每步停)
  10373  self._real_yolo_sense_once()   ← 引擎跑完才轮到
         └─ 画布找 ss_yolo 节点 → node_ss_yolo → _yolo_capture
              → env.reset(seed=0)+render 1帧 → detect_3d  ← 目标断点
```

## 要点
- **引擎源码断点每步命中 → 500 次 F5 才轮到 10373**。解法: 删引擎断点; 或断点设在
  10373 `self._real_yolo_sense_once()` 再 F11 单步进 detect_3d。
- **引擎 obs = 世界状态直读** (_build_obs 拼 self.x/gripper/v/peg/HOLE_POS), YOLO 结果
  **从不进引擎闭环** (引擎侧零 _YOLO_CACHE 引用; det3d 只进缓存给播放演示/日志/单节点执行)。
  单次 ▶运行 metaworld 只渲染 **1 帧** (reset(seed=0) 后), 融合/前馈吃的 43D 全是引擎直读。
  两路径两世界 (引擎简化世界 vs metaworld seed0), 坐标不同源 → 真实值不注入轨迹。
  老倪连环追问 ("渲染几帧" / "融合前馈怎么根据 1 个 YOLO 结果计算") 的完整答案 = YOLO 是
  旁路证据采样, 闭环不吃它。→ 演进方向 = 真实化闭环 (zmax-metaworld-real-loop 技能)。
- **画布无 ss_yolo 节点 = _real_yolo_sense_once 静默 return** (6139 行, 原无日志 = 诊断黑洞)。
  已加显式日志 "⚠️ ▶运行: 当前画布无「🎯 YOLO 目标检测」节点"。**铁律: 静默 return 分支一律打日志**。
- **_EXTERNAL_LOC 指向废弃死代码 = 断点永不命中**: yolo_align 曾映射 pixel_to_ray
  (yolo_state_aligner.py:11) — 2026-08-23 改 cam_mat0 反投影后死代码 (零调用), 右键源码/断点全落空。
  改指 def detect_3d:53 (commit 70cdfa16)。算法重写后旧函数删掉或改映射, 别留展示层假指向。
