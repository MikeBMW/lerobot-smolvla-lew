#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adjust_point_dz.py <点名> <dz_mm> [--dry] ["备注"] — 把已记录示教点沿**基准 Z** 精确平移, 不动机械臂。

为什么需要它: 现场常用小量微调("这个点再高 2 毫米"), 但真动通道的白名单最小步进是 5mm
(`L2.lift/L2.lower d_mm [5,300]/[5,100]`); 为了 2mm 去绕过白名单不值当, 所以在点位数据上做:
新值 = 该点**已采样真值** + (0, 0, dz), 姿态与 x/y 完全不动 ⇒ 纯刚性平移, 不引入任何拾取值。
安全: 写前自动备份到 /tmp/taught_points.pre_dz_<点名>_<时间戳>.json; 条目留痕 dz_applied_at/dz_mm/desc。
铁律: 只允许对**已存在**的点位做 ±20mm 以内的 Z 微调; 其它一律走正常示教(现场点动 + 页面 📝 记住此点)。
"""
import json
import os
import shutil
import sys
import time

PTS = "/home/ubuntu/zmax/data/skills/l2_atomic/taught_points.json"
LIMIT_MM = 20.0


def main(argv):
    args = [a for a in argv[1:] if a != "--dry"]
    dry = "--dry" in argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 2
    name, dz = args[0], float(args[1])
    note = args[2] if len(args) > 2 else ""
    if abs(dz) > LIMIT_MM:
        print("拒绝: |dz|=%.1fmm 超过微调上限 %.0fmm —— 这种量级该重新示教" % (abs(dz), LIMIT_MM))
        return 1
    d = json.load(open(PTS, encoding="utf-8"))
    pts = d["points"]
    if name not in pts:
        print("拒绝: 点位 %s 不存在(微调只对已有点位; 新点位要现场示教)" % name)
        return 1
    e = pts[name]
    old = list(e["pos"])
    new = list(old)
    new[2] = round(old[2] + dz / 1000.0, 7)
    print("点位 %s: z %.6f → %.6f (Δ%+.1fmm) · x/y/姿态不动" % (name, old[2], new[2], dz))
    print("  quat=%s" % [round(v, 6) for v in e["quat"]])
    if dry:
        print("  (--dry: 未写盘)")
        return 0
    b = "/tmp/taught_points.pre_dz_%s_%s.json" % (name, time.strftime("%m%d_%H%M%S"))
    shutil.copy(PTS, b)
    e["pos"] = new
    e["dz_applied_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    e["dz_mm"] = dz
    e["desc"] = (e.get("desc") or "") + " | Z微调%+.1fmm(%s)%s" % (
        dz, e["dz_applied_at"], (" · " + note) if note else "")
    json.dump(d, open(PTS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    back = json.load(open(PTS, encoding="utf-8"))["points"][name]["pos"]
    print("  已写盘并回读: pos=%s" % [round(v, 6) for v in back])
    print("  备份: %s" % b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
