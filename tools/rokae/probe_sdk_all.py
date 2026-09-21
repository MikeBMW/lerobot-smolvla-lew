#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_sdk_all.py — 只读: 把控制器 SDK 暴露的 93 个接口全列出来 (找 清零/标定/负载/报警 类)

用途: 定"力矩传感器清零"和"工具负载校验"到底能不能由 SDK 做, 还是必须示教器/物理操作。
零运动, 只 connect / dir() / disconnect。
"""
import json
import sys

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

r = x.xMateRobot()
r.connectToRobot("192.168.23.160")
names = sorted(n for n in dir(r) if not n.startswith("_"))
out = {"total": len(names), "names": names}
# 关键字的候选
kw = ("zero", "calib", "reset", "clear", "torque", "sensor", "load", "tool",
      "alarm", "error", "drag", "collision", "recover", "power", "state", "limit", "soft")
out["by_keyword"] = {k: [n for n in names if k in n.lower()] for k in kw}
out["by_keyword"] = {k: v for k, v in out["by_keyword"].items() if v}
try:
    r.disconnectFromRobot({})
    out["disconnect"] = "ok"
except Exception as e:                                        # noqa: BLE001
    out["disconnect_err"] = str(e)[:100]
print(json.dumps(out, ensure_ascii=False, indent=1))
