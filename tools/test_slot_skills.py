#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_slot_skills.py — 所有「回槽位」两阶段技能的统一离线自检 (**不连真机、不下发任何指令**)

对注册表里每个 id 以 L2.slot 开头的技能逐个跑同一套判据 (一号位/二号位/三号位… 通用):
  ①结构: 两阶段 · 无夹爪步骤 · quat=taught · 锁点 · z_floor 指向本槽位点 · 限速
  ②dry-run: 阶段1 = 示教点+clearance 竖直上升, 阶段2 = 竖直下降回示教点, 姿态=示教姿态(纯平移), 零下发
  ③阶段2 相对下降守卫(>40mm 拒发, allow_down 放行)
  ④z_floor 硬红线(目标低于示教点必拒, allow_down 无法绕过, allow_below 才能放行)
  ⑤直线距离守卫(>500mm 拒发且零下发)   ⑥真值过期拒发
  ⑦未到位必须中止且只发了一条           ⑧到位判定只看真值
全局: ⑨等待上限按距离估算 · ⑩旧技能(goto_aoi_gold)无回归
"""
import importlib.util
import json
import os
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(REPO, "tools"))
_s = importlib.util.spec_from_file_location("l2d", os.path.join(REPO, "tools/l2_daemon.py"))
l2d = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l2d)
l2d.LOG = "/tmp/l2_test_slot_skills.log"          # 自检日志写 /tmp, 不污染真机执行器日志
l2d.USE_DIRECT_POSE = False       # 离线自检: 禁止真去 docker 读真机话题, 只走喂进去的合成位姿

REG = json.load(open(os.path.join(REPO, "data/skills/l2_atomic/registry.json"), encoding="utf-8"))
PTS = l2d._load_points()
SLOTS = [s for s in REG["skills"] if str(s.get("id", "")).startswith("L2.slot")]
fails = []


class FakeChan:
    def __init__(self):
        self.writes = []

    @property
    def stdin(self):
        return self

    def write(self, s):
        self.writes.append(s)

    def flush(self):
        pass


def set_pose(p, q=None, age=0.0):
    l2d._pose["p"] = list(p)
    l2d._pose["q"] = list(q or [0.0, 0.0, 0.0, 1.0])
    l2d._pose["t"] = time.time() - age


def check(tag, name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + "[%s] " % tag + name + (("  · " + detail) if detail else ""))
    if not cond:
        fails.append("%s/%s" % (tag, name))


if not SLOTS:
    print("❌ 注册表里没有 L2.slot* 技能")
    sys.exit(1)

for SK in SLOTS:
    tag = SK["name"]
    pt = SK["point"]
    P = PTS[pt] if pt in PTS else None
    st1, st2 = SK["steps"][0], SK["steps"][1]
    clr = float(st1["dz_mm"])
    print("── [%s] %s · 点 %s (clearance %.0fmm) ──" % (tag, SK["id"], pt, clr))
    _stepblob = json.dumps(SK["steps"], ensure_ascii=False)
    check(tag, "①两阶段/无夹爪/锁点/quat=taught/z_floor/限速",
          len(SK["steps"]) == 2 and SK.get("point_locked") and SK.get("quat") == "taught"
          and SK["guard"].get("z_floor_point") == pt and SK.get("speed_max")
          and not any(w in _stepblob for w in ("grip", "Grip"))            # 只看**步骤**里有没有夹爪动作
          and all(s.get("op") not in ("gripper",) for s in SK["steps"]),
          "steps=%d guard=%s" % (len(SK["steps"]), SK["guard"]))
    check(tag, "①点位已录(含 quat)", P is not None and bool(P.get("quat")), "spread_pos=%.1e" % (P or {}).get("spread_pos_m", -1))
    if P is None:
        continue
    base = [float(v) for v in P["pos"]]
    set_pose(base, age=0.05)
    ch = FakeChan()
    out = l2d.run_stages(SK, {"skill": SK["id"], "dry": True, "speed": 60}, ch, PTS)
    pl = l2d.plan_stage(SK, st1, PTS, {"speed": 60}, base)
    p2 = l2d.plan_stage(SK, st2, PTS, {"speed": 60}, pl["pos"])
    check(tag, "②阶段1 Δ=(0,0,+%.0f)mm 竖直上升" % clr, abs(pl["dz"] - clr) < 1e-6 and abs(pl["dx"]) < 1e-6, "dz=%+.3f" % pl["dz"])
    check(tag, "②阶段2 Δ=(0,0,-%.0f)mm 竖直下降" % clr, abs(p2["dz"] + clr) < 1e-6 and abs(p2["dx"]) < 1e-6, "dz=%+.3f" % p2["dz"])
    check(tag, "②目标=示教点±clearance", abs(pl["pos"][2] - (base[2] + clr / 1000.0)) < 1e-9 and abs(p2["pos"][2] - base[2]) < 1e-9)
    check(tag, "②姿态=示教姿态(纯平移)", pl["quat"] == [float(v) for v in P["quat"]])
    check(tag, "②限速生效", pl["speed"] == float(SK["speed_max"]), "speed=%s" % pl["speed"])
    check(tag, "②dry 零下发", ch.writes == [] and "DRY-RUN" in out, "writes=%d" % len(ch.writes))

    high100 = [base[0], base[1], base[2] + 0.10]
    r = l2d.plan_stage(SK, st2, PTS, {"speed": 60}, high100)
    check(tag, "③阶段2 向下 100mm > 守卫 40mm → 拒发", "err" in r and "向下" in r["err"], r.get("err", "")[:50])
    r = l2d.plan_stage(SK, st2, PTS, {"speed": 60, "allow_down_mm": 200}, high100)
    check(tag, "③带 allow_down_mm → 放行", "err" not in r, r.get("err", "ok"))

    below = dict(st2); below["dz_mm"] = -20.0
    r = l2d.plan_stage(SK, below, PTS, {"speed": 30}, base)
    check(tag, "④目标低于示教点 → 拒发(z_floor)", "err" in r and "低于下限" in r["err"], r.get("err", "")[:60])
    r = l2d.plan_stage(SK, below, PTS, {"speed": 30, "allow_down_mm": 999}, base)
    check(tag, "④z_floor 不受 allow_down_mm 影响", "err" in r, r.get("err", "err")[:60])
    r = l2d.plan_stage(SK, below, PTS, {"speed": 30, "allow_below_mm": 30}, base)
    check(tag, "④allow_below_mm 显式放行", "err" not in r, r.get("err", "ok"))

    far = [base[0] + 0.60, base[1], base[2]]
    set_pose(far, age=0.05)
    ch = FakeChan()
    out = l2d.run_stages(SK, {"skill": SK["id"], "speed": 60}, ch, PTS)
    check(tag, "⑤远离 600mm → 拒发且零下发", ch.writes == [] and "拒" in out, out[:50])

    set_pose(base, age=30.0)
    ch = FakeChan()
    out = l2d.run_stages(SK, {"skill": SK["id"], "speed": 60}, ch, PTS)
    check(tag, "⑥真值过期 → 拒发", ch.writes == [] and "未就绪" in out, out[:40])

    FAST = json.loads(json.dumps(SK, ensure_ascii=False))
    FAST["steps"][0]["timeout_s"] = 1.0
    FAST["steps"][0]["timeout_dynamic"] = False
    set_pose(base, age=0.05)
    ch = FakeChan()
    out = l2d.run_stages(FAST, {"skill": SK["id"], "speed": 30}, ch, PTS)
    check(tag, "⑦未到位 → 中止且只发 1 条", "中止" in out and len(ch.writes) == 1, "writes=%d" % len(ch.writes))

    set_pose([base[0], base[1], base[2] + clr / 1000.0], age=0.05)
    ok, err, _src = l2d.wait_arrive([base[0], base[1], base[2] + clr / 1000.0], 1.0, 2.0)
    check(tag, "⑧真值在目标 → 判到位", ok and err is not None and err < 0.01, "%.4fmm" % (err if err is not None else -1))
    set_pose(base, age=0.05)
    ok2, err2, _s2 = l2d.wait_arrive([base[0], base[1], base[2] + clr / 1000.0], 1.0, 1.0)
    check(tag, "⑧真值差 clearange → 判未到位", (not ok2) and err2 > clr - 1, "%.1fmm" % (err2 if err2 is not None else -1))
    print()

print("── 全局 ──")
check("全局", "⑨等待上限按距离估(448mm@30 → >160s)", l2d._stage_timeout({"timeout_s": 60}, 448.0, 30) > 160,
      "%.0fs" % l2d._stage_timeout({"timeout_s": 60}, 448.0, 30))
check("全局", "⑨timeout_dynamic=false 用硬值", l2d._stage_timeout({"timeout_s": 1.0, "timeout_dynamic": False}, 448.0, 30) == 1.0)
SKG = [s for s in REG["skills"] if s["id"] == "L2.goto_aoi_gold"][0]
set_pose(PTS["slot1"]["pos"], age=0.05)
r = l2d.build_move(SKG, {}, PTS)
check("全局", "⑩goto_aoi_gold 无回归(位置+姿态回示教点)",
      r is not None and abs(r[0][0] - PTS["aoi_gold_view"]["pos"][0]) < 1e-9
      and r[1] == [float(v) for v in PTS["aoi_gold_view"]["quat"]])

print()
if fails:
    print("❌ %d 项未过: %s" % (len(fails), fails))
    sys.exit(1)
print("✅ 全部自检通过 (%d 个槽位技能 × 15 项 + 全局 3 项) — 未连真机、未下发任何运动指令" % len(SLOTS))
