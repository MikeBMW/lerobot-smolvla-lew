#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_intent_marks.py — 验"前进意图"装饰(起点实心点 / 末端箭头 / 沿程渐变)**真的落笔了**
════════════════════════════════════════════════════════════════════════════
判据用技能里的那条规矩: **同帧 A/B**(同一张原帧 + 同一个 TCP), 只切换 `ZMAX_INTENT`,
逐像素差 = 装饰自己的贡献; 颜色类指标只在"该颜色确属被测对象"时才有意义
(plan 层 origin 色 = (255,255,255), 它的纯白像素 r>250&g>250&b>250 就是管道高光/圆帽/箭头/起点点)。

只读: 只取帧 + 渲染, 不写叠加规格、不动任何服务。

用法:
  ./gui-venv311/bin/python tools/verify_intent_marks.py                       # 用**当前真机 TCP**
  ./gui-venv311/bin/python tools/verify_intent_marks.py --pose observe        # 用观察位(离线: 臂回位时的样子)
  ./gui-venv311/bin/python tools/verify_intent_marks.py --out-dir /tmp/xx
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import scene_overlay as SO                                                        # noqa: E402

OBSERVE = [0.46268, 0.19809, 0.33952]
DEFAULT_OUT = "/home/ubuntu/.hermes/cache/scratch"
SPEC = SO.SPEC_PATH


def white_stats(img, r_lo=250):
    import cv2
    H, W = img.shape[:2]
    r, g, b = img[:, :, 2].astype(int), img[:, :, 1].astype(int), img[:, :, 0].astype(int)
    m = ((r > r_lo) & (g > r_lo) & (b > r_lo)).astype(np.uint8)
    half = m.copy(); half[:H // 2, :] = 0
    out = {"white_total": int(m.sum()), "white_lower_half": int(half.sum())}
    for nm, mm in (("total", m), ("lower_half", half)):
        if mm.sum() == 0:
            out["max_cc_" + nm] = 0
            continue
        n, _l, st, _c = cv2.connectedComponentsWithStats(mm, connectivity=8)
        out["max_cc_" + nm] = max(int(st[i, cv2.CC_STAT_AREA]) for i in range(1, n)) if n > 1 else 0
    return out


def render(tcp7, tag, out_dir, base_frame, drop_plan=False):
    """渲染一遍(当前 INTENT 环境)并落到 out_dir。返回 (img, info, white)。drop_plan=True ⇒ 去掉 plan 层。"""
    import copy
    import cv2
    spec = SO.load_spec()
    if drop_plan:
        sp2 = copy.deepcopy(spec)
        cam = (sp2.get("cameras") or {}).get("arm") or {}
        cam["boxes"] = [b for b in (cam.get("boxes") or []) if b.get("origin") != "plan"]
        spec = sp2
    img = cv2.imread(base_frame)
    img2, info = SO.draw_overlay(img.copy(), spec, "arm", tcp7, {"note": "intent A/B · %s" % tag})
    p = os.path.join(out_dir, "intent_%s.jpg" % tag)
    cv2.imwrite(p, img2)
    return img2, info, white_stats(img2), p


def plan_attributable(img_on, img_off, col=(255, 255, 255), tol=8):
    """**plan 自己的**像素: 用"有/无 plan 层"同帧差定位, 再在差掩膜里数该 origin 原色的像素。
    返回 (plan 掩膜像元数, 其中纯白像素数, 纯白最大连通域, 下半部纯白数, 下半部最大连通域)。"""
    import cv2
    d = (np.abs(img_on.astype(int) - img_off.astype(int)).sum(2) > 25)
    d[-90:, :] = False                                    # 底部真值带(i 计数文字不同)不计
    im = img_on.astype(int)
    white = ((im[:, :, 2] > 250) & (im[:, :, 1] > 250) & (im[:, :, 0] > 250))
    pm = (d & white).astype(np.uint8)
    H, W = pm.shape
    half = pm.copy(); half[:H // 2, :] = 0

    def cc(m):
        if m.sum() == 0:
            return 0
        n, _l, st, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
        return max(int(st[i, cv2.CC_STAT_AREA]) for i in range(1, n)) if n > 1 else 0
    return {"plan_mask_px": int(d.sum()), "plan_white_px": int(pm.sum()),
            "plan_white_max_cc": cc(pm), "plan_white_lower_half": int(half.sum()),
            "plan_white_max_cc_lower_half": cc(half)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="live", choices=["live", "observe"])
    ap.add_argument("--frame", default="", help="基底原帧(缺省取 8791 /snapshot/arm.jpg)")
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    if not a.frame:
        r = subprocess.run(["curl", "-s", "-o", "/tmp/verify_intent_base.jpg", "--max-time", "20",
                            "http://127.0.0.1:8791/snapshot/arm.jpg"], capture_output=True, text=True)
        a.frame = "/tmp/verify_intent_base.jpg"
    if not os.path.isfile(a.frame) or os.path.getsize(a.frame) < 5000:
        print("✗ 取不到基底原帧 %s" % a.frame); return 2

    if a.pose == "observe":
        tcp = np.array(list(OBSERVE) + [0.0, 0.0, 0.0, 1.0])
        # 姿态用当前真机的(位置=观察位真值) —— 位置才是几何主因
        cur = SO.read_tcp()
        if cur is not None:
            tcp[3:7] = cur[3:7]
        src = "观察位真值(离线渲染, 姿态沿用当前真机)"
    else:
        cur = SO.read_tcp()
        if cur is None:
            print("✗ 读不到真机 TCP"); return 2
        tcp, src = cur, "当前真机 TCP(实时)"
    print("─" * 78)
    print("意图装饰同帧 A/B · 位姿来源 = %s" % src)
    print("  TCP = [%s]" % ", ".join("%.5f" % v for v in tcp))
    print("  基底帧 = %s (%d B)" % (a.frame, os.path.getsize(a.frame)))

    # off → on(用 reload 让 INTENT_ON 重新读环境变量)
    os.environ["ZMAX_INTENT"] = "0"
    importlib.reload(SO)
    img_off, info_off, w_off, p_off = render(tcp, "off", a.out_dir, a.frame)
    os.environ["ZMAX_INTENT"] = "1"
    importlib.reload(SO)
    img_on, info_on, w_on, p_on = render(tcp, "on", a.out_dir, a.frame)

    diff = (np.abs(img_on.astype(int) - img_off.astype(int)).sum(2) > 25)
    d_no_band = diff.copy(); d_no_band[-90:, :] = False          # 底部真值带(文案不同)不计
    H, W = img_on.shape[:2]
    ys, xs = np.where(diff)
    print("\n── 同帧 A/B 结果 ──")
    print("  差异像素: 整帧 %d · 去掉底部真值带 %d" % (int(diff.sum()), int(d_no_band.sum())))
    if len(xs):
        print("  差异包围盒: x[%d..%d] y[%d..%d]" % (xs.min(), xs.max(), ys.min(), ys.max()))
    print("  亮白像素(r>250&g>250&b>250): 关装饰 整帧 %d/下半部 %d · 开装饰 整帧 %d/下半部 %d (Δ整帧 %+d)"
          % (w_off["white_total"], w_off["white_lower_half"], w_on["white_total"],
             w_on["white_lower_half"], w_on["white_total"] - w_off["white_total"]))
    print("  最大连通域: 关装饰 %d px → 开装饰 %d px (整帧)"
          % (w_off["max_cc_total"], w_on["max_cc_total"]))
    plan_on = [d for d in info_on["drawn"] if d["origin"] == "plan"]
    print("  plan 元素: %s" % (plan_on[0] if plan_on else "(未绘制)"))
    # plan 自己的像素(有/无 plan 层同帧差)
    _img_np, _i_np, _w_np, p_np = render(tcp, "noplan", a.out_dir, a.frame, drop_plan=True)
    pa = plan_attributable(img_on, _img_np)
    print("\n── plan 层贡献(同帧: 有 plan vs 去 plan) ──")
    print("  plan 掩膜 %d px · 其中**纯白 %d px** · 纯白最大连通域 **%d px** · 下半部纯白 %d px(最大连通域 %d)"
          % (pa["plan_mask_px"], pa["plan_white_px"], pa["plan_white_max_cc"],
             pa["plan_white_lower_half"], pa["plan_white_max_cc_lower_half"]))
    print("  去 plan 基底帧亮白: 整帧 %d · 下半部 %d" % (_w_np["white_total"], _w_np["white_lower_half"]))
    for b in info_on["boxes"]:
        if b.get("origin") == "plan":
            print("  plan 渲染元数据: n_seg=%s · 管径%s px · intent=%s · 意图标记 %s 个 · 像素盒 %s · 被裁=%s"
                  % (b.get("n_seg"), b.get("tube_px"), b.get("intent"), b.get("n_intent_marks"),
                     [round(v) for v in (b.get("xyxy") or [])], b.get("clipped")))
    print("  图: %s | %s" % (p_on, p_off))
    ev = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "pose_src": src,
          "tcp": [round(float(v), 6) for v in tcp], "base_frame": a.frame,
          "diff_px": int(diff.sum()), "diff_px_excl_band": int(d_no_band.sum()),
          "white_off": w_off, "white_on": w_on, "img_on": p_on, "img_off": p_off,
          "plan_drawn": plan_on}
    ep = os.path.join(a.out_dir, "intent_marks_evidence.json")
    with open(ep, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    print("  证据: %s" % ep)
    print("─" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
