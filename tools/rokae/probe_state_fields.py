#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_state_fields.py — 只读枚举 xMateRobot 上与「上电/急停/碰撞/报警」相关的真实字段。

为什么(2026-10-01 老倪: 「我在现场，怎么还是43小时的数据，赶快更新啊」):
  页面三查(上电/急停/碰撞)的唯一来源是 Orin 的 /robot_status 话题 → 该发布者 09-29 起不再通告端点
  ⇒ 缓存 robot_status.json 停在 09-29 13:46。而**直连控制器**这条路(rokae_tcp_sampler)一直新鲜。
  所以要在直连路上把三查也读出来 —— 先把真实可用的字段/方法枚举清楚, 不靠猜。
全程只读: connectToRobot + 状态查询 + disconnect, **不发任何运动指令**。
"""
import json
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = "192.168.23.160"
o = {"ip": IP, "ts": time.strftime("%F %T")}
r = x.xMateRobot()


def safe(fn, label):
    try:
        v = fn()
        o[label] = json.loads(json.dumps(v, default=str)) if not isinstance(v, (str, int, float, bool, type(None))) else v
    except Exception as e:                                        # noqa: BLE001
        o[label + "_err"] = "%s: %s" % (type(e).__name__, str(e)[:120])


r.connectToRobot(IP)
o["methods_state_like"] = sorted(
    n for n in dir(r) if not n.startswith("_") and any(
        k in n.lower() for k in ("state", "safety", "stop", "emerg", "emg", "collision", "alarm", "error", "power", "mode")))

for lab, fn in (
    ("powerState", lambda: str(r.powerState({}))),
    ("operateMode", lambda: str(r.operateMode({}))),
    ("operationState", lambda: str(r.operationState({}))),
):
    safe(fn, lab)

for m in ("getStateData", "stateData", "safetyState", "getSafetyState", "emergencyStop", "getEmergencyStop"):
    if hasattr(r, m):
        safe(lambda m=m: r.__getattribute__(m)({}), m)

# 控制器错误日志(报警真源) —— 与新状态文件同一口径: 最近 30 条里的 error/warning
try:
    errs = r.queryControllerLog(30, {x.LogInfoLevel.error}, {})
    o["log_error_n"] = len(errs)
    o["log_error_head"] = [str(json.loads(json.dumps(L, default=str)))[:160] for L in errs[:4]]
except Exception as e:                                            # noqa: BLE001
    o["log_error_err"] = str(e)[:120]

print(json.dumps(o, ensure_ascii=False, indent=1, default=str))
# 断开方式各家 SDK 不一样: 没 disconnect 就换个名字试, 都不行也无所谓(进程退出即释放)
for _m in ("disconnect", "disconnectFromRobot", "close", "release"):
    try:
        getattr(r, _m)()
        break
    except Exception:                                             # noqa: BLE001
        continue
