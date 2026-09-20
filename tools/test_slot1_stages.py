#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_slot1_stages.py — 【一号位】两阶段技能离线自检 (**不连真机、不下发任何指令**)

做法: 直接把 tools/l2_daemon.py 当模块导入, 用合成位姿喂 _pose 缓存,
     拿假的 chan(只记录写没写) 跑 dry / 守卫 / 到位判定 —— 交付前先自跑通的证据。
覆盖:
  ① dry-run 两阶段目标与 Δ (阶段1 ↑30mm, 阶段2 ↓30mm) 且**一个字节都没写进下发通道**
  ② 阶段2 下降 > 守卫 dz_down_limit_mm → 拒发; 带 allow_down_mm 才放行
  ③ 远离槽位 > max_lin_mm → 拒发 (防大位移直线扫掠)
  ④ 位姿缓存过期 → 拒发
  ⑤ 旧技能(L2.goto_aoi_gold, 无 steps)行为不变 —— 位置+姿态都回示教点
  ⑥ 技能定义里不含 gripper 步骤 → 全程不松爪 (结构性保证)
"""
import importlib.util
import json
import os
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(REPO, "tools"))

spec_ = importlib.util.spec_from_file_location("l2d", os.path.join(REPO, "tools/l2_daemon.py"))
l2d = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(l2d)
l2d.LOG = "/tmp/l2_test_slot1.log"      # 自检日志写 /tmp, 不污染真机执行器日志

REG = json.load(open(os.path.join(REPO, "data/skills/l2_atomic/registry.json"), encoding="utf-8"))
SK1 = [s for s in REG["skills"] if s["id"] == "L2.slot1"][0]
SKG = [s for s in REG["skills"] if s["id"] == "L2.goto_aoi_gold"][0]
PTS = l2d._load_points()
SLOT1 = PTS["slot1"]
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
    l2d._pose["q"] = list(q if q else SLOT1["quat"])
    l2d._pose["t"] = time.time() - age


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (("  · " + detail) if detail else ""))
    if not cond:
        fails.append(name)


print("── ① dry-run: 两阶段目标 + 不下发 ──")
set_pose(SLOT1["pos"], age=0.1)
ch = FakeChan()
out = l2d.run_stages(SK1, {"skill": "L2.slot1", "dry": True, "speed": 60}, ch, PTS)
pl = l2d.plan_stage(SK1, SK1["steps"][0], PTS, {"speed": 60}, SLOT1["pos"])
p2 = l2d.plan_stage(SK1, SK1["steps"][1], PTS, {"speed": 60}, pl["pos"])
check("阶段1 Δ=(0,0,+30)mm 上升", abs(pl["dz"] - 30.0) < 1e-6 and abs(pl["dx"]) < 1e-6, "dz=%+.3f" % pl["dz"])
check("阶段2 Δ=(0,0,-30)mm 下降", abs(p2["dz"] + 30.0) < 1e-6 and abs(p2["dx"]) < 1e-6, "dz=%+.3f" % p2["dz"])
check("阶段1 目标 = 示教点 +30mm", abs(pl["pos"][2] - (SLOT1["pos"][2] + 0.03)) < 1e-9)
check("姿态=示教姿态(纯平移)", pl["quat"] == [float(v) for v in SLOT1["quat"]])
check("限速生效 speed_max=30", pl["speed"] == 30.0, "speed=%s" % pl["speed"])
check("dry 未下发任何字节", ch.writes == [], "writes=%d" % len(ch.writes))
check("返回含两阶段摘要", "DRY-RUN" in out and "阶段2" in out, out[:90])

print("── ② 下降守卫(相对) ──")
# 从槽位点上方 100mm 处执行"阶段2"(目标=槽位点, 该阶段守卫 40mm) → Δz=-100mm 应被拒
base = list(SLOT1["pos"])
high100 = [base[0], base[1], base[2] + 0.10]
r = l2d.plan_stage(SK1, SK1["steps"][1], PTS, {"speed": 60}, high100)
check("向下 100mm > 阶段守卫 40mm → 拒发", "err" in r and "向下" in r["err"], r.get("err", "")[:60])
r2 = l2d.plan_stage(SK1, SK1["steps"][1], PTS, {"speed": 60, "allow_down_mm": 200}, high100)
check("带 allow_down_mm=200 → 放行(目标就是槽位点, 未越 z_floor)", "err" not in r2, r2.get("err", "ok"))

print("── ②b z_floor 硬红线: 目标绝不低于槽位点 ──")
st_below = dict(SK1["steps"][1]); st_below["dz_mm"] = -20.0     # 想压到槽位点以下 20mm
r = l2d.plan_stage(SK1, st_below, PTS, {"speed": 30}, base)
check("目标低于 slot1 → 拒发(z_floor)", "err" in r and "低于下限" in r["err"], r.get("err", "")[:70])
r2 = l2d.plan_stage(SK1, st_below, PTS, {"speed": 30, "allow_down_mm": 999}, base)
check("z_floor 不受 allow_down_mm 影响(仍拒)", "err" in r2, r2.get("err", "err")[:70])
r3 = l2d.plan_stage(SK1, st_below, PTS, {"speed": 30, "allow_below_mm": 30}, base)
check("显式 allow_below_mm=30 → 放行", "err" not in r3, r3.get("err", "ok"))

print("── ②c 现场真实场景: 从槽位上方 185mm 点「一号位」 ──")
high = [base[0], base[1], base[2] + 0.185]                      # 老倪抬升 50+50+100 后停在这里
set_pose(high, age=0.05)
pl = l2d.plan_stage(SK1, SK1["steps"][0], PTS, {"speed": 30}, high)
check("阶段1 允许下降 155.0mm 到正上方", "err" not in pl, pl.get("err", "ok"))
check("阶段1 Δz=-155.0mm(155.4 是现场实测值)", ("err" not in pl) and abs(pl["dz"] + 155.0) < 0.05, "dz=%+.1f" % pl.get("dz", 0))
p2 = l2d.plan_stage(SK1, SK1["steps"][1], PTS, {"speed": 30}, pl["pos"])
check("阶段2 从正上方竖直下 30mm 到槽位点", ("err" not in p2) and abs(p2["dz"] + 30.0) < 1e-6, "dz=%+.1f" % p2.get("dz", 0))

print("── ③ 直线距离守卫 ──")
far = [SLOT1["pos"][0] + 0.60, SLOT1["pos"][1], SLOT1["pos"][2]]
set_pose(far, age=0.1)
ch = FakeChan()
out = l2d.run_stages(SK1, {"skill": "L2.slot1", "speed": 60}, ch, PTS)
check("远离 600mm → 拒发且零下发", ch.writes == [] and "拒" in out, out[:80])

print("── ④ 位姿缓存过期 ──")
set_pose(SLOT1["pos"], age=30.0)
ch = FakeChan()
out = l2d.run_stages(SK1, {"skill": "L2.slot1", "speed": 60}, ch, PTS)
check("真值过期 >5s → 拒发", ch.writes == [] and "未就绪" in out, out[:80])

print("── ⑤ 旧技能行为不变 ──")
set_pose(SLOT1["pos"], age=0.1)
r = l2d.build_move(SKG, {}, PTS)
check("goto_aoi_gold 仍解析出 aoi_gold_view", r is not None and abs(r[0][0] - PTS["aoi_gold_view"]["pos"][0]) < 1e-9)
check("goto_aoi_gold 姿态回示教点(quat:taught)", r[1] == [float(v) for v in PTS["aoi_gold_view"]["quat"]])

print("── ⑥ 全程不松爪(结构性) ──")
blob = json.dumps(SK1, ensure_ascii=False)
check("技能定义无 gripper 步骤/字段", ("grip_open" not in blob) and ("gripper" not in blob) and
      all(s.get("op") not in ("gripper",) for s in SK1["steps"]))
check("阶段数 = 2", len(SK1["steps"]) == 2)

print("── ⑦ 阶段串行铁律: 未到位绝不发下一阶段 ──")
# 目标在 +30mm, 而假真值一直停在槽位点 → wait_arrive 必然超时 → 必须中止(且只发过 1 条)
# 把阶段1 的 timeout 压到 1s, 免得自检等 60s
SK_FAST = json.loads(json.dumps(SK1, ensure_ascii=False))
SK_FAST["steps"][0]["timeout_s"] = 1.0
set_pose(SLOT1["pos"], age=0.05)
ch = FakeChan()
out = l2d.run_stages(SK_FAST, {"skill": "L2.slot1", "speed": 30}, ch, PTS)
check("阶段1 未到位 → 中止, 不继续", ("中止" in out), out[:70])
check("全程只下发 1 条(阶段1)", len(ch.writes) == 1, "writes=%d" % len(ch.writes))
check("下发字节是 move_line 且目标是 +30mm", ("move_line" in ch.writes[0]) and
      ("0.1435467" in ch.writes[0]), ch.writes[0][:80] if ch.writes else "无")

print("── ⑧ 到位判定(只看真值) ──")
set_pose([SLOT1["pos"][0], SLOT1["pos"][1], SLOT1["pos"][2] + 0.03], age=0.05)
ok, err = l2d.wait_arrive([SLOT1["pos"][0], SLOT1["pos"][1], SLOT1["pos"][2] + 0.03], 1.0, 2.0)
check("真值就在目标 → 判到位", ok and err is not None and err < 0.01, "偏差 %.4fmm" % (err if err is not None else -1))
set_pose(SLOT1["pos"], age=0.05)
ok2, err2 = l2d.wait_arrive([SLOT1["pos"][0], SLOT1["pos"][1], SLOT1["pos"][2] + 0.03], 1.0, 1.0)
check("真值差 30mm → 判未到位", (not ok2) and err2 > 25, "最近偏差 %.1fmm" % (err2 if err2 is not None else -1))

print()
if fails:
    print("❌ %d 项未过: %s" % (len(fails), fails))
    sys.exit(1)
print("✅ 全部自检通过 — 未连真机、未下发任何运动指令")
