#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_skill_learn.py — L2 肌肉记忆"快速学习/更新"器 (2026-09-19)

用途: 大模型层(DeepSeek VL)识别出新场景/新路径后, 用它把新点位/新序列快速固化成 L2 技能,
      或就地更新已有技能的点位 —— 执行器侧热加载, 无需重启。

用法:
  --from-trace <pose.txt> [--id L2.MUSCLE.X] [--name 名字]     从演示轨迹(50Hz /robot/tcp_pose echo)提点位生成技能
  --from-plan <plan.json>  [--id ...] [--name ...]             按 VL/L3 规划(点位列表)生成技能
  --set-point <skill_id> <point> <x> <y> <z> <qx> <qy> <qz> <qw>  就地更新组合技能的点位(新路径/新场景)
  --registry-add <skill_id> <name> <url|ros> [--param k=v]      把新原子技能登记进 registry
  --list | --show <id>                                          查看
每次变更都追加 data/skills/CHANGELOG.jsonl (可回溯)
"""
import argparse, json, math, os, time

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(R, "data/skills/l2_atomic/registry.json")
MUSDIR = os.path.join(R, "data/skills/l2_muscle")
LOG = os.path.join(R, "data/skills/CHANGELOG.jsonl")


def logev(kind, sid, extra=None):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    ev = {"t": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "skill": sid}
    if extra:
        ev.update(extra)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def parse_trace(path, min_dwell=0.3, vth=0.002, merge_mm=3.0):
    import re
    txt = open(path, encoding="utf-8", errors="ignore").read()
    S = []
    for b in txt.split("---"):
        m = re.search(r"sec:\s*(\d+).*?nanosec:\s*(\d+)", b, re.S)
        p = re.search(r"position:\s*x:\s*(-?[\d.eE+-]+)\s*y:\s*(-?[\d.eE+-]+)\s*z:\s*(-?[\d.eE+-]+)", b, re.S)
        o = re.search(r"orientation:\s*x:\s*(-?[\d.eE+-]+)\s*y:\s*(-?[\d.eE+-]+)\s*z:\s*(-?[\d.eE+-]+)\s*w:\s*(-?[\d.eE+-]+)", b, re.S)
        if m and p and o:
            t = int(m.group(1)) + int(m.group(2)) * 1e-9
            S.append((t, [float(x) for x in p.groups()], [float(x) for x in o.groups()]))
    runs, cur = [], []
    for i in range(1, len(S)):
        t0, p0, _ = S[i - 1]; t1, p1, _ = S[i]
        v = math.dist(p0, p1) / max(t1 - t0, 1e-6)
        if v < vth:
            cur.append(S[i])
        else:
            if len(cur) >= 8: runs.append(cur)
            cur = []
    if len(cur) >= 8: runs.append(cur)
    pts = []
    for rr in runs:
        t = sum(x[0] for x in rr) / len(rr)
        p = [sum(x[1][k] for x in rr) / len(rr) for k in range(3)]
        q = [sum(x[2][k] for x in rr) / len(rr) for k in range(4)]
        d = rr[-1][0] - rr[0][0]
        if d < min_dwell: continue
        if pts and math.dist(pts[-1]["pos"], p) * 1000 < merge_mm: continue
        pts.append({"t": round(t - S[0][0], 2), "pos": [round(v, 6) for v in p], "quat": [round(v, 6) for v in q], "dwell_s": round(d, 2)})
    return pts


def make_skill(pts, sid, name, src_note):
    named = ["home"] + ["p%d" % i for i in range(1, len(pts) - 1)] + ["end"] if len(pts) > 2 else ["home", "end"]
    P, steps = {}, []
    for i, pt in enumerate(pts):
        key = named[i] if i < len(named) else "p%d" % i
        P[key] = {"pos": pt["pos"], "quat": pt["quat"], "dwell_s": pt["dwell_s"]}
        steps.append({"op": "move", "to": key})
    return {"id": sid, "name": name, "layer": "L2", "kind": "muscle_memory", "version": 1,
            "source": src_note, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "points": P, "steps": steps,
            "contact_guard": {"enabled": True, "low_point_margin_mm": 5,
                              "why": "从演示/规划学来的低位点必须留余量(collision_detection=False)",
                              "two_stage_descent": True},
            "notes": ["由 l2_skill_learn 生成; 执行前须逐步校验"]}


def save_skill(sk, update=False):
    os.makedirs(MUSDIR, exist_ok=True)
    p = os.path.join(MUSDIR, "%s.json" % sk["id"].replace(".", "_"))
    if os.path.exists(p):
        old = json.load(open(p, encoding="utf-8"))
        sk["version"] = int(old.get("version", 1)) + 1
        sk["prev_version"] = old.get("version", 1)
        update = True
    json.dump(sk, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    logev("update" if update else "create", sk["id"], {"file": os.path.basename(p), "version": sk["version"], "points": len(sk["points"])})
    return p, update


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-trace"); ap.add_argument("--from-plan")
    ap.add_argument("--id"); ap.add_argument("--name")
    ap.add_argument("--set-point", nargs=9); ap.add_argument("--list", action="store_true"); ap.add_argument("--show")
    a = ap.parse_args()
    if a.list:
        for fn in sorted(os.listdir(MUSDIR)):
            d = json.load(open(os.path.join(MUSDIR, fn), encoding="utf-8"))
            print("%-34s v%s  %-28s 点%d 步%d" % (d["id"], d.get("version", 1), d.get("name", ""), len(d.get("points", {})), len(d.get("steps", []))))
        return
    if a.show:
        p = os.path.join(MUSDIR, "%s.json" % a.show.replace(".", "_"))
        print(open(p, encoding="utf-8").read()[:800])
        return
    if a.set_point:
        sid, pname, x, y, z, qx, qy, qz, qw = a.set_point
        p = os.path.join(MUSDIR, "%s.json" % sid.replace(".", "_"))
        sk = json.load(open(p, encoding="utf-8"))
        if pname not in sk["points"]:
            print("无此点位:", pname, "现有:", list(sk["points"])); return
        old = sk["points"][pname].get("pos")
        sk["points"][pname] = {"pos": [float(x), float(y), float(z)], "quat": [float(qx), float(qy), float(qz), float(qw)]}
        sk["version"] = int(sk.get("version", 1)) + 1
        json.dump(sk, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        logev("set_point", sid, {"point": pname, "old": old, "new": [float(x), float(y), float(z)], "version": sk["version"]})
        print("已更新 %s.%s → %s (v%s)" % (sid, pname, [float(x), float(y), float(z)], sk["version"]))
        return
    pts = None; note = ""
    if a.from_trace:
        pts = parse_trace(a.from_trace); note = "演示轨迹: %s" % os.path.basename(a.from_trace)
    elif a.from_plan:
        pl = json.load(open(a.from_plan, encoding="utf-8"))
        pts = [{"pos": q["pos"], "quat": q.get("quat", [0, 0, 0, 1]), "dwell_s": 0.0} for q in pl.get("points", pl)]
        note = "VL/L3 规划: %s" % os.path.basename(a.from_plan)
    if pts is not None:
        if not pts:
            print("未提取到点位"); return
        sid = a.id or ("L2.MUSCLE.LEARNED.%s" % time.strftime("%H%M%S"))
        sk = make_skill(pts, sid, a.name or ("学习技能 %s" % time.strftime("%H:%M:%S")), note)
        p, up = save_skill(sk)
        print("%s %s → %s (v%s, %d 点)" % ("已更新" if up else "已新建", sid, p, sk["version"], len(sk["points"])))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
