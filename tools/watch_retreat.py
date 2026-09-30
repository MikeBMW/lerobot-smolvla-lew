#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_retreat.py — 只读观察窗: 看(不下发)老倪手动退让危险点的全过程。
规矩(2026-10-01 老倪: 「我先做, 你先看」): 危险点/新点位一律他先操作, 本脚本只读真值 + 只打印。
数据源 = 页面同源 rokae_sdk/tcp_out/latest.json (xcoreSDK endInRef, 5Hz)。
输出: 运动段(分段) · 每段四轴净位移与方向 · 峰值/平均速度 · 起止位姿 · 停顿判据。
"""
import json, math, os, sys, time

P = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
STEP = 0.28
QUIET_S = 4.0          # 连续静止这么久 ⇒ 认为一段结束


def rd():
    try:
        d = json.load(open(P))
        return (d["x"], d["y"], d["z"], math.degrees(d["rx"]), math.degrees(d["ry"]), math.degrees(d["rz"]),
                float(d["ts"]), time.time() - float(d["ts"]))
    except Exception:
        return None


def label(dp):
    out = []
    names = ["前后(X)", "左右(Y)", "升降(Z)"]
    for i, n in enumerate(names):
        if abs(dp[i]) < 1.0:
            continue
        if i == 0:
            out.append("前+X" if dp[0] > 0 else "后−X")
        elif i == 1:
            out.append("左+Y" if dp[1] > 0 else "右−Y")
        else:
            out.append("升+Z" if dp[2] > 0 else "降−Z")
    return "/".join(out) if out else "原地(仅姿态)"


print("👀 只读观察窗 %.0fs —— 不下发任何指令 (规矩: 危险点他先做, 我只看着)" % DUR)
print("   源: %s" % P)
t0 = time.time()
last = rd()
if last:
    print("   起  pos=(%.4f, %.4f, %.4f) abc=(%.2f, %.2f, %.2f)" % last[:6])
S = []
segs = []            # [start_sample, end_sample, dist_mm, peak_speed]
cur = None
lastmove = t0
while time.time() - t0 < DUR:
    c = rd()
    if c:
        S.append((time.time() - t0, c))
        if last:
            d = math.dist(c[:3], last[:3]) * 1000
            dt = max(1e-6, S[-1][0] - (S[-2][0] if len(S) > 1 else 0))
            if d > 0.05:
                if cur is None:
                    cur = [S[-1], S[-1], 0.0, 0.0, 0.0]
                cur[1] = S[-1]
                cur[2] += d
                cur[3] = max(cur[3], d / dt)
                lastmove = time.time()
        if cur is not None and (time.time() - lastmove) > QUIET_S:
            segs.append(cur)
            cur = None
    last = c or last
    time.sleep(STEP)
if cur is not None:
    segs.append(cur)
print("   止  pos=(%.4f, %.4f, %.4f) abc=(%.2f, %.2f, %.2f)" % tuple(S[-1][1][:6]) if S else "   止  (无样本)")
print("   采样 %d 点 · 真值帧龄 %.2f~%.2fs" % (len(S), min(s[1][7] for s in S), max(s[1][7] for s in S)) if S else "")
print("   ── 检出 %d 段动作 ──" % len(segs))
tot = 0.0
for i, g in enumerate(segs, 1):
    a, b = g[0][1], g[1][1]
    dp = [(b[k] - a[k]) * 1000 for k in range(3)]
    da = [b[k] - a[k] for k in (3, 4, 5)]
    tot += g[2]
    print("   段%d: %s → 行程 %.1fmm · 净位移 Δ=(%+.1f, %+.1f, %+.1f)mm · 姿态Δ=(%+.2f,%+.2f,%+.2f)° · 峰值 %.1fmm/s"
          % (i, label(dp), g[2], dp[0], dp[1], dp[2], da[0], da[1], da[2], g[3]))
print("   ── 合计行程 %.1f mm ──" % tot)
