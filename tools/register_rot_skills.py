#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_rot_skills.py — 绕工具轴旋转技能 A/B/C (2026-09-27 老倪手动控制区)

「手动控制机器人」要 6 个自由度: X Y Z 平动(已有 L2.forward/backward/left/right/lift/lower)
+ **A B C 绕轴旋转**。旋转以前只有命令行工具 `tools/l2_pose_rot.py`, 没有注册技能 ⇒
画布/控制台/网页都调不到它。本脚本把 6 个旋转技能注册进 L2 原子技能注册表:

  L2.rot_a_pos / L2.rot_a_neg   绕**工具 X 轴** (A · 俯仰)
  L2.rot_b_pos / L2.rot_b_neg   绕**工具 Y 轴** (B · 倾侧)
  L2.rot_c_pos / L2.rot_c_neg   绕**工具 Z 轴** (C · 光轴自转)

口径 (与方向点动完全一致, 现场不用填负号):
  · 度数只填**正数**, 方向由技能内定 (pos/neg)。
  · 位置**不动**, 只改姿态 —— R_new = R_cur · R_axis(θ) (右手定则, **工具系**)。
  · 执行层守卫: 单次 |deg| ≤ max_deg(默认 10°, 由 tools/l2_daemon.py build_pose_rot 收口),
    要更大角度分次转 (单次大角度会顶到控制器空闲超时, 实测踩过)。
  · 走 /move_pose: 实测该通道**不掉电**(不像 joint 通道会 power off), 免去反复上电解锁。

幂等: 同 id 覆盖, 不重复插入; 跑前自动备份注册表。
用法: gui-venv311/bin/python tools/register_rot_skills.py [--max-deg 10]
"""
import argparse
import json
import os
import shutil
import time

REPO = os.environ.get("ZMAX_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")

AXES = [
    ("a", "x", "A", "绕工具X轴", "俯仰(抬头/低头)"),
    ("b", "y", "B", "绕工具Y轴", "倾侧(左右歪)"),
    ("c", "z", "C", "绕工具Z轴", "自转(画面原地转)"),
]


def build(ax_key, _tool, tag, axis_name, human, sign, max_deg):
    sid = "L2.rot_%s_%s" % (ax_key, "pos" if sign > 0 else "neg")
    arrow = "正" if sign > 0 else "反"
    return {
        "id": sid,
        "name": "%s轴%s转" % (tag, arrow),
        "icon": "🔄",
        "ros": "pose_rot",
        "axis": ax_key,
        "param": {"deg": {"default": 5, "unit": "deg", "min": 1, "max": max_deg,
                          "label": "旋转角度(只填正数)"}},
        "guard": {"max_deg": max_deg},
        "speed_max": 20,
        "note": ("%s(%s) %s向旋转; **位置不动, 只改姿态**; 度数只填正数(方向内定) · "
                 "单次≤%d°(要更大分次转) · 走 /move_pose 不掉电" % (axis_name, human, arrow, max_deg)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-deg", type=float, default=10.0, help="单次旋转上限(度)")
    a = ap.parse_args()
    with open(REG, encoding="utf-8") as f:
        reg = json.load(f)
    shutil.copy2(REG, "/tmp/registry.json.prerot_%d" % time.time())
    ids = [s["id"] for s in reg["skills"]]
    at = ids.index("L2.lower") + 1 if "L2.lower" in ids else len(ids)
    added, updated = [], []
    for ax_key, tool, tag, axis_name, human in AXES:
        for sign in (1, -1):
            sk = build(ax_key, tool, tag, axis_name, human, sign, a.max_deg)
            if sk["id"] in ids:
                reg["skills"][ids.index(sk["id"])] = sk
                updated.append(sk["id"])
            else:
                reg["skills"].insert(at, sk)
                ids.insert(at, sk["id"])
                at += 1
                added.append(sk["id"])
    with open(REG, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    print("注册表: %s" % REG)
    print("新增 %d: %s" % (len(added), ", ".join(added)))
    print("覆盖 %d: %s" % (len(updated), ", ".join(updated) or "无"))
    print("总技能数: %d" % len(reg["skills"]))
    print("备份: /tmp/registry.json.prerot_*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
