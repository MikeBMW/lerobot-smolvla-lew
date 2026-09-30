#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_point_sdk.py — 从 ROKAE SDK 直采源记录示教点 (只读, 不下发任何运动)

为什么不用 tools/record_l2_point.py: 那个走本机 Docker tap 的 /robot/tcp_pose 只读订阅,
新订阅者常收不到(会话陈旧时全 0), 录下去就是坏点位。本工具读**页面同源**的真值:
`rokae_tcp_sampler` → `~/zmax_data/rokae_sdk/tcp_out/latest.json` (xcoreSDK endInRef, 5Hz)。

纪律 (与 record_l2_point.py 同口径, 另加两条):
  · 连续采样 ≥6 帧算均值 + 极差; pos 极差 >1e-4 m = 机械臂还在动 → 拒绝记录;
  · **陈旧/坏值闸**: 帧龄 >2s, 或位置范数 ~0 (全 0 = 会话陈旧) → 拒绝记录;
  · 写库前留痕: `reports/aoi_points/<点名>.history.jsonl` 追加一条 + 旧库 `.bak` 备份。

用法:
  python3 tools/record_point_sdk.py --record 侧面点1 --desc "表面检测观察位(侧面点1)"
  python3 tools/record_point_sdk.py --show                # 只读: 看看当前位姿与稳定性
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("ZMAX_TCP_SDK_SRC",
                     os.path.join(os.path.expanduser("~"), "zmax_data/rokae_sdk/tcp_out/latest.json"))
STORE = os.environ.get("ZMAX_TAUGHT_POINTS",
                       os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json"))
HIST_DIR = os.path.join(ROOT, "reports/aoi_points")

MAX_SPREAD_M = 1e-4          # 位置极差上限: 超过 = 还在动
MAX_AGE_S = 2.0              # 帧龄上限: 超过 = 采样器卡了/陈旧的坏值
MIN_NORM_M = 1e-3            # 位置范数下限: 低于 = 全 0 这类坏值


def _one():
    with open(SRC, encoding="utf-8") as f:
        d = json.load(f)
    return {
        "pos": [float(d["x"]), float(d["y"]), float(d["z"])],
        "quat": [float(d["qx"]), float(d["qy"]), float(d["qz"]), float(d["qw"])],
        "ts": float(d.get("ts") or 0.0),
        "src": str(d.get("src") or ""),
        "frame": str(d.get("frame") or "base_link"),
    }


def sample(n: int = 6, gap: float = 0.35):
    rows = []
    for _ in range(n):
        rows.append(_one())
        time.sleep(gap)
    return rows


def analyse(rows):
    cols = list(zip(*[r["pos"] + r["quat"] for r in rows]))
    mean = [sum(c) / len(c) for c in cols]
    spread = [max(c) - min(c) for c in cols]
    return mean, max(spread[:3]), max(spread[3:])


def vet(rows, mean, spread_pos, spread_quat):
    """返回 (ok, 原因)"""
    age = time.time() - rows[-1]["ts"] if rows[-1]["ts"] else 999.0
    norm = math.sqrt(sum(v * v for v in mean[:3]))
    if age > MAX_AGE_S:
        return False, "帧龄 %.1fs > %.1fs ⇒ 采样器没在更新(别拿陈旧值当示教点)" % (age, MAX_AGE_S)
    if norm < MIN_NORM_M:
        return False, "位置范数 %.2e m ≈ 0 ⇒ 典型\"会话陈旧全 0\"坏值" % norm
    if spread_pos > MAX_SPREAD_M:
        return False, "pos 极差 %.2e m > %.0e ⇒ 机械臂还在动" % (spread_pos, MAX_SPREAD_M)
    return True, "静止(pos 极差 %.2e m ≤ 1e-4) · 帧龄 %.2fs · 源=%s" % (spread_pos, age, rows[-1]["src"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", metavar="点名")
    ap.add_argument("--desc", default="")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--n", type=int, default=6)
    a = ap.parse_args()
    if not (a.record or a.show):
        ap.print_help()
        return 2
    if not os.path.exists(SRC):
        print("❌ 读不到真值源: %s (rokae_tcp_sampler 在跑吗?)" % SRC)
        return 1
    rows = sample(a.n)
    mean, sp, sq = analyse(rows)
    ok, why = vet(rows, mean, sp, sq)
    print("采样 %d 帧 · pos=(%.7f, %.7f, %.7f) · quat(xyzw)=(%.7f, %.7f, %.7f, %.7f)"
          % (len(rows), mean[0], mean[1], mean[2], mean[3], mean[4], mean[5], mean[6]))
    print("极差: pos %.2e m · quat %.2e" % (sp, sq))
    print(("✅ " if ok else "❌ ") + why)
    if a.show or not ok or not a.record:
        return 0 if (ok or a.show) else 1

    try:
        store = json.load(open(STORE, encoding="utf-8"))
    except Exception:
        store = {"version": "v1", "note": "L2 示教绝对点位", "frame": "base_link", "points": {}}
    store.setdefault("points", {})
    os.makedirs(HIST_DIR, exist_ok=True)
    old = store["points"].get(a.record)
    if old:
        with open(os.path.join(HIST_DIR, "%s.history.jsonl" % a.record), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "action": "replaced",
                                "old": old, "new_pos": [round(v, 7) for v in mean[:3]]},
                               ensure_ascii=False) + "\n")
        shutil.copy2(STORE, STORE + ".bak_before_%s_%s"
                     % (a.record, time.strftime("%Y%m%d_%H%M%S")))
    store["points"][a.record] = {
        "pos": [round(v, 7) for v in mean[:3]],
        "quat": [round(v, 7) for v in mean[3:7]],
        "desc": a.desc,
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "ROKAE SDK 直读 endInRef (rokae_tcp_sampler → tcp_out/latest.json, 页面同源)",
        "frame": rows[-1]["frame"],
        "n_samples": len(rows),
        "spread_pos_m": round(sp, 8),
        "spread_quat": round(sq, 8),
    }
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    ctx = os.path.join(HIST_DIR, "%s.json" % a.record)
    with open(ctx, "w", encoding="utf-8") as f:
        json.dump({"point": a.record, "recorded_at": store["points"][a.record]["recorded_at"],
                   "pos": store["points"][a.record]["pos"], "quat": store["points"][a.record]["quat"],
                   "source": store["points"][a.record]["source"], "desc": a.desc},
                  f, ensure_ascii=False, indent=1)
    print("✅ 已记录点位 %s → %s" % (a.record, STORE))
    print(json.dumps(store["points"][a.record], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
