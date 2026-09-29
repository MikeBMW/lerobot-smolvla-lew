#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
traj_display.py — "轨迹显示开关 + 清除" 的**单一真源**(页面/发布器/服务都读它)
════════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 「我看手臂相机也已经有了轨迹了, 要增加一个显示轨迹和清除轨迹的按钮, 要不走的多了
                  轨迹就很乱; **默认不要一开始就显示轨迹**, 需要人工开启轨迹显示功能。」

状态文件: data/scene/traj_display.json
    {"show": bool,        # 总开关: false ⇒ 叠加层里把 trace/plan 两类折线全部撤掉
     "baseline_n": int,   # 清除线: 只发布录制器里**第 n 个点之后**的轨迹(= 清除走过的路)
     "plan_hidden": bool, # 规划航路(origin=plan)当前是否被撤掉
     "at": "..."}

为什么不改 cam_live_stream.py: 那个服务老倪正看着, 改它必须重启(会掐断他眼前的 MJPEG)。
  本模块只操作 **叠加规格(overlay_spec.json)**, 推流服务本来每帧热读它 ⇒ 点了按钮立刻生效、零重启。

约定:
  · 撤掉 = 从 spec 里把这类元素**挪到缓存**(data/scene/_hidden_paths.json), 不是删数据 ⇒ 再显示能原样恢复。
  · 轨迹的历史(录制器 /tmp/live_trace.json + jsonl)一律不动 —— 那是标定/复盘要用的原始数据。
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

SCENE = os.path.join(REPO, "data", "scene")
STATE = os.path.join(SCENE, "traj_display.json")
HIDDEN = os.path.join(SCENE, "_hidden_paths.json")
SPEC = os.path.join(SCENE, "overlay_spec.json")
PATH_ORIGINS = ("trace", "plan")
CAM = "arm"


def _rj(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                             # noqa: BLE001
        return d


def _wj(p, o):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def get_state() -> dict:
    s = _rj(STATE) or {}
    return {"show": bool(s.get("show", False)),                       # 🔴 默认关: 人工开启才画
            "baseline_n": int(s.get("baseline_n", 0) or 0),
            "plan_hidden": bool(s.get("plan_hidden", False)),
            "at": s.get("at") or ""}


def set_state(show=None, baseline_n=None, plan_hidden=None) -> dict:
    s = get_state()
    if show is not None:
        s["show"] = bool(show)
    if baseline_n is not None:
        s["baseline_n"] = int(baseline_n)
    if plan_hidden is not None:
        s["plan_hidden"] = bool(plan_hidden)
    s["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _wj(STATE, s)
    return s


def _load_spec():
    import scene_overlay as SO                                                     # noqa: E402
    return SO.load_spec(), SO


def strip_origins(origins=PATH_ORIGINS) -> dict:
    """把指定 origin 的折线元素从 spec 挪到缓存文件(可恢复)。返回计数。"""
    spec, SO = _load_spec()
    cam = (spec.get("cameras") or {}).get(CAM) or {}
    keep, moved = [], []
    for b in cam.get("boxes") or []:
        (moved if str(b.get("origin")) in origins else keep).append(b)
    if not moved:
        return {"moved": 0, "cached": len((_rj(HIDDEN) or {}).get("boxes") or [])}
    h = _rj(HIDDEN) or {}
    have = {json.dumps(b, sort_keys=True, ensure_ascii=False) for b in (h.get("boxes") or [])}
    for b in moved:
        k = json.dumps(b, sort_keys=True, ensure_ascii=False)
        if k not in have:
            h.setdefault("boxes", []).append(b)
    h["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _wj(HIDDEN, h)
    cam["boxes"] = keep
    SO.save_spec(spec)
    return {"moved": len(moved), "cached": len(h["boxes"])}


def restore_origins(origins=PATH_ORIGINS) -> dict:
    """把缓存里的折线元素放回 spec(同 origin 的旧元素先清掉, 避免叠加两份)。"""
    spec, SO = _load_spec()
    h = _rj(HIDDEN) or {}
    box_all = h.get("boxes") or []
    use = [b for b in box_all if str(b.get("origin")) in origins]
    rest = [b for b in box_all if str(b.get("origin")) not in origins]
    if not use:
        return {"restored": 0}
    cam = (spec.get("cameras") or {}).get(CAM) or {}
    cam["boxes"] = [b for b in (cam.get("boxes") or []) if str(b.get("origin")) not in origins] + use
    spec.setdefault("cameras", {})[CAM] = cam
    SO.save_spec(spec)
    h["boxes"] = rest
    _wj(HIDDEN, h)
    return {"restored": len(use)}


def paths_cached() -> dict:
    """缓存里(_hidden_paths.json)还有多少折线元素。"""
    h = _rj(HIDDEN) or {}
    out = {}
    for b in h.get("boxes") or []:
        o = str(b.get("origin"))
        out.setdefault(o, {"n_el": 0, "n_pts": 0})
        out[o]["n_el"] += 1
        out[o]["n_pts"] += len(b.get("pts3d") or [])
    return out


def paths_in_spec() -> dict:
    spec = _rj(SPEC) or {}
    cam = (spec.get("cameras") or {}).get(CAM) or {}
    out = {}
    for b in cam.get("boxes") or []:
        if b.get("kind") == "path3d":
            o = str(b.get("origin"))
            out.setdefault(o, {"n_el": 0, "n_pts": 0})
            out[o]["n_el"] += 1
            out[o]["n_pts"] += len(b.get("pts3d") or [])
    return out


def apply(show: bool) -> dict:
    """按开关立即落盘(页面点按钮后调用): show=False ⇒ 撤掉 trace+plan; True ⇒ 恢复 plan(trace 由发布器发)。"""
    if show:
        set_state(show=True, plan_hidden=False)
        r = restore_origins()
        return {"show": True, "restored": r}
    set_state(show=False, plan_hidden=True)
    return {"show": False, "stripped": strip_origins()}


if __name__ == "__main__":                                                        # 小 CLI, 便于命令行核验
    act = sys.argv[1] if len(sys.argv) > 1 else "state"
    if act == "on":
        print(json.dumps(apply(True), ensure_ascii=False))
    elif act == "off":
        print(json.dumps(apply(False), ensure_ascii=False))
    elif act == "baseline":                       # 命令行改清除线: 0 = 显示全部历史
        print(json.dumps(set_state(baseline_n=int(sys.argv[2])), ensure_ascii=False))
    else:
        print(json.dumps({"state": get_state(), "in_spec": paths_in_spec(),
                          "cached": paths_cached()}, ensure_ascii=False, indent=1))
