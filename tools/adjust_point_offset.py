#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adjust_point_offset.py <点名> [<dz_mm>] [--dx=mm] [--dy=mm] [--dz=mm] [--dry] ["备注"]
   —— 把已记录示教点沿**基准轴**做小量刚性平移, 不动机械臂。

为什么需要它: 现场常用毫米级微调("再高 2 毫米" / "向右 2 毫米"), 但真动通道白名单最小步进是 5mm
(`L2.lift/L2.left/L2.lower d_mm [5,300]/[5,100]`); 为了 2mm 去绕白名单不值当, 所以在点位数据上做:
新值 = 该点**已采样真值** + (dx, dy, dz), 姿态完全不动 ⇒ 纯刚性平移, 不引入任何拾取值。
方向口径**与页面按钮一致**(registry axis): 向左=+Y(`L2.left`), 向右=−Y(`L2.right`),
抬升=+Z(`L2.lift`), 下降=−Z(`L2.lower`) —— 现场说"向右"就传 --dy=-2。
安全: |每个轴| ≤ 20mm; 写前自动备份 /tmp/taught_points.pre_off_<点名>_<时间戳>.json; 条目留痕。
铁律: 只对**已存在**的点位微调; 更大改动/新点位一律回现场点动 + 页面 📝 记住此点。
"""
import json
import shutil
import sys
import time

PTS = "/home/ubuntu/zmax/data/skills/l2_atomic/taught_points.json"
LIMIT_MM = 20.0


def _isnum(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def main(argv):
    rest, opt = [], {"dx": 0.0, "dy": 0.0, "dz": 0.0}
    dry = False
    for a in argv[1:]:
        if a == "--dry":
            dry = True
        elif a.startswith("--dx=") or a.startswith("--dy=") or a.startswith("--dz="):
            k, v = a[2:].split("=", 1)
            opt[k] = float(v)
        elif a.startswith("--"):
            print("未知参数 %s" % a)
            return 2
        else:
            rest.append(a)
    if len(rest) < 1:
        print(__doc__)
        return 2
    name = rest[0]
    if len(rest) > 1 and _isnum(rest[1]):    # 位置参数第 2 个 = dz(旧 CLI 兼容); 不是数字就当备注
        opt["dz"] = float(rest[1])
        note = rest[2] if len(rest) > 2 else ""
    else:
        note = rest[1] if len(rest) > 1 else ""
    for k, v in opt.items():
        if abs(v) > LIMIT_MM:
            print("拒绝: %s=%.1fmm 超过微调上限 %.0fmm ⇒ 这种量级该重新示教" % (k, v, LIMIT_MM))
            return 1
    d = json.load(open(PTS, encoding="utf-8"))
    if name not in d["points"]:
        print("拒绝: 点位 %s 不存在(微调只对已有点位; 新点位要现场示教)" % name)
        return 1
    e = d["points"][name]
    old = list(e["pos"])
    new = [round(old[0] + opt["dx"] / 1000.0, 7),
           round(old[1] + opt["dy"] / 1000.0, 7),
           round(old[2] + opt["dz"] / 1000.0, 7)]
    print("点位 %s: (%s) → (%s)  [dx%+.1f dy%+.1f dz%+.1f] mm · 姿态不动"
          % (name, ", ".join("%.6f" % v for v in old), ", ".join("%.6f" % v for v in new),
             opt["dx"], opt["dy"], opt["dz"]))
    print("  quat=%s" % [round(v, 6) for v in e["quat"]])
    if dry:
        print("  (--dry: 未写盘)")
        return 0
    b = "/tmp/taught_points.pre_off_%s_%s.json" % (name, time.strftime("%m%d_%H%M%S"))
    shutil.copy(PTS, b)
    e["pos"] = new
    e["offset_applied_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    e["offset_mm"] = opt
    e["desc"] = (e.get("desc") or "") + " | 三轴微调(dx%+.1f dy%+.1f dz%+.1f mm @%s)%s" % (
        opt["dx"], opt["dy"], opt["dz"], e["offset_applied_at"], (" · " + note) if note else "")
    json.dump(d, open(PTS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    back = json.load(open(PTS, encoding="utf-8"))["points"][name]["pos"]
    print("  已写盘并回读: pos=%s" % [round(v, 6) for v in back])
    print("  备份: %s" % b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
