#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_torque_stability.py — 只读: 清零后 10s 稳定性复读 + 报警/错误状态查询

清零 (calibrateForceSensor) 后的验收:
  ① 读数是否稳定 (不能是一次性跳变) ② J5 是否远离 22.000 Nm 门槛
  ③ 控制器是否还挂着锁存报警 (errors / operationState / powerState)
**零运动、零写入。**
"""
import json
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = "192.168.23.160"
LIMIT5 = 22.0


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP)
    rows = []
    print(f"{'t(s)':>5s}  jointTorque (Nm) J1..J6")
    t0 = time.time()
    for k in range(6):
        try:
            tq = [float(v) for v in r.jointTorque({})]
        except Exception as e:                                # noqa: BLE001
            tq = None
            print("  读失败:", str(e)[:100])
        if tq:
            rows.append(tq)
            print(f"{time.time()-t0:5.1f}  " + "  ".join(f"{v:+8.4f}" for v in tq)
                  + f"   | J5 余量 {LIMIT5 - abs(tq[4]):+7.4f}")
        time.sleep(2.0)
    if rows:
        import statistics as st
        j5 = [r_[4] for r_ in rows]
        print(f"\nJ5: 均值 {st.mean(j5):+.4f} · 极差 {max(j5)-min(j5):.4f} Nm · "
              f"距门槛余量 {LIMIT5 - max(abs(v) for v in j5):+.4f} Nm")
        print(f"J1: {rows[-1][0]:+.4f} (应为 ≈0)  · 全轴极差 "
              f"{max(max(abs(rows[i][k]-rows[0][k]) for i in range(len(rows))) for k in range(6)):.4f} Nm")

    st_out = {}
    for lab, fn in (("powerState", lambda: str(r.powerState({}))),
                    ("operateMode", lambda: str(r.operateMode({}))),
                    ("operationState", lambda: str(r.operationState({})))):
        try:
            st_out[lab] = fn()
        except Exception as e:                                # noqa: BLE001
            st_out[lab + "_err"] = str(e)[:100]
    # 报警/错误查询 (接口名以 SDK 为准, 存在才调)
    for name in ("errors", "errorCode", "getError", "alarmInfo"):
        if hasattr(r, name):
            try:
                v = getattr(r, name)({})
                try:
                    v = json.loads(json.dumps(v, default=lambda o: [str(a) for a in o] if hasattr(o, "__iter__") else str(o)))[:6]
                except Exception:                             # noqa: BLE001
                    v = str(v)[:300]
                st_out[name] = v
            except Exception as e:                            # noqa: BLE001
                st_out[name + "_err"] = str(e)[:120]
    print("\n== 状态/报警 ==")
    for k, v in st_out.items():
        print(f"  {k:16s}{v}")

    try:
        r.disconnectFromRobot({})
    except Exception:                                         # noqa: BLE001
        pass
    p = "/sdk/torque_stability_%s.json" % time.strftime("%m%d_%H%M%S")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "state": st_out}, f, ensure_ascii=False, indent=1)
    print("\n落盘:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
