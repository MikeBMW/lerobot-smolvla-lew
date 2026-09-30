#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_model.py —— 真机**环境模型 / 安全边界**：每次运动都往里学，转移前先查它。

2026-09-30 老倪: 「你在移动的过程中, 要理解你的工作环境。状态空间现在是 L5自主运行, 你要理解你的环境,
  在任何一次运动中, 学习你的环境, 理解安全边界」

做三件事(都只读日志/点位库, 不动设备):
  build  从**示教点库** + **执行器逐条真下发流水**重建模型 → ``~/zmax_data/env_model.json``
         · zones: 料盘槽位排 / 插入工位 / 观察位 / 标定区 (按点名与几何自动聚类, 附区域包络)
         · envelope: 已到过的工作范围(x/y/z), 之外一律算"未验证"
         · corridors: 每条**真实执行过**的运动段(起点→终点/高度/速度/技能) —— 这就是"学过"的证据
         · free_bands: 在料盘区**实测可通行**的最低转移高度(z)与证据时刻
         · rules: 现场定的转移规矩 + 从此推出的阈值
         · noncompliant: 计划里"没有就地抬升就从 A 斜插到 B"的技能(按 4 段规矩应整改的清单)
  verify 给两点/一个目标点 → 用模型判"能不能按规矩走", 并打印 4 段计划; 未验证区域 ⇒ 拒发(要人目视)
  learn  见 build(增量: 只追加新段) —— 建议挂 cron, 让"每次运动"自动变成环境知识

用法:
  python3 tools/env_model.py build [--quiet]
  python3 tools/env_model.py verify slot5 [--from slot4]
  python3 tools/env_model.py zones | corridors | rules
"""
import argparse
import json
import os
import re
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
LOGS = [os.path.expanduser("~/zmax_data/l2_daemon_stdout.log"),
        os.path.expanduser("~/zmax_data/l2_daemon.log")]
OUT = os.path.expanduser("~/zmax_data/env_model.json")
TRUTH = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")

RE_SEG = re.compile(r"\[(\d\d:\d\d:\d\d)\] 目标 (L2\.\S+): pos=\(([-\d.]+), ([-\d.]+), ([-\d.]+)\)"
                    r" · Δ=\(([-+\d.]+), ([-+\d.]+), ([-+\d.]+)\)mm ([^\s·]+)")
MAX_SEG = 2000

# 区域判据(按点名 + 几何, 口径写在模型里, 便于复核)
def zone_of(name, p):
    x, y, z = p
    if re.match(r"^slot\d", name):
        return "料盘槽位排"
    if name.startswith(("insert_", "hole_", "x_mid")):
        return "插入工位/夹具"
    if x < 0.55 and z > 0.30:
        return "观察位"
    if name.startswith(("afx", "loop")):
        return "标定区"
    return "其它"


def load_points():
    with open(PTS, encoding="utf-8") as f:
        return json.load(f).get("points", {})


def parse_segments():
    """从执行器流水里还原**真实执行过的运动段**: 目标 pos + Δ ⇒ 起点 = 目标 − Δ。"""
    segs, seen = [], set()
    for lg in LOGS:
        if not os.path.exists(lg):
            continue
        with open(lg, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = RE_SEG.search(line)
                if not m:
                    continue
                t, sk = m.group(1), m.group(2)
                tx, ty, tz = (float(m.group(i)) for i in (3, 4, 5))
                dx, dy, dz = (float(m.group(i)) for i in (6, 7, 8))
                fx, fy, fz = tx - dx / 1000.0, ty - dy / 1000.0, tz - dz / 1000.0
                key = (t, sk, round(tx, 4), round(ty, 4), round(tz, 4))
                if key in seen:
                    continue
                seen.add(key)
                kind = "抬升" if dz > 0.5 else ("下降" if dz < -0.5 else "平动")
                segs.append({"t": t, "skill": sk, "kind": kind,
                             "from": [round(fx, 4), round(fy, 4), round(fz, 4)],
                             "to": [round(tx, 4), round(ty, 4), round(tz, 4)],
                             "dist_mm": round((dx * dx + dy * dy + dz * dz) ** 0.5, 1),
                             "dz_mm": round(dz, 1), "dir": m.group(9)})
    segs.sort(key=lambda s: s["t"])
    # 🧹 垃圾段过滤: z<0.05(=床面以下/解析残渣) · |y|>0.85(工作区外) · 单段>2500mm —— 一律不学,
    #    否则"包络"会被撑大, 形成假的安全区(2026-09-30 实测: 不过滤会混进 y=0.769/z=-0.001)。
    junk = [s for s in segs if min(s["from"][2], s["to"][2]) < 0.05 or max(abs(s["from"][1]), abs(s["to"][1])) > 0.85
            or s["dist_mm"] > 2500]
    segs = [s for s in segs if s not in junk]
    return segs[-MAX_SEG:], len(junk)


def build(quiet=False):
    pts = load_points()
    segs, n_junk = parse_segments()
    # 🧹 再滤一层: **目标离已知点位 bbox 超过 0.25m** 的段一律不学 —— 否则包络会被"从没真去过的目标"
    #    撑大, 形成假安全区(2026-09-30 实测: 不过滤会混进 y=0.769 的段, 而点位库最大 y 只有 0.498)。
    pxs = [p["pos"][0] for p in pts.values()]
    pys = [p["pos"][1] for p in pts.values()]
    pzs = [p["pos"][2] for p in pts.values()]
    bb = {"x": (min(pxs), max(pxs)), "y": (min(pys), max(pys)), "z": (min(pzs), max(pzs))}
    far = [s for s in segs if any(not (bb[a][0] - 0.25 <= v <= bb[a][1] + 0.25)
                                  for a, v in zip("xyz", s["to"]))]
    segs = [s for s in segs if s not in far]
    n_junk += len(far)
    # ① 区域
    zones = {}
    for n, v in pts.items():
        p = v.get("pos") or [0, 0, 0]
        z = zones.setdefault(zone_of(n, p), {"n": 0, "x": [], "y": [], "z": [], "points": []})
        z["n"] += 1
        z["x"].append(p[0]); z["y"].append(p[1]); z["z"].append(p[2])
        z["points"].append(n)
    for k, z in zones.items():
        z["bbox"] = {"x": [round(min(z["x"]), 4), round(max(z["x"]), 4)],
                     "y": [round(min(z["y"]), 4), round(max(z["y"]), 4)],
                     "z": [round(min(z["z"]), 4), round(max(z["z"]), 4)]}
        del z["x"], z["y"], z["z"]
    # ② 包络: 点位 + 真实到过的位置
    xs = [p["pos"][0] for p in pts.values()] + [s["to"][0] for s in segs] + [s["from"][0] for s in segs]
    ys = [p["pos"][1] for p in pts.values()] + [s["to"][1] for s in segs] + [s["from"][1] for s in segs]
    zs = [p["pos"][2] for p in pts.values()] + [s["to"][2] for s in segs] + [s["from"][2] for s in segs]
    env = {"x": [round(min(xs), 4), round(max(xs), 4)],
           "y": [round(min(ys), 4), round(max(ys), 4)],
           "z": [round(min(zs), 4), round(max(zs), 4)]}
    # ③ 料盘: 平面 z / 节距
    slots = [(int(n[4:]), p["pos"]) for n, p in pts.items() if re.match(r"^slot[1-7]$", n)]
    slots.sort()
    tray = {}
    if len(slots) >= 2:
        tray = {"n": len(slots), "plane_z": round(sum(p[2] for _, p in slots) / len(slots), 4),
                "x": round(sum(p[0] for _, p in slots) / len(slots), 4),
                "y_first": round(slots[0][1][1], 4), "y_last": round(slots[-1][1][1], 4),
                "pitch_mm": [round((slots[i][1][1] - slots[i + 1][1][1]) * 1000, 1)
                             for i in range(len(slots) - 1)]}
    # ④ free_bands: 区分"按规矩走过的转移"与"历史低空横移(违规, 不作为基线)"
    compliant, low = [], []
    for i, s in enumerate(segs):
        if s["kind"] != "平动" or abs(s["dz_mm"]) >= 3 or s["dist_mm"] <= 5:
            continue
        if not (s["to"][0] > 0.60 and abs(s["to"][1] - 0.35) < 0.35):
            continue
        # 合规判据: **上一条非平动段是 ≥50mm 的抬升, 且横向就发生在那个高度** —— 这才是"抬够再横移"
        prev = None
        for p in reversed(segs[:i]):
            if p["kind"] != "平动":
                prev = p
                break
        if prev and prev["kind"] == "抬升" and prev["dz_mm"] >= 50 and abs(prev["to"][2] - s["to"][2]) < 0.005:
            compliant.append(s)
        else:
            low.append(s)
    cband = min([s["to"][2] for s in compliant], default=None)
    band, ev = cband, ["%s %s 横向 %.0fmm @z=%.4f" % (s["t"], s["skill"], s["dist_mm"], s["to"][2])
                       for s in compliant[-6:]]
    low_z = min([s["to"][2] for s in low], default=None)
    low_ev = ["%s %s 横向 %.0fmm @z=%.4f(未先抬升 ⇒ 违规, 不计基线)" %
              (s["t"], s["skill"], s["dist_mm"], s["to"][2]) for s in low[-4:]]
    # ⑤ 规矩(逐字) + 阈值
    rules = {
        "现场原话": "要先垂直抬升5厘米, 才能去别的地方。要到任何一个位置, 也要先到这个位置的上方, 再垂直下落。",
        "min_lift_mm": 50.0,
        "above_mm": 30.0,
        "max_descend_per_stage_mm": 40.0,
        "z_floor": "任何目标点 z 不得低于所参考点位的 z",
        "envelope_rule": "包络之外 = 未验证区域 ⇒ 不得自动进入(要人现场目视)",
        "4stage": ["就地垂直抬升 50mm", "高位横移到目标正上方(点位+200mm)", "竖直降到正上方 30mm", "竖直落到点位"],
    }
    # ⑥ 未按规矩的技能清单: 计划第一步不是"就地抬升", 而是直接奔某点(dz>0) ⇒ 斜插
    noncompliant = []
    try:
        with open(REG, encoding="utf-8") as f:
            reg = json.load(f)
        for sk in reg.get("skills", []):
            st = sk.get("steps") or []
            if not st or sk.get("ros") not in ("line_abs",):
                continue
            s1 = st[0]
            if not s1.get("rel") and s1.get("to"):
                noncompliant.append({"id": sk.get("id"), "first_step": "直接斜线到 %s %+gmm" %
                                     (s1.get("to"), s1.get("dz_mm") or 0)})
    except Exception as e:                                                       # noqa: BLE001
        noncompliant.append({"err": str(e)})
    model = {
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": {"taught_points": len(pts), "motion_segments": len(segs), "dropped_junk_segments": n_junk,
                   "logs": [os.path.basename(x) for x in LOGS if os.path.exists(x)]},
        "envelope": env, "zones": zones, "tray": tray,
        "free_bands": {"按规矩转移高度_z": band, "证据": ev,
                       "历史最低横向_z": low_z, "低空横移(违规,不作基线)": low_ev},
        "rules": rules, "noncompliant_skills": noncompliant,
        "corridors_recent": segs[-40:],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=1)
    if not quiet:
        print("环境模型 → %s" % OUT)
        print(" 来源: 示教点 %d · 真实运动段 %d" % (model["source"]["taught_points"], len(segs)))
        print(" 包络: x%s y%s z%s" % (env["x"], env["y"], env["z"]))
        for k, z in zones.items():
            print(" 区域 %-12s %2d 点 bbox x%s y%s z%s" % (k, z["n"], z["bbox"]["x"], z["bbox"]["y"], z["bbox"]["z"]))
        if tray:
            print(" 料盘: %d 槽 · 平面 z=%.4f · x=%.4f · 节距 %s mm" % (tray["n"], tray["plane_z"], tray["x"], tray["pitch_mm"]))
        print(" 已验证可通行下限: %s" % model["free_bands"]["按规矩转移高度_z"])
        print(" 未按规矩的技能 %d 条" % len(noncompliant))
    return model


def verify(target, frm=None, model=None):
    """用模型判"能不能按规矩走" —— 含: 包络检查 + 所需转移高度 + 4 段计划 + 实证。"""
    m = model or json.load(open(OUT, encoding="utf-8"))
    pts = load_points()
    if target not in pts:
        return False, "点位 %s 不在点位库" % target
    t = pts[target]["pos"]
    env, r = m["envelope"], m["rules"]
    lift, above = r["min_lift_mm"], r["above_mm"]
    if frm and frm in pts:
        f, fsrc = pts[frm]["pos"], "点位 %s" % frm
    else:
        try:
            d = json.load(open(TRUTH, encoding="utf-8"))
            f, fsrc = [d["x"], d["y"], d["z"]], "当前真值"
        except Exception:                                                        # noqa: BLE001
            f, fsrc = t, "未知(按目标自身)"
    out, ok = [], True
    if not (env["x"][0] <= t[0] <= env["x"][1] and env["y"][0] <= t[1] <= env["y"][1]
            and env["z"][0] <= t[2] <= env["z"][1]):
        ok = False
        out.append("⛔ 目标 (%.4f, %.4f, %.4f) **在已验证包络之外** ⇒ 不得自动进入(需人现场目视)" % tuple(t))
    zreq = max(t[2], f[2]) + lift / 1000.0            # 转移高度 ≥ 两端较高者 + 50mm
    if zreq > env["z"][1] + 1e-9:
        ok = False
        out.append("⛔ 需要的转移高度 z=%.4f 超出已验证包络上限 z=%.4f ⇒ 该高度**未验证**" % (zreq, env["z"][1]))
    d = ((t[0] - f[0]) ** 2 + (t[1] - f[1]) ** 2 + (t[2] - f[2]) ** 2) ** 0.5 * 1000
    out.append("起点(%s) (%.4f, %.4f, %.4f) → 目标 %s (%.4f, %.4f, %.4f) · 直线 %.0fmm"
               % (fsrc, f[0], f[1], f[2], target, t[0], t[1], t[2], d))
    out.append("转移高度需 ≥ %.0fmm(两端较高者+50) ⇒ z=%.4f; 已按规矩实测过的料盘区转移高度 z=%s"
               % (lift, zreq, m["free_bands"]["按规矩转移高度_z"]))
    if m["free_bands"]["历史最低横向_z"] is not None:
        out.append("⚠️ 历史上还有更低(z=%s)的横向移动 —— 那是不合规矩的低空横移, 不作为安全基线"
                   % m["free_bands"]["历史最低横向_z"])
    out.append("4 段计划: ① 就地抬 %.0fmm ② 高位横移到 %s 正上方(z=%.4f) ③ 竖直降到 +%.0fmm ④ 竖直落到点位"
               % (lift, target, t[2] + 0.200, above))
    out.append("守卫(不变): 不低于点位 z %.4f · 单段下降 ≤%.0fmm · 到位即停" % (t[2], r["max_descend_per_stage_mm"]))
    return ok, "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "learn", "verify", "zones", "corridors", "rules"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.cmd in ("build", "learn"):
        build(quiet=a.quiet)
    elif a.cmd == "verify":
        ok, txt = verify(a.arg, a.frm)
        print(("通过" if ok else "拒绝") + ":\n" + txt)
    else:
        m = json.load(open(OUT, encoding="utf-8"))
        key = {"zones": "zones", "corridors": "corridors_recent", "rules": "rules"}[a.cmd]
        print(json.dumps(m[key], ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
