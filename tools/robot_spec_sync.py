#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤖🔁 真机机器人模型参数同步器 (Z-MAX 全系统单一真源)

老倪 (09-22): 「你现在已经连接真机了，你要同步所有仿真与真机数据，URDF，质量，惯性，
自由度等，按照真实的机器人机械臂，全面更新状态空间的仿真数据」+「不要发出真机控制指令，
但是你可以采集真机的数据」

本工具做三件事 (全部只读, 零运动指令):
  ①  解析现场 URDF (config/robot/xms5_r800_w4g3b4c.urdf) →
      自由度 / 关节轴 / 关节限位(位置·速度·力矩) / 各连杆质量·质心·惯量张量 / 串链 / 工具 TCP
  ②  读**真机实测**做交叉校验 (不编造):
      · 真机只读采集落盘 state_*.jsonl 的 jpos (六关节真值) + tcp (末端真值)
      · 用 URDF 几何做 FK(jpos) → 与 tcp 真值比 (差应 ~mm 级; 差大 = URDF 与现场不符, 报警)
      · 控制器负载 (setToolset: mass/cog) 从 rokae SDK 只读探针产物读取
  ③  合并成**权威参数文件** config/robot/zmax_robot_spec.json
      (每段带 _src 溯源; 缺项写 null + 原因, 绝不编造) — 供 状态空间引擎 / 3D 视图 /
      L2 安全闸 / 感知反投影 / 训练配置 共用 (禁止再各自硬编码)

用法:
  gui-venv311/bin/python tools/robot_spec_sync.py                # 生成 + 打印校验表
  gui-venv311/bin/python tools/robot_spec_sync.py --check        # 只校验, 不写文件
  gui-venv311/bin/python tools/robot_spec_sync.py --json         # 机器可读输出
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import sys
import time
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URDF_DEFAULT = os.path.join(ROOT, "config", "robot", "xms5_r800_w4g3b4c.urdf")
SPEC_DEFAULT = os.path.join(ROOT, "config", "robot", "zmax_robot_spec.json")
TAP_GLOB = os.path.expanduser("~/zmax_data/real_tap_*/state_*.jsonl")
ROKAE_JSON_GLOB = os.path.expanduser("~/zmax_data/rokae_sdk/*.json")


# ───────────────────────── URDF 解析 ─────────────────────────
def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _vec(s, n=3):
    if not s:
        return [0.0] * n
    p = [float(x) for x in s.replace(",", " ").split()]
    return (p + [0.0] * n)[:n]


def parse_urdf(path: str) -> dict:
    tree = ET.parse(path)
    r = tree.getroot()
    links, joints = {}, []
    for ln in r.findall("link"):
        name = ln.get("name")
        item = {"name": name, "mass": None, "com": None, "inertia": None}
        ine = ln.find("inertial")
        if ine is not None:
            m = ine.find("mass")
            item["mass"] = _f(m.get("value")) if m is not None else None
            o = ine.find("origin")
            item["com"] = _vec(o.get("xyz") if o is not None else None)
            I = ine.find("inertia")
            if I is not None:
                item["inertia"] = {k: _f(I.get(k)) for k in
                                   ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")}
        links[name] = item
    for jn in r.findall("joint"):
        j = {
            "name": jn.get("name"), "type": jn.get("type"),
            "parent": jn.find("parent").get("link"), "child": jn.find("child").get("link"),
            "axis": _vec(jn.find("axis").get("xyz") if jn.find("axis") is not None else None),
            "origin_xyz": _vec(jn.find("origin").get("xyz") if jn.find("origin") is not None else None),
            "origin_rpy": _vec(jn.find("origin").get("rpy") if jn.find("origin") is not None else None),
            "limit": None,
        }
        lm = jn.find("limit")
        if lm is not None:
            j["limit"] = {"lower": _f(lm.get("lower")), "upper": _f(lm.get("upper")),
                          "effort": _f(lm.get("effort")), "velocity": _f(lm.get("velocity"))}
        joints.append(j)
    return {"links": links, "joints": joints, "name": r.get("name")}


def serial_chain(doc: dict) -> list:
    """base_link → ... → 最末工具链, 返回有序 (joint, child_link) 列表。

    判据: 从 urdf 的 world→base 固定关节起步, 沿 child 逐级走; 有分叉时走
    自由度最多(主链)的那支。固定关节(type=fixed)保留但标注。
    """
    j_by_parent = {}
    for j in doc["joints"]:
        j_by_parent.setdefault(j["parent"], []).append(j)
    # 起点: base link = world 的 child (若无 world 则 URDF 第一个 link)
    start = None
    for j in doc["joints"]:
        if j["parent"] == "world":
            start = j["child"]
            break
    if start is None:
        kids = {j["child"] for j in doc["joints"]}
        parents = {j["parent"] for j in doc["joints"]}
        roots = [p for p in parents if p not in kids]
        start = doc["joints"][0]["child"] if not roots else \
            (j_by_parent.get(roots[0]) or [doc["joints"][0]])[0]["child"]
    chain, cur = [], start
    seen = set()
    while cur in j_by_parent and cur not in seen:
        seen.add(cur)
        opts = [j for j in j_by_parent[cur] if j["type"] != "fixed"]
        j = opts[0] if opts else j_by_parent[cur][0]
        chain.append(j)
        cur = j["child"]
    return chain


# ───────────────────────── FK (与 tools/ss_fk_xms5.py 同口径) ─────────────────────────
def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def _rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def _rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def _mm(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mv(A, v):
    return [sum(A[i][k] * v[k] for k in range(3)) for i in range(3)]


def _rpy(r, p, y):
    return _mm(_rot_z(y), _mm(_rot_y(p), _rot_x(r)))


def fk_from_chain(chain: list, q: list, upto: str | None = None) -> tuple:
    """链式 FK: 返回 (R, t) 在 base 系。

    upto=None → 走完整链 (含末端固定关节, 即 tool1);
    upto="<link名>" → 走到该 link (即该 link 的原点/法兰系)。

    组合口径 (与 tools/ss_fk_xms5.py::compose 逐位一致):
      T_child = T_parent · T_origin · Rot(axis, q)
      ⇒ 平移用**父系**旋转 R_parent 变换 origin.xyz, 旋转再右乘 origin.rpy 与关节转角.
    (踩坑: 先乘 origin.rpy 再去平移 origin.xyz = 用新旋转变换原点 → 只有 rpy≠0 的
     末段工具关节会错, 实测假偏差 136mm; 6 个运动关节 rpy 全 0 所以看不出来.)
    """
    R = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    t = [0.0, 0.0, 0.0]
    qi = 0
    for j in chain:
        tn, rn = j["origin_xyz"], j["origin_rpy"]
        # ① 平移: 用父系旋转 (R) 变换本关节 origin.xyz
        _d = _mv(R, tn)
        t = [t[i] + _d[i] for i in range(3)]
        # ② 旋转: 先 origin.rpy, 再关节转角 (绕本体系轴)
        R = _mm(R, _rpy(*rn))
        if j["type"] in ("revolute", "continuous", "prismatic"):
            ang = q[qi] if qi < len(q) else 0.0
            qi += 1
            axis = j["axis"] or [0, 0, 1]
            if axis == [0, 0, 1]:
                Rq = _rot_z(ang)
            elif axis == [0, 1, 0]:
                Rq = _rot_y(ang)
            elif axis == [1, 0, 0]:
                Rq = _rot_x(ang)
            elif axis == [0, -1, 0]:
                Rq = _rot_y(-ang)
            elif axis == [0, 0, -1]:
                Rq = _rot_z(-ang)
            else:
                Rq = _rot_z(ang)
            R = _mm(R, Rq)
        if upto is not None and j["child"] == upto:
            break
    return R, t


def _transpose(R):
    return [[R[j][i] for j in range(3)] for i in range(3)]


def quat_to_R(q):
    """quat (x,y,z,w) → 3x3 旋转矩阵 (与 ROOT/tools/real_truth.py 同口径)。"""
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def derive_control_tcp(chain: list, frames: list, flange_link: str = "XMS5-R800-W4G3B4C_link6") -> dict:
    """🔧 从真机只读实测**反解产线 TCP**(/robot/tcp_pose) 相对法兰(link6) 的刚体变换。

    原理: FK(jpos) 的旋转 R6 与平移 t6 是精确已知 (URDF 几何);
          真机 tcp 真值给 (R_tcp, t_tcp)。若 TCP 与法兰刚性固连:
              offset_link6 = R6ᵀ · (t_tcp − t6)      ← 跨多帧应恒定
              R_off        = R6ᵀ · R_tcp
          多帧求均值/标准差: std 小 = 确实是固定工具变换 (可入库);
          std 大 = 现场标定不一致/关节读数与几何不符 → 报警, 不编造。
    只用落盘数据, 零运动指令。
    """
    offs, angs, res = [], [], []
    for jpos, tcp, quat in frames:
        if not (jpos and tcp and quat):
            continue
        if len(jpos) < 6:
            continue
        R6, t6 = fk_from_chain(chain, jpos, upto=flange_link)
        d = [float(tcp[i]) - t6[i] for i in range(3)]
        offs.append(_mv(_transpose(R6), d))
        Rt = quat_to_R(quat)
        angs.append(_mm(_transpose(R6), Rt))
    if not offs:
        return {"ok": False, "reason": "无可用真机帧 (缺 jpos/tcp/tcp_quat)"}
    n = len(offs)
    mean = [sum(o[i] for o in offs) / n for i in range(3)]
    std = [math.sqrt(sum((o[i] - mean[i]) ** 2 for o in offs) / n) for i in range(3)]
    # ⚠️ 诚实性: 采集期间关节若没动, std=0 只说明"同一姿态重复读数", 不能证明刚体一致性
    jr = []
    for k in range(6):
        vs = [float(f[0][k]) for f in frames if f[0] and len(f[0]) > k]
        if vs:
            jr.append(max(vs) - min(vs))
    travel = max(jr) if jr else 0.0
    static = travel < 0.01          # <0.57° 视为静帧
    # 姿态一致性: 各帧 R_off 与首帧的角度偏差
    R0 = angs[0]
    dev = []
    for R in angs:
        Rd = _mm(R, _transpose(R0))
        tr = max(-1.0, min(1.0, (Rd[0][0] + Rd[1][1] + Rd[2][2] - 1) / 2))
        dev.append(math.degrees(math.acos(tr)))
    return {"ok": True, "n_frames": n, "frame": flange_link,
            "offset_xyz_m": [round(v, 6) for v in mean],
            "offset_std_mm": [round(v * 1000, 3) for v in std],
            "rot_dev_deg_max": round(max(dev), 3),
            "joint_travel_rad_max": round(travel, 6),
            "static_frames": static,
            "static_warning": ("采集期间关节极差 %.4f rad (<0.57°) = 静帧: std=0 只证明同姿态重复读数稳定, "
                               "**不能**证明该偏移在整个工作空间是刚体常量 —— 需现场拖动机器人多个位姿后复采"
                               " (零运动指令, 人工拖动即可) 才能闭环标定" % travel) if static else None,
            "verdict": ("刚体一致 (std ≤2mm 且姿态偏差 ≤1°) — 可作产线 TCP 口径入库"
                        if max(std) <= 0.002 and max(dev) <= 1.0 else
                        "不一致 — 现场 TCP 标定/关节读数与 URDF 几何不符, 需现场复核"),
            "_src": "真机只读采集落盘多帧反解 (FK(jpos) 对 tcp_pose)"}


# ───────────────────────── 真机只读实测 ─────────────────────────
def read_live_state() -> dict:
    """读真机只读采集落盘的最新一行 (真值 tcp/jpos). 只读, 不碰任何控制话题。"""
    files = sorted(glob.glob(TAP_GLOB), key=os.path.getmtime, reverse=True)
    if not files:
        return {"ok": False, "reason": "无真机采集落盘 (state_*.jsonl 不存在)"}
    p = files[0]
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = f.read().decode("utf-8", "replace").strip().splitlines()
        rec = json.loads(lines[-1])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"解析失败 {type(e).__name__}: {e}"}
    age = time.time() - _f(rec.get("t"))
    return {"ok": True, "file": p, "age_s": age, "tcp": rec.get("tcp"),
            "tcp_quat": rec.get("tcp_quat"), "jpos": rec.get("jpos"),
            "jvel": rec.get("jvel"), "ft": rec.get("ft"),
            "gripper": rec.get("gripper"), "frame": rec.get("tcp_frame"),
            "prod_stage": rec.get("prod_stage")}


def read_toolset() -> dict:
    """从 rokae SDK 只读探针产物里取控制器负载 (setToolset: mass/cog)。"""
    best = None
    for p in sorted(glob.glob(ROKAE_JSON_GLOB), key=os.path.getmtime, reverse=True):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        ts = d.get("toolset")
        if isinstance(ts, dict) and isinstance(ts.get("load"), dict):
            best = {"mass": ts["load"].get("mass"), "cog": ts["load"].get("cog"),
                    "src": os.path.basename(p), "ts": d.get("ts"),
                    "jointTorque_Nm": d.get("jointTorque_Nm")}
            break
    return best or {"mass": None, "cog": None,
                    "src": None, "reason": "无 rokae 只读探针产物 (toolset 未记录)"}


def _sha256(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def read_live_frames(n: int = 400) -> list:
    """读真机只读采集落盘的最近 n 帧 → [(jpos, tcp, tcp_quat)]。零下行。"""
    files = sorted(glob.glob(TAP_GLOB), key=os.path.getmtime, reverse=True)
    if not files:
        return []
    out = []
    try:
        with open(files[0], "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 2_000_000))
            lines = f.read().decode("utf-8", "replace").strip().splitlines()[-n:]
        for ln in lines:
            try:
                d = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if d.get("jpos") and d.get("tcp") and d.get("tcp_quat"):
                out.append((d["jpos"], d["tcp"], d["tcp_quat"]))
    except Exception:  # noqa: BLE001
        pass
    return out


# ───────────────────────── 主流程 ─────────────────────────
def build_spec(urdf_path: str) -> dict:
    doc = parse_urdf(urdf_path)
    chain = serial_chain(doc)
    dof = sum(1 for j in chain if j["type"] in ("revolute", "continuous", "prismatic"))
    movers = [j for j in chain if j["type"] in ("revolute", "continuous", "prismatic")]
    live = read_live_state()
    tool_payload = read_toolset()

    # FK 校验: URDF 几何 + 真机 jpos → 末端, 与真机 tcp 真值比
    fk_check = {"ok": False, "reason": "无真机实测 (采集未落盘)"}
    if live.get("ok") and live.get("jpos") and len(live["jpos"]) >= dof:
        R, t = fk_from_chain(chain, live["jpos"][:dof])
        tcp = live.get("tcp")
        if tcp and len(tcp) == 3:
            err = math.sqrt(sum((t[i] - float(tcp[i])) ** 2 for i in range(3)))
            fk_check = {"ok": True, "tcp_fk": [round(v, 6) for v in t],
                        "tcp_real": [round(float(v), 6) for v in tcp],
                        "err_mm": round(err * 1000, 3),
                        "verdict": ("一致 (≤5mm)" if err <= 0.005 else
                                    "偏差 >5mm — URDF 的 tool1 不是产线 TCP 口径 (见 control_tcp 段)"),
                        "jpos_used": [round(float(v), 6) for v in live["jpos"][:dof]]}

    # 🔧 产线 TCP 反解 (法兰→/robot/tcp_pose), 只用落盘真机帧
    frames = read_live_frames()
    ctrl_tcp = derive_control_tcp(chain, frames) if frames else \
        {"ok": False, "reason": "无真机多帧 (state_*.jsonl 缺 jpos/tcp)"}

    links_out = []
    for name, L in doc["links"].items():
        if name == "world":
            continue
        links_out.append({"name": name, "mass": L["mass"], "com": L["com"], "inertia": L["inertia"]})

    masses = [L["mass"] for L in links_out if L["mass"] is not None]
    spec = {
        "_doc": ("Z-MAX 真机机器人模型参数 单一真源 — 由 tools/robot_spec_sync.py 生成。"
                 "所有层 (状态空间引擎 / 3D 视图 / L2 安全闸 / 感知反投影 / 训练配置) 一律读本文件, "
                 "禁止再各自硬编码几何/限位/质量。真机只读采集, 零运动指令。"),
        "_generated_at": time.strftime("%F %T"),
        "robot": {"name": doc["name"], "dof": dof,
                  "urdf": os.path.relpath(urdf_path, ROOT), "urdf_sha256_16": _sha256(urdf_path),
                  "mover_joints": [j["name"] for j in movers]},
        "joints": [{"name": j["name"], "type": j["type"], "parent": j["parent"], "child": j["child"],
                    "axis": j["axis"], "origin_xyz": j["origin_xyz"], "origin_rpy": j["origin_rpy"],
                    "limit": j["limit"]} for j in chain],
        "links": links_out,
        "tool": next(({"frame": j["child"], "xyz": j["origin_xyz"], "rpy": j["origin_rpy"]}
                      for j in reversed(chain) if j["type"] == "fixed"), None),
        "control_tcp": ctrl_tcp,
        "payload": {"mass_kg": tool_payload.get("mass"), "cog_m": tool_payload.get("cog"),
                    "_src": tool_payload.get("src"), "_reason": tool_payload.get("reason")},
        "totals": {"link_mass_sum_kg": round(sum(masses), 4) if masses else None,
                   "n_links_with_inertia": sum(1 for L in links_out if L["inertia"]),
                   "n_links_missing_inertial": [L["name"] for L in links_out if L["inertia"] is None]},
        "live_check": {"state_file": live.get("file"), "age_s": live.get("age_s"),
                       "tcp": live.get("tcp"), "jpos": live.get("jpos"), "jvel": live.get("jvel"),
                       "ft": live.get("ft"), "fk": fk_check},
        "_provenance": {
            "kinematics/mass/inertia": f"现场 URDF {os.path.basename(urdf_path)} (厂家导出)",
            "payload": f"控制器 setToolset 只读回读 ({tool_payload.get('src')})",
            "live_truth": "真机只读采集落盘 (ROS2 远程只读订阅, 零下行)",
        },
    }
    return spec


def print_table(spec: dict) -> None:
    r = spec["robot"]
    print(f"🤖 机器人 {r['name']} — 自由度 {r['dof']} (URDF {r['urdf']} sha256:{r['urdf_sha256_16']})")
    print("─" * 86)
    print(f"{'#':>2} {'关节':<34}{'轴':>10}{'下限':>10}{'上限':>10}{'速度':>8}{'力矩':>8}")
    for i, j in enumerate(spec["joints"], 1):
        if j["type"] == "fixed":
            print(f"{i:>2} {j['name']:<34}{'(fixed)':>10}{'':>10}{'':>10}{'':>8}{'':>8}")
            continue
        L = j["limit"] or {}
        vp = "—" if j["type"] == "continuous" else f"{L.get('lower', 0):>10.4f}"
        vu = "∞" if j["type"] == "continuous" else f"{L.get('upper', 0):>10.4f}"
        print(f"{i:>2} {j['name']:<34}{str(j['axis']):>10}{vp}{vu}"
              f"{L.get('velocity', 0):>8.2f}{L.get('effort', 0):>8.1f}")
    print("─" * 86)
    print(f"{'连杆':<40}{'质量(kg)':>10}{'质心(m)':>28}")
    for L in spec["links"]:
        m = "—" if L["mass"] is None else f"{L['mass']:.3f}"
        c = "—" if not L["com"] else "[" + ",".join(f"{v:+.3f}" for v in L["com"]) + "]"
        print(f"{L['name']:<40}{m:>10}{c:>28}")
    t = spec["totals"]
    print("─" * 86)
    print(f"连杆质量合计 {t['link_mass_sum_kg']} kg · 有惯量张量 {t['n_links_with_inertia']} 个连杆"
          f" · 缺惯量 {t['n_links_missing_inertial'] or '无'}")
    tp = spec["tool"]
    if tp:
        print(f"工具系(末端) {tp['frame']} 偏移 xyz={tp['xyz']} rpy={tp['rpy']}")
    p = spec["payload"]
    print(f"控制器负载 setToolset: mass={p['mass_kg']} cog={p['cog_m']} (源 {p['_src'] or p.get('_reason')})")
    lc = spec["live_check"]
    print("─" * 86)
    ct = spec.get("control_tcp") or {}
    if ct.get("ok"):
        print(f"🔧 产线 TCP 反解 (法兰 {ct['frame']} → /robot/tcp_pose, {ct['n_frames']} 帧只读)")
        print(f"  offset xyz = {ct['offset_xyz_m']} m   std = {ct['offset_std_mm']} mm"
              f"   关节极差 {ct['joint_travel_rad_max']} rad")
        print(f"  姿态一致性最大偏差 {ct['rot_dev_deg_max']}° → {ct['verdict']}")
        if ct.get("static_warning"):
            print(f"  ⚠️ {ct['static_warning']}")
    else:
        print(f"🔧 产线 TCP 反解: {ct.get('reason')}")
    if lc.get("fk", {}).get("ok"):
        fk = lc["fk"]
        print(f"真机实测校验 ({os.path.basename(str(lc['state_file']))} · 帧龄 {lc['age_s']:.1f}s)")
        print(f"  URDF FK(jpos)@tool1 = {fk['tcp_fk']}")
        print(f"  真机 tcp 真值       = {fk['tcp_real']}")
        print(f"  偏差 {fk['err_mm']} mm → {fk['verdict']}")
    else:
        print(f"真机实测校验: {lc.get('fk', {}).get('reason')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="真机机器人模型参数同步 (URDF + 真机只读实测 → 单一真源)")
    ap.add_argument("--urdf", default=URDF_DEFAULT)
    ap.add_argument("--out", default=SPEC_DEFAULT)
    ap.add_argument("--check", action="store_true", help="只校验, 不写文件")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.urdf):
        print(f"❌ 缺 URDF: {a.urdf}")
        return 2
    spec = build_spec(a.urdf)
    if not a.quiet:
        print_table(spec)
    if a.check:
        if not a.quiet:
            print("\n(--check: 未写文件)")
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.out)
    if a.json:
        print(json.dumps({"written": a.out, "dof": spec["robot"]["dof"],
                          "fk_err_mm": spec["live_check"].get("fk", {}).get("err_mm")},
                         ensure_ascii=False))
    elif not a.quiet:
        print(f"\n✅ 已写单一真源: {os.path.relpath(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
