#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_slot7_route.py — 观察位 → 7号位 的**优化航路**(只规划 · 不下发 · 可复算)
════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 手工拖动示教(到 7 号位)的路径绕行比 **3.81**(1123.2mm / 直线 294.4mm),
那是人手拖动的不最优路径 ⇒ 重新规划成"人做得到、控制器也执行得了"的三段航路。

路线(不靠减少安全余量换长度):
  ① 抬离     : 在当前 x,y 竖直上抬 LIFT_MM(默认 60mm) —— 先离开原位/夹具
  ② 高度横移 : **在抬离后的高度上**横移到目标正上方(x,y 到位, z 不变)
  ③ 分步下落 : 竖直分步下落到位, **每步下降 ≤ MAX_DOWN_MM**(默认 30mm, 守卫按*段*判)

与 `tools/live_plan_segment.py` **同源**:
  · 起点 = 真机 TCP 真值(只读); 分段/守卫判定**直接调用** `live_plan_segment.segment()`
    (同一函数、同一口径 —— 单步 ≤50mm、向下 ≤30mm/段), 不另造一套判据。
  · 叠加发布沿用 `scene_overlay.merge_origin(spec, "arm", "plan", [一个 kind=path3d 元素])`
    ⇒ 画的是一整条路线(管道), 只重写 plan 这一层, 不冲掉 sim/det/vlm/meas/trace。

⚠️ 本工具**只写规划与叠加层**: 从不写 ~/zmax_data/l2_cmd.fifo, 不调任何运动服务。

用法:
  # 只算不发布(默认): 打印逐段守卫结论 + 总长/绕行比
  ./gui-venv311/bin/python tools/plan_slot7_route.py

  # 发布到 plan 层(整条路线画成管道路径) + 取帧统计亮白像素
  ./gui-venv311/bin/python tools/plan_slot7_route.py --publish --snapshot

  # 换参数/换目标
  ./gui-venv311/bin/python tools/plan_slot7_route.py --lift-mm 60 --max-down-mm 30 --points 150
  ./gui-venv311/bin/python tools/plan_slot7_route.py --to-xyz 0.64648 0.20246 0.10958
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
import scene_overlay as SO                                                        # noqa: E402
import live_plan_segment as LPS                                                   # noqa: E402  (同源守卫/分段)

# ── 口径常量 ────────────────────────────────────────────────────────────────
# 观察位(真机真值): = 手工示教轨迹的**起点** reports/taught/slot7_drag_20260929.json 的 p_start
OBSERVE = [0.46268, 0.19809, 0.33952]
OBSERVE_SRC = ("reports/taught/slot7_drag_20260929.json 的 p_start "
               "(50Hz 真机采样, 2026-09-29 手工拖动示教起点)")
SLOTS = os.path.join(_REPO, "models", "l5_slots.json")
DRAG = os.path.join(_REPO, "reports", "taught", "slot7_drag_20260929.json")
SPEC = SO.SPEC_PATH
CAM = "arm"
# 守卫口径(与 live_plan_segment 一致; 见 --max-step-mm/--max-down-mm)
MAX_STEP_MM = 50.0          # 单步直线 ≤50mm (arm_control/l2_daemon 同口径)
MAX_DOWN_MM = 30.0          # 单段下降 ≤30mm (L2.slot7 阶段2 守卫 = 40mm; 这里按更严的 30 设计)
FRAME_OUT = "/home/ubuntu/.hermes/cache/scratch/plan_slot7_route.jpg"


# ══════════════════════ 工具 ══════════════════════
def slot_xyz(slot_id="slot_07"):
    d = json.load(open(SLOTS, encoding="utf-8"))
    s = (d.get("slots") or {}).get(slot_id)
    if not s or not s.get("tcp"):
        raise SystemExit("❌ %s 里没有 %s 的 TCP" % (SLOTS, slot_id))
    return list(s["tcp"]), list(s.get("quat") or []), s.get("origin", ""), s.get("status", "")


def drag_stats():
    """手工拖动轨迹的真实绕行比(原始 50Hz 与空间抽稀两口径都算, 不许只挑对自己有利的那个)。"""
    if not os.path.isfile(DRAG):
        return None
    d = json.load(open(DRAG, encoding="utf-8"))
    w = d.get("waypoints") or []
    if len(w) < 2:
        return None
    straight = math.dist(w[0], w[-1]) * 1000.0
    dec = sum(math.dist(w[i], w[i + 1]) for i in range(len(w) - 1)) * 1000.0
    return {"file": os.path.relpath(DRAG, _REPO), "n_raw": d.get("n"), "n_wp": len(w),
            "path_raw_mm": float(d.get("path_len_mm", 0.0)), "straight_mm": straight,
            "ratio_raw": float(d.get("path_len_mm", 0.0)) / straight if straight else None,
            "path_decimated_mm": dec, "ratio_decimated": dec / straight if straight else None,
            "max_step_mm": d.get("max_step_mm"), "net_rot_deg": d.get("net_rot_deg")}


def guard_rows(a, b, max_step, max_down):
    """**调用同源函数** live_plan_segment.segment() 做逐段守卫判定(单步 ≤max_step, 向下 ≤max_down)。"""
    rows, _dist = LPS.segment(a, b, max_step, max_down)
    return rows


def build_legs(s, t, lift_mm):
    """三段航路(几何): 抬离 → 高度横移 → 分步下落。返回 [(段名, 起点, 终点)]"""
    up = [s[0], s[1], s[2] + lift_mm / 1000.0]
    return [("P1_抬离", list(s), up),
            ("P2_高度横移", list(up), [t[0], t[1], up[2]]),
            ("P3_分步下落", [t[0], t[1], up[2]], list(t))]


def split_steps(a, b, max_step_mm, max_down_mm):
    """把一条直段切成**执行步**: 每步同时满足 ①直线 ≤max_step ②**下降量** ≤max_down。

    注意: `live_plan_segment.segment()` 只按**直线长度**切(竖直下降段会切出 48mm/步 ⇒ 下降守卫必被拒),
    所以规划侧必须先按"下降占比"把步长收口; 判据仍由同源函数给(见 guard_rows)。
    这是技能里那条铁律: **下降守卫按*段*判, 不是按"一腿"判** —— 超了就插中继点。
    """
    L = math.dist(a, b)
    if L < 1e-12:
        return []
    down_frac = max(0.0, -(b[2] - a[2]) / L)              # 该踏的"下降占比"
    lim = max_step_mm
    if down_frac > 1e-9:
        lim = min(lim, max_down_mm / down_frac)
    n = max(1, int(math.ceil(L / (lim / 1000.0) - 1e-9)))
    return [[a[i] + (b[i] - a[i]) * ((k + 1) / float(n)) for i in range(3)] for k in range(n)]


def resample(legs, n_points):
    """把三段按长度比例重采样成 n_points 个点(段边界必留), 供渲染/落库; 起点=观察位, 终点=7号位。"""
    lens = [math.dist(a, b) for _nm, a, b in legs]
    tot = sum(lens) or 1.0
    pts, segs = [], []
    for (nm, a, b), L in zip(legs, lens):
        frac = L / tot
        n_sub = max(1, int(round((n_points - 1) * frac)))
        for k in range(1, n_sub + 1):
            f = k / float(n_sub)
            pts.append([a[i] + (b[i] - a[i]) * f for i in range(3)])
            segs.append(nm)
    pts.insert(0, list(legs[0][1]))
    segs.insert(0, legs[0][0])
    return pts, segs


def project_check(pts, tcp7, cam_w=640, cam_h=480):
    """投影预检(只读): 这条路线在手眼+真机 TCP 下有多少点落在画面里。"""
    he = SO.load_handeye()
    if not he["ok"] or tcp7 is None:
        return {"ok": False, "why": "无手眼/TCP"}
    K = SO.load_intrinsics(cam_w, cam_h)
    P = SO.base_to_cam(pts, he["X"], tcp7)
    zc = P[:, 2]
    uv = SO.cam_to_px(P, K)
    fin = (zc > 0.12) & (uv[:, 0] > -1.5 * cam_w) & (uv[:, 0] < 2.5 * cam_w) & \
          (uv[:, 1] > -1.5 * cam_h) & (uv[:, 1] < 2.5 * cam_h)
    inb = fin & (uv[:, 0] >= 0) & (uv[:, 0] < cam_w) & (uv[:, 1] >= 0) & (uv[:, 1] < cam_h)
    lower = inb & (uv[:, 1] >= cam_h / 2.0)
    return {"ok": True, "n": len(pts), "n_usable": int(fin.sum()), "n_in_frame": int(inb.sum()),
            "n_in_lower_half": int(lower.sum()),
            "zc_m": [round(float(zc.min()), 3), round(float(zc.max()), 3)],
            "uv_first": [round(float(uv[0, 0]), 1), round(float(uv[0, 1]), 1)],
            "uv_last": [round(float(uv[-1, 0]), 1), round(float(uv[-1, 1]), 1)]}


def live_tcp_sample():
    """**起点必须用实时 TCP**(老倪 2026-09-29: 现场在手动移臂 ⇒ 写死观察位会锚错)。
    返回 (tcp7, 采样信息)。采样信息含: 来源 / 样本号 / 时刻 —— 供计划 JSON 追溯。
    """
    tcp, js, src = LPS.now_tcp()                       # 同源只读: 50Hz recorder 的 head(或 docker cp 一份)
    sdk = "/home/ubuntu/zmax_data/rokae_sdk/tcp_out/latest.json"
    sdk_ts, sdk_t = None, None
    try:
        d = json.load(open(sdk, encoding="utf-8"))
        sdk_ts, sdk_t = float(d.get("ts")), d.get("t")
    except Exception:                                                        # noqa: BLE001
        pass
    head_t, head_wall = None, None
    try:
        h = json.load(open(os.path.join(_REPO, "reports", "moveit", "live_head.json"), encoding="utf-8"))["head"]
        head_t, head_wall = h[-1].get("t"), h[-1].get("wall")
    except Exception:                                                        # noqa: BLE001
        pass
    info = {"src": src, "read_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "recorder_t_s": head_t, "recorder_wall": head_wall,
            "est_sample_no_50hz": int(head_t * 50) if head_t else None,
            "sdk_ts": sdk_ts, "sdk_t": sdk_t, "joints": js,
            "note": "样本号按 recorder 自身时钟 ×50Hz 估算(该 recorder 全程连续跑, 不重启)"}
    return tcp, info


def publish_route(pts, label):
    """发布成 plan 层的一整条 kind=path3d(管道)。只重写 plan 这一层。"""
    bak = SPEC.with_name(SPEC.name + ".bak_slot7route_" + time.strftime("%H%M%S"))
    shutil.copy2(SPEC, bak)
    spec = SO.load_spec()
    el = {"origin": "plan", "label": label, "kind": "path3d", "pts3d": pts,
          "width": 4, "no_label": True, "conf": 1.0}
    SO.merge_origin(spec, CAM, "plan", [el], meta={
        "source": "tools/plan_slot7_route.py", "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n": 1, "pts": len(pts), "ifaces": "观察位→7号位(抬离/横移/分步下落)"})
    SO.save_spec(spec)
    back = SO.load_spec()
    cam = (back.get("cameras") or {}).get(CAM) or {}
    plans = [b for b in (cam.get("boxes") or []) if b.get("origin") == "plan"]
    return {"backup": str(bak), "mode": back.get("mode"),
            "n_plan_elems": len(plans),
            "n_plan_pts": sum(len(b.get("pts3d") or []) for b in plans),
            "by_origin": cam.get("by_origin"),
            "all_origins": sorted({b.get("origin") for b in (cam.get("boxes") or [])}),
            "total_boxes": len(cam.get("boxes") or [])}


def snap(path_tmp, url="http://127.0.0.1:8791/snapshot/overlay_arm.jpg"):
    r = subprocess.run(["curl", "-s", "-o", path_tmp, "-w", "%{http_code} %{size_download}",
                        "--max-time", "20", url], capture_output=True, text=True)
    out = (r.stdout or "").strip().split()
    return {"url": url, "http": out[0] if out else "?", "bytes": int(out[1]) if len(out) > 1 else 0,
            "path": path_tmp}


def white_stats(img):
    """亮白像素统计: r>250 & g>250 & b>250; 分整帧 / 下半部, 并给最大连通域。"""
    import cv2
    import numpy as np
    H, W = img.shape[:2]
    r, g, b = img[:, :, 2].astype(int), img[:, :, 1].astype(int), img[:, :, 0].astype(int)
    mask = ((r > 250) & (g > 250) & (b > 250)).astype(np.uint8)
    half = mask.copy()
    half[:H // 2, :] = 0
    out = {"h": H, "w": W,
           "white_total": int(mask.sum()),
           "white_lower_half": int(half.sum())}
    for name, m in (("lower_half", half), ("total", mask)):
        if m.sum() == 0:
            out["max_cc_" + name] = 0
            continue
        n, _lab, stats, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
        areas = [int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n)]
        out["max_cc_" + name] = max(areas) if areas else 0
        out["n_cc_" + name] = len(areas)
    return out


def offline_ab(tcp7):
    """同帧 A/B(姿态无关的强证据): 同一张原帧、同一个 TCP, 渲染"有 plan 层/去掉 plan 层"两遍做逐像素差。
    证明 plan 层真的在这个渲染器里落笔, 且给出它贡献的像素数。"""
    import copy
    try:
        import cv2
        import numpy as np
    except Exception as e:                                                     # noqa: BLE001
        return {"ok": False, "err": str(e)}
    s = snap("/tmp/plan_slot7_route_raw.jpg", "http://127.0.0.1:8791/snapshot/arm.jpg")
    img = cv2.imread(s["path"])
    if img is None:
        return {"ok": False, "err": "读不到原帧", "frame": s}
    spec = SO.load_spec()
    spec_b = copy.deepcopy(spec)
    cam = (spec_b.get("cameras") or {}).get(CAM) or {}
    cam["boxes"] = [b for b in (cam.get("boxes") or []) if b.get("origin") != "plan"]
    cam.get("by_origin", {}).pop("plan", None)
    img_a, _ = SO.draw_overlay(img.copy(), spec, CAM, tcp7, {"note": "A/B: 含 plan"})
    img_b, _ = SO.draw_overlay(img.copy(), spec_b, CAM, tcp7, {"note": "A/B: 去 plan"})
    diff = (np.abs(img_a.astype(int) - img_b.astype(int)).sum(2) > 25)
    band = 90                                   # 底部真值带(两遍的计数文字不同)不计入差
    diff_nb = diff.copy(); diff_nb[-band:, :] = False
    wa, wb = white_stats(img_a), white_stats(img_b)
    out = {"ok": True, "frame": s, "diff_px": int(diff.sum()), "diff_px_excl_band": int(diff_nb.sum()),
           "white_with_plan": {"total": wa["white_total"], "lower_half": wa["white_lower_half"],
                               "max_cc_total": wa["max_cc_total"],
                               "max_cc_lower_half": wa["max_cc_lower_half"]},
           "white_without_plan": {"total": wb["white_total"], "lower_half": wb["white_lower_half"],
                                  "max_cc_total": wb["max_cc_total"],
                                  "max_cc_lower_half": wb["max_cc_lower_half"]}}
    out["white_delta_total"] = wa["white_total"] - wb["white_total"]
    out["white_delta_lower_half"] = wa["white_lower_half"] - wb["white_lower_half"]
    os.makedirs(os.path.dirname(FRAME_OUT), exist_ok=True)
    cv2.imwrite(FRAME_OUT.replace(".jpg", "_AB_with_plan.jpg"), img_a)
    cv2.imwrite(FRAME_OUT.replace(".jpg", "_AB_without_plan.jpg"), img_b)
    return out


def wait_observe_capture(pts, start, seconds, tol_mm=25.0, poll=5.0):
    """等**臂回到观察位附近**时抓一张**实时叠加帧**(不是离线渲染) —— 操作者会自己回位, 所以等一等比假装省事。

    判据: 直接读珞石 SDK 5Hz 真值文件(只读) → 距观察位 ≤tol_mm 就抓帧统计。
    """
    import cv2
    sdk = "/home/ubuntu/zmax_data/rokae_sdk/tcp_out/latest.json"
    t0, best, n = time.time(), 9e9, 0
    p = None
    while time.time() - t0 < seconds:
        dmm = None
        try:
            d = json.load(open(sdk, encoding="utf-8"))
            p = [float(d["x"]), float(d["y"]), float(d["z"])]
            dmm = math.dist(p, start) * 1000.0
            best = min(best, dmm)
        except Exception:                                                      # noqa: BLE001
            pass
        if dmm is not None and dmm <= tol_mm:
            time.sleep(1.5)
            fr = snap("/tmp/plan_slot7_route_live_at_observe.jpg")
            img = cv2.imread(fr["path"])
            if img is None:
                return {"ok": False, "why": "到点了但读不到帧"}
            st = white_stats(img)
            out = FRAME_OUT.replace(".jpg", "_live_at_observe.jpg")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            cv2.imwrite(out, img)
            return {"ok": True, "waited_s": round(time.time() - t0, 1), "dist_to_observe_mm": round(dmm, 2),
                    "frame": fr, "saved_to": out, "tcp": [round(float(v), 6) for v in (p or [])], **st}
        n += 1
        time.sleep(poll)
    return {"ok": False, "why": "等待 %.0fs 内臂未回到观察位(全程最近 %.1fmm)"
                                % (seconds, best if best < 9e8 else -1), "n_poll": n}


def live_overlay_info():
    """从**在跑的** 8791 取 `/scene.json` 的 `_overlay_info`(真实叠加循环每帧的落笔记录)。
    这是"服务端真画了"的直接证据: 该 origin 元素的 n_seg / tube_px / 像素包围盒 / 是否被裁。"""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8791/scene.json", timeout=10) as r:
            d = json.load(r)
    except Exception as e:                                                     # noqa: BLE001
        return {"ok": False, "err": str(e)}
    oi = (d.get("_overlay_info") or {}).get(CAM) or {}
    el = [b for b in (oi.get("boxes") or []) if b.get("origin") == "plan"]
    return {"ok": True, "live_drawn": oi.get("drawn"), "live_skipped": oi.get("skipped"),
            "live_mode": oi.get("mode"), "tcp_ok": oi.get("tcp_ok"),
            "plan_elems_drawn": len(el),
            "plan_elem": el[0] if el else None,
            "origins": oi.get("origins")}


def offline_at_pose(pts, pose7, tag):
    """离线渲染(明确标注): 同一张原帧 + 指定 TCP 位姿(如观察位), 看这条路线在那时的画面里落在哪。
    ⚠️ 这是**离线渲染**, 不是实时叠加帧 —— 只用来回答"臂回到观察位时它会画在哪"。"""
    import copy
    try:
        import cv2
    except Exception as e:                                                     # noqa: BLE001
        return {"ok": False, "err": str(e)}
    s = snap("/tmp/plan_slot7_route_pose_%s.jpg" % tag, "http://127.0.0.1:8791/snapshot/arm.jpg")
    img = cv2.imread(s["path"])
    if img is None:
        return {"ok": False, "err": "读不到原帧"}
    spec = SO.load_spec()
    spec_b = copy.deepcopy(spec)
    cam = (spec_b.get("cameras") or {}).get(CAM) or {}
    cam["boxes"] = [b for b in (cam.get("boxes") or []) if b.get("origin") != "plan"]
    img_a, _ = SO.draw_overlay(img.copy(), spec, CAM, pose7, {"note": "离线渲染 @%s" % tag})
    img_b, _ = SO.draw_overlay(img.copy(), spec_b, CAM, pose7, {"note": "离线渲染 @%s(去plan)" % tag})
    wa, wb = white_stats(img_a), white_stats(img_b)
    p = FRAME_OUT.replace(".jpg", "_offline_at_%s.jpg" % tag)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cv2.imwrite(p, img_a)
    pre = project_check(pts, pose7)
    return {"ok": True, "label": "离线渲染(非实时帧), 臂位姿=%s" % tag, "png": p,
            "pose7": [round(float(v), 6) for v in pose7], "projection": pre,
            "white_with_plan": {"total": wa["white_total"], "lower_half": wa["white_lower_half"],
                                "max_cc_total": wa["max_cc_total"],
                                "max_cc_lower_half": wa["max_cc_lower_half"],
                                "n_cc_lower_half": wa.get("n_cc_lower_half")},
            "white_without_plan": {"total": wb["white_total"], "lower_half": wb["white_lower_half"],
                                   "max_cc_lower_half": wb["max_cc_lower_half"]},
            "white_delta_total": wa["white_total"] - wb["white_total"],
            "white_delta_lower_half": wa["white_lower_half"] - wb["white_lower_half"]}


# ══════════════════════ 主流程 ══════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", nargs=3, type=float, default=None, help="起点(缺省=**实时 TCP** 采样)")
    ap.add_argument("--start-obs", action="store_true", help="起点改用观察位真值(默认不用: 现场会手动移臂)")
    ap.add_argument("--to-slot", default="slot_07")
    ap.add_argument("--to-xyz", nargs=3, type=float, default=None)
    ap.add_argument("--lift-mm", type=float, default=60.0, help="① 抬离量(mm)")
    ap.add_argument("--max-step-mm", type=float, default=MAX_STEP_MM)
    ap.add_argument("--max-down-mm", type=float, default=MAX_DOWN_MM, help="③ 每步下降上限")
    ap.add_argument("--points", type=int, default=150, help="折线点数(会夹到 100~200)")
    ap.add_argument("--publish", action="store_true", help="发布到叠加层 plan 层(整条路线)")
    ap.add_argument("--snapshot", action="store_true", help="取 overlay_arm 帧并统计亮白像素")
    ap.add_argument("--pose-check", action="store_true",
                    help="额外做一次'离线渲染 @观察位'(明确标注非实时帧), 回答臂回位时管道画在哪")
    ap.add_argument("--wait-observe", type=float, default=0.0,
                    help="等臂回到观察位(≤25mm)最多 N 秒, 到点抓**实时叠加帧**(非离线)统计")
    ap.add_argument("--out-json", default="", help="计划 JSON 路径(缺省 reports/moveit/plan_slot7_route_<ts>.json)")
    a = ap.parse_args()

    t_created = time.strftime("%Y-%m-%d %H:%M:%S")
    n_pts = max(100, min(200, int(a.points)))
    print("═" * 78)
    print("观察位 → 7号位 优化航路规划 (只规划 · 不下发运动指令)")
    print("═" * 78)

    # ── 起点/终点 ──────────────────────────────────────────────────────────
    # 起点口径(2026-09-29 老倪新口径): **默认用实时 TCP**(现场在手动移臂) —— 写死观察位会锚错。
    tcp, js, tcp_src = LPS.now_tcp()
    start_sample = None
    if a.start:
        start, start_src = list(a.start), "命令行 --start(显式指定)"
    elif a.start_obs:
        start, start_src = list(OBSERVE), OBSERVE_SRC
    else:
        tcp, start_sample = live_tcp_sample()
        js = (start_sample or {}).get("joints")
        tcp_src = "实时 TCP 采样(%s)" % (start_sample or {}).get("src")
        if tcp is None:
            start, start_src = list(OBSERVE), OBSERVE_SRC + " [实时 TCP 取不到 ⇒ 回退]"
        else:
            start = [float(v) for v in tcp[:3]]
            start_src = ("**实时 TCP 采样** · %s · recorder壁钟 %s · 约第 %s 个 50Hz 样本 · 读于 %s"
                         % ((start_sample or {}).get("src"), (start_sample or {}).get("recorder_wall"),
                            (start_sample or {}).get("est_sample_no_50hz"),
                            (start_sample or {}).get("read_at")))
    if a.to_xyz:
        tgt, tgt_quat, tgt_src, tgt_status = list(a.to_xyz), [], "命令行 --to-xyz", "-"
    else:
        tgt, tgt_quat, tgt_src, tgt_status = slot_xyz(a.to_slot)

    # 真机 TCP 只读交叉核对(臂现在到底在哪 —— 这决定"抬离"相对谁)
    tcp, js, tcp_src = LPS.now_tcp()
    live = tcp[:3] if tcp is not None else None
    d_live = [round((live[i] - start[i]) * 1000.0, 2) for i in range(3)] if live else None
    d_live_norm = round(math.dist(live, start) * 1000.0, 2) if live else None

    straight_mm = math.dist(start, tgt) * 1000.0
    print("\n── 端点 ──")
    print("  起点(观察位) p=[%s]  ← %s" % (", ".join("%.5f" % v for v in start), start_src))
    print("  终点(7号位)   p=[%s]  ← %s · status=%s" % (", ".join("%.5f" % v for v in tgt),
                                                      tgt_src, tgt_status))
    print("  直线距离 = %.1f mm" % straight_mm)
    if live:
        print("  真机 TCP 只读(%s): p=[%s]" % (tcp_src, ", ".join("%.5f" % v for v in live)))
        print("    ⟹ 与观察位差 Δ=(%+.1f, %+.1f, %+.1f)mm · |Δ|=%.2fmm %s"
              % (d_live[0], d_live[1], d_live[2], d_live_norm,
                 "(一致 ✓)" if d_live_norm <= 5.0 else "⚠️ 臂不在观察位上(见报告 unfinished)"))
    else:
        print("  ⚠️ 取不到真机 TCP(%s) —— 规划不受影响, 但叠加渲染需要它" % tcp_src)

    # ── 三段航路 ───────────────────────────────────────────────────────────
    legs = build_legs(start, tgt, a.lift_mm)
    print("\n── 航路(三段) ──")
    leg_info = []
    for nm, p0, p1 in legs:
        d = [round((p1[i] - p0[i]) * 1000.0, 2) for i in range(3)]
        L = math.dist(p0, p1) * 1000.0
        print("  %-10s %s → %s   Δ=(%+.1f,%+.1f,%+.1f)mm · 段长 %.2fmm"
              % (nm, "[" + ", ".join("%.5f" % v for v in p0) + "]",
                 "[" + ", ".join("%.5f" % v for v in p1) + "]", d[0], d[1], d[2], L))
        leg_info.append({"leg": nm, "p0": p0, "p1": p1, "delta_mm": d, "len_mm": round(L, 3),
                         "dz_mm": d[2]})

    # ── 逐段守卫(同源函数) ─────────────────────────────────────────────────
    print("\n── 守卫判定(与 live_plan_segment 同一套: 单步 ≤%.0fmm · 单段下降 ≤%.0fmm) ──"
          % (a.max_step_mm, a.max_down_mm))
    print("  " + "─" * 74)
    dispatch, bad = [], []
    for nm, p0, p1 in legs:
        prev = p0
        for pt in split_steps(p0, p1, a.max_step_mm, a.max_down_mm):
            rows = guard_rows(prev, pt, a.max_step_mm, a.max_down_mm)     # 同源判定
            r = rows[-1]
            ok = bool(r["ok_step"] and r["ok_down"])
            dispatch.append({"leg": nm, "pt": [round(v, 6) for v in pt],
                             "seg_mm": round(r["seg_mm"], 3), "down_mm": round(r["down_mm"], 3),
                             "ok_step": r["ok_step"], "ok_down": r["ok_down"], "pass": ok})
            if not ok:
                bad.append((nm, r))
            prev = pt
        seg_ok = [d for d in dispatch if d["leg"] == nm]
        print("  %s: %d 步 · 段长 %.2f~%.2fmm · 下降 %.2f~%.2fmm · %s"
              % (nm, len(seg_ok), min(d["seg_mm"] for d in seg_ok), max(d["seg_mm"] for d in seg_ok),
                 min(d["down_mm"] for d in seg_ok), max(d["down_mm"] for d in seg_ok),
                 "全部过闸 ✓" if all(d["pass"] for d in seg_ok) else "有不过闸 ✗"))
    for i, r in enumerate(dispatch, 1):
        print("    %2d/%2d  %-10s 段长 %6.2fmm · 下降 %6.2fmm  %s"
              % (i, len(dispatch), r["leg"], r["seg_mm"], r["down_mm"], "✓" if r["pass"] else "✗"))
    n_bad_step = sum(1 for r in dispatch if not r["ok_step"])
    n_bad_down = sum(1 for r in dispatch if not r["ok_down"])
    print("  执行步守卫结论: %d/%d 步过闸 %s (单步超限 %d · 下降超限 %d)"
          % (len(dispatch) - len(bad), len(dispatch), "✓" if not bad else "✗", n_bad_step, n_bad_down))

    # 守卫口径敏感度: 同一路线在更严/更松的口径下要多少步、会不会被拒
    sens = []
    for md in (40.0, 30.0, 20.0):
        nb = n_tot = 0
        for nm, p0, p1 in legs:
            prev = p0
            for pt in split_steps(p0, p1, a.max_step_mm, md):
                r = guard_rows(prev, pt, a.max_step_mm, md)[-1]
                n_tot += 1
                if not (r["ok_step"] and r["ok_down"]):
                    nb += 1
                prev = pt
        sens.append({"max_down_mm": md, "steps": n_tot, "n_fail": nb})
    print("  守卫口径敏感度: " + " · ".join("%.0fmm⇒%d步/%d不过" % (s["max_down_mm"], s["steps"], s["n_fail"])
                                            for s in sens))

    # ── 折线(100~200 点) ──────────────────────────────────────────────────
    pts, segs = resample(legs, n_pts)
    assert len(pts) == len(segs)
    total_mm = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) * 1000.0
    ratio = total_mm / straight_mm if straight_mm else float("inf")
    fine_bad = 0
    fine_min, fine_max = 1e9, 0.0
    for i in range(len(pts) - 1):
        for r in guard_rows(pts[i], pts[i + 1], a.max_step_mm, a.max_down_mm):
            fine_min = min(fine_min, r["seg_mm"]); fine_max = max(fine_max, r["seg_mm"])
            if not (r["ok_step"] and r["ok_down"]):
                fine_bad += 1
    print("\n── 折线(发布用) ──")
    print("  点数 = %d (起点=观察位, 终点=7号位; 段边界保留)" % len(pts))
    print("  折线总长 = %.2f mm · 绕行比 = %.3f (= 总长 / 直线 %.1fmm)" % (total_mm, ratio, straight_mm))
    print("  折线逐步守卫: %d 步 · 段长 %.2f~%.2fmm · 不过闸 %d"
          % (len(pts) - 1, fine_min, fine_max, fine_bad))

    # ── 绕行比目标达成判定 + 几何下界 ──────────────────────────────────────
    floor_diag = a.lift_mm + math.dist([start[0], start[1], start[2] + a.lift_mm / 1000.0], tgt) * 1000.0
    floor_ratio = floor_diag / straight_mm
    target_hit = 1.1 <= ratio <= 1.3
    h13, _d13 = _lift_for(straight_mm, start, tgt, 1.3)
    h12, _d12 = _lift_for(straight_mm, start, tgt, 1.2)
    print("\n── 绕行比(目标 1.1~1.3) ──")
    print("  实际: 总长 %.2fmm · 绕行比 %.3f  ⇒ %s" % (total_mm, ratio, "达标 ✓" if target_hit else "**未达标 ✗ (如实报实际值)**"))
    print("  几何下界: 抬离 %.0fmm 后**最短**路径 = 抬离段 + 抬离点到终点的直线" % a.lift_mm)
    print("            = %.1f + %.1f = **%.2fmm ⇒ 绕行比下界 %.3f**"
          % (a.lift_mm, floor_diag - a.lift_mm, floor_diag, floor_ratio))
    print("            (要做进 1.1~1.3 得把抬离压到 ≤%.0fmm[1.3] / ≤%.0fmm[1.2]; 且必须允许斜向下落)"
          % (h13, h12))
    print("  本路线(按老倪口径: 高度上横移过去再分步下落) = %.2fmm ⇒ %.3f" % (total_mm, ratio))
    dr = drag_stats()
    if dr:
        print("  对照手工拖动(同一份 50Hz 记录): 原始 %.1fmm ⇒ %.2f · 抽稀 %d 点 %.1fmm ⇒ %.2f"
              % (dr["path_raw_mm"], dr["ratio_raw"], dr["n_wp"], dr["path_decimated_mm"],
                 dr["ratio_decimated"]))
        print("  ⇒ 相比原始拖动路径缩短 %.1f%% (%.1f → %.1f mm)"
              % ((1 - total_mm / dr["path_raw_mm"]) * 100.0, dr["path_raw_mm"], total_mm))

    # ── 姿态口径 ───────────────────────────────────────────────────────────
    quat = tcp[3:7] if tcp is not None else [0.0, 0.0, 0.0, 1.0]
    ang = ang_raw = None
    if tgt_quat and tcp is not None:
        ang = LPS.quat_angle_deg(quat, tgt_quat)                       # 口径: |dot| (忽略反极)
        d = sum(x * y for x, y in zip(quat, tgt_quat))                 # 带符号: 反极⇒166°
        ang_raw = math.degrees(2.0 * math.acos(max(-1.0, min(1.0, d))))
    print("\n── 姿态 ──")
    print("  计划姿态 = **沿用当前腕部** quat=[%s](本计划是纯平移; 姿态通道当前被控制器忽略)"
          % ", ".join("%.5f" % v for v in quat))
    if ang is not None:
        print("  目标示教姿态与当前差: 带符号四元数角 **%.1f°**(= 反极口径, 现场说的 166°) · |dot| 口径 %.1f°"
              % (ang_raw, ang))
        print("  ⇒ **不纳入本计划**(不去转它), 仅登记; 要转得先解决姿态通道")

    json_path = a.out_json or os.path.join(
        _REPO, "reports", "moveit", "plan_slot7_route_%s.json" % time.strftime("%Y%m%d_%H%M"))
    report = {
        "kind": "plan_slot7_route(观察位→7号位: 抬离→高度横移→分步下落)",
        "created": t_created, "tool": "tools/plan_slot7_route.py",
        "motion_sent": False,
        "no_motion_note": "本工具只写规划与叠加层: 未写 ~/zmax_data/l2_cmd.fifo, 未调任何运动服务",
        "guard_source": "tools/live_plan_segment.py 的 segment() (同一函数, 单步 ≤%.0fmm · 向下 ≤%.0fmm 每段)"
                        % (a.max_step_mm, a.max_down_mm),
        "guard_registry_facts": {
            "L2.slot7": {"guard": {"max_lin_mm": 500, "z_floor_point": "slot7", "z_floor_offset_mm": 0},
                         "stage1": "to slot7 dz=+30mm 到正上方, guard.dz_down_limit_mm=400",
                         "stage2": "to slot7 dz=0 竖直下降, guard.dz_down_limit_mm=40"},
            "live_plan_segment_defaults": {"max_step_mm": 50.0, "max_down_mm": 20.0},
            "note": "本计划按 30mm/段设计 ⇒ 比 L2.slot7 阶段2 的 40mm 更严 ⇒ 过闸; 若按 20mm 口径需再拆(见 sensitivity)",
        },
        "start": {"p": start, "src": start_src, "sample": start_sample},
        "start_drift_check": {"note": "执行前若起点又变了 >10mm 必须重新规划",
                              "live_read_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "live_xyz": [round(float(v), 6) for v in live] if live else None,
                              "delta_mm": d_live, "delta_norm_mm": d_live_norm},
        "target": {"p": tgt, "quat": tgt_quat, "src": tgt_src, "status": tgt_status, "slot": a.to_slot},
        "live_tcp_at_plan_time": {"tcp": [round(float(v), 6) for v in tcp] if tcp is not None else None,
                                  "joints": js, "src": tcp_src,
                                  "delta_vs_observe_mm": d_live, "delta_norm_mm": d_live_norm},
        "straight_mm": round(straight_mm, 3),
        "legs": leg_info,
        "dispatch_steps": dispatch,
        "guard_summary": {"n_steps": len(dispatch), "n_pass": len(dispatch) - len(bad),
                          "n_fail": len(bad), "n_fail_step": n_bad_step, "n_fail_down": n_bad_down,
                          "all_pass": not bad},
        "guard_sensitivity": sens,
        "polyline": {"n": len(pts), "total_len_mm": round(total_mm, 3), "ratio": round(ratio, 4),
                     "ratio_target": [1.1, 1.3], "target_hit": bool(target_hit),
                     "min_step_mm": round(fine_min, 3), "max_step_mm": round(fine_max, 3),
                     "n_fail_steps": fine_bad,
                     "points": [{"i": i, "leg": segs[i],
                                 "xyz": [round(v, 6) for v in pts[i]],
                                 "quat": [round(float(v), 6) for v in quat],
                                 "cum_mm": round(sum(math.dist(pts[j], pts[j + 1])
                                                     for j in range(i)) * 1000.0, 3)}
                                for i in range(len(pts))]},
        "geometry_floor": {"lift_mm": a.lift_mm, "min_possible_mm": round(floor_diag, 3),
                           "min_possible_ratio": round(floor_ratio, 4),
                           "lift_needed_for_ratio_1.3_mm": _lift_for(straight_mm, start, tgt, 1.3)[0],
                           "lift_needed_for_ratio_1.2_mm": _lift_for(straight_mm, start, tgt, 1.2)[0]},
        "drag_reference": dr,
        "pose_note": "每点 quat = 当前腕部姿态(纯平移计划); 与目标示教姿态差 %s°(带符号反极口径) 不纳入本计划"
                     % (round(ang_raw, 1) if ang_raw is not None else "未知"),
        "pose_angle_vs_target_deg_signed": round(ang_raw, 2) if ang_raw is not None else None,
        "pose_angle_vs_target_deg_absdot": round(ang, 2) if ang is not None else None,
        "publish": None, "snapshot": None, "projection_precheck": None,
    }

    # ── 投影预检 ───────────────────────────────────────────────────────────
    pre = project_check(pts, tcp)
    report["projection_precheck"] = pre
    print("\n── 投影预检(手眼+真机 TCP, 只读) ──")
    if pre.get("ok"):
        print("  可用投影 %d/%d 点 · 落在画面内 %d 点(其中下半部 %d) · 深度 %.3f~%.3f m"
              % (pre["n_usable"], pre["n"], pre["n_in_frame"], pre["n_in_lower_half"],
                 pre["zc_m"][0], pre["zc_m"][1]))
        print("  首点 uv=%s · 末点 uv=%s" % (pre["uv_first"], pre["uv_last"]))
    else:
        print("  ⚠️ %s" % pre.get("why"))

    # ── 发布 ───────────────────────────────────────────────────────────────
    base_snap = None
    if a.snapshot:
        base_snap = snap("/tmp/plan_slot7_route_before.jpg")
        try:
            import cv2
            b_img = cv2.imread(base_snap["path"])
            base_snap.update(white_stats(b_img) if b_img is not None else {"err": "读不到基线帧"})
        except Exception as e:                                                # noqa: BLE001
            base_snap["err"] = str(e)
        print("\n── 基线帧(发布前) ──")
        print("  HTTP %s · %d bytes · 亮白整帧=%s · 下半部=%s · 下半部最大连通域=%s"
              % (base_snap.get("http"), base_snap.get("bytes"), base_snap.get("white_total"),
                 base_snap.get("white_lower_half"), base_snap.get("max_cc_lower_half")))

    if a.publish:
        label = "观察位→7号位 优化航路(%d点/%.0fmm/比%.2f)" % (len(pts), total_mm, ratio)
        pub = publish_route(pts, label)
        report["publish"] = pub
        print("\n── 已发布 plan 层 ──")
        print("  kind=path3d 元素 %d 个 · 共 %d 点 · mode=%s · 备份 %s"
              % (pub["n_plan_elems"], pub["n_plan_pts"], pub["mode"], os.path.basename(pub["backup"])))
        print("  spec 回读: by_origin=%s · 全部来源=%s · 该相机框数=%d"
              % (pub["by_origin"], pub["all_origins"], pub["total_boxes"]))

    # ── 在跑的 8791 到底画了没有(服务端自证) ───────────────────────────────
    if a.publish:
        time.sleep(1.0)
        li = live_overlay_info()
        report["live_overlay_info"] = li
        print("\n── 在跑的 8791 叠加循环自证(/scene.json · _overlay_info.arm) ──")
        if li.get("ok"):
            e = li.get("plan_elem")
            print("  本轮落笔 %s 个 · mode=%s · tcp_ok=%s · plan 元素绘制 %d 个"
                  % (li["live_drawn"], li["live_mode"], li["tcp_ok"], li["plan_elems_drawn"]))
            if e:
                print("  plan 元素: kind=%s · n_seg=%s · 管径 %s px · 像素包围盒 xyxy=%s · 被裁=%s"
                      % (e.get("kind"), e.get("n_seg"), e.get("tube_px"), e.get("xyxy"), e.get("clipped")))
            print("  本轮跳过: %s" % li.get("live_skipped"))
        else:
            print("  ⚠️ 取不到(%s)" % li.get("err"))

    # ── 取帧统计亮白像素(证明管道真画上了) ─────────────────────────────────
    if a.snapshot:
        time.sleep(2.0)                       # 叠加是 10fps 的独立循环, 给它两拍重画
        s = snap("/tmp/plan_slot7_route_after.jpg")
        ev = {"frame": s}
        try:
            import cv2
            img = cv2.imread(s["path"])
            if img is None:
                ev["err"] = "cv2 读不到帧"
            else:
                st = white_stats(img)
                ev.update(st)
                ev["saved_to"] = FRAME_OUT
                os.makedirs(os.path.dirname(FRAME_OUT), exist_ok=True)
                cv2.imwrite(FRAME_OUT, img)
                ev["std"] = round(float(img.std()), 2)
                orig = snap("/tmp/plan_slot7_route_raw.jpg", "http://127.0.0.1:8791/snapshot/arm.jpg")
                ev["raw_frame"] = orig
        except Exception as e:                                                # noqa: BLE001
            ev["err"] = str(e)
        ev["baseline"] = base_snap
        report["snapshot"] = ev
        print("\n── 发布后取帧(overlay_arm.jpg) ──")
        print("  HTTP %s · %d bytes · 帧 std=%s" % (s.get("http"), s.get("bytes"), ev.get("std")))
        if ev.get("white_total") is not None:
            print("  亮白像素(r>250&g>250&b>250): 整帧 %d · **下半部 %d** · 下半部最大连通域 **%d** px (连通域 %s 个)"
                  % (ev["white_total"], ev["white_lower_half"], ev["max_cc_lower_half"],
                     ev.get("n_cc_lower_half")))
            print("  整帧最大连通域 %d px" % ev.get("max_cc_total", 0))
            if base_snap and base_snap.get("white_lower_half") is not None:
                print("  基线对照(发布前): 整帧 %s→%d · 下半部 %s→%d"
                      % (base_snap.get("white_total"), ev["white_total"],
                         base_snap.get("white_lower_half"), ev["white_lower_half"]))
            print("  帧已存: %s" % FRAME_OUT)

        # 同帧 A/B(姿态无关的强证据): 有/无 plan 层各渲一遍, 逐像素差
        ab = offline_ab(tcp)
        ev["offline_ab"] = ab
        print("\n── 同帧 A/B(同一张原帧+同一 TCP, 有/无 plan 层) ──")
        if ab.get("ok"):
            print("  差异像素 %d (去掉底部真值带后 %d) ⇒ plan 层确实落笔"
                  % (ab["diff_px"], ab["diff_px_excl_band"]))
            print("  亮白像素: 含 plan 整帧 %d/下半部 %d · 去 plan 整帧 %d/下半部 %d · Δ整帧 %+d"
                  % (ab["white_with_plan"]["total"], ab["white_with_plan"]["lower_half"],
                     ab["white_without_plan"]["total"], ab["white_without_plan"]["lower_half"],
                     ab["white_delta_total"]))
            print("  A/B 图: %s | %s" % (FRAME_OUT.replace(".jpg", "_AB_with_plan.jpg"),
                                         FRAME_OUT.replace(".jpg", "_AB_without_plan.jpg")))
        else:
            print("  ⚠️ 跳过(%s)" % ab.get("err"))

        # 离线渲染 @ 观察位(明确标注): 臂回到观察位时这条管道画在哪
        if a.pose_check:
            obs7 = [start[0], start[1], start[2]] + list(quat)
            oc = offline_at_pose(pts, obs7, "观察位")
            ev["offline_at_observe"] = oc
            print("\n── 离线渲染 @观察位(非实时帧, 只回答'臂回到观察位时管道画在哪') ──")
            if oc.get("ok"):
                pre_o = oc["projection"]
                print("  投影: 可用 %d/%d · 画面内 %d 点(下半部 %d)"
                      % (pre_o["n_usable"], pre_o["n"], pre_o["n_in_frame"], pre_o["n_in_lower_half"]))
                print("  亮白像素: 含 plan 整帧 %d · **下半部 %d** · 下半部最大连通域 **%d** px"
                      % (oc["white_with_plan"]["total"], oc["white_with_plan"]["lower_half"],
                         oc["white_with_plan"]["max_cc_lower_half"]))
                print("  去 plan 对照: 整帧 %d · 下半部 %d ⇒ Δ整帧 %+d · Δ下半部 %+d"
                      % (oc["white_without_plan"]["total"], oc["white_without_plan"]["lower_half"],
                         oc["white_delta_total"], oc["white_delta_lower_half"]))
                print("  离线图: %s" % oc["png"])
            else:
                print("  ⚠️ 跳过(%s)" % oc.get("err"))

        # 等臂回观察位 → 抓**实时叠加帧**(不是离线渲染)
        if a.wait_observe > 0:
            wc = wait_observe_capture(pts, start, a.wait_observe)
            ev["live_at_observe_capture"] = wc
            print("\n── 等臂回到观察位后抓实时帧(≤%.0fs) ──" % a.wait_observe)
            if wc.get("ok"):
                print("  等到! 距观察位 %.1fmm · 等了 %.1fs · TCP=%s"
                      % (wc["dist_to_observe_mm"], wc["waited_s"], wc["tcp"]))
                print("  亮白像素: 整帧 %d · **下半部 %d** · 下半部最大连通域 **%d** px (连通域 %s)"
                      % (wc["white_total"], wc["white_lower_half"], wc["max_cc_lower_half"],
                         wc.get("n_cc_lower_half")))
                print("  帧: %s" % wc["saved_to"])
            else:
                print("  ⚠️ %s" % wc.get("why"))

    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n计划 JSON: %s" % json_path)
    print("⚠️ 全程未下发任何运动指令(未写 l2_cmd.fifo / 未调运动服务)。")
    print("═" * 78)
    return 0


def _lift_for(straight_mm, start, tgt, ratio):
    """解 h: (h + |抬离点到终点|) / 直线 = ratio"""
    D = math.dist([start[0], start[1]], [tgt[0], tgt[1]]) * 1000.0
    H = (start[2] - tgt[2]) * 1000.0
    target_len = ratio * straight_mm
    lo, hi = 0.0, 400.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        L = mid + math.hypot(D, H + mid)
        if L < target_len:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 1), round(math.hypot(D, H + (lo + hi) / 2.0), 1)


if __name__ == "__main__":
    raise SystemExit(main())
