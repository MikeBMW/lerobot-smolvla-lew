#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_taught_path.py — 从 3DGS 采集会话的位姿轨迹里切出「示教路径」(零运动, 只读)

老倪 2026-10-01: 「从刚才 侧面点2 到现在的 侧面点3 的路径, 你也要记住, 一会会走 侧面点1 2 3 的连续路径」

为什么用采集会话而不是别处: gs_capture 以 ~8Hz 把 TCP 真值(pos+quat) 逐帧配对落盘
(`frames.jsonl` 每行含 pose_before/pose_after), 这就是**他手走的真实轨迹**, 比事后拿点连直线保真。

做法:
  1. 读 frames.jsonl → (t_mono, pos, quat) 序列;
  2. 用示教点的**位置**(≤tol_mm 判定"停在该点"; 姿态可能在该点原地转过, 所以只按位置认驻留);
  3. 起点驻留的最后一帧 → 终点驻留的第一帧 = 该段路径; 两端各带 short 段驻留便于复现;
  4. 按 min_step_mm 抽稀(默认 2mm, 保端点) → 存成命名路径 + 统计(长/时长/速度/弯曲比)。

输出: data/skills/l2_atomic/taught_paths.json (追加/覆盖同名路径) + 可选 --npz 存稠密轨迹

用法:
  python3 tools/extract_taught_path.py --session ~/zmax_data/gs_scan/scan_XXX --from 侧面点2 --to 侧面点3
  python3 tools/extract_taught_path.py --list
"""
from __future__ import annotations
import argparse, json, math, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POINTS = os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json")
PATHS = os.path.join(ROOT, "data/skills/l2_atomic/taught_paths.json")


def load_trace(session):
    recs = []
    fp = os.path.join(os.path.expanduser(session), "frames.jsonl")
    with open(fp, encoding="utf-8") as f:
        for ln in f:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            p = r.get("pose_after") or r.get("pose_before")
            if not (isinstance(p, dict) and all(k in p for k in ("x", "y", "z"))):
                continue
            t = r.get("t_mono_fetch1") or r.get("t_mono_fetch0") or 0.0
            recs.append({"seq": r.get("seq"), "t": float(t),
                         "pos": [float(p["x"]), float(p["y"]), float(p["z"])],
                         "quat": [float(p[k]) for k in ("qx", "qy", "qz", "qw")],
                         "ts": p.get("ts")})
    return recs


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def quat_ang_deg(q1, q2):
    d = abs(sum(a * b for a, b in zip(q1, q2)))
    return 2.0 * math.degrees(math.acos(max(-1.0, min(1.0, d))))


def resample(seg, min_step_mm):
    out = [seg[0]]
    acc = 0.0
    for i in range(1, len(seg)):
        acc += dist(seg[i - 1]["pos"], seg[i]["pos"])
        if acc * 1000.0 >= min_step_mm:
            out.append(seg[i])
            acc = 0.0
    if out[-1] is not seg[-1]:
        out.append(seg[-1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="")
    ap.add_argument("--from", dest="frm", default="")
    ap.add_argument("--to", dest="to", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--tol-mm", type=float, default=1.5)
    ap.add_argument("--min-step-mm", type=float, default=2.0)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        d = json.load(open(PATHS, encoding="utf-8")) if os.path.exists(PATHS) else {"paths": {}}
        for k, v in d.get("paths", {}).items():
            print("%-28s %s→%s · %d 路点 · %.1fmm · %.1fs · %s"
                  % (k, v.get("from"), v.get("to"), len(v.get("samples", [])), v.get("length_mm", 0),
                     v.get("duration_s", 0), v.get("recorded_at", "")))
        return 0

    if not (args.session and args.frm and args.to):
        print("需要 --session --from --to"); return 2
    P = json.load(open(POINTS, encoding="utf-8"))["points"]
    for nm in (args.frm, args.to):
        if nm not in P:
            print("❌ 示教点不存在: %s" % nm); return 2
    tr = load_trace(args.session)
    if len(tr) < 20:
        print("❌ 轨迹太短(%d 帧)" % len(tr)); return 2
    tol = args.tol_mm / 1000.0
    at_from = [i for i, r in enumerate(tr) if dist(r["pos"], P[args.frm]["pos"]) <= tol]
    at_to = [i for i, r in enumerate(tr) if dist(r["pos"], P[args.to]["pos"]) <= tol]
    if not at_from or not at_to:
        print("❌ 轨迹里找不到驻留: %s=%d帧 %s=%d帧 (容差 %.1fmm; 轨迹范围 x[%.4f,%.4f] y[%.4f,%.4f] z[%.4f,%.4f])"
              % (args.frm, len(at_from), args.to, len(at_to), args.tol_mm,
                 min(r["pos"][0] for r in tr), max(r["pos"][0] for r in tr),
                 min(r["pos"][1] for r in tr), max(r["pos"][1] for r in tr),
                 min(r["pos"][2] for r in tr), max(r["pos"][2] for r in tr)))
        return 3
    i0 = max(at_from)                      # 离开起点前的最后一帧
    cand = [i for i in at_to if i > i0]
    if not cand:
        print("❌ 起点的驻留出现在终点之后(时间顺序不对)"); return 3
    i1 = min(cand)                         # 到达终点后的第一帧
    seg = tr[i0:i1 + 1]
    dense_len = sum(dist(seg[i - 1]["pos"], seg[i]["pos"]) for i in range(1, len(seg)))
    dur = seg[-1]["t"] - seg[0]["t"]
    steps = [dist(seg[i - 1]["pos"], seg[i]["pos"]) for i in range(1, len(seg))]
    samples = [[round(v, 6) for v in (r["pos"] + r["quat"])] for r in resample(seg, args.min_step_mm)]
    name = args.name or ("%s→%s" % (args.frm, args.to))
    rec = {
        "from": args.frm, "to": args.to, "from_pos": [round(v, 6) for v in P[args.frm]["pos"]],
        "to_pos": [round(v, 6) for v in P[args.to]["pos"]],
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": os.path.expanduser(args.session) + "/frames.jsonl",
        "frame_rate_hz": round(len(seg) / max(dur, 1e-6), 2),
        "raw_frames": len(seg), "duration_s": round(dur, 2),
        "length_mm": round(dense_len * 1000, 1),
        "straight_mm": round(dist(seg[0]["pos"], seg[-1]["pos"]) * 1000, 1),
        "bend_ratio": round(dense_len / max(dist(seg[0]["pos"], seg[-1]["pos"]), 1e-9), 3),
        "speed_mm_s_median": round(sorted(steps)[len(steps) // 2] / max(dur / max(len(steps), 1), 1e-6) * 1000, 2),
        "speed_mm_s_max": round(max(steps) / max(dur / max(len(steps), 1), 1e-6) * 1000, 2),
        "min_step_mm": args.min_step_mm,
        "samples": samples,
        "sample_format": "每行 [x,y,z,qx,qy,qz,qw] (m, xyzw, base_link)",
    }
    d = json.load(open(PATHS, encoding="utf-8")) if os.path.exists(PATHS) else {"version": 1, "paths": {}}
    d.setdefault("paths", {})[name] = rec
    d["updated_at"] = rec["recorded_at"]
    with open(PATHS, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("✅ 已记路径『%s』→ %s" % (name, PATHS))
    print("   原始 %d 帧 / %.1fs · 实走 %.1fmm · 直线 %.1fmm · 弯曲比 %.2f · 路点 %d 个(抽稀 %.0fmm) · 速度中位 %.1fmm/s 峰 %.1fmm/s"
          % (rec["raw_frames"], rec["duration_s"], rec["length_mm"], rec["straight_mm"], rec["bend_ratio"],
             len(samples), args.min_step_mm, rec["speed_mm_s_median"], rec["speed_mm_s_max"]))
    for i, s in enumerate(samples[:3]):
        print("   点%d pos=(%.5f,%.5f,%.5f)" % (i, s[0], s[1], s[2]))
    print("   ...")
    for i, s in enumerate(samples[-2:]):
        print("   点%d pos=(%.5f,%.5f,%.5f)" % (len(samples) - 2 + i, s[0], s[1], s[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
