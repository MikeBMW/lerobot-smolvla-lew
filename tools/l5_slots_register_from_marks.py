#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_slots_register_from_marks.py — 把「四角光模块+14槽位」的几何标注灌进 L5 槽位登记表 + 14 类 YOLO 数据集

来源: ~/zmax_data/l5_corners/marks_*/slots_marks.json (tools/l5_corner_slots_mark.py 的产物)
口径(红线, 逐条可查):
  · 登记表 models/l5_slots.json: 14 个槽位**全部**有记录; 被光模块盖住/外推的 4 个标 status=待确认,
    其余(暗区实测+视觉复核)也标 **待确认** —— 因为本批**没有 TCP 演示真值**(不许动机器人),
    位置来自「四角光模块 40mm 定标 + 治具几何推算」, 不是 status=已记录(=TCP 演示口径)。
  · 数据集 data/yolo_annot_l5slots: 14 类 = 14 槽位;**一张实帧同时打 14 个框**(而不是一张图复制 14 份
    各打一个框 —— 那会让同一张图带互相矛盾的标签); 多张实帧均取自**同一静止场景**(逐张与当前帧比
    mean|d| 阈值过滤, 不拿变过的帧冒充同名标注)。
  · 自动标注样本**只进 train**, val 只放实测帧并显式标注 val 样本数少。

用法: python3 tools/l5_slots_register_from_marks.py [--marks path] [--n-frames 8] [--max-mean-diff 6]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import cv2                                                              # noqa: E402
import numpy as np                                                      # noqa: E402

REG = REPO / "models" / "l5_slots.json"
DS_ROOT = REPO / "data" / "yolo_annot_l5slots"
WORK = Path.home() / "zmax_data" / "l5_corners"
FRAMES_DIRS = [Path.home() / "zmax_data" / "demo_20260928" / "frames", WORK]


def latest_marks() -> Path:
    c = sorted((Path.home() / "zmax_data" / "l5_corners").glob("marks_*/slots_marks.json"))
    if not c:
        raise SystemExit("✗ 先跑 tools/l5_corner_slots_mark.py")
    return c[-1]


def pick_frames(ref: np.ndarray, n: int, max_mean_diff: float) -> list:
    """挑同一静止场景的实帧: 与 ref 比 mean|d| ≤ 阈值, 按时间排序去 md5"""
    cands = []
    for d in FRAMES_DIRS:
        cands += glob.glob(str(d / "*arm*.jpg"))
    cands = sorted(set(cands), key=lambda p: os.path.getmtime(p), reverse=True)[:60]
    out, seen = [], set()
    for p in cands:
        im = cv2.imread(p)
        if im is None or im.shape != ref.shape:
            continue
        md = cv2.absdiff(im, ref).mean()
        if md > max_mean_diff:
            continue
        h = hash(Path(p).read_bytes())
        if h in seen:
            continue
        seen.add(h)
        out.append((p, round(md, 2)))
        if len(out) >= n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--marks", default="")
    ap.add_argument("--n-frames", type=int, default=8)
    ap.add_argument("--max-mean-diff", type=float, default=6.0)
    a = ap.parse_args()
    mp = Path(a.marks) if a.marks else latest_marks()
    m = json.loads(mp.read_text(encoding="utf-8"))
    ref = cv2.imread(m["img"])
    if ref is None:
        raise SystemExit("✗ 标注帧读不到: %s" % m["img"])
    H, W = ref.shape[:2]
    ts = time.strftime("%F %T")

    # ── ① 登记表 ─────────────────────────────────────────────────────────────
    reg = json.loads(REG.read_text(encoding="utf-8")) if REG.exists() else {}
    reg.setdefault("slots", {})
    reg["_note"] = ("L5 槽位登记表 — 位置来自四角光模块(40mm标尺)+治具几何推算 + 暗区实测 + 大模型/视觉复核; "
                    "**未做 TCP 演示**(不许动机器人) ⇒ 本批全部 status=待确认, 绝不写已记录充数")
    reg["n_slots"] = 14
    for s in m["slots"]:
        k = s["id"]
        old = reg["slots"].get(k) or {}
        low = bool(s.get("covered_by"))
        rec = dict(old)
        rec.update({
            "id": k, "idx": int(k.split("_")[1]),
            "status": "待确认",
            "status_reason": ("被 %s 光模块盖住 ⇒ 位置为外推, 像素不确定度 ±12px" % s["covered_by"]) if low
                             else "视觉几何推算(非 TCP 演示) ⇒ 未经演示确认; 像素不确定度 ±10px",
            "origin": "视觉: 四角光模块40mm定标 + 治具几何推算 + 暗区扫描 + 视觉复核 (无 TCP 演示)",
            "row": s["row"], "col": s["col"],
            "box_uv": [round(v, 1) for v in s["box"]],
            "center_uv": [round(s["cx"], 1), round(s["cy"], 1)],
            "size_px": [s["w"], s["h"]],
            "size_mm": s["size_mm"],
            "mm_per_px": s["mm_per_px"],
            "center_mm_from_TL_corner_module": s["center_mm_from_TL"],
            "occluded_by": s.get("covered_by"),
            "frames": {"arm": m["img"]},
            "recorded_at": old.get("recorded_at") or ts,
            "annotated_at": ts,
            "marks_file": str(mp),
            "tcp": None, "quat": None,
            "depth_online": False,
            "evidence": {"frame": m["img"], "frame_md5": __import__("hashlib").md5(Path(m["img"]).read_bytes()).hexdigest()[:12],
                         "ruler": "光模块40mm ↔ 白色本体像素长 (0.321~0.406 mm/px, 四角各一)"},
        })
        rec.setdefault("vlm", {"verdict": "待确认", "why": "本批几何标注, 未走 VLM 逐槽位复核通道"})
        reg["slots"][k] = rec
    for i in range(1, 15):
        reg["slots"].setdefault("slot_%02d" % i, {"id": "slot_%02d" % i, "idx": i, "status": "未演示",
                                                 "tcp": None, "quat": None, "box_uv": None, "frames": {}})
    reg["updated_at"] = ts
    reg["batch"] = {"marks": str(mp), "ts": ts, "n_slots": 14,
                    "status_hist": {"待确认": 14, "已记录": 0},
                    "note": "全部 14 个槽位为几何推算标注, 无 TCP 演示真值 ⇒ 一律待确认"}
    REG.parent.mkdir(parents=True, exist_ok=True)
    REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    n_conf = sum(1 for v in reg["slots"].values() if v.get("status") == "待确认")
    n_rec = sum(1 for v in reg["slots"].values() if v.get("status") == "已记录")
    print("① 登记表 %s: 14 槽位 · 待确认 %d · 已记录 %d (无 TCP 演示 ⇒ 不写已记录)" % (
        REG.relative_to(REPO), n_conf, n_rec))

    # ── ② 数据集 ────────────────────────────────────────────────────────────
    names = ["slot_%02d" % i for i in range(1, 15)]
    frames = pick_frames(ref, a.n_frames, a.max_mean_diff)
    if not frames:
        print("✗ 找不到与标注帧同场景的实帧 → 只登记、不建集")
        return 1
    sess = "l5slots_geom_%s" % time.strftime("%Y%m%d_%H%M%S")
    src = DS_ROOT / "sessions" / sess
    (src / "frames").mkdir(parents=True, exist_ok=True)
    (src / "labels").mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (p, md) in enumerate(frames):
        stem = "l5slots_%02d_%s" % (i + 1, Path(p).stem)
        shutil.copy2(p, src / "frames" / (stem + ".jpg"))
        lines = []
        for s in m["slots"]:
            cls = int(s["id"].split("_")[1]) - 1
            x1, y1, x2, y2 = s["box"]
            cx, cy = (x1 + x2) / 2.0 / W, (y1 + y2) / 2.0 / H
            bw, bh = (x2 - x1) / W, (y2 - y1) / H
            lines.append("%d %.6f %.6f %.6f %.6f" % (cls, cx, cy, bw, bh))
        (src / "labels" / (stem + ".txt")).write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows.append({"image": str(src / "frames" / (stem + ".jpg")), "n_boxes": len(lines), "mean_diff_vs_ref": md})
    import yolo_annot_dataset as yad                                       # noqa: E402
    yad.ensure_layout(str(DS_ROOT), names)
    try:
        yad._register_session(str(DS_ROOT), sess, "arm(D405)", W, H, "auto:l5_corner_geometry",
                              "L5 14 类槽位几何标注(四角光模块40mm定标); 同一静止场景多帧; 无人工把关")
    except Exception as e:                                                 # noqa: BLE001
        print("⚠️ 会话登记: %s: %s" % (type(e).__name__, e))
    try:
        build = yad.build_dataset(str(DS_ROOT), names) or {}
    except TypeError:
        build = yad.build_dataset(str(DS_ROOT)) or {}
    chk = yad.check_dataset(str(DS_ROOT)) or {}
    rep = {"ts": ts, "marks": str(mp), "session": sess, "classes": names,
           "n_images": len(rows), "n_boxes_total": sum(r["n_boxes"] for r in rows),
           "frames": rows, "build": build, "check": chk,
           "note": ("一张实帧同时打 14 个框(不是同图复制 14 份); 帧均与标注帧同场景(mean|d|≤%.1f); "
                    "样本量 %d 张 ⇒ 远低于收敛所需, 报告不据此宣称精度" % (a.max_mean_diff, len(rows)))}
    (WORK / "slots_dataset_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print("② 数据集 %s: %d 张实帧 × 14 框 = %d 框 · 类数 %d" % (
        DS_ROOT.relative_to(REPO), len(rows), rep["n_boxes_total"], len(names)))
    print("   build=%s" % json.dumps(build, ensure_ascii=False)[:200])
    print("   check=%s" % json.dumps(chk, ensure_ascii=False)[:260])
    print("   每帧与标注帧 mean|d|: %s" % [r["mean_diff_vs_ref"] for r in rows])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
