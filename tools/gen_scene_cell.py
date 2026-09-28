#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「仿真元素」(光模块 / 料盘插槽 / 插孔位置 …) 组装成 base 系 3D 场景, 并投到真机画面上。

老倪 (2026-09-28): 「你现在有三个相机, 还有深度信号 … 你的 L2 层也可以 YOLO 检测;
你来指导, 将仿真元素都叠加到这个场景中, 有光模块, 料盘的插槽, 插孔位置等」

设计口径 (避免"画上去好看但没数"):
  · 3D 真值只取**现场示教/实测**：
      光模块抓握位 & 孔口/插到底 ← ~/zmax_data/real_cell_geometry.json (2026-09-27 现场)
      料盘槽位 1/2            ← data/skills/l2_atomic/taught_points.json (老倪现场示教 slot1/slot2)
      标定板                  ← 手眼闭环实测 (objects3d.json, std=1.74mm)
  · 尺寸没有实测的一律标"标称值", 不假装量过 → 每个元素带 source/note, 真值带与页面都能看到。
  · 落盘 data/scene/objects3d.json (先备份) ⇒ 既有 🎯仿真投影 链路原样可用 (build_from_sim 读它)。
  · 投影用 tools/scene_overlay.py 的 base_to_px (手眼 TSAI + 实时 TCP + K 640×480)。

用法:
  python tools/gen_scene_cell.py           # 只算, 打印每个元素的 base 坐标 + 投影像素 + 是否在画面内
  python tools/gen_scene_cell.py --apply   # 写 objects3d.json + 生成 sim 规格 (merge_origin 不动别的来源)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import numpy as np                                                                   # noqa: E402
import scene_overlay as SO                                                            # noqa: E402

TAUGHT = REPO / "data" / "skills" / "l2_atomic" / "taught_points.json"
CELLGEO = Path.home() / "zmax_data" / "real_cell_geometry.json"
OBJ3D = REPO / "data" / "scene" / "objects3d.json"
DEPTH_NPY = Path("/home/ubuntu/zmax_ss_remote/zmax_scene/depth_raw.npy")
DEPTH_META = Path("/home/ubuntu/zmax_ss_remote/zmax_scene/depth_meta.json")


def _pos(rec):
    """示教点记录 → (x,y,z) 米"""
    if isinstance(rec, dict):
        p = rec.get("pos") or rec.get("position")
        if p:
            return [float(v) for v in p[:3]]
        if "x" in rec:
            return [float(rec["x"]), float(rec["y"]), float(rec["z"])]
    if isinstance(rec, (list, tuple)):
        return [float(v) for v in rec[:3]]
    return None


def load_truths():
    taught = json.loads(TAUGHT.read_text(encoding="utf-8"))
    pts = taught.get("points", taught)
    geo = json.loads(CELLGEO.read_text(encoding="utf-8")).get("points", {})
    return pts, geo


def build_elements(pts, geo):
    """→ [(name, center_m, size_mm, source, note)]  顺序即绘制顺序"""
    els = []

    def add(name, c, size, source, note):
        if c:
            els.append({"name": name, "center": [round(float(v), 5) for v in c],
                        "size": list(size), "source": source, "note": note})

    # ① 现场示教的两个槽位 (抓握点) —— 只标"槽位", 不替它宣称"里面有模块"(那是实测的事)
    for key, label in (("slot1", "示教·槽位1"), ("slot2", "示教·槽位2")):
        c = _pos(pts.get(key))
        add(label, c, [22, 18, 12],
            "现场示教 %s (taught_points.json, 抓取时 TCP)" % key,
            "槽口尺寸=标称; 用示教抓握点定位(槽口平面在抓握点下方, 未单独测)")
    # ③ 插孔位置: 孔口 + 插到底 (老倪现场指的两个位置)
    add("插孔·孔口", _pos(geo.get("hole")), [22, 22, 14],
        "现场示教 real_cell_geometry.hole (2026-09-27 16:09 真值)",
        "老倪现场: 臂正在孔边上未插入")
    add("插孔·插到底", _pos(geo.get("goal")), [22, 22, 14],
        "现场示教 real_cell_geometry.goal (16:13 真值)",
        "孔口→插到底 = %.1fmm ≈ 模块长 40mm ⇒ 与标称尺寸自洽" % (
            1000 * float(np.linalg.norm(np.array(_pos(geo["goal"])) - np.array(_pos(geo["hole"]))))))
    # ④ 标定板 (手眼闭环实测, 用于验证投影链)
    old = json.loads(OBJ3D.read_text(encoding="utf-8")).get("objects", []) if OBJ3D.exists() else []
    for o in old:
        if o.get("name") in ("标定板",) and o.get("center"):
            add(o["name"], o["center"], o.get("size", [136, 78, 3]),
                str(o.get("source", "手眼闭环实测")), "keep: 既有实测物体")
    return els


# ─────────────────────────────────────────────────────────────
# 状态空间 3D 视图 (tools/gui/ss_dreamview.py, 参考 dreamview) 的**元素清单** → 真机锚点实现
# 老倪 2026-09-28: 「你看 3D视图, 状态空间 3D 分层视图, 参考 dreamview 做的仿真环境,
#   这里就可以看到所有元素的边界框; 你要把这些边界框叠加到手臂相机上」
# 口径(为什么不直接投仿真坐标):
#   仿真世界(metaworld 几何) 与真机 base 之间**没有可信的相似变换** —— 三点刚体解残差
#   7.1/20.4/25.7mm (sim2base_anchor.json validated=false), 且同一件东西尺度差 5 倍
#   (仿真光模块长 0.20m, 真机 ~0.04m; 仿真孔口→终点 66mm, 真机 40.9mm)
#   ⇒ 照 3D 视图的**元素清单**逐件用真机可测/可查的锚点实现; 量不出的如实标"未测/无锚点"。
# ─────────────────────────────────────────────────────────────
DREAMVIEW = REPO / "tools" / "gui" / "ss_dreamview.py"
_SIM_CONSTS = ("_HOLE", "_HOLE_MOUTH", "_BOX_CENTER", "_BOX_SIZE", "_TABLE_CENTER",
               "_TABLE_SIZE", "_PEG_SIZE", "_PEG_CENTER_OFF", "_ARM_H_BASE", "_AOI_FOCUS")


def read_dreamview_consts():
    """AST 读 3D 视图场景常量 (同源取数; 不 import 该模块, 免拉起重型 Qt/GL)。np.array([...]) 取内层。"""
    import ast
    out = {}
    try:
        tree = ast.parse(DREAMVIEW.read_text(encoding="utf-8"))
    except Exception as e:
        return out, "读不到 %s: %s" % (DREAMVIEW.name, e)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name not in _SIM_CONSTS:
            continue
        v = node.value
        if isinstance(v, ast.Call) and getattr(v.func, "attr", "") == "array" and v.args:
            v = v.args[0]
        try:
            out[name] = ast.literal_eval(v)
        except Exception:
            pass
    return out, "同源常量 %d/%d (%s)" % (len(out), len(_SIM_CONSTS), DREAMVIEW.name)


def measure_table_plane(K, tcp7, X, pts, band_mm=15.0, span_m=0.5):
    """台面/料盘上表面 = 深度图里「示教槽位平面 ±band_mm 且在槽位附近 span」的像素范围 (数据驱动)。"""
    if not DEPTH_NPY.exists():
        return None, "无深度文件"
    meta = json.loads(DEPTH_META.read_text(encoding="utf-8")) if DEPTH_META.exists() else {}
    dep = np.load(str(DEPTH_NPY))
    scale = float(meta.get("depth_scale", 0.0001))
    H, W = dep.shape
    zs = [p for p in (_pos(pts.get(k)) for k in ("slot1", "slot2")) if p]
    if not zs:
        return None, "无示教槽位点"
    cx0 = float(np.mean([p[0] for p in zs]))
    cy0 = float(np.mean([p[1] for p in zs]))
    zref = float(np.mean([p[2] for p in zs]))
    R_x, t_x = X[:3, :3], X[:3, 3]
    R_g, t_g = SO.quat_to_R(tcp7[3:7]), np.array(tcp7[:3])
    sel = []
    for v in range(0, H, 4):
        for u in range(0, W, 4):
            zz = float(dep[v, u]) * scale
            if not (0.15 <= zz <= 1.0):
                continue
            p_cam = np.array([(u - K["cx"]) / K["fx"] * zz, (v - K["cy"]) / K["fy"] * zz, zz])
            pb = R_g @ (R_x @ p_cam + t_x) + t_g
            if abs(pb[2] - zref) <= band_mm / 1000.0 and np.hypot(pb[0] - cx0, pb[1] - cy0) <= span_m:
                sel.append((float(pb[0]), float(pb[1]), float(pb[2])))
    if len(sel) < 200:
        return None, "平面像素太少(%d)" % len(sel)
    A = np.array(sel)
    px = np.percentile(A[:, 0], [2, 98])
    py = np.percentile(A[:, 1], [2, 98])
    c = [float((px[0] + px[1]) / 2), float((py[0] + py[1]) / 2), float(np.median(A[:, 2]))]
    size = [round(float(px[1] - px[0]) * 1000, 1), round(float(py[1] - py[0]) * 1000, 1), 10.0]
    return ({"name": "台面·工作台面", "center": [round(v, 5) for v in c], "size": size,
             "source": "深度图: 示教槽位平面±%.0fmm 的像素范围(数据驱动)" % band_mm,
             "note": "台面上表面 z=%.1fmm(中位) · %d 像素(P2~P98 定范围) · z 离散 %.1fmm · 厚度=标称" % (
                 c[2] * 1000, len(sel), float(np.std(A[:, 2])) * 1000)},
            "选中 %d 像素 · z 中位 %.1fmm" % (len(sel), c[2] * 1000))


def build_view_elements(K, tcp7, X, pts):
    """3D 视图元素清单 → 真机锚点实现。→ (els, 对照表, note)"""
    sim, cnote = read_dreamview_consts()
    els, mapping = [], []

    tab, tnote = measure_table_plane(K, tcp7, X, pts)
    if tab:
        els.append(tab)
    mapping.append(("台面 _TABLE_SIZE=%s" % (tuple(sim.get("_TABLE_SIZE", ())) or "?",),
                    "台面·工作台面" if tab else "—(未画出)", tnote))

    tcp = np.array(tcp7[:3])
    els.append({"name": "末端·TCP", "center": [round(float(v), 5) for v in tcp], "size": [40, 40, 60],
                "source": "实时 TCP 真值 (tcp_pose 50Hz)",
                "note": "位置=真值; 外廓尺寸标称(夹爪未单独测)"})
    mapping.append(("腕/爪连杆(轨迹实时位姿)", "末端·TCP", "位置=TCP 真值 · 尺寸标称"))

    h = float(sim.get("_ARM_H_BASE", 0.317))
    els.append({"name": "臂底座", "center": [0.0, 0.0, round(h / 2, 5)],
                "size": [400, 400, round(h * 1000, 1)],
                "source": "base 原点(定义) + 视图肩高 %.3fm" % h,
                "note": "位置=base 原点(定义真值); 底座外廓尺寸标称"})
    mapping.append(("臂底座 _ARM_BASE+肩高 %.3fm" % h, "臂底座", "base 原点=定义真值"))

    mapping.append(("孔口 _HOLE_MOUTH=%s" % (sim.get("_HOLE_MOUTH"),), "插孔·孔口", "现场示教真值"))
    mapping.append(("插到底 _HOLE=%s" % (sim.get("_HOLE"),), "插孔·插到底", "现场示教真值"))
    mapping.append(("光模块 _PEG_SIZE=%s" % (sim.get("_PEG_SIZE"),), "光模块·实测1/2", "检测框+深度实测"))
    mapping.append(("带孔盒 _BOX_SIZE=%s" % (sim.get("_BOX_SIZE"),), "—(未画)",
                    "真机夹具外廓未测; 孔口/插到底已单独标"))
    mapping.append(("AOI 设备 _AOI_FOCUS=%s" % (sim.get("_AOI_FOCUS"),), "—(未画)",
                    "真机 AOI 工位不在本相机视场 · 无锚点"))
    return els, mapping, cnote


def measure_from_depth(els, K, tcp7, X):
    """深度实测: 画面里已检出的框 (det/vlm) → 中位深度 → base 3D, 作为"实测"元素附上"""
    if not DEPTH_NPY.exists():
        return None, "无深度文件"
    meta = json.loads(DEPTH_META.read_text(encoding="utf-8")) if DEPTH_META.exists() else {}
    dep = np.load(str(DEPTH_NPY))
    scale = float(meta.get("depth_scale", 0.0001))
    H, W = dep.shape
    spec = SO.load_spec()
    boxes = [b for b in (spec.get("cameras", {}).get("arm", {}).get("boxes") or []) if b.get("xyxy")
             and any(k in str(b.get("label", "")) for k in ("光模块", "peg", "module"))]
    out = []
    R_x, t_x = X[:3, :3], X[:3, 3]
    R_g, t_g = SO.quat_to_R(tcp7[3:7]), np.array(tcp7[:3])
    seen = []
    for b in boxes:
        x1, y1, x2, y2 = [int(round(float(v))) for v in b["xyxy"]]
        cx0, cx1 = max(0, x1), min(W, x2)
        cy0, cy1 = max(0, y1), min(H, y2)
        if cx1 - cx0 < 4 or cy1 - cy0 < 4:
            continue
        patch = dep[cy0:cy1, cx0:cx1]
        pv = patch[patch > 0]
        if pv.size < 20:
            continue
        z = float(np.median(pv)) * scale
        if not (0.15 <= z <= 1.00):                  # 工作距离外的不收
            continue
        u, v = (cx0 + cx1) / 2.0, (cy0 + cy1) / 2.0
        if any(np.hypot(u - su, v - sv) < 20 for su, sv in seen):   # det/vlm 同一物体去重
            continue
        seen.append((u, v))
        p_cam = np.array([(u - K["cx"]) / K["fx"] * z, (v - K["cy"]) / K["fy"] * z, z])
        p_base = R_g @ (R_x @ p_cam + t_x) + t_g
        out.append({"name": "光模块·实测%d" % (len(out) + 1),
                    "center": [round(float(q), 5) for q in p_base], "size": [40, 16, 12],
                    "source": "%s 框[%s] 框中位深度 × 手眼 × TCP 真值" % (b.get("origin"), b.get("label")),
                    "note": "深度 %.0fmm · %d 像素 · 框心(%.0f,%.0f) · 该框来源=%s" % (
                        z * 1000, pv.size, u, v, b.get("origin")),
                    "px": [round(u, 1), round(v, 1)],
                    "depth_mm": round(z * 1000, 1)})
    return out, ("深度 %dx%d 有效 %.1f%% · 元数据龄 %.2fs" % (
        W, H, float(meta.get("valid_pct", 0)), float(meta.get("src_stamp_age_s", -1))))


def measure_green_modules(els, K, tcp7, X, cam="arm"):
    """光模块定位: L5/YOLO 框当"眼睛" + 颜色(绿)掩膜 当"确认" + 深度 定 3D。

    为什么加这一步: 示教点 slot1/slot2 只是"两个被教过的槽位", 料盘是多槽的 ——
    本帧相机看到的模块未必在 slot1/slot2 上。用 L5 框锁候选区、绿色确认是光模块、
    深度给位置, 才能把**当前料盘上真实的光模块**量出来 (不靠猜, 也不靠画上去好看)。
    纯颜色分割会把绿色电路板也算进来(实测 22 个连通域), 所以必须有锚框约束。
    """
    try:
        import cv2
    except Exception as e:                                                          # noqa: BLE001
        return [], "无 cv2: %s" % e
    raw = SO.fetch_frame(cam)
    if not raw:
        return [], "取不到 %s 帧" % cam
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return [], "帧解码失败"
    spec = SO.load_spec()
    anchors = [b for b in (spec.get("cameras", {}).get(cam, {}).get("boxes") or [])
               if b.get("xyxy") and b.get("origin") in ("vlm", "det")
               and any(k in str(b.get("label", "")) for k in ("光模块", "peg", "module"))]
    if not anchors:
        return [], "没有 L5/YOLO 的光模块锚框(先跑 gen_overlay_from_vlm/det)"
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 实测: 该曝光下光模块是很暗的灰绿 (BGR≈(66,76,65) HSV≈(45,36,77)),
    # 严阈值(35,60,40)只覆盖 14~17% ⇒ 会漏。用宽阈, 靠"锚框 + 细长条"约束保精度。
    mask = cv2.inRange(hsv, (30, 20, 15), (100, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    if not DEPTH_NPY.exists():
        return [], "无深度文件"
    dep = np.load(str(DEPTH_NPY))
    meta = json.loads(DEPTH_META.read_text(encoding="utf-8")) if DEPTH_META.exists() else {}
    scale = float(meta.get("depth_scale", 0.0001))
    H, W = img.shape[:2]
    R_x, t_x = X[:3, :3], X[:3, 3]
    R_g, t_g = SO.quat_to_R(tcp7[3:7]), np.array(tcp7[:3])
    out = []
    seen_g = []
    for b in anchors:
        x1, y1, x2, y2 = [int(round(float(v))) for v in b["xyxy"]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(W, x2), min(H, y2)
        if x2 - x1 < 6 or y2 - y1 < 6:
            continue
        sub = mask[y1:y2, x1:x2]
        n, _lab, stats, cent = cv2.connectedComponentsWithStats(sub, 8)
        best = None
        for i in range(1, n):
            _x, _y, w, h, area = stats[i]
            if area < 80 or w < 6 or h < 3:
                continue
            ar = max(w, h) / max(1, min(w, h))
            if not (1.2 <= ar <= 6.0):          # 光模块是细长条
                continue
            if best is None or area > best[4]:
                best = (_x, _y, w, h, area)
        if best is None:
            continue
        _x, _y, w, h, area = best
        gx1, gy1 = x1 + _x, y1 + _y
        gx2, gy2 = gx1 + w, gy1 + h
        patch = dep[gy1:gy2, gx1:gx2]
        pv = patch[(patch > 0)]
        if pv.size < 30:
            continue
        z = float(np.median(pv)) * scale
        if not (0.20 <= z <= 0.80):             # 工作距离外 ⇒ 不是料盘上的模块
            continue
        cx, cy = gx1 + w / 2.0, gy1 + h / 2.0
        acx, acy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        if any(np.hypot(cx - su, cy - sv) < 20 for su, sv in seen_g):    # 同一模块去重
            continue
        seen_g.append((cx, cy))
        p_cam = np.array([(cx - K["cx"]) / K["fx"] * z, (cy - K["cy"]) / K["fy"] * z, z])
        p_base = R_g @ (R_x @ p_cam + t_x) + t_g
        out.append({"name": "光模块·实测%d" % (len(out) + 1),
                    "center": [round(float(q), 5) for q in p_base], "size": [40, 16, 12],
                    "source": "L5/YOLO 锚框[%s] + 颜色(绿)掩膜 + 深度中位 × 手眼 × TCP 真值" % b.get("label"),
                    "note": "绿掩膜 %dx%d(%d px) · 掩膜心比锚框心偏 %.1fpx · 深度 %.0fmm · 像素(%3.0f,%3.0f)" % (
                        w, h, area, float(np.hypot(cx - acx, cy - acy)), z * 1000, cx, cy),
                    "px": [round(cx, 1), round(cy, 1)], "depth_mm": round(z * 1000, 1)})
    out.sort(key=lambda o: (o["px"][1], o["px"][0]))
    return out, "锚框 %d 个 → 量到 %d 个光模块" % (len(anchors), len(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写 objects3d.json + 生成 sim 规格")
    ap.add_argument("--cam", default="arm")
    ap.add_argument("--report", action="store_true", help="写 reports/scene_cell_elements_<ts>.{json,md} (证据)")
    ap.add_argument("--green-refine", action="store_true",
                    help="用颜色(绿)掩膜精修光模块像素区。**默认关**: 2026-09-28 实测该曝光下"
                         "模块是很暗的灰绿(BGR≈(66,76,65)), 宽阈会把邻近绿块也圈进来 —— "
                         "实测把同一模块量成了两个、偏移 20.8px, 还漏掉第二个模块。"
                         "锚框(框中位深度)反而给出正确两点(292,184)/(420,181)。")
    a = ap.parse_args()

    he = SO.load_handeye()
    K = SO.load_intrinsics(640, 480)
    tcp7 = SO.read_tcp()
    if not he["ok"] or tcp7 is None:
        print("✗ 缺手眼(%s) 或 读不到 TCP(%s) — 无法投影" % (he["ok"], tcp7 is not None))
        return 1
    X = he["X"]

    pts, geo = load_truths()
    els = build_elements(pts, geo)
    measured, mnote = measure_from_depth(els, K, tcp7, X)
    print("══ 深度侧 (锚框→深度→base) ══ %s" % mnote)
    for m in measured:
        print("  %-14s base=(%7.1f,%7.1f,%7.1f)mm · 像素(%3.0f,%3.0f) · 深度 %.0fmm · %s" % (
            m["name"], m["center"][0] * 1000, m["center"][1] * 1000, m["center"][2] * 1000,
            m["px"][0], m["px"][1], m["depth_mm"], m["source"]))

    greens, gnote = measure_green_modules(els, K, tcp7, X, cam=a.cam)
    print("══ 颜色(绿)精修 ══ %s" % gnote)
    for g in greens:
        print("  %-14s base=(%7.1f,%7.1f,%7.1f)mm · 像素(%3.0f,%3.0f) · 深度 %.0fmm · %s" % (
            g["name"], g["center"][0] * 1000, g["center"][1] * 1000, g["center"][2] * 1000,
            g["px"][0], g["px"][1], g["depth_mm"], g["note"]))
    mods = greens if (a.green_refine and greens) else measured   # 见 --green-refine 说明
    if mods:
        slots = [{"name": m["name"].replace("光模块·实测", "料盘插槽·实测"),
                  "center": m["center"], "size": [22, 18, 12],
                  "source": m["source"] + " (槽位=该模块所在槽, 同 XY)",
                  "note": "槽口在模块下方(未单独测) · " + m.get("note", "")} for m in mods]
        els = els + mods + slots

    # ── 状态空间 3D 视图元素清单 → 真机锚点 (台面/末端/TCP/底座) ──
    view_els, view_map, vnote = build_view_elements(K, tcp7, X, pts)
    print("══ 3D 视图元素清单 → 真机锚点 ══ %s" % vnote)
    for src, dst, how in view_map:
        print("   %-42s → %-14s %s" % (src[:42], dst, how[:60]))
    els = els + view_els

    print("══ TCP 真值 ══ (%.4f, %.4f, %.4f) quat=(%.3f,%.3f,%.3f,%.3f)" % tuple(tcp7))
    print("══ 手眼 %s · 闭环 std=%.2fmm · X_t=%.1f,%.1f,%.1f mm" % (
        he.get("method"), float(he.get("closed_loop_std_mm", -1)), *(np.array(he["X"][:3, 3]) * 1000)))
    print("══ 元素 → base 坐标 → 臂上相机像素 ══")
    img_w, img_h = 640, 480

    def _in_frame(bb):
        """框与画面有实质交集 (≥25% 面积在画面内) 才算"在画面内\""""
        if bb is None:
            return False, 0.0
        x1, y1, x2, y2 = [float(v) for v in bb]
        ix1, iy1 = max(0.0, x1), max(0.0, y1)
        ix2, iy2 = min(float(img_w), x2), min(float(img_h), y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        area = max(1e-6, (x2 - x1) * (y2 - y1))
        return (inter / area) >= 0.25, inter / area

    drawn, outside = [], []
    for e in els:
        px = SO.base_to_px(np.array([e["center"]]), K, X, tcp7)
        front = bool(np.isfinite(px).all())
        bb = SO.box3d_to_xyxy(e["center"], e["size"], K, X, tcp7, None) if front else None
        infr, frac = _in_frame(bb)
        if infr:
            drawn.append((e, bb))
        else:
            outside.append(e)
        print("  %-24s base=(%7.1f,%7.1f,%7.1f)mm  %s  %s" % (
            e["name"], e["center"][0] * 1000, e["center"][1] * 1000, e["center"][2] * 1000,
            ("px=(%6.1f,%6.1f)" % (px[0][0], px[0][1])) if front else "px=相机背后/离面",
            ("框 %-24s 画面内 %.0f%%" % ([int(v) for v in bb], frac * 100)) if bb is not None else "画面外"))
        print("      ↳ %s | %s" % (e["source"], e["note"]))
    print("  小结: 在画面内 %d 个 · 画面外 %d 个 %s" % (
        len(drawn), len(outside), [e["name"] for e in outside] or ""))

    # ── det 链 vs sim 链 收敛核对 (有 det 框时才做) ──
    spec0 = SO.load_spec()
    dets = [b for b in (spec0.get("cameras", {}).get(a.cam, {}).get("boxes") or [])
            if b.get("origin") in ("det", "vlm") and b.get("xyxy")]
    if dets and measured:
        b = [x for x in drawn if x[0]["name"].startswith("光模块")] or None
        if b:
            e, bb = b[0]
            d = dets[0]
            dc = ((bb[0] + bb[2]) / 2 - (float(d["xyxy"][0]) + float(d["xyxy"][2])) / 2,
                  (bb[1] + bb[3]) / 2 - (float(d["xyxy"][1]) + float(d["xyxy"][3])) / 2)
            print("  ⚖ 双链收敛: sim 框心 vs %s 框心 Δ=(%.1f, %.1f)px  |Δ|=%.1fpx" % (
                d.get("origin"), dc[0], dc[1], float(np.hypot(*dc))))

    # ── 校验 ① 往返一致性: 深度实测元素 base→像素, 应回到它自己的来源框 (det/vlm) ──
    print("══ 校验① 往返一致 (det 像素 → 深度 → base → 投回像素, 应回到原框) ══")
    det_by_origin = {}
    for b in (SO.load_spec().get("cameras", {}).get(a.cam, {}).get("boxes") or []):
        if b.get("xyxy") and b.get("origin") in ("det", "vlm"):
            det_by_origin.setdefault(b.get("origin"), []).append(b)
    rt = None
    if measured and det_by_origin.get("det"):
        e0, d0 = measured[0], det_by_origin["det"][0]
        px = SO.base_to_px(np.array([e0["center"]]), K, X, tcp7)
        dcx = (float(d0["xyxy"][0]) + float(d0["xyxy"][2])) / 2
        dcy = (float(d0["xyxy"][1]) + float(d0["xyxy"][3])) / 2
        rt = float(np.hypot(px[0][0] - dcx, px[0][1] - dcy))
        print("  深度实测点 base=(%.1f,%.1f,%.1f)mm → px=(%.1f,%.1f) · 来源 det 框心=(%.1f,%.1f) · 往返误差 %.1fpx" % (
            e0["center"][0] * 1000, e0["center"][1] * 1000, e0["center"][2] * 1000,
            px[0][0], px[0][1], dcx, dcy, rt))
        print("  (同深度口径下往返误差小 ⇒ 手眼/TCP/K 这条链自洽; 剩下的是深度量化与框中位取样的误差)")
    else:
        print("  (没有 det 框或没有深度实测点, 跳过)")

    # ── 校验② 凹陷检查: 槽位/插孔是"凹"的 ⇒ 投影框内深度应比四周深几 mm ──
    print("══ 校验② 凹陷检查 (槽位/插孔: 框内中位深度 vs 四周环带中位深度) ══")
    recess = []
    if DEPTH_NPY.exists():
        dep = np.load(str(DEPTH_NPY))
        meta = json.loads(DEPTH_META.read_text(encoding="utf-8")) if DEPTH_META.exists() else {}
        scale = float(meta.get("depth_scale", 0.0001))
        H, W = dep.shape
        for e, bb in drawn:
            if not any(k in e["name"] for k in ("槽", "插孔", "孔口")):
                continue
            x1, y1, x2, y2 = [int(round(float(v))) for v in bb]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(W, x2), min(H, y2)
            if x2 - x1 < 3 or y2 - y1 < 3:
                print("  %-14s 框太小, 跳过" % e["name"])
                continue
            inner = dep[y1:y2, x1:x2]
            iv = inner[inner > 0]
            pad = 8
            ox1, oy1 = max(0, x1 - pad), max(0, y1 - pad)
            ox2, oy2 = min(W, x2 + pad), min(H, y2 + pad)
            outer = dep[oy1:oy2, ox1:ox2].copy()
            outer[y1 - oy1:y2 - oy1, x1 - ox1:x2 - ox1] = 0      # 挖掉内框 ⇒ 只剩环带
            ov = outer[(outer > 0) & (outer < np.percentile(outer[outer > 0], 90) if (outer > 0).sum() else 0)]
            if iv.size < 20 or ov.size < 50:
                print("  %-14s 深度样本不足(内 %d 外 %d) — 该处可能被臂/夹爪遮挡或无回波" % (e["name"], iv.size, ov.size))
                continue
            di = float(np.median(iv)) * scale * 1000
            do = float(np.median(ov)) * scale * 1000
            recess.append({"name": e["name"], "in_mm": round(di, 1), "ring_mm": round(do, 1),
                           "delta_mm": round(di - do, 1)})
            print("  %-14s 框内 %.1fmm · 四周 %.1fmm · Δ=%+.1fmm %s" % (
                e["name"], di, do, di - do,
                "⇒ 凹(符合槽/孔)" if (di - do) > 2 else ("⇒ 平/凸(该处不是凹槽, 或投影没对上)" if (di - do) < 2 else "")))
    else:
        print("  (无深度文件)")

    if a.report:
        ts = time.strftime("%Y%m%d_%H%M%S")
        rep = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "cam": a.cam,
               "tcp": [round(float(v), 6) for v in tcp7],
               "handeye": {"method": he.get("method"), "std_mm": he.get("closed_loop_std_mm"),
                           "X_t_mm": [round(float(v), 1) for v in (np.array(he["X"][:3, 3]) * 1000)]},
               "elements": [{"name": e["name"], "center_mm": [round(float(v) * 1000, 1) for v in e["center"]],
                             "size_mm": e["size"], "source": e["source"], "note": e["note"],
                             "px": next(([round(float(px[0][0]), 1), round(float(px[0][1]), 1)] for px in
                                         [SO.base_to_px(np.array([e["center"]]), K, X, tcp7)]), None),
                             "in_frame": any(e is x[0] for x in drawn)}
                            for e in els],
               "verify": {"chain_roundtrip_px": None if rt is None else round(rt, 2), "recess": recess},
               "in_frame": len(drawn), "out_of_frame": [e["name"] for e in outside]}
        (REPO / "reports" / ("scene_cell_elements_%s.json" % ts)).write_text(
            json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        md = ["# 场景叠加元素清单 (仿真元素 → 真机 base 系 → 臂上相机像素)", "",
              "- 时间: %s · 相机: %s · 手眼: %s 闭环 std=%.2fmm · TCP: (%.4f, %.4f, %.4f)" % (
                  rep["at"], a.cam, he.get("method"), float(he.get("closed_loop_std_mm", -1)), *tcp7[:3]),
              "- 在画面内 %d 个 · 画面外 %s" % (len(drawn), ", ".join(rep["out_of_frame"]) or "无"),
              "- 校验① 链路自洽(px→深度→base→px 往返误差): %s px" % rep["verify"]["chain_roundtrip_px"],
              "", "| 元素 | base(mm) | 尺寸(mm) | 像素 | 画面内 | 来源 |", "|---|---|---|---|---|---|"]
        for e in rep["elements"]:
            md.append("| %s | (%.1f, %.1f, %.1f) | %s | %s | %s | %s |" % (
                e["name"], *e["center_mm"], "×".join(str(s) for s in e["size_mm"]),
                e["px"], "✓" if e["in_frame"] else "✗", e["source"]))
        md += ["", "## 校验② 凹陷检查 (槽位/插孔框内 vs 四周环带深度)", "",
               "| 元素 | 框内(mm) | 四周(mm) | Δ(mm) |", "|---|---|---|---|"]
        for r in recess:
            md.append("| %s | %.1f | %.1f | %+.1f |" % (r["name"], r["in_mm"], r["ring_mm"], r["delta_mm"]))
        md += ["", "> Δ>0 = 框内比四周深 ⇒ 投影框落在真实凹槽/孔口上; Δ≈0 或负 ⇒ 该处平/凸, 需复核。",
               "> 注: 四周环带可能含抬高结构(料盘边), 所以 Δ 只作\"是否落在凹陷处\"的辅助判据, 不作唯一结论。", ""]
        (REPO / "reports" / ("scene_cell_elements_%s.md" % ts)).write_text("\n".join(md), encoding="utf-8")
        print("  ✓ 报告: reports/scene_cell_elements_%s.{json,md}" % ts)

    if not a.apply:
        print("\n(未写盘; 加 --apply 落 objects3d.json 并生成 sim 规格)")
        return 0

    # ── 落盘 objects3d.json (备份后整体替换; 只保留 base 系 + 真值来源) ──
    if OBJ3D.exists():
        bak = OBJ3D.with_name("objects3d.json.bak_before_cell_%s" % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(OBJ3D, bak)
        print("  备份 → %s" % bak.name)
    doc = {"objects": [{"name": e["name"], "center": e["center"], "size": e["size"],
                        "coord": "base", "source": e["source"], "note": e["note"]}
                       for e in els],
           "coord": "base", "source": "gen_scene_cell.py (现场示教 + 深度实测)",
           "handeye": he.get("method"), "tcp": [round(float(v), 6) for v in tcp7],
           "at": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": time.time()}
    OBJ3D.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  ✓ 写 %s (%d 个元素)" % (OBJ3D, len(els)))

    boxes = [{"label": e["name"], "origin": "sim",
              "box3d": {"center": e["center"], "size": e["size"], "R": None},
              "conf": None, "note": "%s | %s" % (e["source"], e["note"])} for e in els]
    spec = SO.merge_origin(SO.load_spec(), a.cam, "sim", boxes,
                           meta={"tool": "gen_scene_cell.py", "at": doc["at"],
                                 "source": str(OBJ3D), "n": len(boxes)})
    spec["mode"] = spec.get("mode") or "sim-projection"
    SO.save_spec(spec)
    print("  ✓ spec: origin=sim %d 框 · mode=%s · 总框数=%d" % (
        len(boxes), spec.get("mode"),
        len(spec.get("cameras", {}).get(a.cam, {}).get("boxes") or [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
