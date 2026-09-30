#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_rotate_to.py — 用 C 轴自转技能(≤10°/次)把末端姿态转到目标四元数, 逐步核对 50Hz 真值。

现场口径(2026-09-29): 位置已到位后, 姿态需绕工具轴转回原观察姿态(约176°)。实测 C 轴 = 绕工具轴
自转(位置漂移 0.0mm)。每步读 /tmp/live_motion.jsonl 真值, 任一步不走或位置漂移>10mm 立刻停。
"""
import json, math, os, subprocess, sys, time

FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
TGT_Q = [float(x) for x in sys.argv[1:5]]
MAXSTEP = float(os.environ.get("ROT_STEP", "9"))
TOL = float(os.environ.get("ROT_TOL", "6"))

def live():
    r = subprocess.run(["sudo","docker","exec","ss-remote-tap","bash","-lc","tail -1 /tmp/live_motion.jsonl"],
                       capture_output=True, text=True, errors="replace")
    return json.loads(r.stdout.strip())["tcp"]

def ang(a, b):
    dot = abs(sum(a[i]*b[i] for i in range(4)))
    return math.degrees(2*math.acos(min(1.0, dot)))

def send(skill, **kw):
    c = {"skill": skill}; c.update(kw)
    with open(FIFO, "w") as f: f.write(json.dumps(c, ensure_ascii=False) + "\n")

p0 = live(); P0 = p0[:3]
print("目标 quat:", TGT_Q)
print("起转: pos=%s quat=%s · 与目标差 %.1f°" % ([round(v,5) for v in P0], [round(v,4) for v in p0[3:7]], ang(p0[3:7], TGT_Q)))
d = None
for i in range(30):
    cur = live(); a = ang(cur[3:7], TGT_Q); drift = math.dist(cur[:3], P0)*1000
    print("  #%02d 差 %.1f° · 位置漂移 %.1fmm" % (i, a, drift))
    if a <= TOL: print("✅ 姿态到位(差 %.1f°)"%a); break
    if drift > 10: print("⛔ 位置漂移 %.1fmm > 10mm ⇒ 停"%drift); break
    step = min(MAXSTEP, max(1.0, a - TOL + 2))
    if d is None:
        d = "pos"
        q_before = cur[3:7]
        send("L2.rot_c_pos", deg=round(step,1)); time.sleep(10); cur2 = live()
        if ang(cur2[3:7], TGT_Q) > a - 0.5:      # 没往目标方向走 ⇒ 换向
            d = "neg"; a_before = a
            send("L2.rot_c_neg", deg=round(step,1)); time.sleep(10); cur2 = live()
            if ang(cur2[3:7], TGT_Q) > a_before - 0.5:
                print("⛔ 两个方向都不缩小夹角 ⇒ 停(交诊)"); break
    else:
        send("L2.rot_c_%s" % d, deg=round(step,1)); time.sleep(10)
print("末: pos=%s quat=%s" % ([round(v,5) for v in live()[:3]], [round(v,4) for v in live()[3:7]]))
