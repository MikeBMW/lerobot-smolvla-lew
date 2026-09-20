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

print("── 方向点动技能: 前进 / 后退 / 向左 / 向右 (2026-09-20 拆分) ──")
_regj = {s["id"]: s for s in REG["skills"]}
_JOG = {"L2.forward": (0, +1, "前进"), "L2.backward": (0, -1, "后退"),
        "L2.left": (1, +1, "向左"), "L2.right": (1, -1, "向右")}
for _sid, (_axi, _sg, _nm) in _JOG.items():
    _sk = _regj.get(_sid)
    check("点动", "%s「%s」已注册" % (_sid, _nm), _sk is not None)
    if not _sk:
        continue
    set_pose([0.5, 0.2, 0.3], age=0.05)
    _r = l2d.build_move(_sk, {"skill": _sid, "d_mm": 50}, PTS)
    _tgt = [0.5, 0.2, 0.3]
    _tgt[_axi] += _sg * 0.05
    check("点动", "%s 目标 = 当前 %+d×50mm, 其余轴不动" % (_nm, _sg),
          _r is not None and max(abs(_r[0][i] - _tgt[i]) for i in range(3)) < 1e-9,
          "(%.4f, %.4f, %.4f)" % tuple(_r[0]) if _r else "无")
    _r2 = l2d.build_move(_sk, {"skill": _sid, "d_mm": -50}, PTS)
    check("点动", "%s 距离填负数也按本方向走(方向内定, 不靠符号)" % _nm,
          _r2 is not None and _r2[0][_axi] == _tgt[_axi])
check("点动", "旧 L2.move_x / L2.move_y 已下线", "L2.move_x" not in _regj and "L2.move_y" not in _regj)
check("点动", "方向标签自解释(日志口径)",
      l2d._dir_label(50, 0, 0) == "→前进(+X)" and l2d._dir_label(0, -50, 0) == "→向右(-Y)"
      and l2d._dir_label(0, 0, 50) == "↑上升(+Z)")
_servo = open(os.path.join(REPO, "tools/aoi_gold_servo.py"), encoding="utf-8").read()
check("点动", "视觉伺服不再用旧技能名/已无 sign 字段",
      "L2.move_x" not in _servo and "L2.move_y" not in _servo and "sign=1 if" not in _servo)

print("── 里萨如力控插入 (L2.lissa_insert, 配方只读抄自产线) ──")
LK = _regj.get("L2.lissa_insert")
check("里萨如", "技能已注册", LK is not None)
if LK:
    IP = PTS.get(LK["point"])
    st1, st2, st3 = LK["steps"]
    check("里萨如", "三阶段: 退到插槽口 → 推进插入位 → 调力控服务",
          st1.get("local_mm") == [0.0, 0.0, -60.0] and st2.get("local_mm") == [0.0, 0.0, 0.0]
          and st3.get("op") == "service" and len(LK["steps"]) == 3)
    check("里萨如", "服务名/类型 = 产线原服务",
          st3["srv"] == "/lissajous_force_search" and st3["type"] == "interfaces/srv/LissajousForceSearch")
    A = st3["args"]
    check("里萨如", "参数=产线配方(6N 工具系 XY面 ±10mm/8s 自标定 负载1.51kg)",
          A["cartesian_desired_force"] == [0.0, 0.0, 6.0, 0.0, 0.0, 0.0] and A["frame_type"] == 3 and A["plane"] == 0
          and A["search_box"] == [-0.01, 0.01, -0.01, 0.01, -0.01, 0.01] and A["search_box_timeout_sec"] == 8.0
          and A["calibrate_force_sensor"] is True and A["load"][0] == 1.51
          and A["use_current_pose_as_box_origin"] is True and A["amplify_one"] == 6.0 and A["frequency_one"] == 3.0)
    check("里萨如", "全程无夹爪步骤", "grip" not in json.dumps(LK["steps"], ensure_ascii=False))
    set_pose(IP["pos"], q=IP["quat"], age=0.05)
    r_no = l2d.plan_stage(LK, st1, PTS, {"speed": 30}, IP["pos"])
    check("里萨如", "阶段1(拔出段)未确认解锁 → 拒发(硬守卫)",
          "err" in r_no and "解锁" in r_no["err"], r_no.get("err", "")[:64])
    p1 = l2d.plan_stage(LK, st1, PTS, {"speed": 30, "allow_unlocked_retract": True}, IP["pos"])
    p2 = l2d.plan_stage(LK, st2, PTS, {"speed": 30}, p1["pos"])
    Rm = l2d._quat_R(IP["quat"])
    exp1 = [IP["pos"][i] + Rm[i][2] * (-0.06) for i in range(3)]
    check("里萨如", "插槽口 = 插入位 + R·(0,0,-60mm) (沿模块轴向退, 不是 base 竖直)",
          max(abs(p1["pos"][i] - exp1[i]) for i in range(3)) < 1e-9, "退到 (%.4f, %.4f, %.4f)" % tuple(p1["pos"]))
    check("里萨如", "阶段2 回到插入位(退/进互为逆)",
          max(abs(p2["pos"][i] - IP["pos"][i]) for i in range(3)) < 1e-9)
    check("里萨如", "两段直线各 60mm · 限速 30", abs(p1["lin"] - 60.0) < 1.0 and p1["speed"] == 30.0)
    ch = FakeChan()
    out_no = l2d.run_stages(LK, {"skill": "L2.lissa_insert", "speed": 30, "dry": True}, ch, PTS)
    check("里萨如", "三段技能 dry(未确认解锁) → 被守卫拒 且 零下发",
          ch.writes == [] and "拒绝" in out_no, out_no[:52])
    ch = FakeChan()
    out = l2d.run_stages(LK, {"skill": "L2.lissa_insert", "speed": 30, "dry": True,
                              "allow_unlocked_retract": True}, ch, PTS)
    check("里萨如", "确认已解锁后 dry → 三段计划齐全 且 零下发",
          ch.writes == [] and "DRY-RUN" in out and "阶段3" in out)
    SR = _regj.get("L2.lissa_search")
    check("里萨如", "只搜索技能已注册(单阶段=力控服务)", SR is not None and len(SR["steps"]) == 1
          and SR["steps"][0]["op"] == "service")
    if SR:
        ch = FakeChan()
        out = l2d.run_stages(SR, {"skill": "L2.lissa_search", "dry": True}, ch, PTS)
        check("里萨如", "只搜索 dry → 只调服务 且 零运动下发",
              ch.writes == [] and "DRY-RUN" in out and "服务 /lissajous_force_search" in out, out[:60])
    # 服务回执路径: 用桩替换真调用, 绝不真打服务
    _stub = {"id": "T.lissa", "name": "t", "steps": [dict(st3, timeout_s=2)]}
    set_pose(IP["pos"], q=IP["quat"], age=0.05)
    l2d._service_call = lambda st: (False, "3.2s · success=False · FORCE_CONTROL_CLEANUP_FAILED setToolset(tool1, wobj0) failed")
    ch = FakeChan()
    out = l2d.run_stages(_stub, {"skill": "T.lissa"}, ch, PTS)
    check("里萨如", "服务 success=False → 中止 且 零运动下发",
          "服务失败" in out and ch.writes == [], out[:60])
    l2d._service_call = lambda st: (True, "0.9s · success=True · 插入完成")
    ch = FakeChan()
    out = l2d.run_stages(_stub, {"skill": "T.lissa"}, ch, PTS)
    check("里萨如", "服务 success=True → 阶段完成 且 零运动下发",
          "全部 1 阶段完成" in out and ch.writes == [], out[:60])
    check("里萨如", "服务请求串含全部字段(%d 个)" % len(A), l2d._args_to_yaml(A).count(":") >= len(A),
          l2d._args_to_yaml(A)[:60] + " …")

print("── 解锁并拔出 (L2.pull_module, 机理=夹爪后方钩子) ──")
PK = _regj.get("L2.pull_module")
check("拔出", "技能已注册(5 段)", PK is not None and len(PK["steps"]) == 5)
if PK:
    IP2 = PTS[PK["point"]]
    s1, s2, s3, s4, s5 = PK["steps"]
    check("拔出", "段1 = 垂直下移 3mm 补偿下垂 · 相对量", s1.get("rel") is True and abs(s1["dz_mm"] + 3.0) < 1e-9)
    check("拔出", "段2/段4 = 夹爪步(产线参数 pos1000/f50 · pos0/f30)",
          s2.get("op") == "gripper" and s2["pos"] == 1000.0 and s2["force"] == 50.0
          and s4.get("op") == "gripper" and s4["pos"] == 0.0 and s4["force"] == 30.0)
    check("拔出", "段3 = 沿工具轴退 15mm(钩绿环) · 相对量", s3.get("rel") is True and s3["local_mm"][2] == -15.0)
    check("拔出", "段5 = 沿工具轴退 120mm(拉出) · 相对量", s5.get("rel") is True and s5["local_mm"][2] == -120.0)
    deep = [IP2["pos"][0] + 0.0114, IP2["pos"][1], IP2["pos"][2] - 0.0007]   # 力控后: 比示教插入位深 11.4mm
    set_pose(deep, q=IP2["quat"], age=0.05)
    p1 = l2d.plan_stage(PK, s1, PTS, {"speed": 30}, deep)
    check("拔出", "段1 目标 = 当前位姿-3mm(**不回示教插入位**)",
          ("err" not in p1) and abs(p1["pos"][0] - deep[0]) < 1e-9 and abs(p1["pos"][2] - (deep[2] - 0.003)) < 1e-9,
          "Δ=(%+.1f,%+.1f,%+.1f)mm" % (p1["dx"], p1["dy"], p1["dz"]))
    p3 = l2d.plan_stage(PK, s3, PTS, {"speed": 30}, p1["pos"])
    p5 = l2d.plan_stage(PK, s5, PTS, {"speed": 30}, p3["pos"])
    check("拔出", "段3 退 15mm / 段5 退 120mm(每次按当时位姿重算)",
          abs(p3["lin"] - 15.0) < 1.0 and abs(p5["lin"] - 120.0) < 3.0,
          "lin=%.1f/%.1f mm" % (p3.get("lin", -1), p5.get("lin", -1)))
    check("拔出", "终点比起点外移 >130mm(真往外拔)", (deep[0] - p5["pos"][0]) * 1000 > 130,
          "%.0fmm" % ((deep[0] - p5["pos"][0]) * 1000))
    ch = FakeChan()
    out = l2d.run_stages(PK, {"skill": "L2.pull_module", "speed": 30, "dry": True, "stages": [1]}, ch, PTS)
    check("拔出", "分段执行 stages=[1] → 只计划 1 段且零下发",
          ch.writes == [] and "1 阶段" in out, out[:56])

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
