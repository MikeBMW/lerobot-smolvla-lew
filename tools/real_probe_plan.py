#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_probe_plan.py — S0「探针运动」计划生成 + 可辨识性预检 (**不连机器人, 不下发任何动作**)

老倪 2026-09-18: 「根据真机 + L2 + 训练模式, 自动根据机器人动作学习。」
这是 S0 的"该走哪些位姿"的**可离线验证**那一半: 机器人不在线也能把计划算出来并自检;
上线后由操作者/带闸门的驱动按计划走位姿, 采图+真值 → real_autolabel.py --probe 出自标定。

为什么位姿要这么挑 (每条都是演练里真跑出来的, 不是推的):
  · **非共面**: 只在正对相机的平面上平移 → DLT 病态, 反解出的 K 为 0 (实测 rms 244px)。
    所以计划里必须带真实深度变化 (本工具默认 60~130mm)。
  · **带姿态变化**: 只平移时, "模块偏移给错"会被 DLT 自洽吸收而不报错 (实测 rms 1.64px 看着很好,
    盲测误差 35px)。加 ±16° 以上姿态变化, 误差才会暴露在验证位姿上。
  · **步距适中**: 相邻位姿在画面里要动 ~20~40px (太小差分没有运动域, 太大对称差会跑出模块区域)。
  · **覆盖画面**: 3x3 栅格 + 3 个不同深度的点, 让点对分布开。

用法:
  python3 tools/real_probe_plan.py --tcp 0.30,0.05,0.10            # 只出计划 + 自检 (默认)
  python3 tools/real_probe_plan.py                                  # 从旁路真值读当前 TCP
  python3 tools/real_probe_plan.py --tcp ... --out plan.json --safe-box 0.15,0.75,-0.35,0.35,0.0,0.5
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

SS_REMOTE = os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote")

# 默认工作域 (base_link, 米): x 前 y 左 z 上。**必须现场按实际可达空间改**, 越界即拒。
SAFE_BOX = (0.10, 0.80, -0.45, 0.45, -0.05, 0.70)
# 位姿表: (dx, dy, dz) 相机/工具系近似下的相对位移 (米) —— 3x3 正对栅格 + 3 个深度
GRID_MM = 40.0
DEPTHS_MM = (0.0, 55.0, 55.0, 110.0, 110.0)
TILT_DEG = 16.0


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def axis_quat(axis, deg):
    ax = np.asarray(axis, float)
    ax = ax / (np.linalg.norm(ax) or 1.0)
    h = math.radians(deg) / 2.0
    return [float(ax[0] * math.sin(h)), float(ax[1] * math.sin(h)), float(ax[2] * math.sin(h)), math.cos(h)]


def read_current_tcp():
    """从旁路落盘的真值读当前 TCP (只读, 不外呼)"""
    import glob
    fs = sorted(glob.glob(os.path.join(SS_REMOTE, "state_*.jsonl")), key=os.path.getmtime)
    if not fs:
        return None, "无 state 文件 (旁路 tap 没在写)"
    f = fs[-1]
    age = time.time() - os.path.getmtime(f)
    lines = [ln for ln in open(f, errors="ignore").read().strip().split("\n") if ln.strip()]
    for ln in reversed(lines[-50:]):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("tcp"):
            return d["tcp"], f"来自 {os.path.basename(f)} (age {age:.0f}s)"
    return None, f"{os.path.basename(f)} 里最近 50 行都没有 tcp (Orin 在线? 发包正常? age {age:.0f}s)"


def build_plan(tcp, quat):
    """→ [(tcp, quat, tag), ...] : 3x3 栅格 → 蛇形 → 3 个深度位姿; 每个都带姿态倾斜"""
    tcp = np.asarray(tcp, float)
    q0 = [float(v) for v in (quat or [0, 0, 0, 1.0])]
    # 工具系的三个轴 (用工具姿态的列): 这里用姿态矩阵的近似 —— 姿态未知时退化为 base 轴
    try:
        from real_autolabel import quat_to_R
        R = quat_to_R(q0)
        u, v, w = R[:, 0], R[:, 1], R[:, 2]
    except Exception:                                                       # noqa: BLE001
        u, v, w = np.array([1, 0, 0.0]), np.array([0, 1, 0.0]), np.array([0, 0, 1.0])
    g = GRID_MM / 1000.0
    pts = []
    for j, jv in enumerate((1, 0, -1)):
        for iv in ([-1, 0, 1] if j % 2 == 0 else [1, 0, -1]):
            pts.append((tcp + iv * g * u + jv * g * v, "grid", (iv, jv)))
    for k, dz in enumerate(DEPTHS_MM):
        s = 1 if k % 2 == 0 else -1
        pts.append((tcp + (dz / 1000.0) * w + s * 0.020 * u, "depth", (dz, int(s * 20))))
    plan = []
    for i, (p, kind, meta) in enumerate(pts):
        tilt = TILT_DEG if i % 2 == 0 else -TILT_DEG
        amp = meta[0] if kind == "grid" else (1 if meta[1] >= 0 else -1)
        q = quat_mul(q0, axis_quat([0, 1, 0], tilt * (amp or 1)))
        plan.append({"idx": i, "kind": kind, "meta": list(meta),
                     "tcp": [round(float(x), 6) for x in p], "quat": [round(float(x), 6) for x in q],
                     "tilt_deg": round(tilt * (amp or 1), 1)})
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tcp", default=None, help="基准 TCP 'x,y,z' (米); 不给就从旁路真值读当前值")
    ap.add_argument("--quat", default=None, help="基准姿态四元数 'x,y,z,w'; 不给按单位姿态")
    ap.add_argument("--out", default=None, help="计划落盘 (json)")
    ap.add_argument("--safe-box", default=None, help="xmin,xmax,ymin,ymax,zmin,zmax (米), 越界即拒")
    ap.add_argument("--max-step-mm", type=float, default=80.0, help="相邻位姿最大位移 (安全上限)")
    a = ap.parse_args()

    if a.tcp:
        tcp = [float(x) for x in a.tcp.split(",")]
        src = "命令行给定"
    else:
        tcp, src = read_current_tcp()
        if tcp is None:
            print(f"❌ 拿不到当前 TCP: {src}")
            print("   可以显式给基准: --tcp 0.30,0.05,0.10")
            return 1
    quat = [float(x) for x in a.quat.split(",")] if a.quat else None
    box = [float(x) for x in a.safe_box.split(",")] if a.safe_box else list(SAFE_BOX)
    if len(box) != 6:
        print("❌ --safe-box 需要 6 个数")
        return 1

    plan = build_plan(tcp, quat)
    print(f"═══ S0 探针运动计划 · 基准 TCP = {[round(v, 4) for v in tcp]} ({src}) ═══")
    print(f"安全盒 x[{box[0]},{box[1]}] y[{box[2]},{box[3]}] z[{box[4]},{box[5]}] · 最大步距 {a.max_step_mm}mm\n")

    bad = []
    for p in plan:
        x, y, z = p["tcp"]
        if not (box[0] <= x <= box[1] and box[2] <= y <= box[3] and box[4] <= z <= box[5]):
            bad.append((p["idx"], "越出安全盒"))
    steps = []
    for i in range(1, len(plan)):
        d = float(np.linalg.norm(np.asarray(plan[i]["tcp"]) - np.asarray(plan[i - 1]["tcp"])))
        steps.append(d * 1000)
        if d * 1000 > a.max_step_mm:
            bad.append((plan[i]["idx"], f"相邻步距 {d*1000:.1f}mm > 上限 {a.max_step_mm}mm"))
    print(f"{'idx':>4} {'类型':<6} {'TCP (m)':<28} {'倾斜°':>6}")
    for p in plan:
        print(f"{p['idx']:>4} {p['kind']:<6} {str(p['tcp']):<28} {p['tilt_deg']:>6}")
    print(f"\n相邻步距(mm): {[round(s,1) for s in steps]}")
    print(f"位移跨度(mm): x {round((max(p['tcp'][0] for p in plan)-min(p['tcp'][0] for p in plan))*1000,1)}"
          f" · y {round((max(p['tcp'][1] for p in plan)-min(p['tcp'][1] for p in plan))*1000,1)}"
          f" · z {round((max(p['tcp'][2] for p in plan)-min(p['tcp'][2] for p in plan))*1000,1)}"
          f" · 姿态倾斜 ±{TILT_DEG:.0f}°")

    if bad:
        print("\n❌ 计划不合格 (拒绝):")
        for i, why in bad:
            print(f"   #{i}: {why}")
        print("   → 调整 --safe-box / --max-step-mm, 或挪基准点重新生成")
        return 1
    print("\n✅ 计划合格: 非共面(带 60~130mm 深度变化) · 带 ±16° 姿态变化 · 步距在限内 · 全在安全盒内")
    print("   上线执行: 按此表逐个位姿移动 (走位姿间隙要连续、边动边采图+真值), 采完跑:")
    print("   gui-venv311/bin/python tools/real_autolabel.py --probe <会话>/frames --truth <会话>/truth.jsonl \\")
    print("       --module-offset <实测模块偏移mm> --out models/real_cam_proj.json")
    print("   (预检不过会直接拒落盘; rms >2px 也不要拿去出标签)")
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        json.dump({"created": time.strftime("%F %T"), "base_tcp": tcp, "base_quat": quat,
                   "safe_box": box, "grid_mm": GRID_MM, "tilt_deg": TILT_DEG, "poses": plan},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"📄 计划: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
