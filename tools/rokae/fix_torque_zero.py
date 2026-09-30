#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_torque_zero.py — 关节力矩传感器清零 (修 #41447 / #30400 / #13036)

依据 (xCoreSDK .pyi 原文):
  Cobot_6.calibrateForceSensor(all_axes: bool, axis_index: int, ec)
    "力传感器标定。标定过程需要约100ms, 该函数不会阻塞等待标定完成。
     标定前需要通过 setToolset() 设置正确的负载(Toolset::load), 否则会影响标定结果准确性。"

现状 (2026-09-22 08:25 实测, 静止 vel=0):
  jointTorque = [+29.276, -15.923, -25.191, -11.518, -22.036, +0.806] Nm
  而现场 URDF 重力模型 = [0.000, +28.92, -23.05, +3.32, -2.03, -0.12] Nm
  J1 是竖直轴 (重力恒 0) 却读 +29.28 → 读数含巨大零点偏置 (非负载)
  J5 读 -22.036 而模型 -2.03 → 静止就贴在 RSC 22.000 Nm 门槛上 → 一动即 #30400/#13036

动作: ① 读 before ② calibrateForceSensor(all_axes=True) ③ 读 after ④ 逐轴对照
**不放任何运动指令** (无 move/jog/rt), 只做传感器标定 + 读数。
"""
import json
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = "192.168.23.160"
# 现场 URDF 重力模型 (gravity_torque_check.py 输出)
MODEL = [0.000, 28.92, -23.05, 3.32, -2.03, -0.12]
LIMIT5 = 22.0


def rd(r):
    o = {}
    for lab, fn in (("torque", lambda: [float(v) for v in r.jointTorque({})]),
                    ("pos", lambda: [float(v) for v in r.jointPos({})]),
                    ("vel", lambda: [float(v) for v in r.jointVel({})]),
                    ("power", lambda: str(r.powerState({}))),
                    ("mode", lambda: str(r.operateMode({}))),
                    ("opstate", lambda: str(r.operationState({})))):
        try:
            o[lab] = fn()
        except Exception as e:                                # noqa: BLE001
            o[lab + "_err"] = str(e)[:120]
    return o


def main() -> int:
    apply_ = "--dry" not in sys.argv
    r = x.xMateRobot()
    r.connectToRobot(IP)
    b = rd(r)
    print("== BEFORE ==")
    print(f"  power={b.get('power')} mode={b.get('mode')} opstate={b.get('opstate')}")
    print(f"  vel={[round(v,4) for v in b.get('vel',[])]}")
    print(f"  torque={[round(v,4) for v in b.get('torque',[])]}")
    print(f"  J5 距门槛(22.0): {LIMIT5 - abs(b['torque'][4]):+.4f} Nm")

    res = {"before": b, "dry": not apply_}
    if not apply_:
        print("\n(--dry: 只读, 未标定)")
    else:
        print("\n== 执行 calibrateForceSensor(all_axes=True) — 约 100ms, 不阻塞 ==")
        t0 = time.time()
        ec = {}
        try:
            r.calibrateForceSensor(True, 0, ec)
            res["calib_ok"] = True
        except Exception as e:                                # noqa: BLE001
            res["calib_err"] = f"{type(e).__name__}: {str(e)[:200]}"
            print("  ❌ 调用异常:", res["calib_err"])
        res["calib_ec"] = {str(k): str(v) for k, v in (ec or {}).items()}
        print(f"  返回用时 {time.time()-t0:.2f}s · ec={res['calib_ec'] or '{}'}")
        time.sleep(3.0)                                       # 等标定生效
        a = rd(r)
        res["after"] = a
        print("\n== AFTER ==")
        print(f"  torque={[round(v,4) for v in a.get('torque',[])]}")
        print(f"\n{'轴':4s}{'BEFORE':>12s}{'AFTER':>12s}{'变化':>12s}{'URDF模型':>12s}{'清零后误差':>12s}")
        for i, ax in enumerate("J1 J2 J3 J4 J5 J6".split()):
            tb, ta = b["torque"][i], a["torque"][i]
            print(f"{ax:4s}{tb:12.4f}{ta:12.4f}{ta-tb:12.4f}{MODEL[i]:12.4f}{ta-MODEL[i]:12.4f}")
        j5 = abs(a["torque"][4])
        print(f"\n判据: J1 应 ≈0 (现 {a['torque'][0]:+.3f}) · J5 应 ≈2 Nm 量级 (现 {a['torque'][4]:+.3f})")
        print(f"      J5 距门槛余量: {LIMIT5 - j5:+.4f} Nm  "
              f"{'✅ 有余量, 可动' if j5 < 8 else '❌ 仍贴门槛 → 传感器/参数侧, 需厂家'}")

    try:
        r.disconnectFromRobot({})
    except Exception:                                         # noqa: BLE001
        pass
    p = "/sdk/torque_zero_%s.json" % time.strftime("%m%d_%H%M%S")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\n落盘:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
