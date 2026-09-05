#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧑🔬 gen_viz_evidence.py — GUI 测试工程师自动取证 (2026-09-04 老倪)

真人测试工程师流程自动化: 打开环境(状态空间画布) → 跑引擎 → 按功能清单逐类
可视化验证 → 操作所有图表(直方图/归因/仿真波形/3D/操作视频窗口真实打开渲染) →
截图证据 + 内容断言 → 汇总 JSON。

用法 (gui-venv311, 需 X DISPLAY 供 3D GL 渲染):
  gui-venv311/bin/python tools/gen_viz_evidence.py
输出:
  reports/viz_evidence/viz_<kind>.png   每类窗口真实截图
  reports/viz_evidence/viz_results.json 逐项断言结果 (PASS/FAIL + 实测数值)
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
if not os.environ.get("DISPLAY"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"   # 无 X 回退离屏 (3D GL 会失败, 诚实记录)
OUT = os.path.join(ROOT, "reports", "viz_evidence")
os.makedirs(OUT, exist_ok=True)

from PyQt5.QtWidgets import QApplication
app = QApplication([])

RESULTS = []   # {case, desc, pass, evidence, detail}


def record(case, desc, ok, evidence="", detail=""):
    RESULTS.append({"case": case, "desc": desc, "pass": bool(ok),
                    "evidence": evidence, "detail": detail})
    print(f"  {'✅' if ok else '❌'} {case}: {desc} | {detail}")


def png_content_ratio(path):
    """非背景像素占比 (内容断言)"""
    from PIL import Image
    import numpy as np
    a = np.asarray(Image.open(path).convert("L"))
    return float((a > 40).mean())


def grab_save(widget, name):
    from PIL import Image
    widget.grab().save(os.path.join(OUT, name))
    return os.path.join(OUT, name)


def run_viz():
    """GUI 测试工程师自动取证 — 返回逐项结果 list (供报告集成调用; 内部建 QApplication)"""
    app = QApplication.instance() or QApplication([])
    return _main_inner()


def _main_inner():
    t0 = time.time()
    import simulink_module as sm
    m = sm.SimulinkModule()
    m.open_state_space()
    record("viz_env", "打开环境: 状态空间画布加载 (42 节点含🔭可视化层)", len(m.nodes) >= 40,
           detail=f"nodes={len(m.nodes)}")

    # ── 引擎真实跑一次 (StateSpaceSim + YOLO 真实采样一次) ──
    tr = None
    try:
        tr = m._ss_ensure_trace(force=True)
        record("viz_engine", "引擎仿真: 轨迹生成 (可视化数据源)",
               tr is not None and len(tr.get("t", [])) > 50,
               detail=f"轨迹 {len(tr.get('t', []))} 步")
    except Exception as e:
        record("viz_engine", "引擎仿真: 轨迹生成", False, detail=str(e)[:120])

    # 先开观察窗 → 逐帧喂真实激活 (150 帧, 与真人操作一致: 窗口开着看数据进来)
    m._open_viz_node("hist")
    m._open_viz_node("attrib")
    app.processEvents()
    w_hist = getattr(m, "_ff_hist_win", None)
    w_attr = getattr(m, "_ff_attr_win", None)

    # 多帧激活数据: 真实 obs 回放 (data/ss_insert_lerobot parquet, MLP 真实 forward)
    sim = getattr(m, "_ss_last_sim", None)
    acc = getattr(sim, "accel", None) if sim else None
    n_feed = 0
    if acc is not None:
        try:
            import numpy as np, pandas as pd
            import glob
            pf = sorted(glob.glob(os.path.join(ROOT, "data", "ss_insert_lerobot",
                                               "data", "chunk-*", "file-*.parquet")))
            if pf:
                S = np.stack(pd.read_parquet(pf[0])["observation.state"].values).astype(np.float32)
                d3 = np.linalg.norm(S[:, 36:39] - S[:, :3], axis=1)
                idx = np.argsort(d3)[:: max(1, len(d3) // 150)][:150]  # 远→近 150 帧
                for i in idx:
                    acc.forward(S[i])
                    if w_hist is not None:
                        w_hist.push(acc.probe)
                    if w_attr is not None:
                        w_attr.push(acc.probe)
                    n_feed += 1
            record("viz_feed", "激活采集: 真实 obs 150 帧回放 (MLP 真实前向)",
                   n_feed >= 100, detail=f"{n_feed} 帧")
        except Exception as e:
            record("viz_feed", "激活采集", False, detail=str(e)[:120])

    # ── ① 前馈激活直方图 ──
    try:
        w = w_hist
        ok = w is not None and any(len(b) > 10 for b in w.buf)
        ev = grab_save(w, "viz_hist.png") if w else ""
        ratio = png_content_ratio(ev) if ev else 0
        record("viz_hist", "🧠 直方图: 三层 512 激活分布窗口打开且有数据",
               ok and ratio > 0.002, ev,
               detail=f"buf={[len(b) for b in w.buf] if w else 0} 内容比={ratio:.3f}")
    except Exception as e:
        record("viz_hist", "🧠 直方图窗口", False, detail=str(e)[:120])

    # ── ② 归因分工 (堆叠 + PCA 散点) ──
    try:
        w = w_attr
        if w is not None and len(w.x3_buf) >= 10:
            w._project("pca")
            app.processEvents()
        pts = w.pts2d if w is not None else None
        ok = pts is not None and pts.shape == (512, 2)
        ev = grab_save(w, "viz_attrib.png") if w else ""
        ratio = png_content_ratio(ev) if ev else 0
        detail = (f"帧={len(w.x3_buf) if w else 0} PCA={pts.shape if pts is not None else None} "
                  f"内容比={ratio:.3f}") if w else "窗口未创建"
        record("viz_attrib", "🎯 归因: 堆叠图 + 512 单元 PCA 散点 (4 输出维分工)",
               ok and ratio > 0.002, ev, detail)
    except Exception as e:
        record("viz_attrib", "🎯 归因窗口", False, detail=str(e)[:120])

    # ── ③ 仿真波形 (Scope) ──
    try:
        trr = getattr(m, "_ss_tr", None) or tr
        from simulink_module import StateSpaceScopeDialog
        dlg = StateSpaceScopeDialog(trr)
        dlg.show()
        app.processEvents()
        ev = grab_save(dlg, "viz_scope.png")
        ratio = png_content_ratio(ev)
        record("viz_scope", "📊 仿真波形: 距离/前馈/残差/接触 曲线",
               len(trr.get("t", [])) > 50 and ratio > 0.005, ev,
               detail=f"轨迹 {len(trr.get('t', []))} 步 内容比={ratio:.3f}")
        dlg.close()
    except Exception as e:
        record("viz_scope", "📊 仿真波形窗口", False, detail=str(e)[:120])

    # ── ④ 3D 视图 ──
    try:
        m.open_ss_3d()
        for _ in range(30):
            app.processEvents()
            time.sleep(0.1)
            wins = [w for w in app.topLevelWidgets()
                    if w.__class__.__name__ in ("DreamView3D",)]
            if wins:
                break
        app.processEvents()
        if wins:
            ev = grab_save(wins[0], "viz_3d.png")
            ratio = png_content_ratio(ev)
            record("viz_3d", "🧭 3D 视图: 分层视图窗口渲染",
                   ratio > 0.005, ev, detail=f"内容比={ratio:.3f}")
        else:
            record("viz_3d", "🧭 3D 视图窗口", False, detail="窗口未出现")
    except Exception as e:
        record("viz_3d", "🧭 3D 视图", False, detail=str(e)[:150])

    # ── ⑤ 操作视频 ──
    try:
        m.play_mlp_rollout()
        for _ in range(20):
            app.processEvents()
            time.sleep(0.1)
            vw = [w for w in app.topLevelWidgets()
                  if w.__class__.__name__ in ("MLPRolloutDialog", "InferenceVideoDialog")]
            if vw:
                break
        if vw:
            ev = grab_save(vw[0], "viz_video.png")
            ratio = png_content_ratio(ev)
            record("viz_video", "🎥 操作视频: 播放窗口", ratio > 0.01, ev,
                   detail=f"内容比={ratio:.3f}")
        else:
            record("viz_video", "🎥 操作视频窗口", False, detail="播放窗口未出现")
    except Exception as e:
        record("viz_video", "🎥 操作视频", False, detail=str(e)[:120])

    # 汇总
    n_pass = sum(1 for r in RESULTS if r["pass"])
    print(f"\n══ 可视化验证: {n_pass}/{len(RESULTS)} PASS ({time.time()-t0:.0f}s) ══")
    json.dump(RESULTS, open(os.path.join(OUT, "viz_results.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"VIZ_JSON={os.path.join(OUT, 'viz_results.json')}")
    return list(RESULTS)


def main():
    """CLI 入口: 跑可视化取证, 退出码 = 是否全 PASS"""
    app = QApplication.instance() or QApplication([])
    res = _main_inner()
    return all(r["pass"] for r in res)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
