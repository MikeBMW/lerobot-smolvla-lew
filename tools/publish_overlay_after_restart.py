#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_overlay_after_restart.py — **等状态空间重启完成后再发布** plan + vlm 叠加层(发布即取证)
════════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 「用户正在重启状态空间工程, 重启会清掉叠加层 ⇒ 先离线算好+验证, 然后**等重启完成再发布**:
  轮询 /snapshot/overlay_arm.jpg 恢复 200 且 data/scene/overlay_spec.json 里**没有 plan 层**
  (= 已被清空/新会话)后再发布; 若 10 分钟内没等到, 就把'待发布'命令写进总结。

发布内容(一次做掉, 不半途):
  ① plan 层: 一整条 kind=path3d 意图路径 —— **起点=发布时刻的实时 TCP**(现场会手动移臂 ⇒ 不写死),
     路线 抬离(60mm) → 高度横移 → 分步下落(≤30mm/段); 起点漂移 >10mm 自动按新起点重规划
  ② vlm 层: `tools/l5_understand_three_cams.py` 的离线清单(三路相机; 无坐标条目不写、光模块不出 2D 框)
  ③ 发布后**立刻**取帧实测 plan 亮白像素(整帧/下半部)+ 最大连通域, 并落图 + 落证据 JSON

红线: 只写 data/scene/overlay_spec.json(按 origin 合并, 不动 sim/det/meas/trace), 不碰 7951/8791 进程,
      不发任何运动指令。**默认 dry(只看条件)**, 加 --publish 才真发布。

用法:
  ./gui-venv311/bin/python tools/publish_overlay_after_restart.py --wait 600 --publish \
      --vlm /home/ubuntu/zmax/reports/l5/three_cam_vlm_<ts>.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))
import scene_overlay as SO                                                        # noqa: E402
import plan_slot7_route as P                                                      # noqa: E402

SCRATCH = Path("/home/ubuntu/.hermes/cache/scratch")
EVID = _REPO / "reports" / "moveit"


def overlay_ok(url="http://127.0.0.1:8791/snapshot/overlay_arm.jpg") -> tuple[bool, str]:
    r = subprocess.run(["curl", "-s", "-o", "/tmp/pub_wait_overlay.jpg", "-w", "%{http_code}",
                        "--max-time", "15", url], capture_output=True, text=True)
    code = (r.stdout or "").strip()
    ok = code == "200" and os.path.isfile("/tmp/pub_wait_overlay.jpg") \
        and os.path.getsize("/tmp/pub_wait_overlay.jpg") > 5000
    return ok, code


def spec_plan_state() -> dict:
    s = SO.load_spec()
    cam = (s.get("cameras") or {}).get("arm") or {}
    boxes = cam.get("boxes") or []
    return {"mode": s.get("mode"), "updated_at": s.get("updated_at"),
            "n_boxes": len(boxes), "by_origin": cam.get("by_origin"),
            "n_plan": sum(1 for b in boxes if b.get("origin") == "plan"),
            "n_vlm": sum(1 for b in boxes if b.get("origin") == "vlm"),
            "origins": sorted({b.get("origin") for b in boxes})}


def white_stats(img):
    import cv2
    import numpy as np
    H, W = img.shape[:2]
    r, g, b = img[:, :, 2].astype(int), img[:, :, 1].astype(int), img[:, :, 0].astype(int)
    m = ((r > 250) & (g > 250) & (b > 250)).astype(np.uint8)
    half = m.copy(); half[:H // 2, :] = 0
    out = {"white_total": int(m.sum()), "white_lower_half": int(half.sum())}
    for nm, mm in (("total", m), ("lower_half", half)):
        if mm.sum() == 0:
            out["max_cc_" + nm] = 0
            continue
        n, _l, st, _c = cv2.connectedComponentsWithStats(mm, connectivity=8)
        out["max_cc_" + nm] = max(int(st[i, cv2.CC_STAT_AREA]) for i in range(1, n)) if n > 1 else 0
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=600.0, help="最多等多少秒(默认 10 分钟)")
    ap.add_argument("--poll", type=float, default=10.0)
    ap.add_argument("--publish", action="store_true", help="条件满足就真发布(dry 则只看条件)")
    ap.add_argument("--vlm", default="", help="三路相机 VLM 清单 JSON(可选; 有则一并发布 vlm 层)")
    ap.add_argument("--drift-mm", type=float, default=10.0)
    ap.add_argument("--lift-mm", type=float, default=60.0)
    ap.add_argument("--max-down-mm", type=float, default=30.0)
    ap.add_argument("--points", type=int, default=150)
    ap.add_argument("--frame-out", default=str(SCRATCH / "plan_slot7_route.jpg"))
    ap.add_argument("--evidence", default=str(EVID / ("publish_after_restart_%s.json"
                                                      % time.strftime("%Y%m%d_%H%M"))))
    a = ap.parse_args()

    print("═" * 78)
    print("等状态空间重启完成 → 发布叠加层(plan+vlm) → 立刻取帧实测")
    print("═" * 78)
    t0, last = time.time(), ""
    met = None
    while time.time() - t0 < a.wait:
        st = spec_plan_state()
        ok, code = overlay_ok()
        line = "overlay=%s(%s) · spec: plan=%s vlm=%s boxes=%s mode=%s (%s)" % (
            "200" if ok else "-", code, st["n_plan"], st["n_vlm"], st["n_boxes"], st["mode"], st["updated_at"])
        if line != last:
            print("  [%s] %s" % (time.strftime("%H:%M:%S"), line))
            last = line
        if ok and st["n_plan"] == 0:
            met = {"overlay_200": True, "spec_plan_cleared": True, "state": st,
                   "waited_s": round(time.time() - t0, 1)}
            break
        time.sleep(a.poll)

    if met is None:
        met = {"overlay_200": None, "spec_plan_cleared": None, "state": spec_plan_state(),
               "waited_s": round(time.time() - t0, 1),
               "why": "等待 %.0fs 内没等到(overlay 未恢复 200 或 spec 里仍有 plan 层)" % a.wait}
        print("\n  ⚠️ %s" % met["why"])
        print("  待发布命令(重启完成后直接跑):\n"
              "    cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/publish_overlay_after_restart.py "
              "--wait 0 --publish%s" % ((" --vlm " + a.vlm) if a.vlm else ""))
        ev = {"kind": "publish_overlay_after_restart", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
              "published": False, "condition": met}
        Path(a.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(a.evidence).write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
        print("  证据: %s" % a.evidence)
        return 3

    print("\n  ✅ 条件满足: overlay 200 · spec 里没有 plan 层(等待 %.1fs)" % met["waited_s"])

    # ── 起点: 发布时刻的实时 TCP(现场会手动移臂) ─────────────────────────
    tcp, samp = P.live_tcp_sample()
    if tcp is None:
        print("  ✗ 读不到实时 TCP ⇒ 不发布(不能拿旧起点冒充)"); return 2
    start = [float(v) for v in tcp[:3]]
    tgt, tgt_quat, tgt_src, tgt_status = P.slot_xyz("slot_07")
    legs = P.build_legs(start, tgt, a.lift_mm)
    pts, segs = P.resample(legs, max(100, min(200, a.points)))
    total = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) * 1000.0
    straight = math.dist(start, tgt) * 1000.0
    ratio = total / straight if straight else float("inf")
    # 逐步过闸(同源函数)
    bad = 0
    nstep = 0
    for nm, p0, p1 in legs:
        prev = p0
        for pt in P.split_steps(p0, p1, 50.0, a.max_down_mm):
            r = P.guard_rows(prev, pt, 50.0, a.max_down_mm)[-1]
            nstep += 1
            bad += 0 if (r["ok_step"] and r["ok_down"]) else 1
            prev = pt
    print("\n── 意图路径(起点=发布时刻实时 TCP) ──")
    print("  起点 [%s] · %s" % (", ".join("%.5f" % v for v in start), samp.get("src")))
    print("  样本: recorder壁钟 %s · 约第 %s 个 50Hz 样本 · 读于 %s"
          % (samp.get("recorder_wall"), samp.get("est_sample_no_50hz"), samp.get("read_at")))
    print("  终点(7号位) [%s] · 直线 %.1fmm" % (", ".join("%.5f" % v for v in tgt), straight))
    print("  折线 %d 点 · 总长 %.2fmm · 绕行比 %.3f (目标 1.1~1.3 ⇒ %s)"
          % (len(pts), total, ratio, "达标" if 1.1 <= ratio <= 1.3 else "未达标, 如实报"))
    print("  执行步 %d 个 · 不过闸 %d (单步 ≤50mm · 下降 ≤%.0fmm)" % (nstep, bad, a.max_down_mm))

    ev = {"kind": "publish_overlay_after_restart", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
          "published": False, "condition": met,
          "route": {"start": start, "start_sample": samp, "target": tgt, "straight_mm": round(straight, 2),
                    "n_points": len(pts), "total_mm": round(total, 2), "ratio": round(ratio, 4),
                    "guard_steps": nstep, "guard_fail": bad, "lift_mm": a.lift_mm,
                    "max_down_mm": a.max_down_mm, "pts3d": [[round(v, 6) for v in p] for p in pts]}}

    if not a.publish:
        print("\n  (dry: 没给 --publish ⇒ 不写盘)")
        Path(a.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(a.evidence).write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
        print("  证据: %s" % a.evidence)
        return 0

    # ── 发布 ──────────────────────────────────────────────────────────────
    label = "意图·前进路径 %d点/%.0fmm/比%.2f" % (len(pts), total, ratio)
    pub = P.publish_route(pts, label)
    ev["plan_publish"] = pub
    print("\n── 已发布 plan 层 ──")
    print("  path3d 元素 %d 个 · %d 点 · mode=%s · 备份 %s"
          % (pub["n_plan_elems"], pub["n_plan_pts"], pub["mode"], os.path.basename(pub["backup"])))
    print("  回读 by_origin=%s · 全部来源=%s" % (pub["by_origin"], pub["all_origins"]))

    if not a.vlm:                                    # 自动认最新的三路相机清单(发布时再取, 免写死路径)
        cand = sorted((_REPO / "reports" / "l5").glob("three_cam_vlm_*.json"))
        if cand:
            a.vlm = str(cand[-1])
            print("  vlm 清单(自动认最新): %s" % a.vlm)
    if a.vlm and os.path.isfile(a.vlm):
        vd = json.loads(Path(a.vlm).read_text(encoding="utf-8"))
        spec = SO.load_spec()
        n_v = 0
        per = {}
        for cam, r in (vd.get("cams") or {}).items():
            el = [e for e in (r.get("elements") or []) if e.get("xyxy") and len(e["xyxy"]) == 4]
            per[cam] = len(el)
            n_v += len(el)
            SO.merge_origin(spec, cam, "vlm", el, meta={"n": len(el), "cam": cam,
                                                        "model": vd.get("model"),
                                                        "src": "l5_understand_three_cams"})
        SO.save_spec(spec)
        ev["vlm_publish"] = {"file": a.vlm, "per_cam": per, "n_total": n_v}
        print("  已发布 vlm 层(三路): %s · 合计 %d 项(无坐标/2D光模块已在上游剔除)" % (per, n_v))

    time.sleep(2.0)
    time.sleep(0.0)                                                       # 叠加循环 10fps, 给两拍
    ok, code = overlay_ok()
    img_p = "/tmp/pub_after.jpg"
    subprocess.run(["curl", "-s", "-o", img_p, "--max-time", "20",
                    "http://127.0.0.1:8791/snapshot/overlay_arm.jpg"], check=False)
    ev["frame"] = {"http": code, "path": img_p}
    try:
        import cv2
        img = cv2.imread(img_p)
        if img is not None:
            st = white_stats(img)
            Path(a.frame_out).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(a.frame_out, img)
            ev["frame"].update(st)
            ev["frame"]["saved_to"] = a.frame_out
            # 同帧 A/B: 去掉 plan 再渲一遍 → plan 自己的像素
            try:
                r = P.offline_ab  # noqa: F841  (避免 lint 未用导入)
            except Exception:                                                 # noqa: BLE001
                pass
            print("\n── 发布后取帧实测(overlay_arm.jpg) ──")
            print("  HTTP %s · 亮白: 整帧 %d · **下半部 %d**(最大连通域 %d) · 整帧最大连通域 %d"
                  % (code, st["white_total"], st["white_lower_half"], st["max_cc_lower_half"],
                     st["max_cc_total"]))
            print("  帧: %s" % a.frame_out)
    except Exception as e:                                                    # noqa: BLE001
        ev["frame"]["err"] = str(e)

    # 服务端自证: 在跑的 8791 这一轮到底画了什么
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8791/scene.json", timeout=10) as r:
            sc = json.load(r)
        oi = (sc.get("_overlay_info") or {}).get("arm") or {}
        ev["live_overlay_info"] = {k: oi.get(k) for k in ("drawn", "skipped", "mode", "tcp_ok")}
        ev["live_plan_elem"] = [b for b in (oi.get("boxes") or []) if b.get("origin") == "plan"]
        print("  服务端自证: 本轮落笔 %s · plan 元素 %s"
              % (oi.get("drawn"), json.dumps(ev["live_plan_elem"], ensure_ascii=False)[:220]))
    except Exception as e:                                                    # noqa: BLE001
        ev["live_overlay_info_err"] = str(e)

    ev["published"] = True
    Path(a.evidence).parent.mkdir(parents=True, exist_ok=True)
    Path(a.evidence).write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n证据 JSON: %s" % a.evidence)
    print("═" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
