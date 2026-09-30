#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔧 补全示教点库里**缺 w 的四元数**(3 分量 → 4 分量) —— 幂等, 可 --dry。

背景(2026-09-30 实测): `slot3` / `slot7` / `slot7_up` 的 ``quat`` 只有 3 个分量(x,y,z),
执行器 ``plan_stage`` 取 ``q[3]`` ⇒ ``IndexError: list index out of range`` ⇒ 日志只留
``执行异常``, 号位技能**干点不动**(dry 与真动同一条路, 两边都坏)。
物证: 同批记录的 slot1 `[-0.7392295, 0.0034448, -0.6733875, 0.0087852]`、slot2、金手指点1、
insert_pose 都是 4 分量, ``|xyz|≈0.9999``、w 为正(≈0.004~0.04) —— 3 分量那几条是抄 slot1
改写 pos 时把 w 丢了。

补法(唯一允许的"补", 且有据可查):
  w = +sqrt(1 - (x²+y²+z²))
  · 单位四元数约束 ⇒ w 只能由 xyz 定出, 只有 ± 一个自由度;
  · 取 **+** 的依据: 同盘/同姿态族已记录的 slot1(w=+0.0088) / slot2(+0.0117) /
    金手指点1(+0.0395) / insert_pose(+0.0038) 全是正号;
  · 误判代价: 两候选姿态差 ≈ 2·asin(|w|) ≈ 0.9°(~1°) 量级。
  · 同时写 ``quat_repaired_at`` / ``quat_repaired_note`` 留痕; 现场若在画面上看出末端朝向
    有偏差 ⇒ 用 ``tools/record_l2_point.py --name slot3`` 重录该点即可(30 秒)。

用法: python3 tools/fix_taught_quat.py --dry     # 只看要补哪些
      python3 tools/fix_taught_quat.py           # 落盘(自动备份)
"""
import argparse
import json
import math
import os
import shutil
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PF = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")


def complete_w(xyz):
    """3 分量 → 4 分量(单位约束补 w, 取正号)。返回 (quat4, w, 说明) 或 (None, None, 原因)。"""
    s = sum(float(v) ** 2 for v in xyz)
    if s > 1.0 + 1e-6:
        return None, None, "x²+y²+z²=%.6f > 1 ⇒ 不是单位四元数的前三个分量, 不能补(需重录)" % s
    w = math.sqrt(max(0.0, 1.0 - s))
    return [float(xyz[0]), float(xyz[1]), float(xyz[2]), w], w, "w=+%.6f (1-Σ=%.6f)" % (w, 1.0 - s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只打印将要修的点, 不落盘")
    a = ap.parse_args()

    with open(PF, encoding="utf-8") as f:
        doc = json.load(f)
    pts = doc.get("points", {})
    todo, bad, ok = [], [], []
    for name, v in sorted(pts.items()):
        q = v.get("quat")
        if not isinstance(q, list):
            continue
        if len(q) == 4:
            ok.append(name)
            continue
        if len(q) != 3:
            bad.append((name, "quat 有 %d 个分量(既不是 3 也不是 4)" % len(q)))
            continue
        q4, w, why = complete_w(q)
        if q4 is None:
            bad.append((name, why))
        else:
            todo.append((name, q, q4, why))

    print("点位库: %s" % PF)
    print("  已是 4 分量: %d 个 (%s…)" % (len(ok), ", ".join(ok[:6])))
    for name, q, q4, why in todo:
        print("  🔧 %-12s %s → %s   %s" % (name, [round(x, 6) for x in q], [round(x, 6) for x in q4], why))
    for name, why in bad:
        print("  ⛔ %-12s %s" % (name, why))
    if a.dry:
        print("(--dry: 未落盘; 要修 %d 个)" % len(todo))
        return
    if not todo:
        print("无需修改。")
        return
    bak = "/tmp/taught_points.pre_quatfix_%s.json" % time.strftime("%m%d_%H%M%S")
    shutil.copy(PF, bak)
    for name, q, q4, why in todo:
        pts[name]["quat"] = [round(v, 7) for v in q4]
        pts[name]["quat_repaired_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        pts[name]["quat_repaired_note"] = ("原 quat 只有 3 分量(缺 w) ⇒ 按单位四元数约束补 w(取正, 同盘已记录点同号), "
                                           "%s; 现场若见末端朝向偏差请重录本点" % why)
    doc["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(PF, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print("已修 %d 个; 备份 %s" % (len(todo), bak))


if __name__ == "__main__":
    main()
