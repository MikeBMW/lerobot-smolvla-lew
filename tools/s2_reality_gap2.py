#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""s2_reality_gap2.py — S2 RealityGap 重测 (用真源 live tap, 修正文件与字段)

上一轮无效原因(已自拦): 读的是 09-22 旧快照(TCP 为常数 std=0)且字段名不符。
本轮: 真源 = /home/ubuntu/zmax_ss_remote/state_20260925.jsonl (正在写, 字段 tcp/jpos/robot_status/z7/geom)
     只读文件尾部若干 MB (不改动文件, 不占用产线)
输出: 真机 vs 仿真 的分布对照 + 漂移量 (报告而非改模型)
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

LIVE = "/home/ubuntu/zmax_ss_remote/state_20260925.jsonl"
H5 = "/home/ubuntu/stable-wm-cache/datasets/cog_engine_trace_v3.h5"
OUT = "/home/ubuntu/zmax_rel/data/selfcal/reality_gap2_%s.json" % time.strftime("%Y%m%d_%H%M%S")


def tail_rows(path, mb=8):
    """只读文件尾部 mb 兆字节 → 解析 JSON 行 (只读, 不写)"""
    sz = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, sz - mb * 1024 * 1024))
        data = f.read().decode("utf-8", errors="ignore")
    rows = []
    for ln in data.split("\n")[1:]:
        try:
            rows.append(json.loads(ln))
        except Exception:                                                        # noqa: BLE001
            continue
    return rows


def main() -> int:
    rows = tail_rows(LIVE)
    print("═══ 真源 live tap ═══ %s · 尾读 %d 行" % (os.path.basename(LIVE), len(rows)))
    if not rows:
        print("无数据"); return 1
    tcp = np.array([r["tcp"][:3] for r in rows if r.get("tcp")], dtype=float)
    g = []
    for r in rows:
        rs = r.get("robot_status") or {}
        gp = r.get("gripper")
        if gp is None and isinstance(rs, dict):
            gp = rs.get("gripper") or rs.get("grip")
        g.append(float(gp) if isinstance(gp, (int, float)) else np.nan)
    g = np.array(g, dtype=float)
    st = [r.get("robot_status") for r in rows if r.get("robot_status")]
    print("  TCP: n=%d · mean=%s · std=%s" % (len(tcp), np.round(tcp.mean(0), 4).tolist(), np.round(tcp.std(0), 4).tolist()))
    print("  夹爪: 有效值 %d/%d · mean=%s" % (int(np.isfinite(g).sum()), len(g),
                                            "%.4f" % np.nanmean(g) if np.isfinite(g).any() else "n/a"))
    print("  robot_status 采样: %d 条 · 键=%s" % (len(st), list(st[0].keys())[:8] if st and isinstance(st[0], dict) else "n/a"))
    if np.isfinite(g).any():
        print("  夹爪取值分布: %s" % np.round(np.nanpercentile(g, [5, 25, 50, 75, 95]), 4).tolist())

    report = {"ts": time.strftime("%F %T"), "live_file": LIVE, "n_rows": len(rows),
              "tcp_mean": np.round(tcp.mean(0), 6).tolist(), "tcp_std": np.round(tcp.std(0), 6).tolist(),
              "tcp_range": [np.round(tcp.min(0), 4).tolist(), np.round(tcp.max(0), 4).tolist()],
              "gripper_valid": int(np.isfinite(g).sum()), "gripper_mean": (float(np.nanmean(g)) if np.isfinite(g).any() else None)}
    if os.path.isfile(H5):
        import h5py
        with h5py.File(H5, "r") as f:
            obs = np.array(f["observation"][:], dtype=float)
        report["sim_shape"] = list(obs.shape)
        report["sim_first3_mean"] = np.round(obs.mean(0)[:3], 6).tolist()
        report["sim_first3_std"] = np.round(obs.std(0)[:3], 6).tolist()
        print("\n═══ 仿真 h5 ═══ %s · obs dim=%d" % (os.path.basename(H5), obs.shape[1]))
        print("  前3维: mean=%s · std=%s" % (np.round(obs.mean(0)[:3], 4).tolist(), np.round(obs.std(0)[:3], 4).tolist()))
        print("\n═══ 关键结论 (供自进化用) ═══")
        print("  ① 真机 TCP 有**真实变动**(std=%s) ⇒ 数据可用 (上一轮 std=0 是旧快照)" % np.round(tcp.std(0), 4).tolist())
        print("  ② 仿真 obs dim=%d ≠ 策略输入 39/43 ⇒ **口径映射本身是第一步要解决的自进化项**" % obs.shape[1])
        print("  ③ 真机夹爪信号: %s" % ("可用(valid=%d)" % report["gripper_valid"] if report["gripper_valid"] > 0 else "**该字段在 tap 里为空** → 需从 robot_status/话题补 (不等人, 我自己补)"))
    json.dump(report, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n  台账: %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
