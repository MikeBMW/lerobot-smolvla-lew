#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_settle_final.py — 关机前最后一次: 等静止 → (若偏离) 慢速回位到激励前位姿 → 确认静止
安全: 仅当控制权在我(指令已验证生效) · speed=8 · 位移 <10cm · 只做一次 · 之后不再下发动作
"""
import json
import sys
import time

import numpy as np

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, R + "/tools")
from selfcal_kinematic import sdk, status                                             # noqa: E402
from a5_handeye_collect import move_pose, wait_idle, joints                            # noqa: E402
from s2_excite_collect import tap_last                                                # noqa: E402

TARGET = [0.5368, -0.0294, 0.2916]        # 激励前位姿 (脚本内记录的起始, 关机前回到这里)


def state():
    s = status()
    p = np.array((s.get("endInRef") or [])[:3], dtype=float)
    v = s.get("jointVel") or []
    return s, p, v


def main() -> int:
    for _ in range(6):
        s, p, v = state()
        if all(abs(x) < 5e-4 for x in v[:6]):
            break
        time.sleep(2)
    print("等待静止... 当前 TCP(mm)=%s 速度=%s" % ([round(x*1000, 1) for x in p], [round(x, 5) for x in v]))
    if np.linalg.norm(p - np.array(TARGET)) * 1000 < 2.0:
        print("✅ 已在下发前位姿 2mm 内, 无需动作")
    else:
        d = (np.array(TARGET) - p) * 1000
        print("偏离 %.2f mm %s → 慢速回位一次 (speed=8)" % (np.linalg.norm(d), np.round(d, 1).tolist()))
        if np.linalg.norm(d) > 100:
            print("❌ 偏离 >10cm → 超出授权范围, 不回位, 报现场"); return 2
        t = tap_last() or {}
        quat = list(t.get("tcp_quat") or [0, 0, 0, 1])
        move_pose(TARGET, quat, 8.0, joints())
        wait_idle()
    time.sleep(3)
    s, p, v = state()
    print("回位后 TCP(mm)=%s · 与目标差 %.3f mm · 速度=%s" %
          ([round(x*1000, 1) for x in p], np.linalg.norm(p - np.array(TARGET))*1000, [round(x, 5) for x in v[:6]]))
    print("静止: %s · %s/%s" % ("✅" if all(abs(x) < 5e-4 for x in v[:6]) else "⚠️ 仍有微动",
                                s.get("powerState"), s.get("operateMode")))
    print("【关机前状态】本次为最后一次真机动作, 之后不再下发任何指令")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
