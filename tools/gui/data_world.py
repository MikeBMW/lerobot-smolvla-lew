# -*- coding: utf-8 -*-
"""data_world.py — 🗺 DataWorld: 状态空间仿真"数据世界"(2026-09-03 v3.4.6 老倪)

对齐百度 Apollo Dreamview 架构: 每个画布节点 = 一个算法模块 (channel),
引擎每步把各模块的 in/out 发布到数据世界 → 画布播放 / 3D 视图 / 数据总线
消费**同一个数据世界 + 同一个帧游标** → 点击 ▶运行 后, 3D 渲染数据与画布
实际信号严格同帧同步 (Dreamview 的"模块输出 → 主视图渲染"语义)。

数据来源: state_space_sim.run() 每步 append 的 tr["io_trace"] —
    [(t, io_dict), ...], io_dict key = 画布节点名 (📡传感器融合/⚡前馈加速器/...),
    value = {"in": [(label, val)...], "out": [(label, val)...]} (引擎 _io_snapshot)。
    纯 numpy 无 Qt 依赖 — 引擎侧/GUI 侧/测试均可使用。

典型用法 (GUI):
    dw = DataWorld(tr)
    self._dw = dw                          # 播放/3D/总线共用一个 dw
    ... 播放循环每帧 ...
    frame = dw.frame(step_i)               # 该步全模块 I/O
    io = dw.module(step_i, "🧭 动作调制器") # 单模块 in/out
"""

# 引擎 io_trace 帧里"模块 key"= 画布节点名。以下为信号链路顺序 (3D/面板按此排序)
MODULE_ORDER = [
    "📦 metaworld 数据源", "🎯 YOLO 目标检测", "📐 2D→3D 解算", "🖐 触觉感知",
    "🔍 外观质量检测", "📡 传感器融合",
    "⚡ 前馈加速器", "🔮 自适应状态估计器", "📈 先验动力学预测器", "🧪 状态校正器",
    "🧭 动作调制器", "🛡 安全限幅", "🤖 执行器", "🌍 物理世界",
]


class DataWorld:
    """🗺 数据世界 — 逐帧全模块信号 + 帧游标 (单一事实源, 保证 3D/画布/总线同帧)。

    由引擎轨迹 tr 构建 (io_trace 逐帧全量, v3.4.6 起引擎每步发布)。
    """

    def __init__(self, tr):
        self.tr = tr
        self.frames = tr.get("io_trace", []) if tr is not None else []
        self._t = tr.get("t", []) if tr is not None else []
        self._stage = tr.get("stage", []) if tr is not None else []
        self._n = len(self._t)             # 引擎总步数
        self._cursor = 0                   # 帧游标 (画布播放推进它, 消费方只读它)
        # 帧数可能 < 步数 (旧轨迹兼容) — 建立 io 帧 → 引擎步 的映射

    @property
    def n_steps(self):
        return self._n

    @property
    def cursor(self):
        """当前播放游标 (引擎步) — 画布播放循环推进, 3D/总线读同一游标 = 严格同帧"""
        return self._cursor

    def set_cursor(self, step):
        self._cursor = int(max(0, min(step, max(0, self._n - 1))))

    def t(self, step=None):
        step = self._cursor if step is None else step
        return self._t[step] if step < len(self._t) else None

    def stage(self, step=None):
        """当前/指定步的阶段 (引擎 stage 记录: '阶段 插入' → '插入')"""
        step = self._cursor if step is None else step
        if step >= len(self._stage):
            return ""
        return str(self._stage[step]).replace("阶段 ", "")

    # ── 模块 (channel) 查询 ──
    def frame(self, step=None):
        """该步全模块 I/O dict (io_trace 帧; 无帧时回退最邻近旧帧)"""
        step = self._cursor if step is None else step
        if not self.frames:
            return {}
        i = min(step, len(self.frames) - 1)
        return self.frames[i][1]

    def module(self, name, step=None):
        """单模块该步 I/O: {"in": [...], "out": [...]} (无则 {})
        画布节点名可能带后缀 ([W-01]/序号) → 按 MODULE_ORDER 前缀匹配回退"""
        fr = self.frame(step)
        mo = fr.get(name)
        if not mo:
            for _k in MODULE_ORDER:
                if _k in str(name):
                    mo = fr.get(_k)
                    break
        return mo or {}

    def module_out_values(self, name, step=None):
        """该模块该步所有 out 数值 {label: value} (面板/3D 显示用)"""
        mo = self.module(name, step)
        return dict(mo.get("out", []))

    def active_module_summary(self, step=None, n=3):
        """当前步关键模块摘要文本 — 3D「画布信号」行 (与画布 log 同源)"""
        st = self.stage(step)
        try:
            sched = self.module_out_values("🧭 动作调制器", step)
            corr = self.module_out_values("🧪 状态校正器", step)
            phys = self.module_out_values("🌍 物理世界", step)
            rows = [f"阶段 {st}" if st else ""]
            for lbl, v in list(sched.items())[:2]:
                rows.append(f"{lbl}: {_fmt(v)}")
            for lbl, v in list(corr.items())[:2]:
                rows.append(f"{lbl}: {_fmt(v)}")
            for lbl, v in list(phys.items())[:2]:
                rows.append(f"{lbl}: {_fmt(v)}")
            return " · ".join([r for r in rows if r])
        except Exception:
            return f"阶段 {st}"

    def diff_modules(self, step):
        """哪些模块在本步有输出变化 (相邻帧 out 任一值不等) — Dreamview 'Module Delay'/活动感"""
        if step <= 0 or step >= len(self.frames):
            return []
        a, b = self.frames[step - 1][1], self.frames[step][1]
        changed = []
        for name in MODULE_ORDER:
            oa, ob = a.get(name, {}).get("out", []), b.get(name, {}).get("out", [])
            try:
                va = [float(x[1]) if hasattr(x[1], "__float__") else str(x[1]) for x in oa]
                vb = [float(x[1]) if hasattr(x[1], "__float__") else str(x[1]) for x in ob]
                if va != vb:
                    changed.append(name)
            except Exception:
                pass
        return changed


def _fmt(v):
    """数值 → 显示文本 (np 数组截断)"""
    import numpy as _np
    if isinstance(v, _np.ndarray):
        return "[" + " ".join(f"{x:+.3f}" for x in v.ravel()[:6]) + (" …]" if v.size > 6 else "]")
    try:
        f = float(v)
        return f"{f:+.3f}" if abs(f) < 1000 else f"{f:.3g}"
    except Exception:
        return str(v)[:40]


def world_from_trace(tr):
    """兼容入口: tr 无逐帧 io_trace (旧 episode) → None (消费方回退旧路径)"""
    if tr is None or not tr.get("io_trace"):
        return None
    return DataWorld(tr)


if __name__ == "__main__":
    # 自测: 引擎跑 30 步 → DataWorld 逐帧 + 模块查询 + 游标
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from state_space_sim import StateSpaceSim
    sim = StateSpaceSim(log=lambda *a: None)
    sim.t_end = 0.6          # 30 步
    tr = sim.run()
    dw = DataWorld(tr)
    assert dw.n_steps == len(tr["t"]) == len(tr["io_trace"]), "逐帧 io 必须每步一帧"
    for step in (0, len(tr["t"]) // 2, len(tr["t"]) - 1):
        f = dw.frame(step)
        assert "🧭 动作调制器" in f and "🌍 物理世界" in f
        assert dw.stage(step) == str(tr["stage"][step]).replace("阶段 ", "")
    dw.set_cursor(len(tr["t"]) // 2)
    assert dw.cursor == len(tr["t"]) // 2
    sched = dw.module_out_values("🧭 动作调制器")
    assert len(sched) >= 2
    print(f"自测 OK: {len(tr['t'])} 步 / {len(dw.frames)} 帧逐帧 · 14 模块可查 · "
          f"游标 {dw.cursor} · stage={dw.stage()} · 摘要: {dw.active_module_summary()[:60]}…")
