#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""s2_reality_gap.py — S2 策略自进化·第一步: 真机↔仿真 观测分布差距量化 (零真机动作)

思路 (L5 章程 §3-C): 无外部真值也能进化 —— 用"真机只读 tap 的观测分布" vs "引擎仿真的观测分布"
  逐维对比 (mean/std/KS), 找出**哪些维度真机与仿真不同源** ⇒ 这就是 RealityGap 的坐标;
  策略的自进化方向 = 对漂移维度做输入重标定 / 域随机化, 而不是等人给标定。
数据源 (已有): 真机 tap jsonl (只读) · 引擎 trace (仿真同源 h5)
判据: 报每维 |Δmean|/std 与 KS 统计量, 标出漂移最大的前几维 + 该维可否用已有量重建
用法: ./gui-venv311/bin/python tools/s2_reality_gap.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

R = "/home/ubuntu/zmax_rel"
TAP = sorted(glob.glob("/home/ubuntu/zmax_rel/data/**/state_*.jsonl", recursive=True) +
             glob.glob("/home/ubuntu/tap/state_*.jsonl") + glob.glob("/home/ubuntu/zmax_data/**/state_*.jsonl", recursive=True))
H5 = "/home/ubuntu/stable-wm-cache/datasets/cog_engine_trace_v3.h5"


def load_real(n=4000):
    """从 tap jsonl 取最近 n 帧的可映射字段 (tcp xyz + gripper + jpos6)"""
    if not TAP:
        return None
    f = max(TAP, key=os.path.getmtime)
    rows = []
    with open(f, encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            try:
                d = json.loads(ln)
            except Exception:                                                    # noqa: BLE001
                continue
            tcp = d.get("tcp") or d.get("tcp_pose")
            jp = d.get("jpos") or d.get("joints")
            gp = d.get("gripper")
            if tcp and len(tcp) >= 3:
                rows.append(list(tcp[:3]) + ([float(gp)] if gp is not None else [float("nan")]) +
                            list(jp[:6]) if jp else list(tcp[:3]) + [float("nan")])
    rows = rows[-n:]
    return (np.array(rows, dtype=float), os.path.basename(f), len(rows)) if rows else None


def main() -> int:
    print("═══ S2 RealityGap 量化 (真机只读 vs 仿真引擎) ═══")
    real = load_real()
    if real is None:
        print("❌ 未找到真机 tap jsonl → 换路径再试"); return 1
    Rr, fname, n = real
    print("真机: %s · 取 %d 帧 · 列 = [tcp_x, tcp_y, tcp_z, gripper, j1..j6]" % (fname, n))
    print("  真机 mean = %s" % np.round(np.nanmean(Rr, 0), 4).tolist()[:4])
    print("  真机 std  = %s" % np.round(np.nanstd(Rr, 0), 4).tolist()[:4])
    if not os.path.isfile(H5):
        print("仿真 h5 不在 → 仅报真机分布"); return 0
    import h5py
    with h5py.File(H5, "r") as f:
        obs = f["observation"][:] if "observation" in f else None
    if obs is None:
        print("h5 无 observation → 仅报真机分布"); return 0
    S = np.array(obs, dtype=float)
    print("\n仿真 h5: observation %s · %d 帧" % (S.shape, S.shape[0]))
    print("  仿真 mean(前4) = %s" % np.round(S.mean(0), 4).tolist()[:4])
    print("  仿真 std (前4) = %s" % np.round(S.std(0), 4).tolist()[:4])
    # 比较可映射维 (前 3 = 位置量级; 第 4 = 夹爪)
    print("\n═══ 逐维漂移 (真机 vs 仿真, 前 4 维) ═══")
    for i in range(min(4, Rr.shape[1], S.shape[1])):
        rm, rs = np.nanmean(Rr[:, i]), np.nanstd(Rr[:, i])
        sm, ss = S[:, i].mean(), S[:, i].std()
        z = abs(rm - sm) / (ss + 1e-9)
        print("  维%d: 真机 %.4f±%.4f | 仿真 %.4f±%.4f → |Δmean|/σ_sim = %.2f%s"
              % (i, rm, rs, sm, ss, z, "  ⚠️ 漂移大" if z > 1.0 else ""))
    print("\n判读: |Δmean|/σ_sim > 1 的维度 = 真机与仿真**不同源**, 是策略上真机失败的首因候选")
    print("  下一步(自进化): 对这些维做输入重标定(用真机分布的 mean/std) 或域随机化, 再回引擎闭环复测成功率")
    out = os.path.join(R, "data/selfcal/reality_gap_%s.json" % __import__("time").strftime("%Y%m%d_%H%M%S"))
    json.dump({"tap_file": fname, "n_real": int(n), "real_mean4": np.round(np.nanmean(Rr, 0), 6).tolist()[:4],
               "real_std4": np.round(np.nanstd(Rr, 0), 6).tolist()[:4],
               "sim_shape": list(S.shape), "sim_mean4": np.round(S.mean(0), 6).tolist()[:4],
               "sim_std4": np.round(S.std(0), 6).tolist()[:4]},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  台账: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
