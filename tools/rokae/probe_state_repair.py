#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_state_repair.py — 只读: 现场状态 + 可修接口存在性 (2026-09-22 复查)

背景: 用户报「机器人还是报警, 现在动不了了」。
昨天报告里写「SDK 无语力矩/碰撞力接口」—— 复查 xCoreSDK 的 .pyi 发现**是错的**:
  · calibrateForceSensor(all_axes, axis_index)  ← 力(矩)传感器标定/清零, 正是 #41447 的正解
  · enableCollisionDetection(sensitivity[DoF], behaviour, fallback_compliance)
  · disableCollisionDetection()
  · enableDrag/disableDrag
本探针只做两件事: ① 读现状 ② 确认这三个接口在本机型实例上真实可调用。**零运动、零写入。**

跑法:
  sudo docker run --rm --network host -v ~/zmax_data/rokae_sdk:/sdk -w /sdk ros:humble-ros-base \
      python3 /sdk/probe_state_repair.py
"""
import json
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = "192.168.23.160"
OUT = "/sdk/state_repair_%s.json" % time.strftime("%m%d_%H%M%S")


def safe(fn, label, out, *a, **kw):
    try:
        out[label] = fn(*a, **kw)
    except Exception as e:                                    # noqa: BLE001
        out[label + "_err"] = f"{type(e).__name__}: {str(e)[:150]}"


def main() -> int:
    o = {"ip": IP, "ts": time.strftime("%F %T")}
    r = x.xMateRobot()
    r.connectToRobot(IP)

    for lab, fn in (
        ("powerState", lambda: str(r.powerState({}))),
        ("operateMode", lambda: str(r.operateMode({}))),
        ("operationState", lambda: str(r.operationState({}))),
        ("robotState", lambda: str(r.robotState({}))),
    ):
        safe(fn, lab, o)
    safe(lambda: [round(float(v), 6) for v in r.jointPos({})], "jointPos_rad", o)
    safe(lambda: [round(float(v), 6) for v in r.jointVel({})], "jointVel_rad_s", o)
    safe(lambda: [round(float(v), 6) for v in r.jointTorque({})], "jointTorque_Nm", o)
    safe(lambda: [round(float(v), 6) for v in r.cartPosture(x.CoordinateType.endInRef, {}).trans],
         "tcp_m", o)

    # 工具负载 (力传感器标定的前提: 负载必须正确)
    try:
        ts = r.toolset({})
        o["toolset"] = {"name": getattr(ts, "name", None)}
        ld = getattr(ts, "load", None)
        if ld is not None:
            o["toolset"]["load"] = {"mass": float(getattr(ld, "mass", -1)),
                                    "cog": [float(c) for c in getattr(ld, "cog", [])]}
        info = getattr(ts, "toolsInfo", None)
        o["toolset"]["tools_n"] = len(info) if info is not None else None
    except Exception as e:                                    # noqa: BLE001
        o["toolset_err"] = f"{type(e).__name__}: {str(e)[:150]}"

    # ★ 关键: 可修接口在本机型是否真实存在
    o["repair_ifaces"] = {k: bool(hasattr(r, k)) for k in
                          ("calibrateForceSensor", "enableCollisionDetection",
                           "disableCollisionDetection", "enableDrag", "disableDrag",
                           "clearServoAlarm", "recoverState", "setToolset", "setLoad")}

    # 控制器日志原文 (最近错误 + 警告)
    try:
        errs = r.queryControllerLog(30, {x.LogInfoLevel.error}, {})
        o["log_error_n"] = len(errs)
        o["log_error"] = [json.loads(json.dumps(L, default=str)) for L in errs[:10]]
    except Exception as e:                                    # noqa: BLE001
        o["log_error_err"] = str(e)[:150]
    try:
        w = r.queryControllerLog(20, {x.LogInfoLevel.warning}, {})
        o["log_warn_n"] = len(w)
        o["log_warn"] = [json.loads(json.dumps(L, default=str)) for L in w[:6]]
    except Exception as e:                                    # noqa: BLE001
        o["log_warn_err"] = str(e)[:150]

    try:
        r.disconnectFromRobot({})
    except Exception:                                         # noqa: BLE001
        pass

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)

    print("== 现状 ==")
    for k in ("powerState", "operateMode", "operationState", "robotState"):
        print(f"  {k:16s}{o.get(k, o.get(k + '_err'))}")
    print(f"  jointTorque_Nm  {o.get('jointTorque_Nm')}")
    print(f"  jointVel_rad_s  {o.get('jointVel_rad_s')}")
    print(f"  tcp_m           {o.get('tcp_m')}")
    print(f"  toolset         {o.get('toolset', o.get('toolset_err'))}")
    print("== 可修接口 ==")
    for k, v in o["repair_ifaces"].items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"== 控制器日志: 错误 {o.get('log_error_n')} 条 / 警告 {o.get('log_warn_n')} 条 ==")
    for L in o.get("log_error", [])[:6]:
        print("  E:", json.dumps(L, ensure_ascii=False)[:300])
    for L in o.get("log_warn", [])[:4]:
        print("  W:", json.dumps(L, ensure_ascii=False)[:240])
    print("\n落盘:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
