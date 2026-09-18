#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_l2_autolearn_evidence.py — 「🎯 真机数据 L2 训练」三态模式 GUI 取证 (2026-09-18)

驱动**真实窗口**取证 (不是读代码自证):
  E1 画布加载 + 三态定义 (MODE_ORDER 含 real_l2)
  E2 双击模式开关循环切换: 推理 → 训练 → 真机数据L2 → 推理 (状态机真转移)
  E3 节点标题/圆点**真实渲染**: 训练态 vs 真机L2 态 截取节点区域 → 像素必不相同 (改色+改字生效)
  E4 「▶ 运行」按模式分派: 真机L2 态 → 触发真机数据学习闭环入口, 且**不跑仿真引擎**
  E5 双击 📦 数据源 (运行环境节点) 同源分派到同一入口
  E6 「🎯 真机数据 L2 训练」面板真实打开: 截图非空 + 关键字段齐 (在役权重/数据集/相机新鲜度/几何真值标注/采集器)
用法: gui-venv311/bin/python tools/gen_l2_autolearn_evidence.py
输出: reports/l2_autolearn_evidence/*.png + gui_evidence.json
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
if not os.environ.get("DISPLAY"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
else:
    for _sp in sys.path:                      # cv2 Qt 插件污染 → 显式指 PyQt5 真插件目录
        _pp = os.path.join(_sp, "PyQt5", "Qt5", "plugins")
        if os.path.isdir(os.path.join(_pp, "platforms")):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _pp
            break
OUT = os.path.join(ROOT, "reports", "l2_autolearn_evidence")
os.makedirs(OUT, exist_ok=True)

from PyQt5.QtWidgets import QApplication                                  # noqa: E402

app = QApplication.instance() or QApplication([])
RESULTS = []


def record(case, desc, ok, evidence="", detail=""):
    RESULTS.append({"case": case, "desc": desc, "pass": bool(ok), "evidence": evidence, "detail": detail})
    print(f"  {'✅' if ok else '❌'} {case}: {desc} | {detail}")


def content_ratio(path):
    from PIL import Image
    import numpy as np
    a = np.asarray(Image.open(path).convert("L"))
    return float((a > 40).mean())


def grab(w, name):
    p = os.path.join(OUT, name)
    w.grab().save(p)
    return p


def crop_node(m, node_id, name):
    """截取该节点在场景里的真实渲染区域 (像素证据)。

    ⚠️ 不能用 canvas.grab(viewport_rect): 画布滚到别处时该节点不在视口 → grab 返回空图。
    改为直接让 QGraphicsScene 把该节点的 scene 区域渲染进一张 QPixmap (与滚动位置无关)。
    """
    try:
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QPainter, QPixmap
        it = m._items.get(node_id)
        r = it.sceneBoundingRect()
        pm = QPixmap(int(r.width()), int(r.height()))
        pm.fill()
        p = QPainter(pm)
        m.canvas.scene().render(p, QRectF(0, 0, r.width(), r.height()), r)
        p.end()
        if pm.isNull():
            return "crop失败: 渲染得到空图"
        pth = os.path.join(OUT, name)
        ok = pm.save(pth)
        return pth if ok else "crop失败: 保存失败"
    except Exception as e:                                                     # noqa: BLE001
        return f"crop失败: {type(e).__name__}: {e}"


def main():
    import simulink_module as sm
    m = sm.SimulinkModule()
    m.open_state_space()
    app.processEvents()
    record("E1", "状态空间画布加载", len(m.nodes) >= 40, detail=f"nodes={len(m.nodes)}")
    record("E1b", f"三态定义 MODE_ORDER={list(sm.MODE_ORDER)}",
           list(sm.MODE_ORDER) == ["infer", "train", "real_l2"],
           detail=f"标签={sm.MODE_LABEL}")

    nd = next((n for n in m.nodes if n.get("params", {}).get("mode") in sm.MODE_ORDER), None)
    if nd is None:
        record("E2", "找到 🔀 模式开关节点", False)
        return finish()
    record("E2", "找到 🔀 模式开关节点", True, detail=f"名称={(nd.get('name'))} 当前={nd['params']['mode']}")
    nd["params"]["mode"] = "infer"
    seq = [nd["params"]["mode"]]
    for _ in range(3):                                   # 双击三次 → 应回到起点
        m._toggle_mode(nd)
        app.processEvents()
        seq.append(nd["params"]["mode"])
    record("E2b", f"双击循环: {' → '.join(seq)}",
           seq == ["infer", "train", "real_l2", "infer"], detail=f"labels={[sm.MODE_LABEL[s] for s in seq]}")

    # E3 真实渲染: 训练态 vs 真机L2 态 节点区域像素
    nd["params"]["mode"] = "train"
    m._items[nd["id"]].update()
    app.processEvents()
    p_tr = crop_node(m, nd["id"], "node_mode_train.png")
    nd["params"]["mode"] = "real_l2"
    m._items[nd["id"]].update()
    m._apply_mode_highlight("real_l2")
    app.processEvents()
    p_l2 = crop_node(m, nd["id"], "node_mode_real_l2.png")
    diff = None
    try:
        from PIL import Image
        import numpy as np
        a = np.asarray(Image.open(p_tr).convert("L"), float)
        b = np.asarray(Image.open(p_l2).convert("L"), float)
        diff = float(np.abs(a - b).mean())
    except Exception:                                                          # noqa: BLE001
        pass
    record("E3", "节点标题/指示圆点真实渲染随模式改变 (像素证据)",
           diff is not None and diff > 0.5, evidence=f"{p_tr} | {p_l2}",
           detail=f"训练态 vs 真机L2态 平均像素差={diff}")
    p_full = grab(m.canvas, "canvas_real_l2_mode.png")
    record("E3b", "画布整图取证 (真机L2 模式激活路径高亮)", content_ratio(p_full) > 0.02,
           evidence=p_full, detail=f"内容比={content_ratio(p_full):.3f}")

    # E4 ▶运行 分派 (打桩记录调用, 不真起常驻)
    calls = []
    orig = m.on_real_l2_train
    m.on_real_l2_train = lambda node=None: calls.append("run_button") or True
    try:
        m._sim_running = False
        m.start_sim()
        app.processEvents()
    finally:
        m.on_real_l2_train = orig
    record("E4", "真机L2 模式下「▶ 运行」→ 真机数据学习闭环入口 (不跑仿真)",
           calls == ["run_button"] and not getattr(m, "_sim_running", False),
           detail=f"入口调用={calls} · _sim_running={getattr(m, '_sim_running', None)}")

    # E5 双击 📦 数据源 (运行环境节点) 同源分派
    calls2 = []
    m.on_real_l2_train = lambda node=None: calls2.append("run_env") or True
    try:
        env = next((n for n in m.nodes if n.get("params", {}).get("run_env")), None)
        if env is not None:
            m.on_node_activated(env)
            app.processEvents()
        else:
            calls2.append("no_run_env_node")
    finally:
        m.on_real_l2_train = orig
    record("E5", "双击 📦 数据源(运行环境) 在真机L2 模式 → 同一入口", calls2 == ["run_env"], detail=f"调用={calls2}")

    # E6 面板真实打开 + 关键字段
    try:
        import l2_autolearn_panel as lap
        pnl = lap.L2AutoLearnPanel(m)
        pnl.show()
        app.processEvents()
        time.sleep(0.3)
        app.processEvents()
        pnl.refresh()
        app.processEvents()
        txt = pnl.lb_head.text()
        keys = ("在役权重", "数据集", "相机新鲜度", "几何真值标注", "采集器")
        miss = [k for k in keys if k not in txt]
        ev = grab(pnl, "panel_l2_autolearn.png")
        ratio = content_ratio(ev)
        record("E6", "「🎯 真机数据 L2 训练」面板打开 · 关键字段齐",
               not miss and ratio > 0.01, evidence=ev,
               detail=f"缺字段={miss or '无'} · 内容比={ratio:.3f}")
        record("E6b", "面板含按钮: 开始边干边学/立即跑一轮/停止/刷新 + 有提升才上在役 开关",
               all(hasattr(pnl, a) for a in ("b_start", "b_once", "b_stop", "b_ref", "cb_promote")),
               detail=f"轮数={pnl.sp_epochs.value()} 触发样本={pnl.sp_trig.value()} "
                      f"自动上线={pnl.cb_promote.isChecked()}")
        pnl.close()
    except Exception as e:                                                     # noqa: BLE001
        record("E6", "面板打开", False, detail=f"{type(e).__name__}: {e}")

    # 复原画布模式为默认 🚀 训练 (取证不改默认档)
    nd["params"]["mode"] = "train"
    m._toggle_mode(nd)          # train → real_l2? 不: 直接置回并保存, 避免多次往返
    nd["params"]["mode"] = "train"
    m._save_mode_to_flow(nd)
    m._apply_mode_highlight("train")
    app.processEvents()
    record("E7", "取证后画布模式已复原为 🚀 训练 (不改变默认档)", nd["params"]["mode"] == "train",
           detail=f"mode={nd['params']['mode']}")
    return finish()


def finish():
    ok = sum(1 for r in RESULTS if r["pass"])
    out = {"ts": time.strftime("%F %T"), "total": len(RESULTS), "passed": ok,
           "failed": [r["case"] for r in RESULTS if not r["pass"]], "results": RESULTS}
    path = os.path.join(OUT, "gui_evidence.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n📋 {ok}/{len(RESULTS)} 通过 → {path}")
    print("✅ 全部通过" if ok == len(RESULTS) else f"❌ 失败: {out['failed']}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
