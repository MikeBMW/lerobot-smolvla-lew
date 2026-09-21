#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_torque_alarm.py — 只读追问珞石控制器: 六轴力矩真值 + 工具负载/报警接口发现

背景 (2026-09-22): 现场报「5 轴总超过限制扭矩, 且仍是报警状态」。
驱动日志 (/tmp/tashan_robot_run.log) 里**一次 Axis5 都没有**, 但控制器报警历史有:
  #41447 力矩传感器与模型偏差较大 Axis1: sensor_torque≈28~30Nm 而 torque command≈0  (工具负载/质心未设的典型症状)
  #13047 RSC 参数与主控不一致, 需硬重启机器人才生效
  #10014 上电状态无法打开拖动 / #10013 下电失败
⇒ 本探针只读取关节力矩真值(判 J5 是否长期贴着 22Nm 限值), 并枚举控制器可查询的
   工具负载/报警/安全类接口, 为下一步定修法提供证据。**零运动**, 只 connect/读/disconnect。

跑法:
  sudo docker run --rm --network host -v ~/zmax_data/rokae_sdk:/sdk -w /sdk ros:humble-ros-base \
      python3 /sdk/probe_torque_alarm.py
"""
import json
import sys

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

ROBOT_IP = "192.168.23.160"
# 关节力矩限值参考 (软限幅): 现场控制器报 J5 限值 22.0 Nm (2026-09-21 实测 22.013951)
REF_LIMIT = {1: None, 2: None, 3: None, 4: None, 5: 22.0, 6: None}


def safe(fn, label, out, *a, **kw):
    try:
        v = fn(*a, **kw)
        out[label] = v
    except Exception as e:                                   # noqa: BLE001
        out[label + "_err"] = str(e)[:160]


def main():
    out = {"ip": ROBOT_IP}
    r = x.xMateRobot()
    r.connectToRobot(ROBOT_IP)

    # ---- 只读状态 ----
    safe(lambda: [round(float(v), 9) for v in r.jointPos({})], "jointPos_rad", out)
    safe(lambda: [round(float(v), 6) for v in r.jointVel({})], "jointVel_rad_s", out)
    safe(lambda: [round(float(v), 6) for v in r.jointTorque({})], "jointTorque_Nm", out)
    safe(lambda: [round(float(v), 9) for v in r.cartPosture(x.CoordinateType.endInRef, {}).trans],
         "tcp_endInRef_m", out)
    safe(lambda: str(r.operateMode({})), "operateMode", out)
    for name, fn in (
        ("powerState", lambda: str(r.powerState({}))),
        ("robotState", lambda: str(r.robotState({}))),
        ("safetyState", lambda: str(r.safetyState({}))),
        ("getError", lambda: str(r.getError({}))),
        ("errorCode", lambda: str(r.errorCode({}))),
        ("getToolset", lambda: str(r.getToolset({}))),
        ("getLoad", lambda: str(r.getLoad({}))),
        ("getPayload", lambda: str(r.getPayload({}))),
        ("getToolLoad", lambda: str(r.getToolLoad({}))),
        ("getTorqueLimit", lambda: str(r.getTorqueLimit({}))),
    ):
        if hasattr(r, name):
            safe(fn, name, out)

    # ---- 接口发现: 按关键字列出控制器暴露的查询/设置函数名 ----
    keys = ("tool", "load", "payload", "alarm", "error", "safety", "torque",
            "limit", "collision", "drag", "power", "reset", "clear", "state")
    found = {}
    for src_name, src in (("instance", r), ("class", type(r))):
        try:
            names = [n for n in dir(src) if not n.startswith("_")]
        except Exception:                                     # noqa: BLE001
            continue
        for kw in keys:
            hit = [n for n in names if kw in n.lower()]
            if hit:
                found.setdefault(kw, {})[src_name] = sorted(hit)
        found.setdefault("_all_count", {})[src_name] = len(names)
    out["interfaces_found"] = found

    try:
        r.disconnectFromRobot({})
        out["disconnect"] = "ok"
    except Exception as e:                                    # noqa: BLE001
        out["disconnect_err"] = str(e)[:120]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
