#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_toolset_fields.py — 只读: 打印控制器里 工具集/工具列表 的全部字段 (质量/质心/坐标系)

判据: 若当前使用的工具 (toolset) 质量与质心为 0 或与实际末端(夹爪+工装+模块)不符
      ⇒ 动力学模型不补偿负载 ⇒ 腕部力矩长期贴限值 (J5 实测 21.96 / 限值 22.0)
零运动, 只读。
"""
import json
import sys

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

ROBOT_IP = "192.168.23.160"


def dump_obj(o, depth=0):
    """把 pybind11 对象的所有可读字段导成 dict (只读 getattr)."""
    out = {}
    try:
        names = [n for n in dir(o) if not n.startswith("_")]
    except Exception as e:                                    # noqa: BLE001
        return {"_dir_err": str(e)[:120]}
    for n in names:
        try:
            v = getattr(o, n)
        except Exception as e:                                # noqa: BLE001
            out[n] = f"<err {str(e)[:60]}>"
            continue
        if callable(v):
            continue
        if isinstance(v, (str, int, float, bool, list, tuple, type(None))):
            out[n] = v
        else:
            if depth < 2:
                out[n] = dump_obj(v, depth + 1)
            else:
                out[n] = str(v)[:80]
    return out


def main():
    out = {"ip": ROBOT_IP}
    r = x.xMateRobot()
    r.connectToRobot(ROBOT_IP)

    # 模块级枚举发现
    for kw in ("Limit", "Type", "Torque", "Tool", "Frame", "Coord"):
        try:
            out[f"module_{kw}"] = [n for n in dir(x) if kw.lower() in n.lower()][:20]
        except Exception:                                     # noqa: BLE001
            pass

    try:
        out["toolset"] = dump_obj(r.toolset({}))
    except Exception as e:                                    # noqa: BLE001
        out["toolset_err"] = str(e)[:200]

    try:
        items = r.toolsInfo({})
        out["toolsInfo_count"] = len(items)
        out["toolsInfo"] = [dump_obj(it) for it in items]
    except Exception as e:                                    # noqa: BLE001
        out["toolsInfo_err"] = str(e)[:200]

    try:
        r.disconnectFromRobot({})
        out["disconnect"] = "ok"
    except Exception as e:                                    # noqa: BLE001
        out["disconnect_err"] = str(e)[:120]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
