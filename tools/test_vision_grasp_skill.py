#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_vision_grasp_skill.py — 「视觉引导抓取」(L2.grasp_vision) 离线自检

**不连真机、不下发任何指令** (补强: 把执行层的 chan_send / _call_remote / _service_call 全部
换成记录器 —— 老式自检只把 USE_DIRECT_POSE 关掉, 运动步仍会走真通道, 这是隐患)。

判据分四组:
  A 结构: 注册表条目四阶段 / 视觉门 / 占位点 / 守卫 / 限速
  B 视觉判据 (合成输入, 双路独立证据): 正例 slot2 · 正例 slot1 · 两路冲突 · 无检出 ·
    框偏出咬合带 · 负帧龄(时钟回拨) · 无棱边信号 —— 只有①双路一致才 ok
  C 执行器内的视觉门 (fail-closed): 判不出→零下发 · 解析成功→目标=该槽且 z_floor 同步解析 ·
    远离>500mm 拒发 · 真值过期拒发 · 未到位中止且只发一条(不重发)
  D 非回归: L2.slot1/L2.slot2/L2.pull_module 条目结构不变 · L2.slot2 dry-run 仍 2 阶段 0 下发
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time

import cv2
import numpy as np

REPO = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(REPO, "tools"))

_s = importlib.util.spec_from_file_location("l2d", os.path.join(REPO, "tools/l2_daemon.py"))
l2d = importlib.util.module_from_spec(_s)
_s.loader.exec_module(l2d)
l2d.USE_DIRECT_POSE = False
l2d.LOG = "/tmp/l2_test_grasp_vision.log"

SENDS: list[str] = []
GRIP_CALLS: list[str] = []


def _rec_send(call):
    SENDS.append(call)
    return True


def _rec_remote(cmd, timeout=40):
    (GRIP_CALLS if "gripper" in cmd else SENDS).append(cmd)
    return True, "response: curr_pos=185.0"


l2d.chan_send = _rec_send                              # 🛡 双保险: 任何路径都不许碰真通道
l2d._call_remote = _rec_remote
l2d._service_call = lambda st: (SENDS.append("srv:%s" % st.get("srv")) or True, "ok")

import vision_grasp_skill as vgs                        # noqa: E402

REG = json.load(open(os.path.join(REPO, "data/skills/l2_atomic/registry.json"), encoding="utf-8"))
PTS = l2d._load_points()
SID = "L2.grasp_vision"
FIX_POSE = {"pos": [0.491494, 0.417166, 0.254241], "quat": [-0.810036, 0.000586, -0.586349, 0.005998]}
fails: list[str] = []


def check(tag, name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + "[%s] " % tag + name + (("  · " + detail) if detail else ""))
    if not cond:
        fails.append("%s/%s" % (tag, name))


def set_pose(p, q=None, age=0.0):
    l2d._pose["p"] = list(p)
    l2d._pose["q"] = list(q or FIX_POSE["quat"])
    l2d._pose["t"] = time.time() - age


def fake_frame(proj, stripe_slot, w=640, h=480, bar=200):
    """合成帧: 在指定槽的投影列画一条竖直亮带 (模块轮廓) → 只有它的列剖面有强棱边。"""
    img = np.full((h, w), 90, np.uint8)
    u = int(proj[stripe_slot][0])
    v = int(proj[stripe_slot][1])
    img[max(0, v - 130):min(h, v + 5), max(0, u - 8):min(w, u + 8)] = bar
    return img


def fake_det(proj, slot, age=0.5, dy_off=13.0, w=42, h=131, conf=0.81):
    u, v, _d = proj[slot]
    x1, y1 = u - w / 2, v + dy_off - h
    return {"frame_age_s": age, "n": 1, "detections": [
        {"cls": "peg", "conf": conf, "xyxy": [x1, y1, x1 + w, y1 + h]}]}


def judge(proj, stripe_slot, box_slot=None, **kw):
    geom = vgs.load_geom()
    det = fake_det(proj, box_slot, **kw) if box_slot else {"frame_age_s": kw.get("age", 0.5), "n": 0, "detections": []}
    img = fake_frame(proj, stripe_slot)
    return vgs.judge_slot(_geom=geom, _det=det, _img=img, _tcp=(FIX_POSE["pos"], FIX_POSE["quat"], "fixture"))


# ─────────────────────────── A 结构 ───────────────────────────
print("═" * 78)
print("A. 注册表结构 %s" % SID)
print("═" * 78)
sk = next((s for s in REG["skills"] if s["id"] == SID), None)
check("结构", "条目已注册", sk is not None)
if sk is None:
    print("❌ 先跑 tools/register_vision_grasp_skill.py"); sys.exit(1)
check("结构", "四阶段 = 上升/下降/合爪/抬升", len(sk["steps"]) == 4
      and sk["steps"][0].get("to") == "slot_vision" and float(sk["steps"][0]["dz_mm"]) == 30.0
      and sk["steps"][1].get("to") == "slot_vision" and float(sk["steps"][1]["dz_mm"]) == 0.0
      and sk["steps"][2].get("op") == "gripper" and float(sk["steps"][2]["pos"]) == 0.0
      and float(sk["steps"][2]["force"]) == 40.0
      and sk["steps"][3].get("rel") and float(sk["steps"][3]["dz_mm"]) == 50.0,
      "stages=%d" % len(sk["steps"]))
check("结构", "视觉门声明 + fail_closed", bool(sk.get("vision_gate"))
      and sk["vision_gate"].get("fail_closed") is True
      and sk["vision_gate"].get("require") == "module_present"
      and sk["vision_gate"].get("candidates") == ["slot1", "slot2"],
      str(sk.get("vision_gate", {}).get("double_witness")))
check("结构", "守卫: z_floor=占位点(执行时解析) · 直线≤500mm · 下降限幅 40mm", 
      (sk["guard"].get("z_floor_point") == "slot_vision" and float(sk["guard"]["max_lin_mm"]) == 500.0
       and float(sk["steps"][1]["guard"]["dz_down_limit_mm"]) == 40.0),
      str(sk["guard"]))
check("结构", "限速 30 (收口在执行层) + quat=taught(纯平移)", sk.get("speed_max") == 30 and sk.get("quat") == "taught")
check("结构", "候选槽位都在点位库", all(n in PTS for n in sk["vision_gate"]["candidates"]),
      str([n for n in sk["vision_gate"]["candidates"] if n in PTS]))

# ─────────────────────────── B 视觉判据 (合成) ───────────────────────────
print("\n" + "═" * 78)
print("B. 视觉判据 · 双路独立证据 (合成输入, 零真机)")
print("═" * 78)
geom = vgs.load_geom()
proj = vgs.project_slots(FIX_POSE["pos"], FIX_POSE["quat"], *geom[:3], geom[3])
print("  夹具位姿投影: %s" % {k: (round(v[0], 1), round(v[1], 1)) for k, v in proj.items()})

j2 = judge(proj, "slot2", "slot2")
check("视觉", "正例: 框+棱边都在 slot2 → ok/slot2", j2["ok"] and j2["slot"] == "slot2", j2["reason"])
j1 = judge(proj, "slot1", "slot1")
check("视觉", "正例: 框+棱边都在 slot1 → ok/slot1 (非写死槽位)", j1["ok"] and j1["slot"] == "slot1", j1["reason"])
jc = judge(proj, "slot2", "slot1")
check("视觉", "两路冲突(棱边 slot2 / 框 slot1) → 拒判", (not jc["ok"]) and "冲突" in jc["reason"], jc["reason"])
jn = judge(proj, "slot2", None)
check("视觉", "无检出 → 拒判", (not jn["ok"]), jn["reason"])
jy = judge(proj, "slot2", "slot2", dy_off=60.0)
check("视觉", "框底偏出咬合带(dy=+60px) → 单路不足, 拒判", (not jy["ok"]), jy["reason"])
ja = judge(proj, "slot2", "slot2", age=-28800.0)
check("视觉", "负帧龄(时钟回拨) → 拒判", (not ja["ok"]) and "新鲜" in ja["reason"], ja["reason"])
je = judge(proj, "slot1", "slot1", age=99.0)
check("视觉", "帧龄 99s 过期 → 拒判", (not je["ok"]) and "新鲜" in je["reason"], je["reason"])
jq = judge(proj, "slot1", "slot2")            # 棱边在 slot1(错) / 框在 slot2(对)
check("视觉", "反向冲突(棱边 slot1 / 框 slot2) → 拒判", (not jq["ok"]), jq["reason"])
# 前置闸门在视觉不过时必须整体不过
pf_bad = vgs.preflight({"ok": False, "slot": None, "reason": "x", "evidence": {"frame_age_s": 0.4}}, require_slot=True)
check("视觉", "视觉不过 → 前置总闸不过(拒发)", pf_bad["ok"] is False, json.dumps(pf_bad["checks"], ensure_ascii=False)[:120])

# ─────────────────────────── C 执行器内的视觉门 ───────────────────────────
print("\n" + "═" * 78)
print("C. 执行器内视觉门 (fail-closed, 零真通道)")
print("═" * 78)
slot2 = [float(v) for v in PTS["slot2"]["pos"]]

# C1 判不出 → 拒发, 零下发
os.environ["L2_VISION_FAKE"] = "none"
set_pose(slot2, age=0.05)
SENDS.clear(); GRIP_CALLS.clear()
out = l2d.run_stages(sk, {"skill": SID, "dry": True}, None, PTS)
check("视觉门", "判不出 → 拒发且零下发", ("视觉门拒发" in out) and not SENDS and not GRIP_CALLS, out[:60])

# C2 解析成功 → 目标=该槽, z_floor 同步解析, dry 零下发
os.environ["L2_VISION_FAKE"] = "slot2"
set_pose(slot2, age=0.05)
SENDS.clear()
out = l2d.run_stages(sk, {"skill": SID, "dry": True}, None, PTS)
check("视觉门", "解析 slot2 → dry-run 四阶段且零下发", ("DRY-RUN" in out) and not SENDS and not GRIP_CALLS, out[:80])
_steps2, _guard2 = l2d._apply_vision_names(sk["steps"], sk["guard"], "slot2")
check("视觉门", "占位点解析: 阶段 to 与 z_floor 都变成 slot2",
      _steps2[0]["to"] == "slot2" and _guard2["z_floor_point"] == "slot2"
      and all(st.get("guard", {}).get("z_floor_point", "slot2") == "slot2" for st in _steps2),
      "%s / %s" % (_steps2[0]["to"], _guard2["z_floor_point"]))
_pl = l2d.plan_stage({**sk, "steps": _steps2, "guard": _guard2}, _steps2[0], PTS,
                     {"skill": SID, "speed": 30}, slot2)
check("视觉门", "阶段1 计划: 目标=slot2 正上方 30mm · 限速 30",
      ("err" not in _pl) and abs(_pl["pos"][2] - (slot2[2] + 0.030)) < 1e-9 and _pl["speed"] == 30.0
      and abs(_pl["pos"][0] - slot2[0]) < 1e-9 and abs(_pl["pos"][1] - slot2[1]) < 1e-9,
      _pl.get("err") or ("dz=%+.1fmm speed=%s" % (_pl["dz"], _pl["speed"])))
# z_floor 必须锁在该槽: 低于 slot2 抓取位 → 拒
_below = dict(_steps2[1]); _below["dz_mm"] = -20.0
_r = l2d.plan_stage({**sk, "steps": _steps2, "guard": _guard2}, _below, PTS,
                    {"skill": SID, "speed": 30}, slot2)
check("视觉门", "z_floor 已解析到 slot2: 目标低于抓取位 → 拒发", "err" in _r and "低于下限" in _r["err"], _r.get("err", "")[:60])
# 反证: 若占位点没被解析(仍叫 slot_vision), 守卫会因"点位不存在"拒发 → 说明解析是必需环节
_r2 = l2d.plan_stage(sk, _steps2[1], PTS, {"skill": SID, "speed": 30}, slot2)
check("视觉门", "反证: 未解析占位点 → 守卫拒发(证明解析链路必需)", "err" in _r2, _r2.get("err", "")[:60])

# C3 远离 600mm → 守卫拒发, 零下发
set_pose([slot2[0] + 0.60, slot2[1], slot2[2]], age=0.05)
SENDS.clear()
out = l2d.run_stages(sk, {"skill": SID, "speed": 30}, None, PTS)
check("视觉门", "远离 600mm → 拒发且零下发", (not SENDS) and ("拒" in out or "中止" in out), out[:60])

# C4 真值过期 → 拒发
set_pose(slot2, age=30.0)
SENDS.clear()
out = l2d.run_stages(sk, {"skill": SID, "speed": 30}, None, PTS)
check("视觉门", "真值过期(30s) → 拒发且零下发", (not SENDS) and ("未就绪" in out or "拒" in out), out[:60])

# C5 未到位 → 中止且只发一条 (绝不重发)
FAST = json.loads(json.dumps(sk, ensure_ascii=False))
FAST["steps"][0]["timeout_s"] = 1.0
FAST["steps"][0]["timeout_dynamic"] = False
set_pose(slot2, age=0.05)
SENDS.clear()
out = l2d.run_stages(FAST, {"skill": SID, "speed": 30}, None, PTS)
check("视觉门", "未到位 → 中止且只发 1 条(不重发)", ("中止" in out) and len(SENDS) == 1, "writes=%d" % len(SENDS))
os.environ.pop("L2_VISION_FAKE", None)

# ─────────────────────────── D 非回归 ───────────────────────────
print("\n" + "═" * 78)
print("D. 非回归 (既有技能与老路径)")
print("═" * 78)
_regj = {s["id"]: s for s in REG["skills"]}
check("回归", "L2.slot1/slot2 仍两阶段 · 锁点 · z_floor=自身",
      all(len(_regj[i]["steps"]) == 2 and _regj[i].get("point_locked")
          and _regj[i]["guard"]["z_floor_point"] == _regj[i]["point"] for i in ("L2.slot1", "L2.slot2")))
check("回归", "L2.pull_module 仍五段(解锁+拔出口径未动)",
      len(_regj["L2.pull_module"]["steps"]) == 5
      and _regj["L2.pull_module"]["steps"][3].get("force") == 30.0
      and _regj["L2.pull_module"]["steps"][4]["local_mm"] == [0.0, 0.0, -120.0])
check("回归", "L2.grasp_vision 是唯一带 vision_gate 的条目",
      [s["id"] for s in REG["skills"] if s.get("vision_gate")] == [SID])
set_pose([float(v) for v in PTS["slot2"]["pos"]], q=[float(v) for v in PTS["slot2"]["quat"]], age=0.05)
SENDS.clear()
out = l2d.run_stages(_regj["L2.slot2"], {"skill": "L2.slot2", "dry": True, "speed": 30}, None, PTS)
check("回归", "L2.slot2 dry-run 仍 2 阶段且零下发(视觉门不误伤)",
      ("DRY-RUN" in out) and not SENDS and len(_regj["L2.slot2"]["steps"]) == 2, out[:80])
_pl2 = l2d.plan_stage(_regj["L2.slot2"], _regj["L2.slot2"]["steps"][0], PTS, {"speed": 30}, slot2)
check("回归", "L2.slot2 老路径点位解析不变(目标=示教点+30mm)",
      ("err" not in _pl2) and abs(_pl2["pos"][2] - (slot2[2] + 0.030)) < 1e-9
      and abs(_pl2["pos"][1] - slot2[1]) < 1e-9, _pl2.get("err") or ("dz=%+.1fmm" % _pl2["dz"]))
check("回归", "技能总数未减", len(REG["skills"]) >= 20, "n=%d" % len(REG["skills"]))

print("\n" + "═" * 78)
print(("✅ 全部通过 (%d 项)" % 0) if not fails else ("❌ 失败 %d 项: %s" % (len(fails), ", ".join(fails))))
print("═" * 78)
print("零真机接触自证: 运动/夹爪/服务调用全部被记录器拦下 (SENDS=%d, GRIP=%d, 且都在预期用例内)"
      % (len(SENDS), len(GRIP_CALLS)))
sys.exit(1 if fails else 0)
