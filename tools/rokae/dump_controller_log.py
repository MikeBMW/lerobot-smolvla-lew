#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_controller_log.py — 只读导出控制器报警日志(错误+警告), 带时间戳。

用途: ①事故复盘的**真值**(谁在什么时刻报了什么) ②页面「三查」的报警来源。
2026-10-01 首次跑即命中本次碰撞: 「RSC检测到关节[2 ]碰撞力超限, 触发安全停止」。
只读: connectToRobot + queryControllerLog + 退出, 不发任何运动指令。
用法: python3 /sdk/dump_controller_log.py [条数=40]
"""
import json
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
r = x.xMateRobot()
r.connectToRobot("192.168.23.160")


def rows(lvl, n):
    try:
        out = []
        for L in r.queryControllerLog(n, {lvl}, {}):
            d = {}
            for k in ("id", "timestamp", "content", "repair", "level"):
                try:
                    d[k] = str(getattr(L, k))
                except Exception:                                 # noqa: BLE001
                    pass
            if not d:
                for k in ("id", "timestamp", "content", "repair"):
                    try:
                        d[k] = str(L.__getattribute__(k))
                    except Exception:                             # noqa: BLE001
                        pass
            out.append(d)
        return out
    except Exception as e:                                        # noqa: BLE001
        return [{"err": "%s: %s" % (type(e).__name__, str(e)[:140])}]


res = {"ts_container": time.strftime("%F %T"), "ip": "192.168.23.160",
       "error": rows(x.LogInfoLevel.error, N), "warning": rows(x.LogInfoLevel.warning, min(N, 20))}
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
