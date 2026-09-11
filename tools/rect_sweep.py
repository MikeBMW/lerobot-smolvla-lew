# -*- coding: utf-8 -*-
"""📐 矩形截面候选扫描 (2026-09-11): 找"yaw 有区分度 且 不破坏插入"的截面尺寸

方法: 直接改 L4 场景 XML 的 peg geom size(a b 0.12) → 对每候选跑
  抓(真实摩擦抓+抬升, φ=0/90) 与 插(δ=0/90) → 判定 yaw 区分度与兼容性。
判据: (1) 插入 0° 必须成功 (不回退); (2) 且至少一个角度失败 (有区分度)。
用法: MUJOCO_GL=glfw gui-venv311/bin/python tools/rect_sweep.py
"""
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np  # noqa: E402
import gen_l4_demo_video as G  # noqa: E402

XML = G.L4_XML
CANDS = [(0.015, 0.015), (0.020, 0.008), (0.028, 0.008), (0.034, 0.010), (0.040, 0.010)]
BAK = XML + ".sweepbak"


def patch_peg_size(a, b):
    src = open(BAK, encoding="utf-8").read()
    if not re.search(r'<geom name="peg"[^>]*?size="[^"]+"', src):
        raise AssertionError("L4 XML 里找不到 peg geom size 行")
    out = re.sub(r'(<geom name="peg"[^>]*?)size="[^"]+"',
                 lambda mo: mo.group(1) + f'size="{a} {b} 0.12"', src, count=1)
    assert f'size="{a} {b} 0.12"' in out, "peg geom size 替换未生效"
    open(XML, "w", encoding="utf-8").write(out)
    return out


def grasp_test(seed, phi_deg):
    demo = G.L4Demo(seed=seed, record=False, mani_yaw=False)
    try:
        demo.stage_turntable90()
        pc = demo.peg_center()
        demo.env._grip_yaw = 0.0
        demo.servo(pc + np.array([0, 0, 0.15]), tol=0.006, max_steps=600)
        demo.ramp_yaw(np.radians(phi_deg), step_rad=0.06, hold=None, g=0.0, max_steps=400)
        demo.servo(pc + np.array([0, 0, 0.022]), tol=0.003, max_steps=400)
        demo._grab = False
        for _ in range(30):
            demo.step(np.array([0.0, 0.0, 0.0, 0.0]))
        for _ in range(80):
            demo.step(np.array([0.0, 0.0, 0.0, 1.0]))
        z0 = float(demo.peg_center()[2])
        demo.servo(pc + np.array([0, 0, 0.18]), tol=0.008, max_steps=500)
        dz = float(demo.peg_center()[2] - z0)
        return bool(dz > 0.08), round(dz * 1000, 1)
    finally:
        try:
            demo.env.close()
        except Exception:
            pass


def insert_test(seed, delta_deg):
    demo = G.L4Demo(seed=seed, record=False, mani_yaw=False)
    try:
        demo.stage_turntable90()
        demo.stage_adapt_grasp()
        demo.stage_yaw_back()
        demo.stage_grasp_std()
        _orig = demo.ramp_yaw

        def _patched(target, **kw):
            if str(getattr(demo, "_stage", "")).startswith("⑤"):
                target = target + np.radians(float(delta_deg))
            return _orig(target, **kw)

        demo.ramp_yaw = _patched
        ok = bool(demo.stage_insert())
        m = re.search(r"插入: 真物理推入深度 ([\d.]+)mm", "\n".join(demo.history))
        return ok, float(m.group(1)) if m else 0.0
    finally:
        try:
            demo.env.close()
        except Exception:
            pass


def main():
    if not os.path.exists(BAK):
        shutil.copy2(XML, BAK)
    rows, t0 = [], time.time()
    try:
        for a, b in CANDS:
            patch_peg_size(a, b)
            r = {"a": a, "b": b, "long_mm": 2 * a * 1000, "short_mm": 2 * b * 1000}
            r["grasp0"] = grasp_test(0, 0.0)
            r["grasp90"] = grasp_test(0, 90.0)
            r["ins0"] = insert_test(0, 0.0)
            r["ins90"] = insert_test(0, 90.0)
            rows.append(r)
            print(f"截面 {r['long_mm']:4.0f}×{r['short_mm']:3.0f}mm → "
                  f"抓0°={r['grasp0']} 抓90°={r['grasp90']} | "
                  f"插0°={r['ins0']} 插90°={r['ins90']}", flush=True)
    finally:
        shutil.copy2(BAK, XML)          # 恢复原 stock 尺寸 (不留副作用)
        os.remove(BAK)
        print("已恢复原始 peg 截面")
    print(f"用时 {time.time()-t0:.0f}s")
    keep = [r for r in rows if r["ins0"][0] and not (r["grasp0"][0] and r["grasp90"][0]
                                                     and r["ins90"][0])]
    print("既有区分度又不回退的候选:", json.dumps(keep, ensure_ascii=False) if keep else "无")
    out = os.path.join(G.REP, f"rect_sweep_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(" → JSON:", out)


if __name__ == "__main__":
    main()
