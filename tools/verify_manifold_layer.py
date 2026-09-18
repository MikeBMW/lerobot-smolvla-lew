#!/usr/bin/env python3
"""F17 用例: 接触/性能流形 (L4) — 误差分解与风险度量

对应功能: F17 "接触流形(风险) + 性能流形(度量)" (模块 manifold_layer)
真实接口: ContactManifold.decompose(hand, peg_head, target, v, stage) → r; .summarize(r)
         PerformanceManifold.evaluate(peg_head, stage) → r; .summarize(r)
判据: ① 两流形可实例化 ② 误差分解可算 ③ 对齐时优于偏离时 ④ 性能度量有限
"""
import os, sys
ROOT = "/home/ubuntu/lerobot-smolvla-lew"; sys.path.insert(0, f"{ROOT}/src"); os.chdir(ROOT)
import numpy as np
fails = []
def chk(n, ok, ex=""):
    print(f"  {'OK ' if ok else 'FAIL'} {n} {ex}")
    if not ok: fails.append(n)
try:
    from lerobot.manifold.manifold_layer import ContactManifold, PerformanceManifold
except Exception as e:
    print(f"  FAIL 导入 manifold_layer: {type(e).__name__}: {e}"); sys.exit(1)
hole = np.array([0.0, 0.0, 0.13], np.float32)
cm = ContactManifold(hole_pos=hole)
pm = PerformanceManifold(hole_pos=hole)
chk("① 两流形可实例化", cm is not None and pm is not None, f"| risk_th={getattr(cm,'risk_th','?')}")
def decomp(peg):
    """真实接口: decompose(hand, peg_head, target, v, stage) → dict(含 risk)"""
    peg = np.asarray(peg, np.float32)
    hand = peg + np.array([0.0, 0.0, 0.05], np.float32)
    return cm.decompose(hand, peg, hole, np.zeros(3, np.float32), "下降")


try:
    r_ok  = decomp(hole + np.array([0.0, 0.0, 0.015], np.float32))    # 正对孔轴
    r_bad = decomp(hole + np.array([0.08, 0.08, 0.015], np.float32))  # 横向大偏
    chk("② 误差分解可算", np.isfinite(r_ok["risk"]) and np.isfinite(r_ok["V"]),
        f"| risk_ok={r_ok['risk']:.4f} V_ok={r_ok['V']:.5f} state={r_ok['state']}")
    chk("③ 偏离 ≥ 对齐", r_bad["risk"] >= r_ok["risk"] - 1e-9,
        f"| risk ok={r_ok['risk']:.4f} ≤ bad={r_bad['risk']:.4f}")
except Exception as e:
    chk("接触流形行为", False, f"{type(e).__name__}: {e}")
try:
    rp = pm.evaluate(hole + np.array([0.0, 0.0, 0.015], np.float32), "插入")
    chk("④ 性能度量有限", np.isfinite(rp["Vp"]) and np.isfinite(rp["eta"]),
        f"| Vp={rp['Vp']:.5f} η={rp['eta']:.4f} d_ax={rp['d_axial']:.4f}")
except Exception as e:
    chk("④ 性能度量有限", False, f"{type(e).__name__}: {e}")
print("结论:", "✅ 通过" if not fails else f"❌ 有不通过项: {fails}")
sys.exit(0 if not fails else 1)
