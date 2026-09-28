#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 实时标注器 (l5_live_mark) — 臂上 D405 画面里的 ①光模块 ②14 个槽位，持续写进叠加规格
════════════════════════════════════════════════════════════════════════════
老倪需求 (2026-09-28):「我挪动一个位置，你能实时标记么？而且每个槽位也要标记。你看直，
检测光模块个槽位」⇒ 相机移动后页面上框要自动重算、不断更新。

做什么 (每轮 ≤1/hz 秒):
  1. 从臂相机取当前帧 (默认 http://192.168.23.66:8792/frame.jpg，退路走本地 8791 /snapshot/arm.jpg)
  2. YOLO 在役检测器 models/yolo_peg_live.pt 逐帧检测光模块 → 框 (origin=l5live, label 带类别)
  3. 槽位几何量测 → 上排 7 + 下排 7 = 14 个 (origin=l5live, label slot_01..slot_14)
  4. 只改 spec 里 origin==l5live 的框，其余键原样保留 → 服务每帧热读 ⇒ 页面实时跟随

槽位几何量测 (无写死坐标, 逐帧实测; 相机挪动后自动重算):
  A. 水平长边能量 E(y)=|灰度-大核高斯| 在中央 x 窗的均值 → 5 条锚线:
     上边框 / 上排槽底沿 / 中分隔条 / 下排槽底沿 / 下边框   (下排槽底沿用上下排对称性约束)
  B. 两个行带内取列剖面 P(x) → 自相关求 pitch → 折叠求"槽内暗陷"相位与槽宽 w
     → 用该模板做 1D 归一化互相关 (cv2.matchTemplate TM_CCOEFF_NORMED) 找每个槽心
  C. 逐点局部精修 (槽心=剖面局部极小) + 置信度 (实测/外推分开标)
  D. 治具不可见 (锚线不成对/行带高度非法) ⇒ 本轮不写槽位框, 如实记 未检出

红线: 只写 origin==l5live 的框; 检不出就不画; 低置信用 conf 如实标; 不动机器人、不重启推流服务。
用法:
  gui-venv311/bin/python tools/l5_live_mark.py --probe            # 单次: 打印测量+出图, 不写 spec
  gui-venv311/bin/python tools/l5_live_mark.py --hz 5             # 常驻: 5Hz 写 spec
  gui-venv311/bin/python tools/l5_live_mark.py --selfcheck         # 断言框合法 (不出画/不退化)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
import urllib.request
from pathlib import Path

import cv2
import numpy as np

REPO = Path("/home/ubuntu/zmax_rel")
SPEC = REPO / "data" / "scene" / "overlay_spec.json"
OUT = Path("/home/ubuntu/zmax_data/l5live")
ORIGIN = "l5live"
N_SLOT_PER_ROW = 7          # 治具固定 7+7 (领域常量, 位置逐帧实测)
W_MIN, W_MAX = 8, 200       # 框合法性断言 (像素)


# ══════════════════ 1. 取帧 ══════════════════
_FR = {"md5": None, "since": 0.0}


def fetch_frame(url: str, fallback: str, timeout: float = 2.0) -> tuple[np.ndarray | None, str, float, str]:
    """返回 (BGR 帧, 来源, 取图耗时, 备注)。
    备注里带"画面静止"判定: 源端卡住时(帧字节长时间不变)如实标注 —— 因为页面上显示的也是
    同一份帧, 此时框与画面仍是对齐的, 但那不是"新画面", 不能假装是实时新帧。"""
    note = ""
    for tag, u in (("orin", url), ("local", fallback)):
        if not u:
            continue
        try:
            t0 = time.time()
            with urllib.request.urlopen(u, timeout=timeout) as r:
                b = r.read()
            if not b or len(b) < 512:
                continue
            img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            h = hashlib.md5(b).hexdigest()
            if h != _FR["md5"]:
                _FR["md5"], _FR["since"] = h, time.time()
            elif _FR["since"] and (time.time() - _FR["since"]) > 3.0:
                note = "画面静止 %.0fs(源可能卡住/场景无变化)" % (time.time() - _FR["since"])
            return img, tag, time.time() - t0, note
        except Exception:
            continue
    return None, "取帧失败(所有源)", -1.0, note


# ══════════════════ 2. 槽位几何量测 ══════════════════
def _peaks(v: np.ndarray, min_dist: int, thr: float) -> list[int]:
    out, taken = [], np.zeros(len(v), bool)
    for i in np.argsort(v)[::-1]:
        if v[i] < thr:
            break
        if taken[max(0, i - min_dist):i + min_dist + 1].any():
            continue
        taken[i] = True
        out.append(int(i))
    return sorted(out)


def _fold(P: np.ndarray, p: int) -> np.ndarray:
    F = np.zeros(p)
    cnt = np.zeros(p)
    for x in range(len(P)):
        F[x % p] += P[x]
        cnt[x % p] += 1
    return F / np.maximum(1.0, cnt)


def _smooth(v: np.ndarray, k: int) -> np.ndarray:
    """奇数核滑动平均 (边界复制)"""
    k = max(1, int(k) | 1)
    pad = k // 2
    vp = np.concatenate([v[:pad][::-1], v, v[-pad:][::-1]])
    return np.convolve(vp, np.ones(k) / k, mode="same")[pad:pad + len(v)]


def _foldz(z: np.ndarray, p: int, idx: np.ndarray | None = None) -> np.ndarray:
    """把 z 按周期 p 折叠平均 (只统计 idx 内的样本)"""
    if idx is None:
        idx = np.arange(len(z))
    F = np.zeros(p)
    cnt = np.zeros(p)
    for i in idx:
        F[i % p] += z[i]
        cnt[i % p] += 1
    return F / np.maximum(1.0, cnt)


def detect_slots(gray: np.ndarray, diag: dict | None = None) -> dict | None:
    """
    逐帧从图像量出两个行带 + 每行 7 个槽位。
    返回 {'rows':{'up':(y0,y1),'lo':(y0,y1)}, 'slots':[{cx,cy,w,h,conf,ev,dip,ncc,y0,y1,tag}], 'diag':{...}}
    治具不可见 ⇒ None (调用方如实记"未检出", 不画)
    """
    H, W = gray.shape
    d = diag if diag is not None else {}
    gf = gray.astype(np.float32)
    lc = gf - cv2.GaussianBlur(gf, (0, 0), 9)

    # ── A. 水平锚线 ──
    x0, x1 = int(0.15 * W), int(0.85 * W)
    E = np.abs(lc[:, x0:x1]).mean(axis=1)
    E = np.convolve(E, np.ones(5) / 5, mode="same")
    E[:int(0.04 * H)] = 0
    E[int(0.96 * H):] = 0
    pk = _peaks(E, min_dist=int(0.05 * H), thr=0.30 * E.max())
    d["E_peaks"] = [(int(y), round(float(E[y]), 1)) for y in pk]
    if len(pk) < 3:
        d["reason"] = "锚线不足 %d" % len(pk)
        return None
    top = [y for y in pk if y < 0.30 * H]
    mid = [y for y in pk if 0.30 * H <= y <= 0.70 * H]
    if not top or not mid:
        d["reason"] = "缺上边框/中隔条"
        return None
    rim_t = max(top, key=lambda y: E[y])       # 上边框 = 顶部最强长横边
    div = max(mid, key=lambda y: E[y])
    up_c = [y for y in pk if rim_t < y < div]
    if not up_c:
        d["reason"] = "缺上排槽底沿"
        return None
    gb_up = max(up_c, key=lambda y: E[y])
    lo_c = [y for y in pk if div < y < 0.96 * H]
    if not lo_c:
        d["reason"] = "缺下排槽底沿"
        return None
    want = 2 * div - gb_up                      # 治具上下排近似对称 ⇒ 约束下排槽底沿
    gb_lo = min(lo_c, key=lambda y: abs(y - want))
    pad = max(4, int(0.015 * H))
    rows = {"up": (rim_t + pad, gb_up - 2), "lo": (div + pad, gb_lo - 2)}
    d["anchors"] = {"rim_top": int(rim_t), "gb_up": int(gb_up), "div": int(div),
                    "gb_lo": int(gb_lo), "want_lo": int(want)}
    for tag, (a, b) in rows.items():
        if not (25 <= b - a <= 0.45 * H):
            d["reason"] = "行带高度非法 %s=%d" % (tag, b - a)
            return None

    # ── B/C. 每行: 周期(折叠方差) → 槽心(1D NCC 模板匹配) → 清洗 → 格点补齐 ──
    # 整幅的"长竖直边"掩码: 托盘侧壁/模块边缘的竖边几乎贯穿整帧, 而槽的两侧竖边只跨
    # 行带高度 ⇒ 用"强竖边行数"把侧壁/模块边从槽位候选里剔掉 (实测: 真槽 0 行, 侧壁 13~26 行)
    gxa = np.abs(cv2.Sobel(gf, cv2.CV_32F, 1, 0, ksize=3))
    tall = (gxa > 0.45 * float(gxa.max())).sum(axis=0)
    tall_thr = max(6.0, 0.03 * H)
    slots = []
    for tag, (y0, y1) in rows.items():
        P = _smooth(gf[y0:y1, :].mean(axis=0), 7)
        z = P - _smooth(P, 61)                    # 去掉照明梯度, 只留周期纹理
        # 周期只在**画面中央窗**里估: 全宽会把背景/托盘侧壁的大幅非周期结构算进来
        # → 周期估计被带偏 (实测踩过: 全宽报 94, 中央窗报 61.5~64)
        iw = np.arange(int(0.25 * W), int(0.75 * W))
        best_p, best_v, allv = None, -1.0, []
        for p in np.arange(40.0, 100.01, 0.5):
            v = float(_foldz(z, int(round(p)), iw).var() / max(1e-9, z[iw].var()))
            allv.append((round(float(p), 1), round(v, 3)))
            if v > best_v:
                best_v, best_p = v, float(p)
        p = int(round(best_p))
        F = _foldz(z, p, iw)
        # 折叠波形里"槽"(暗区) = 低于阈值的连续段; 用该段**中点**作模板中心
        # (用 argmin 会把框整体带偏 ~10px: 槽内最暗点不在几何中心)
        lo_thr = F.min() + 0.5 * (F.max() - F.min())
        i0 = int(np.argmin(F))
        a = i0
        while F[a % p] < lo_thr:
            a -= 1
        b = i0
        while F[b % p] < lo_thr:
            b += 1
        gw = float((b - a) % p) or 20.0
        ucen = (a + 1 + b - 1) / 2.0                  # 折叠波形里槽中心
        half = max(7, int(gw * 0.7))
        Fr = np.roll(F, (p // 2 - int(round(ucen))) % p)
        T = np.array([Fr[u % p] for u in range(p // 2 - half, p // 2 + half + 1)], np.float32)
        pad = len(T) // 2
        Pp = np.concatenate([z[:pad][::-1], z, z[-pad:][::-1]]).astype(np.float32).reshape(1, -1)
        score = cv2.matchTemplate(Pp, T.reshape(1, -1), cv2.TM_CCOEFF_NORMED)[0]
        raw = []
        for c in _peaks(score, min_dist=max(12, int(0.6 * p)), thr=0.35):
            lo = int(max(0, c - 0.5 * p))
            hi = int(min(W, c + 0.5 * p))
            seg = P[lo:hi]
            if len(seg) < 5:
                continue
            base = float(np.percentile(seg, 80))      # 两侧脊顶基线
            dip = base - float(P[c])                  # 槽底比脊顶暗多少 (灰阶)
            if dip < 5.0 or score[c] < 0.45:          # 证据太弱不算实测
                continue
            # 槽的两侧必须有"脊"(局部抬升): 托盘侧壁/背景交界只是大片暗区, 没有两侧脊 ⇒ 剔除
            lw = P[max(0, int(c - 0.5 * p)):max(1, int(c - 0.25 * p))]
            rw = P[min(W - 1, int(c + 0.25 * p)):min(W, int(c + 0.5 * p))]
            if len(lw) < 3 or len(rw) < 3:
                continue
            if lw.max() < P[c] + 0.5 * dip or rw.max() < P[c] + 0.5 * dip:
                continue
            # 长竖边掩码: ±0.15p 内有贯穿帧的强竖边 ⇒ 是托盘侧壁/模块边, 不是槽
            w0, w1 = max(0, int(c - 0.15 * p)), min(W, int(c + 0.15 * p) + 1)
            if tall[w0:w1].max(initial=0) >= tall_thr:
                continue
            raw.append({"cx": float(c), "ncc": float(score[c]), "dip": dip, "ev": "measured"})
        # 清洗①: 去重 (同一槽相邻两个峰) 取 dip 大的
        raw.sort(key=lambda s: s["cx"])
        dedup = []
        for s in raw:
            if dedup and s["cx"] - dedup[-1]["cx"] < 0.40 * p:
                if s["dip"] > dedup[-1]["dip"]:
                    dedup[-1] = s
            else:
                dedup.append(s)
        # 清洗②: 格点一致性 (RANSAC 式) —— 槽位必然等间距成排; 托盘侧壁/模块投影虽然
        #         更"黑"(dip 更大) 但与槽位不成格点 ⇒ 只留能组成最多数一致格点的那一簇
        def best_cluster(cs, p):
            best = None
            for m in cs:
                inl = []
                for c in cs:
                    k = int(round((c["cx"] - m["cx"]) / p))
                    if abs(c["cx"] - (m["cx"] + k * p)) <= 0.22 * p:
                        inl.append((c, k))
                key = (len(inl), sum(c["dip"] for c, _ in inl))
                if best is None or key > best[0]:
                    best = (key, inl)
            return best[1] if best else []
        inl = best_cluster(dedup, p)
        if len(inl) >= 3:                              # 最小二乘精修格点 (含间距非严格等距)
            ks = np.array([k for _, k in inl], float)
            xs = np.array([c["cx"] for c, _ in inl], float)
            A = np.vstack([np.ones_like(ks), ks]).T
            coef, *_ = np.linalg.lstsq(A, xs, rcond=None)
            c0, step = float(coef[0]), float(coef[1])
            step = float(np.clip(step, 0.6 * p, 1.6 * p))
            kidx = {}
            for c in dedup:
                k = int(round((c["cx"] - c0) / step))
                if abs(c["cx"] - (c0 + k * step)) <= 0.30 * step:
                    prev = kidx.get(k)
                    if prev is None or c["dip"] > prev["dip"]:
                        kidx[k] = c
            cen_list = list(kidx.values())
        else:
            c0, step, kidx = None, float(p), {}
            cen_list = []
        d[tag] = {"y": (int(y0), int(y1)), "pitch": p, "pitch_var_ratio": round(best_v, 3),
                  "groove_w": round(gw, 1), "n_raw": len(raw), "n_cluster": len(inl),
                  "n_measured": len(cen_list),
                  "centers_raw": [round(s["cx"], 1) for s in raw],
                  "centers": [round(s["cx"], 1) for s in cen_list],
                  "dips": [round(s["dip"], 1) for s in cen_list],
                  "allv_head": sorted(allv, key=lambda t: -t[1])[:4]}

        # ② 相位/步长来自清洗后的格点簇; 选连续 7 个格点, 缺的如实标"外推"
        n_meas = len(cen_list)
        d[tag]["accepted"] = bool(n_meas >= 3 and best_v >= 0.25 and kidx)
        if not d[tag]["accepted"]:
            d[tag]["reject"] = "格点一致槽位 %d 个 / 周期解释度 %.2f 不足" % (n_meas, best_v)
            continue
        # 选连续 7 个格点: 落在里面的实测数最多; 并列时取窗口中心最接近实测中位数的
        # (治具一排槽位关于排中心对称 ⇒ 实测中位数 ≈ 排中心)
        kmin0, kmax0 = min(kidx), max(kidx)
        cmed = float(np.median([s["cx"] for s in cen_list]))
        bestwin, bestsc = None, None
        for k0 in range(kmin0 - N_SLOT_PER_ROW + 1, kmax0 + 1):
            win = list(range(k0, k0 + N_SLOT_PER_ROW))
            n = sum(1 for k in win if k in kidx)
            mid = c0 + (k0 + (N_SLOT_PER_ROW - 1) / 2.0) * step
            key = (n, -abs(mid - cmed))
            if bestsc is None or key > bestsc:
                bestsc, bestwin = key, win
        sd = gf[y0:y1, :].std(axis=0)
        sd_thr = 0.25 * float(np.median(sd[int(0.2 * W):int(0.8 * W)]))
        final = []
        for k in bestwin:
            v = c0 + k * step
            if v < 6 or v > W - 6 or sd[int(min(W - 1, max(0, v)))] < sd_thr:
                continue
            s = kidx.get(k)
            if s is not None:
                conf = 0.75 if s["dip"] >= 8 else 0.55
                final.append({"cx": s["cx"], "w": gw, "conf": conf, "ev": "measured",
                              "dip": s["dip"], "ncc": s["ncc"]})
            else:
                final.append({"cx": float(v), "w": gw, "conf": 0.3, "ev": "extrapolated",
                              "dip": 0.0, "ncc": 0.0})
        final.sort(key=lambda f: f["cx"])
        d[tag]["n_final"] = len(final)
        d[tag]["n_extrapolated"] = sum(1 for f in final if f["ev"] == "extrapolated")
        d[tag]["lattice_c0"] = round(c0, 1)
        d[tag]["lattice_step"] = round(step, 1)
        for f in final:
            slots.append({"tag": tag, **f})
    return {"rows": rows, "slots": slots, "diag": d}


def slots_to_boxes(res: dict, H: int, W: int) -> tuple[list[dict], list[str]]:
    """槽位 → 轴对齐框 (横平竖直), 附合法性断言"""
    boxes, bad = [], []
    for i, s in enumerate(sorted(res["slots"], key=lambda z: (0 if z["tag"] == "up" else 1, z["cx"]))):
        y0, y1 = res["rows"][s["tag"]]
        w = float(np.clip(s["w"], 10, 120))
        x1, x2 = s["cx"] - w / 2.0, s["cx"] + w / 2.0
        x1, x2 = max(1.0, x1), min(W - 1.0, x2)
        y0c, y1c = max(1.0, y0), min(H - 1.0, y1)
        if (x2 - x1) < W_MIN or (y1c - y0c) < W_MIN or (x2 - x1) > W_MAX or (y1c - y0c) > W_MAX:
            bad.append("slot_%02d 尺寸非法 %.0fx%.0f" % (i + 1, x2 - x1, y1c - y0c))
            continue
        boxes.append({
            "label": "slot_%02d" % (i + 1),
            "origin": ORIGIN,
            "kind": "slot_geom",
            "xyxy": [round(x1, 1), round(y0c, 1), round(x2, 1), round(y1c, 1)],
            "conf": round(float(s["conf"]), 2),
            "ev": s["ev"],
            "dip": round(float(s["dip"]), 1),
            "ncc": round(float(s["ncc"]), 2),
            "row": s["tag"],
            "note": ("槽位实测(剖面色阶 %.1f)" % s["dip"]) if s["ev"] == "measured" else "格点外推(该槽被遮挡/证据弱)",
        })
    return boxes, bad


# ══════════════════ 3. YOLO ══════════════════
class Detector:
    def __init__(self, weights: str, conf: float, device: str = "0"):
        from ultralytics import YOLO
        self.m = YOLO(weights)
        self.conf = conf
        self.device = device
        self.names = self.m.names
        self.err = ""
        self.ms = 0.0

    def run(self, bgr: np.ndarray) -> tuple[list[dict], list[str]]:
        """ultralytics 吃 BGR numpy (cv2.imread 直出), 传 RGB 会 0 框"""
        t0 = time.time()
        try:
            r = self.m.predict(bgr, conf=self.conf, imgsz=640, device=self.device, verbose=False)[0]
        except Exception as e:
            self.err = str(e)[:160]
            return [], ["YOLO 推理失败: %s" % self.err]
        self.ms = (time.time() - t0) * 1000.0
        self.err = ""
        out, bad = [], []
        if r.boxes is None:
            return [], bad
        for b in r.boxes:
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
            cf = float(b.conf[0]) if b.conf is not None else 0.0
            cid = int(b.cls[0]) if b.cls is not None else -1
            nm = self.names.get(cid, str(cid)) if isinstance(self.names, dict) else str(cid)
            if (x2 - x1) < W_MIN or (y2 - y1) < W_MIN or (x2 - x1) > W_MAX or (y2 - y1) > W_MAX:
                bad.append("module 尺寸非法 %.0fx%.0f (conf %.2f)" % (x2 - x1, y2 - y1, cf))
                continue
            out.append({"label": "mod_%s" % nm, "origin": ORIGIN, "kind": "optical_module",
                        "xyxy": [round(max(1.0, x1), 1), round(max(1.0, y1), 1),
                                 round(min(bgr.shape[1] - 1.0, x2), 1), round(min(bgr.shape[0] - 1.0, y2), 1)],
                        "conf": round(cf, 3), "cls": cid, "ev": "detected",
                        "note": "在役 yolo_peg_live.pt 检测 (%s, conf>=%.2f)" % (nm, self.conf)})
        return out, bad


# ══════════════════ 4. 写 spec (只动 origin==l5live) ══════════════════
def write_spec(boxes: list[dict], status: dict, spec_path: Path | None = None) -> dict:
    spec_path = spec_path or SPEC
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    cams = spec.setdefault("cameras", {})
    cam = cams.setdefault("arm", {})
    old = cam.get("boxes") or []
    kept = [b for b in old if b.get("origin") != ORIGIN]
    cam["boxes"] = kept + boxes
    bo = cam.setdefault("by_origin", {})
    bo[ORIGIN] = len(boxes)
    spec["l5live"] = status
    spec["ts"] = time.time()
    spec["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = spec_path.with_suffix(".l5tmp")
    tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, spec_path)
    return {"kept": len(kept), "mine": len(boxes), "spec": str(spec_path)}


# ══════════════════ 5. 一轮 ══════════════════
def one_cycle(det: Detector | None, args, state: dict) -> dict:
    spec_path = Path(args.spec)
    t0 = time.time()
    img, src, lat, note = fetch_frame(args.http, args.fallback, args.timeout)
    status = {"ts": time.strftime("%H:%M:%S"), "src": src, "fetch_ms": round(lat * 1000, 1)}
    if note:
        status["frame_note"] = note
    if img is None:
        status.update({"ok": False, "why": "取帧失败(Orin 8792 + 本地 8791 都不通)"})
        state["fail"] = state.get("fail", 0) + 1
        if not args.dry:
            write_spec([], status, spec_path)
        return status
    H, W = img.shape[:2]
    t1 = time.time()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    boxes, bad = [], []
    diag = {}
    res = None
    try:
        res = detect_slots(gray, diag)
    except Exception as e:
        status["slot_err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    acc = [t for t in ("up", "lo") if (diag.get(t) or {}).get("accepted")]
    if res is None or not acc:
        why = diag.get("reason") or "; ".join(
            "%s: %s" % (t, (diag.get(t) or {}).get("reject", "行未通过证据门槛")) for t in ("up", "lo"))
        status["slot_state"] = "未检出(治具不可见/行结构不成对) — %s" % why
        status["rows"] = {t: ((diag.get(t) or {}).get("y")) for t in ("up", "lo")}
    else:
        sb, sbad = slots_to_boxes(res, H, W)
        boxes += sb
        bad += sbad
        status["slot_state"] = "槽位 %d/14 (实测 %d 外推 %d, 行 %s)" % (
            len(sb),
            sum(1 for b in sb if b.get("ev") == "measured"),
            sum(1 for b in sb if b.get("ev") == "extrapolated"), "+".join(acc))
        for t in ("up", "lo"):
            dd = diag.get(t) or {}
            if dd:
                status["row_" + t] = {"pitch": dd.get("pitch"), "w": dd.get("groove_w"),
                                      "measured": dd.get("n_measured"), "box": len(
                                          [b for b in sb if b.get("row") == t])}
    t2 = time.time()
    if det is not None:
        try:
            mb, mbad = det.run(img)
            boxes += mb
            bad += mbad
            status["module_state"] = "光模块 %d (最高 conf %.2f)" % (
                len(mb), max([b["conf"] for b in mb], default=0.0))
            status["yolo_ms"] = round(det.ms, 1)
        except Exception as e:
            status["module_state"] = "YOLO 异常: %s" % str(e)[:100]
    t3 = time.time()
    status.update({"ok": True, "n_boxes": len(boxes), "bad": bad,
                   "slot_ms": round((t2 - t1) * 1000, 1), "yolo_ms_total": round((t3 - t2) * 1000, 1),
                   "cycle_ms": round((t3 - t0) * 1000, 1)})
    if diag:
        status["anchors"] = diag.get("anchors")
        status["rows"] = {k: diag.get(k, {}).get("y") for k in ("up", "lo")}
    if not args.dry:
        info = write_spec(boxes, status, spec_path)
        status["spec"] = info
    state["fail"] = 0
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", default="http://192.168.23.66:8792/frame.jpg")
    ap.add_argument("--fallback", default="http://127.0.0.1:8791/snapshot/arm.jpg")
    ap.add_argument("--weights", default=str(REPO / "models" / "yolo_peg_live.pt"))
    ap.add_argument("--conf", type=float, default=0.20, help="低置信也保留但如实标 conf")
    ap.add_argument("--device", default="0")
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--probe", action="store_true", help="单次测量: 打印+出图, 不写 spec")
    ap.add_argument("--frames", type=int, default=1, help="probe 帧数")
    ap.add_argument("--probe-img", default="", help="直接量测这张图 (不联网)")
    ap.add_argument("--dry", action="store_true", help="不写 spec (演练)")
    ap.add_argument("--spec", default=str(SPEC), help="写哪份规格 (演练/取证时可指副本, 不碰老倪在看的那份)")
    ap.add_argument("--no-yolo", action="store_true")
    ap.add_argument("--log", default=str(OUT / "l5_live_mark.log"))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    det = None
    if not args.no_yolo:
        try:
            det = Detector(args.weights, args.conf, args.device)
            print("[l5live] YOLO 就绪 classes=%s weights=%s" % (det.names, args.weights))
            w0 = time.time()
            det.run(np.zeros((480, 640, 3), np.uint8))
            print("[l5live] YOLO 预热 %.0fms (首帧最慢), 稳定 %.0fms/帧" % ((time.time() - w0) * 1000, det.ms))
        except Exception as e:
            print("[l5live] YOLO 加载失败(仍跑槽位): %s" % e)

    if args.probe:
        for k in range(max(1, args.frames)):
            if args.probe_img:
                img = cv2.imread(args.probe_img)
                src = Path(args.probe_img).name
                lat = 0.0
            else:
                img, src, lat, _n = fetch_frame(args.http, args.fallback, args.timeout)
            if img is None:
                print("取帧失败"); return 2
            H, W = img.shape[:2]
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            diag = {}
            res = detect_slots(gray, diag)
            print("── 帧 %s %dx%d 来源=%s" % (src, W, H, src))
            print("   锚线 E_peaks:", diag.get("E_peaks"))
            print("   锚点:", diag.get("anchors"), "reason:", diag.get("reason"))
            boxes, bad = [], []
            if res:
                for tag in ("up", "lo"):
                    print("   %s: %s" % (tag, {k: v for k, v in diag.get(tag, {}).items()}))
                boxes, bad = slots_to_boxes(res, H, W)
            vis = img.copy()
            for b in boxes:
                x1, y1, x2, y2 = [int(v) for v in b["xyxy"]]
                col = (0, 255, 255) if b["ev"] == "measured" else (255, 128, 0)
                cv2.rectangle(vis, (x1, y1), (x2, y2), col, 2)
                cv2.putText(vis, b["label"], (x1, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1)
            if det is not None:
                mb, mbad = det.run(img)
                for b in mb:
                    x1, y1, x2, y2 = [int(v) for v in b["xyxy"]]
                    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(vis, "%s %.2f" % (b["label"], b["conf"]), (x1, y1 - 3),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
                    print("   YOLO:", b["label"], b["conf"], b["xyxy"])
                print("   YOLO %d 框 %.0fms" % (len(mb), det.ms))
            p = OUT / ("probe_%s.jpg" % time.strftime("%H%M%S"))
            cv2.imwrite(str(p), vis, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            print("   槽位框 %d 个: %s" % (len(boxes), [b["xyxy"] for b in boxes]))
            print("   非法框:", bad)
            print("   -> 出图", p)
        return 0

    # ── 常驻循环 ──
    state = {}
    print("[l5live] 常驻启动 hz=%.1f → spec %s" % (args.hz, SPEC))
    every = max(0.05, 1.0 / args.hz)
    last_log = 0.0
    while True:
        t0 = time.time()
        try:
            st = one_cycle(det, args, state)
        except Exception as e:
            st = {"ok": False, "why": "周期异常 %s" % str(e)[:200], "tb": traceback.format_exc()[-500:]}
            try:
                write_spec([], {"ts": time.strftime("%H:%M:%S"), "ok": False, "why": st["why"]}, Path(args.spec))
            except Exception:
                pass
        if time.time() - last_log > 5.0 or not st.get("ok"):
            last_log = time.time()
            print("[%s] %s" % (time.strftime("%H:%M:%S"), json.dumps(st, ensure_ascii=False)[:400]),
                  flush=True)
        dt = time.time() - t0
        time.sleep(max(0.0, every - dt))


if __name__ == "__main__":
    sys.exit(main())
