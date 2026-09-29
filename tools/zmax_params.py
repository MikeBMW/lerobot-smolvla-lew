#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 Z-MAX 全系统参数与标定统一接口 (单一真源读取器)

老倪 (09-22): 「包括标定参数接口」「模块化」「不要发出真机控制指令，但是你可以采集真机的数据」

设计原则
--------
1. **一份真源, 多处读取**: 所有层 (L4/L3/L2, 状态空间引擎, 3D 视图, 感知反投影, 训练配置)
   通过本模块拿参数 —— 禁止再各自硬编码几何/限位/质量/内外参。
   · 机器人模型 → `config/robot/zmax_robot_spec.json`  (tools/robot_spec_sync.py 从 URDF+真机实测生成)
   · 标定参数   → `config/calib/zmax_calib.json`       (tools/zmax_params.py --sync 合并各源)
2. **缺项诚实**: 未标定的项返回 None 并在 `gaps()` 里列原因, 绝不编造默认值冒充已标。
3. **接口稳定**: 对外只暴露函数 (robot_spec / fk / joint_limits / tool / calib / camera /
   plane_z / gaps / check), 内部结构可演进。

用法 (CLI)
----------
  gui-venv311/bin/python tools/zmax_params.py --show           # 打印全部参数 + 标定就绪度
  gui-venv311/bin/python tools/zmax_params.py --check          # 只报缺口 (非零退出=有关键缺口)
  gui-venv311/bin/python tools/zmax_params.py --sync           # 从各源合并 → config/calib/zmax_calib.json
  gui-venv311/bin/python tools/zmax_params.py --fk 0.16 -0.06 -2.54 1.45 0.44 -0.70
                                                               # 用真源几何算 FK (对照真机 tcp)
  gui-venv311/bin/python tools/zmax_params.py --m 2.0 --inertia on
                                                               # 🧮 写流形引擎主标定参数 M (状态空间结构参数)
  gui-venv311/bin/python tools/zmax_params.py --json
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "config", "robot", "zmax_robot_spec.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
REAL_CAM_CALIB = os.path.join(ROOT, "models", "real_cam_calib.json")
# 🧮 流形引擎主标定参数 M 的**可写真源** (config/calib/zmax_manifold.json → 合并进 calib.json)
MANIFOLD_P = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
CALIB_REPORT_GLOB = os.path.expanduser("~/zmax_data/calib_report_*.json")
GEOM_CANDIDATES = [
    os.path.expanduser("~/zmax_data/real_cell_geometry.json"),
    os.path.join(ROOT, "data", "real_cell_geometry.json"),
    os.path.expanduser("~/zmax_data/ss_out/real_cell_geometry.json"),
]
_LIVE_TAP = os.path.expanduser("~/zmax_data/real_tap_*/state_*.jsonl")


# ───────────────────────── 机器人模型 (单一真源) ─────────────────────────
def robot_spec(path: str = SPEC) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def joint_limits(spec: dict | None = None) -> list:
    """六轴位置/速度/力矩限位 → [{name, lower, upper, velocity, effort}]。L2 安全闸直接吃这个。"""
    spec = spec or robot_spec()
    out = []
    for j in spec["joints"]:
        if j["type"] not in ("revolute", "continuous", "prismatic"):
            continue
        L = j["limit"] or {}
        out.append({"name": j["name"], "type": j["type"],
                    "lower": L.get("lower"), "upper": L.get("upper"),
                    "velocity": L.get("velocity"), "effort": L.get("effort")})
    return out


def link_params(spec: dict | None = None) -> list:
    """连杆质量/质心/惯量张量 (给动力学层与仿真)。"""
    spec = spec or robot_spec()
    return [{"name": L["name"], "mass": L["mass"], "com": L["com"], "inertia": L["inertia"]}
            for L in spec["links"] if L.get("mass") is not None]


def tool(spec: dict | None = None) -> dict:
    """末端工具链: URDF 名义 tool 系 + 控制器负载 + **真机反解产线 TCP**。"""
    spec = spec or robot_spec()
    return {"nominal_tool": spec.get("tool"), "payload": spec.get("payload"),
            "control_tcp": spec.get("control_tcp"),
            "tcp_frame": spec.get("control_tcp", {}).get("frame")}


# ───────────────────────── FK (只用真源, 不依赖 URDF 文件) ─────────────────────────
def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def _mm(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mv(A, v):
    return [sum(A[i][k] * v[k] for k in range(3)) for i in range(3)]


def fk(q, spec: dict | None = None, upto: str | None = None) -> tuple:
    """正运动学: 关节角(rad) → (R 3x3, t 3) 在 base 系。

    口径与 tools/ss_fk_xms5.py 逐位一致 (已 50 组随机位形对照, 偏差 0.0)。
    upto="<link名>" 可停在该 link (法兰系); 默认走到链末 (含工具固定关节)。
    """
    spec = spec or robot_spec()
    R = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    t = [0.0, 0.0, 0.0]
    qi = 0
    for j in spec["joints"]:
        tn, rn = j["origin_xyz"], j["origin_rpy"]
        d = _mv(R, tn)
        t = [t[i] + d[i] for i in range(3)]
        R = _mm(R, _mm(_mm(_rz(rn[2]), _ry(rn[1])), _rx(rn[0])))
        if j["type"] in ("revolute", "continuous", "prismatic"):
            ang = q[qi] if qi < len(q) else 0.0
            qi += 1
            ax = j["axis"]
            if ax == [0, 0, 1]:
                Rq = _rz(ang)
            elif ax == [0, 1, 0]:
                Rq = _ry(ang)
            elif ax == [1, 0, 0]:
                Rq = _rx(ang)
            elif ax == [0, -1, 0]:
                Rq = _ry(-ang)
            elif ax == [0, 0, -1]:
                Rq = _rz(-ang)
            else:
                Rq = _rz(ang)
            R = _mm(R, Rq)
        if upto is not None and j["child"] == upto:
            break
    return R, t


# ───────────────────────── 标定注册表 ─────────────────────────
def _load_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


# ───────── 🧮 流形引擎主标定参数 M (真源: src/lerobot/manifold/manifold_engine.py) ─────────
def _manifold_consts():
    """从流形引擎模块取 M 的常量 (单一真源, 不重复硬编码); 失败则回退字面量。"""
    try:
        import importlib.util as _ilu
        _p = os.path.join(ROOT, "src", "lerobot", "manifold", "manifold_engine.py")
        spec = _ilu.spec_from_file_location("lerobot.manifold.manifold_engine", _p)
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        return float(m.MANIFOLD_M_DEFAULT), list(m.MANIFOLD_M_RANGE), str(m.MANIFOLD_M_UNIT)
    except Exception:  # noqa: BLE001
        return 1.0, [0.0, 8.0], "等效惯量尺度 (无量纲归一化)"


MANIFOLD_M_DEFAULT, MANIFOLD_M_RANGE, MANIFOLD_M_UNIT = _manifold_consts()


def _manifold_section() -> dict:
    """流形引擎标定域 (M/inertia/range/unit/…) —— 供 sync_calib 合并与写盘共用。"""
    _mp = _load_json(MANIFOLD_P) or {}
    return {
        "M": float(_mp.get("M", MANIFOLD_M_DEFAULT)),
        "inertia": bool(_mp.get("inertia", False)),
        "range": list(MANIFOLD_M_RANGE),
        "unit": MANIFOLD_M_UNIT,
        "flow": "二阶: v ← v + (F/M)·dt; p ← exp_p(v·dt) (过阻尼极限 = M→0, 旧一阶 GD)",
        "struct_src": "从流形结构导出 (曲率/维度/尺度) — 非自由拟合参数; 现场以单标量暴露",
        "zero_regression": "inertia=false (默认) 或 M=0 ⇒ 引擎行为与旧版一阶过阻尼逐位相同",
        "_src": os.path.relpath(MANIFOLD_P, ROOT) if os.path.isfile(MANIFOLD_P) else
                "默认值 (无 config/calib/zmax_manifold.json)",
    }


def sync_calib(write: bool = True) -> dict:
    """把各处标定产物合并成统一注册表 (每项带 _src 溯源)。缺项写 null + 原因。"""
    reg: dict = {"_doc": ("Z-MAX 标定参数注册表 — 由 tools/zmax_params.py --sync 合并生成。"
                          "所有层读本文件, 禁止硬编码内外参。"),
                 "_generated_at": time.strftime("%F %T")}

    # ① 相机内参/畸变 (真机出厂相机内参, 来自 ROS camera_info 只读订阅)
    cam = _load_json(REAL_CAM_CALIB)
    if cam:
        K = cam.get("K")
        reg["camera"] = {
            "K": K, "dist": cam.get("dist"), "image_size": cam.get("image_size"),
            "fx": K[0] if K else None, "fy": K[4] if K else None,
            "cx": K[2] if K else None, "cy": K[5] if K else None,
            "distortion_model": cam.get("distortion_model"),
            "_src": f"{os.path.relpath(REAL_CAM_CALIB, ROOT)} ({cam.get('K_src', '')})",
        }
    else:
        reg["camera"] = {"K": None, "dist": None, "_reason": "无 models/real_cam_calib.json"}

    # ② 手眼外参 T_base_cam (相机系→base_link) —— 真机未标
    T = (cam or {}).get("T_base_cam")
    reg["T_base_cam"] = {"value": T,
                         "_src": os.path.relpath(REAL_CAM_CALIB, ROOT),
                         "_reason": None if T else
                         "未标定: 需零运动人工拖动 10+ 位姿采 (板: tools/board_handeye_solve.py)"}

    # ③ 台面高度 plane_z (无深度时的光线-平面回退)
    pz = (cam or {}).get("plane_z")
    if not pz:
        rep = sorted(glob.glob(CALIB_REPORT_GLOB))
        for p in reversed(rep):
            d = _load_json(p) or {}
            if d.get("plane_z"):
                pz = d["plane_z"]
                p = os.path.basename(p)
                break
    reg["plane_z"] = {"value": pz,
                      "_src": (os.path.relpath(REAL_CAM_CALIB, ROOT) if (cam or {}).get("plane_z")
                               else "calib_report_*.json"),
                      "_reason": None if pz else "未标定: 需现场用夹爪或塞尺量一次台面高度"}

    # ④ 单目深度尺度 (metaworld 眼在手口径; 真机 RealSense 有米制深度则不需要)
    reg["depth_scale"] = {"value": 0.9616,
                          "_src": "yolo_state_aligner 默认 (2026-09-07 探针 tools/probe_r1_yolo_calib.py 实测均值)",
                          "_scope": "仿真单目深度 (SILog) 专用; 真机走 RealSense 米制深度/plane_z 回退"}

    # ⑤ 现场示教几何 (光模块/孔口/AOI 点, 由 tools/ss_geom_calib.py --record 采集)
    geom = None
    for c in GEOM_CANDIDATES:
        d = _load_json(c)
        if d:
            geom = {"points": d, "_src": c}
            break
    reg["cell_geometry"] = geom or {
        "points": None,
        "_reason": ("无示教几何: 需现场零运动示教 — gui-venv311/bin/python tools/ss_geom_calib.py "
                    "--record peg_head|goal|aoi (人工拖到位置后确认, 无运动指令)")}

    # ⑥ 机器人真源 & 负载/TCP
    spec = robot_spec() if os.path.exists(SPEC) else {}
    reg["robot"] = {"spec": os.path.relpath(SPEC, ROOT),
                    "dof": spec.get("robot", {}).get("dof"),
                    "urdf_sha256_16": spec.get("robot", {}).get("urdf_sha256_16"),
                    "link_mass_sum_kg": spec.get("totals", {}).get("link_mass_sum_kg")}
    reg["tool_payload"] = {**(spec.get("payload") or {}),
                           "_reason": None if (spec.get("payload") or {}).get("mass_kg")
                           else "控制器 setToolset 未回读到负载 (跑 tools/rokae/probe_state_repair.py)"}
    reg["control_tcp"] = {**(spec.get("control_tcp") or {}),
                          "_reason": None if (spec.get("control_tcp") or {}).get("ok")
                          else "无真机帧可反解 (需真机只读采集在线)"}

    # ⑦ 🧮 流形引擎主标定参数 M (状态空间的结构参数/等效惯量) —— 2026-09-29 老倪
    #   为何放这里: calib.json 是本项目已确立的**单一真源**口径; M 是流形引擎(L4 核心)向标定层
    #   暴露的唯一主标定标量, 与内参/几何/TCP 同属"标定参数" → 与其并肩 (不再新开一处硬编码)。
    #   可写真源 = config/calib/zmax_manifold.json (现场标定单标量); 缺省值/范围/单位来自引擎模块。
    reg["manifold_engine"] = _manifold_section()

    if write:
        os.makedirs(os.path.dirname(CALIB), exist_ok=True)
        tmp = CALIB + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CALIB)
    return reg


def calib(path: str = CALIB) -> dict:
    """读统一标定注册表 (不存在则现场合并, 不落盘)。"""
    return _load_json(path) or sync_calib(write=False)


def camera(path: str = CALIB) -> dict:
    """内参/畸变/图像尺寸 — 2D→3D 反投影入口。"""
    return calib(path).get("camera", {})


def plane_z(cls: str | None = None, path: str = CALIB) -> float | None:
    """台面高度 (dict 时按类别取, 标量时通用)。未标 → None (调用方须显式处理, 不许填默认)。"""
    v = calib(path).get("plane_z", {}).get("value")
    if isinstance(v, dict):
        return v.get(cls) if cls else next(iter(v.values()), None)
    return v


def ext_T(path: str = CALIB):
    """手眼外参 4x4 行主序 (相机→base)。未标 → None。"""
    return calib(path).get("T_base_cam", {}).get("value")


# ───────────────────────── 🧮 流形引擎主标定参数 M (读/写) ─────────────────────────
def manifold_M(path: str = CALIB) -> float:
    """读流形引擎主标定参数 M (状态空间的结构参数/等效惯量)。缺项 → 引擎默认值 (1.0)。"""
    c = (calib(path).get("manifold_engine") or {}).get("M")
    return MANIFOLD_M_DEFAULT if c is None else float(c)


def manifold_inertia(path: str = CALIB) -> bool:
    """读是否启用有惯性二阶演化 (默认 False ⇒ 一阶过阻尼, 零回归)。"""
    return bool((calib(path).get("manifold_engine") or {}).get("inertia", False))


def manifold_spec(path: str = CALIB) -> dict:
    """读流形引擎标定域全量 (M/inertia/range/unit/flow/struct_src/zero_regression/_src)。"""
    return dict(calib(path).get("manifold_engine") or {})


def write_manifold_M(value: float, inertia: bool | None = None, path: str = MANIFOLD_P) -> dict:
    """写流形引擎主标定参数 M (**可写口**)。

    落 config/calib/zmax_manifold.json (可写真源) 并重合并 calib.json; 带范围校验 (越界夹取并标注)。
    返回 {M, inertia, clamped, range, dest} — 现场标定后即可被流形引擎/画布节点 n_calib_mani 读到。
    """
    lo, hi = MANIFOLD_M_RANGE
    v = float(value)
    clamped = not (lo <= v <= hi)
    v = min(max(v, lo), hi)
    d = _load_json(path) or {}
    d["_doc"] = ("流形引擎主标定参数 M (状态空间的结构参数/等效惯量) — 标定层单一真源。"
                 "物理: a=F/M ⇒ Δx=F·dt²/M; 信息: 把信息代价梯度换成状态加速度的曲率尺度;"
                 " M 从流形结构导出 (非自由拟合), 现场以单标量标定。inertia=false ⇒ 零回归。")
    d["M"] = v
    d["inertia"] = bool(d.get("inertia", False)) if inertia is None else bool(inertia)
    d["_range"], d["_unit"] = list(MANIFOLD_M_RANGE), MANIFOLD_M_UNIT
    d["_updated_at"] = time.strftime("%F %T")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    # 只更新 calib.json 的 manifold_engine 键 (★ 不整表重合并 —— 避免把现场几何/内参等
    #   其他标定域一起刷新成"当前源"而意外改变在役读值; 本域改动无副作用)。
    c = _load_json(CALIB)
    if isinstance(c, dict):
        c["manifold_engine"] = _manifold_section()
        tmp = CALIB + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CALIB)
    return {"M": v, "inertia": d["inertia"], "clamped": bool(clamped),
            "range": list(MANIFOLD_M_RANGE), "dest": os.path.relpath(path, ROOT)}


# ───────────────────────── 就绪度 / 缺口 ─────────────────────────
KEY_ITEMS = ("camera.K", "T_base_cam", "plane_z", "cell_geometry.points",
             "control_tcp.offset_xyz_m", "tool_payload.mass_kg", "robot.dof")


def _item_value(c: dict, item: str):
    """取"就绪度"该看的**实际值** (注意 T_base_cam / plane_z 是 {value, _reason} 结构,
    直接取容器会永远非 None → 漏报缺口; 2026-09-22 实测踩到)。"""
    if item == "T_base_cam":
        return c.get("T_base_cam", {}).get("value")
    if item == "plane_z":
        return c.get("plane_z", {}).get("value")
    cur = c
    for k in item.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def gaps(path: str = CALIB) -> list:
    c = calib(path)
    out = []
    for it in KEY_ITEMS:
        if _item_value(c, it) is None:
            reason = "缺"
            if it.startswith("T_base_cam"):
                reason = c.get("T_base_cam", {}).get("_reason", "缺")
            elif it.startswith("plane_z"):
                reason = c.get("plane_z", {}).get("_reason", "缺")
            elif it.startswith("cell_geometry"):
                reason = c.get("cell_geometry", {}).get("_reason", "缺")
            elif it.startswith("control_tcp"):
                reason = c.get("control_tcp", {}).get("_reason", "缺")
            elif it.startswith("tool_payload"):
                reason = c.get("tool_payload", {}).get("_reason", "缺")
            out.append({"item": it, "reason": reason})
    return out


def check(path: str = CALIB, verbose: bool = True) -> int:
    c = calib(path)
    cam = c.get("camera", {})
    ct = c.get("control_tcp", {})
    print("🧭 Z-MAX 统一参数/标定就绪度")
    print("─" * 78)
    print(f"  机器人: DOF {c.get('robot', {}).get('dof')} · 连杆质量合计 "
          f"{c.get('robot', {}).get('link_mass_sum_kg')} kg · URDF {c.get('robot', {}).get('urdf_sha256_16')}")
    K = cam.get("K")
    print(f"  相机内参: {'✅ fx=%.2f fy=%.2f cx=%.1f cy=%.1f' % (K[0], K[4], K[2], K[5]) if K else '❌ 缺'}"
          f"  ({cam.get('_src', '')})")
    print(f"  手眼外参: {'✅' if ext_T(path) else '❌ ' + str(c.get('T_base_cam', {}).get('_reason'))}")
    pz = c.get("plane_z", {}).get("value")
    print(f"  台面 plane_z: {'✅ ' + str(pz) if pz else '❌ ' + str(c.get('plane_z', {}).get('_reason'))}")
    cg = c.get("cell_geometry", {})
    print(f"  现场示教几何: {'✅ ' + str(list((cg.get('points') or {}).keys())) if cg.get('points') else '❌ ' + str(cg.get('_reason'))}")
    print(f"  产线 TCP 反解: {'✅ ' + str(ct.get('offset_xyz_m')) if ct.get('ok') else '❌ ' + str(ct.get('_reason'))}")
    pl = c.get("tool_payload", {})
    print(f"  控制器负载: {'✅ mass=' + str(pl.get('mass_kg')) + ' cog=' + str(pl.get('cog_m')) if pl.get('mass_kg') else '❌ ' + str(pl.get('_reason'))}")
    me = c.get("manifold_engine", {})
    print(f"  🧮 流形引擎主参数 M: {me.get('M')} (范围 {me.get('range')} · "
          f"{'有惯性' if me.get('inertia') else '过阻尼=旧行为'} · {me.get('_src', '')})")
    g = gaps(path)
    print("─" * 78)
    if g:
        print(f"⚠️ 关键缺口 {len(g)} 项 (未标定项一律 None, 绝不填默认值冒充已标):")
        for x in g:
            print(f"   · {x['item']}: {x['reason']}")
    else:
        print("✅ 无关键缺口")
    return 1 if g else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Z-MAX 全系统参数/标定统一接口")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--sync", action="store_true", help="从各源合并 → config/calib/zmax_calib.json")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fk", nargs="+", type=float, metavar="Q", help="六个关节角(rad) 算 FK")
    ap.add_argument("--live", action="store_true", help="--fk 时同时读真机 tcp 真值做对照")
    ap.add_argument("--m", dest="m_val", type=float, default=None,
                    help="写流形引擎主标定参数 M (状态空间结构参数/等效惯量)")
    ap.add_argument("--inertia", dest="inertia", default=None,
                    help="写 M 时同时设惯性开关 (on/off; 默认保持)")
    a = ap.parse_args()

    if a.m_val is not None:
        inr = None if a.inertia is None else str(a.inertia).lower() in ("1", "true", "on", "yes")
        r = write_manifold_M(a.m_val, inr)
        print("✅ 已写流形引擎主参数 M:", json.dumps(r, ensure_ascii=False))
        print("   当前:", json.dumps(manifold_spec(), ensure_ascii=False)[:200], "…")
        return 0

    if a.sync:
        r = sync_calib(write=True)
        n = len(gaps())
        print(f"✅ 已合并标定注册表: {os.path.relpath(CALIB, ROOT)}")
        print(f"   关键缺口 {n} 项")
        return 0
    if a.fk:
        R, t = fk(a.fk)
        print(f"FK(q={a.fk}) → t = {[round(v, 6) for v in t]}")
        if a.live:
            try:
                p = sorted(glob.glob(_LIVE_TAP), key=os.path.getmtime)[-1]
                with open(p, "rb") as f:
                    f.seek(max(0, os.path.getsize(p) - 65536))
                    d = json.loads(f.read().decode("utf-8", "replace").strip().splitlines()[-1])
                tcp = d.get("tcp")
                if tcp:
                    err = math.dist(t, [float(v) for v in tcp]) * 1000
                    print(f"真机 tcp 真值   = {[round(float(v), 6) for v in tcp]}")
                    print(f"偏差 = {err:.2f} mm  (帧龄 {time.time()-float(d.get('t',0)):.1f}s)")
            except Exception as e:  # noqa: BLE001
                print(f"（读真机真值失败: {type(e).__name__}: {e}）")
        return 0
    if a.check:
        return check()
    if a.json:
        print(json.dumps({"robot": robot_spec(), "calib": calib(),
                          "gaps": gaps()}, ensure_ascii=False, indent=1))
        return 0
    check()
    if a.show:
        print("\n── 关节限位 (L2 安全闸口径) ──")
        for j in joint_limits():
            print(f"  {j['name']:<34} [{j['lower']:+.4f}, {j['upper']:+.4f}] rad"
                  f"  v≤{j['velocity']:.2f} rad/s  τ≤{j['effort']:.0f} Nm")
        print("\n── 连杆质量/惯量 ──")
        for L in link_params():
            print(f"  {L['name']:<40} m={L['mass']:.3f} kg  I=({L['inertia']['ixx']:.5f},…,{L['inertia']['izz']:.5f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
