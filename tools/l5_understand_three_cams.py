#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
l5_understand_three_cams.py — L5 场景理解: **三路相机一起用**(口径完全沿用 gen_overlay_from_vlm.py)
════════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 「L5 场景理解: 用上所有相机图像 —— 三路都取帧, 按 gen_overlay_from_vlm.py 口径做场景理解,
                  自动标注写入 vlm 层; 禁止 2D 光模块框(光模块只用 3D 框表达); 无坐标的空条目一律不许写盘。」

本工具与 `tools/gen_overlay_from_vlm.py` **同源**: 直接 import 它的 `call_vlm` / `build_prompt` /
`parse_json`, 不另写一套提示词与解析 ⇒ 口径一致(提示词、坐标系、像素 clamp、最小框尺寸判定全一样)。

与它的区别(两处, 都是为了这次的口径):
  · 三路相机一次跑完(可并行), 结果按相机分档; 每路都留**取帧文件 + md5 + 帧时刻**(可追溯)
  · ① **拒绝 2D 光模块框**(label 命中 光模块/模块): 光模块只用 3D 框(meas/box3d)表达 ⇒ 只登记不写盘
    ② **无坐标条目一律不写盘**(bbox 缺失/退化/越界到不可用 ⇒ 丢弃并列在 rejected 里)

⚠️ 本工具**只出离线清单, 不写叠加层**(老倪正在重启状态空间工程, 重启会清掉叠加层 ⇒ 发布统一等重启完成后
   由 tools/publish_overlay_after_restart.py 一次做掉)。加 `--merge` 才写 vlm 层。

用法:
  ./gui-venv311/bin/python tools/l5_understand_three_cams.py                 # 三路并行, 只出清单
  ./gui-venv311/bin/python tools/l5_understand_three_cams.py --cams arm      # 单路
  ./gui-venv311/bin/python tools/l5_understand_three_cams.py --merge         # 额外写 vlm 层(重启完成后再用)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))
import scene_overlay as SO                                                        # noqa: E402
import gen_overlay_from_vlm as G                                                  # noqa: E402  (同源口径)

OUT_DIR = _REPO / "reports" / "l5"
FRAME_DIR = OUT_DIR / "three_cam_frames"
# 只允许 3D 表达的对象(用户的硬口径): 2D 框里的这些 label 一律不写盘
MODULE_KEYS = ("光模块", "模块", "module", "光器件")


def one_cam(cam: str, hint: str = "", negatives=None, keep=None, retry_empty: bool = True) -> dict:
    t0 = time.time()
    raw = SO.fetch_frame(cam)
    if not raw:
        return {"cam": cam, "ok": False, "err": "取不到实帧(端点 /snapshot/%s.jpg)" % cam}
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"cam": cam, "ok": False, "err": "帧解码失败"}
    H, W = img.shape[:2]
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    fp = FRAME_DIR / ("%s_%s.jpg" % (cam, time.strftime("%Y%m%d_%H%M%S")))
    fp.write_bytes(raw)
    md5 = hashlib.md5(raw).hexdigest()[:12]
    prompt = G.build_prompt(W, H, hint=hint, negatives=negatives, keep=keep)
    r = G.call_vlm(raw, W, H, prompt=prompt)
    retried = False
    if not r["txt"] and retry_empty:
        # 🔁 推理型模型额度吃满 ⇒ content 空(仓库既有坑): max_tokens 翻倍重试一次
        G.MAXTOK = max(20000, int(G.MAXTOK) * 2)
        print("     [%s] content 空(推理吃满) ⇒ max_tokens 提到 %d 重试" % (cam, G.MAXTOK))
        r = G.call_vlm(raw, W, H, prompt=prompt, timeout=420)
        retried = True
    txt = r["txt"] or r["reasoning"]
    if not r["txt"]:
        return {"cam": cam, "ok": False, "err": "大模型 content 为空(推理额度吃满) · %.0fs" % r["latency_s"],
                "frame": str(fp), "md5": md5, "w": W, "h": H}
    d = G.parse_json(txt)
    objs = d.get("objects") or []
    elements, rejected, filtered = [], [], []
    for o in objs:
        lab = str(o.get("label", "?") or "?")
        b = o.get("bbox")
        if not (isinstance(b, (list, tuple)) and len(b) == 4):
            rejected.append({"label": lab, "why": "无 bbox 坐标", "raw": o})
            continue                                    # ① 无坐标 ⇒ 一律不写盘
        x1, y1, x2, y2 = [float(v) for v in b]
        x1, x2 = sorted((max(0.0, min(W - 1, x1)), max(0.0, min(W - 1, x2))))
        y1, y2 = sorted((max(0.0, min(H - 1, y1)), max(0.0, min(H - 1, y2))))
        if x2 - x1 < 3 or y2 - y1 < 3:
            rejected.append({"label": lab, "why": "框退化(<3px)", "bbox": [x1, y1, x2, y2]})
            continue
        if any(k in lab for k in MODULE_KEYS):
            filtered.append({"label": lab, "why": "光模块禁止 2D 框(只用 3D 框表达)",
                             "bbox": [x1, y1, x2, y2]})
            continue                                    # ② 光模块不写 2D
        elements.append({"origin": "vlm", "label": lab, "xyxy": [x1, y1, x2, y2],
                         "conf": o.get("conf"), "why": o.get("why", ""), "cam": cam,
                         "frame_md5": md5})
    return {"cam": cam, "ok": True, "frame": str(fp), "md5": md5, "w": W, "h": H,
            "frame_bytes": len(raw), "elements": elements, "rejected": rejected,
            "filtered_2d_module": filtered, "n_objs": len(objs),
            "model": r.get("model"), "latency_s": round(r["latency_s"], 1), "usage": r.get("usage"),
            "scene": (d.get("scene") or "")[:400], "topology": (d.get("topology") or "")[:400],
            "elapsed_s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cams", default="arm,local,local2", help="逗号分隔; 路由名以 8791 页面为准")
    ap.add_argument("--hint", default="")
    ap.add_argument("--negatives", default="")
    ap.add_argument("--keep", default="")
    ap.add_argument("--merge", action="store_true", help="额外把 vlm 层写进叠加规格(重启完成后再用)")
    ap.add_argument("--maxtok", type=int, default=24000, help="推理型模型额度(仓库坑: 9000 会被 reasoning 吃光)")
    ap.add_argument("--merge-into", default="", help="把本次结果并入已有清单(补跑某几路时用)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    G.MAXTOK = max(2000, int(a.maxtok))
    cams = [c.strip() for c in a.cams.split(",") if c.strip()]
    neg = [s for s in (a.negatives or "").split(",") if s.strip()]
    keep = [s for s in (a.keep or "").split(",") if s.strip()]

    print("═" * 78)
    print("L5 场景理解 · 三路相机 (同源口径: tools/gen_overlay_from_vlm.py) · 模型 %s" % G.MODEL)
    print("═" * 78)
    results = {}
    with cf.ThreadPoolExecutor(max_workers=max(1, len(cams))) as ex:
        for r in ex.map(lambda c: one_cam(c, a.hint, neg, keep), cams):
            results[r["cam"]] = r
            if r.get("ok"):
                print("  [%s] %dx%d · %.0fKB · %d 目标 → 写盘 %d · 拒 %d(无坐标/退化) · 滤 %d(2D光模块) · %.0fs"
                      % (r["cam"], r["w"], r["h"], r["frame_bytes"] / 1024.0, r["n_objs"],
                         len(r["elements"]), len(r["rejected"]), len(r["filtered_2d_module"]),
                         r["latency_s"]))
                for e in r["elements"]:
                    print("      + %-16s %s conf=%s · %s" % (e["label"], [round(v) for v in e["xyxy"]],
                                                            e["conf"], (e["why"] or "")[:60]))
                for f in r["filtered_2d_module"]:
                    print("      ⊘ %-16s %s (光模块只用 3D 框)" % (f["label"], [round(v) for v in f["bbox"]]))
            else:
                print("  [%s] ✗ %s" % (r["cam"], r.get("err")))

    out = a.out or str(OUT_DIR / ("three_cam_vlm_%s.json" % time.strftime("%Y%m%d_%H%M%S")))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rep = {"kind": "L5 场景理解·三路相机(同源 gen_overlay_from_vlm 口径)",
           "created": time.strftime("%Y-%m-%d %H:%M:%S"), "model": G.MODEL,
           "tool": "tools/l5_understand_three_cams.py",
           "rules": ["无坐标条目一律不写盘", "光模块禁止 2D 框(只用 3D 框表达)", "每路留取帧文件+md5+时刻"],
           "cams": results,
           "n_total_written": sum(len(r.get("elements") or []) for r in results.values()),
           "merged_to_spec": False}
    if a.merge_into and os.path.isfile(a.merge_into):     # 补跑某几路 → 并进同一份清单
        old = json.loads(Path(a.merge_into).read_text(encoding="utf-8"))
        old.setdefault("cams", {}).update({k: v for k, v in results.items() if v.get("ok")})
        old["runs"] = (old.get("runs") or []) + [{"at": rep["created"], "cams": list(results),
                                                  "maxtok": G.MAXTOK}]
        old["n_total_written"] = sum(len(r.get("elements") or []) for r in old["cams"].values())
        rep, out = old, a.merge_into
    if a.merge:
        spec = SO.load_spec()
        for cam, r in results.items():
            if r.get("ok"):
                SO.merge_origin(spec, cam, "vlm", r["elements"],
                                meta={"model": r.get("model"), "latency_s": r.get("latency_s"),
                                      "n": len(r["elements"]), "at": time.strftime("%H:%M:%S"),
                                      "cam": cam, "src": "l5_understand_three_cams"})
        SO.save_spec(spec)
        rep["merged_to_spec"] = True
        print("\n  已写 vlm 层(三路合计 %d 项)" % rep["n_total_written"])
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print("\n清单: %s" % out)
    print("═" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
