#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_corner_slots_mark.py — 四角光模块 + 14 槽位 的像素/mm 标注(几何模型 + 尺度定标)

口径(全部可复算, 不藏假设):
  · 基准     : 四个角光模块(白色本体+绿色卡扣)实测 AABB + 本体 minAreaRect
  · 尺度     : 光模块 40mm ↔ 本体(银色/白色条)像素长 → mm/px; 每个角各给一个(透视不同)
               槽位的 mm/px 用「以四角模块为基准的单应(摆正)坐标」双线性插值 → 不是全局常数
  · 槽位     : 治具中央两排矩形凹槽, 上排 7 + 下排 7 = 14 (与用户口径一致);
               上排 x 由暗区扫描实测 (204..233 / 265..293 / 324..354 / 387..414 / 450..478) 外推两点
               下排 x 由暗区扫描实测 (168..196 / 236..264 / 304..332 / 372..400 / 444..468) 外推两点
               (外推两端恰好被四角光模块盖住 → 与「模块摆在四个角」自洽)
  · 槽位框   : 实测凹槽开口 ≈ 40 px 宽 / 88 px 高(含近侧亮壁), 两排同一尺寸
红线: 只读图/算/画; 不碰机器人。低把握的一律标出来, 不补假框。

用法: python3 tools/l5_corner_slots_mark.py [--img path] [--outdir dir]
产出: <outdir>/slots_marks.json + arm_annotated.jpg + arm_annotated_big.jpg + log
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
OUTROOT = Path(os.path.expanduser("~/zmax_data/l5_corners"))

# ── 实测基准(原图 640x480 像素) ───────────────────────────────────────────────
MODULES = {                                    # 四角光模块: AABB(含绿色卡扣)
    "TL": {"aabb": [116, 58, 176, 190], "body_center": [152.6, 103.0], "body_L_px": 98.5, "body_W_px": 22.7},
    "TR": {"aabb": [506, 77, 549, 223], "body_center": [527.8, 129.0], "body_L_px": 104.6, "body_W_px": 25.9},
    "BL": {"aabb": [76, 200, 143, 373], "body_center": [116.3, 255.8], "body_L_px": 116.8, "body_W_px": 25.5},
    "BR": {"aabb": [512, 235, 566, 429], "body_center": [530.9, 296.7], "body_L_px": 124.6, "body_W_px": 28.8},
}
GREEN_BLOBS = {"TL": [116, 143, 47, 47], "TR": [506, 171, 43, 52],
               "BL": [76, 304, 52, 69], "BR": [512, 351, 54, 78]}
MODULE_MM = [40.0, 16.0, 12.0]                 # 光模块物理尺寸 (出处 ss_l2_autolearn.py 默认值)

# 治具整体框(黑塑料托盘外沿, 实测灰度<60 大连通域 0,35,629,398 与肉眼左/上/右边界合成)
FIXTURE_AABB = [18, 25, 575, 435]

# 14 槽位(像素): 上排 7 + 下排 7
ROW_A = {"name": "上排", "x": [162.5, 222.5, 283.0, 343.0, 404.5, 468.0, 531.5],
         "y": lambda x: 89.0, "w": 40.0, "h": 88.0,
         "src": "暗区实测 5 点(204-233/265-293/324-354/387-414/450-478) + 线性外推 2 端点 + 视觉复核右移 4px"}
ROW_B = {"name": "下排", "x": [127.0, 195.0, 263.0, 331.0, 399.0, 467.0, 535.0],
         "y": lambda x: 248.5 + 0.088 * (x - 263.0), "w": 40.0, "h": 88.0,
         "src": "暗区实测 5 点(168-196/236-264/304-332/372-400/444-468)+视觉复核右移 ~12px + 外推 2 端点"}

# 摆正用单应: 四角模块本体中心 → 700x284 矩形
_SRC = np.float32([MODULES["TL"]["body_center"], MODULES["TR"]["body_center"],
                   MODULES["BR"]["body_center"], MODULES["BL"]["body_center"]])
H_RECT = cv2.getPerspectiveTransform(_SRC, np.float32([[0, 0], [700, 0], [700, 284], [0, 284]]))
MMPX_MOD = {k: 40.0 / v["body_L_px"] for k, v in MODULES.items()}          # 40mm / 本体像素长


def mmpx_at(pt):
    """某像素点处的 mm/px —— 在摆正坐标里对四角模块的 mm/px 做双线性插值(→ 透视随位置变)"""
    p = cv2.perspectiveTransform(np.float32([pt]).reshape(-1, 1, 2), H_RECT).reshape(2)
    u = float(np.clip(p[0] / 700.0, 0, 1))
    v = float(np.clip(p[1] / 284.0, 0, 1))
    tl, tr = MMPX_MOD["TL"], MMPX_MOD["TR"]
    bl, br = MMPX_MOD["BL"], MMPX_MOD["BR"]
    top = tl * (1 - u) + tr * u
    bot = bl * (1 - u) + br * u
    return top * (1 - v) + bot * v


def build_slots():
    slots = []
    for i, x in enumerate(ROW_A["x"]):
        y = ROW_A["y"](x)
        slots.append({"id": "slot_%02d" % (i + 1), "row": ROW_A["name"], "row_idx": 0, "col": i + 1,
                      "cx": x, "cy": y, "w": ROW_A["w"], "h": ROW_A["h"],
                      "box": [x - ROW_A["w"] / 2, y - ROW_A["h"] / 2, x + ROW_A["w"] / 2, y + ROW_A["h"] / 2],
                      "covered_by": "TL" if i == 0 else ("TR" if i == 6 else None)})
    for i, x in enumerate(ROW_B["x"]):
        y = ROW_B["y"](x)
        slots.append({"id": "slot_%02d" % (i + 8), "row": ROW_B["name"], "row_idx": 1, "col": i + 1,
                      "cx": x, "cy": y, "w": ROW_B["w"], "h": ROW_B["h"],
                      "box": [x - ROW_B["w"] / 2, y - ROW_B["h"] / 2, x + ROW_B["w"] / 2, y + ROW_B["h"] / 2],
                      "covered_by": "BL" if i == 0 else ("BR" if i == 6 else None)})
    sl = []
    for s in slots:
        m = mmpx_at((s["cx"], s["cy"]))
        x0, y0, x1, y1 = s["box"]
        s["mm_per_px"] = round(m, 4)
        s["size_mm"] = [round((x1 - x0) * m, 1), round((y1 - y0) * m, 1)]
        cx_mm = (s["cx"] - MODULES["TL"]["body_center"][0]) * m
        cy_mm = (s["cy"] - MODULES["TL"]["body_center"][1]) * m
        s["center_mm_from_TL"] = [round(cx_mm, 1), round(cy_mm, 1)]
        sl.append(s)
    return sl


def draw(img, slots, title=""):
    out = img.copy()
    x0, y0, x1, y1 = FIXTURE_AABB
    cv2.rectangle(out, (x0, y0), (x1, y1), (255, 255, 0), 2)
    cv2.putText(out, "fixture", (x0 + 3, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
    for k, m in MODULES.items():
        a = m["aabb"]
        cv2.rectangle(out, (a[0], a[1]), (a[2], a[3]), (0, 0, 255), 2)
        g = GREEN_BLOBS[k]
        cv2.rectangle(out, (g[0], g[1]), (g[0] + g[2], g[1] + g[3]), (0, 255, 0), 1)
        cv2.putText(out, "MOD_%s %.2fmm/px" % (k, MMPX_MOD[k]), (a[0] - 10, a[1] + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1)
    for s in slots:
        b = [int(round(v)) for v in s["box"]]
        c = (0, 220, 255) if s["row_idx"] == 0 else (255, 0, 255)
        cv2.rectangle(out, (b[0], b[1]), (b[2], b[3]), c, 1)
        cv2.putText(out, s["id"].replace("slot_", "S"), (b[0], b[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.34, c, 1)
    if title:
        cv2.rectangle(out, (0, 450), (640, 480), (0, 0, 0), -1)
        cv2.putText(out, title, (4, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default=str(OUTROOT / "last_arm_raw.jpg"))
    ap.add_argument("--outdir", default="")
    a = ap.parse_args()
    img = cv2.imread(a.img)
    if img is None:
        print("✗ 读不到 %s" % a.img)
        return 2
    ts = time.strftime("%m%d_%H%M%S")
    outdir = Path(a.outdir) if a.outdir else (OUTROOT / ("marks_" + ts))
    outdir.mkdir(parents=True, exist_ok=True)
    slots = build_slots()
    title = "arm D405 %s | 4 corner modules(40mm ruler) + 14 slots | box px+mm" % time.strftime("%F %T")
    ann = draw(img, slots, title)
    cv2.imwrite(str(outdir / "arm_annotated.jpg"), ann)
    cv2.imwrite(str(outdir / "arm_annotated_big.jpg"),
                cv2.resize(ann, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC))
    rec = {
        "ts": time.strftime("%F %T"), "img": a.img, "wh": list(img.shape[:2][::-1]),
        "module_mm_spec": MODULE_MM, "fixture_aabb": FIXTURE_AABB,
        "modules": {k: {**v, "mm_per_px_from_40mm": round(MMPX_MOD[k], 4),
                        "mm_per_px_from_16mm_width": round(16.0 / v["body_W_px"], 4),
                        "green_blob": GREEN_BLOBS[k]} for k, v in MODULES.items()},
        "row_a_src": ROW_A["src"], "row_b_src": ROW_B["src"],
        "slots": slots,
        "mm_per_px_global_mean": round(float(np.mean(list(MMPX_MOD.values()))), 4),
        "mm_per_px_range": [round(min(MMPX_MOD.values()), 4), round(max(MMPX_MOD.values()), 4)],
        "caveat": ("尺度由「光模块 40mm ↔ 白色本体像素长」定标, 四角各一个值(透视差 %d%%); "
                   "另按「16mm ↔ 本体像素宽」互校会得到 ~0.6 mm/px ⇒ 本体实测宽只 ~9mm, "
                   "与标称 16mm 对不上, 故 40mm 口径下 mm 值不确定度约 ±20%%。"
                   "槽位两端(被模块盖住的两个)是外推值, 不确定度 ±12px ≈ ±4mm。"),
    }
    (outdir / "slots_marks.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print("outdir=%s" % outdir)
    print("mm/px per corner:", {k: round(v, 4) for k, v in MMPX_MOD.items()},
          "mean=%.4f" % np.mean(list(MMPX_MOD.values())))
    for s in slots:
        print("  %-8s %s col=%d px_box=%s  mm/px=%.3f  size_mm=%s  center_mm(TL原点)=%s%s" % (
            s["id"], s["row"], s["col"], [round(v, 1) for v in s["box"]], s["mm_per_px"],
            s["size_mm"], s["center_mm_from_TL"], "  [被%s盖住]" % s["covered_by"] if s["covered_by"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
