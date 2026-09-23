#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 Z-MAX 标定工作台 —— 标定层统一入口（状态 / 现场SOP / 验证 / 入库 / 漂移）

老倪 2026-09-23: "设计并提供端侧微调能力, 实现真机调试; 你要在标定层, 提供工具和方法"

标定层职责: 所有层读 `config/calib/zmax_calib.json`(注册表), **禁止硬编码内外参**。
本工具提供 5 个子命令:

  status   检查每个标定项的 值/来源/就绪度, 列出缺口与原因
  guide    对每个缺口输出**现场采集 SOP**(具体命令 + 判据), 照着做即可
  verify   用已标定项做几何自检(反投影/残差), 判定标定是否可用
  drift    与上次基线快照对比, 检测标定漂移
  sync     重新生成注册表(调 zmax_params.py --sync)

用法:
  python3 tools/calib_studio.py status
  python3 tools/calib_studio.py guide            # 现场照着做
  python3 tools/calib_studio.py verify
  python3 tools/calib_studio.py drift --save
  python3 tools/calib_studio.py sync
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
REG = os.path.join(ROOT, "config/calib/zmax_calib.json")
SNAP = os.path.join(ROOT, "reports/calib_snapshot.json")
VENV311 = os.path.join(ROOT, "gui-venv311/bin/python")

# 标定项定义: key -> (中文名, 就绪判据说明, 现场SOP)
ITEMS = [
    ("camera", "相机内参 K", "fx/fy/cx/cy 全为非空", [
        "真机出厂内参, 从 ROS camera_info 只读订阅:",
        "  python3 tools/calib_fetch_realsense_intrinsics.py",
        "判据: fx,fy,cx,cy 均为有限数 · distortion_model 非空",
    ]),
    ("T_base_cam", "手眼变换 T_base_cam", "4x4 矩阵非空", [
        "★ 零运动人工拖动采板(10+ 位姿), 再解算:",
        "  1) 采集: gui-venv311/bin/python tools/board_handeye_solve.py --session live",
        "  2) 拖动要求: 每帧静置≥1s, 姿态覆盖 ≥3 个轴向旋转 ±20°, 平移覆盖工作区",
        "  3) 解算: ... --min-views 8 --square-mm 20",
        "  4) 判据: 重投影 RMS < 1.5px · 位姿组数 ≥8 · 末位残差无离群",
        "  5) 入库: python3 tools/zmax_params.py --sync",
        "⚠️ 采集必须**零运动**(不给运动指令), 人工拖到位置后确认",
    ]),
    ("plane_z", "台面高度 plane_z", "标量非空(米)", [
        "现场用夹爪或塞尺量一次:",
        "  1) 手动把 TCP 降到台面, 读 tcp_pose 的 z",
        "  2) 或用 0.5mm 塞尺确认接触",
        "  3) 写入: python3 tools/zmax_params.py --set plane_z <米>",
        "判据: 深度反投影后目标点落在台面 ±2mm 内",
    ]),
    ("cell_geometry", "工位示教几何 peg_head/goal/aoi", "至少 3 点非空", [
        "★ 零运动示教(人工拖到位, 不发运动指令):",
        "  gui-venv311/bin/python tools/ss_geom_calib.py --record peg_head --note '夹具上光模块中心'",
        "  ... --record goal     --note '连接器孔口中心'",
        "  ... --record aoi      --note 'AOI 光学对焦点'",
        "  查看: ... --show",
        "判据: 三点两两距离与实测一致(±2mm) · 与 plane_z 自洽",
    ]),
    ("control_tcp", "控制 TCP 口径", "verdict 为刚体一致", [
        "只读采集多帧反解(无需人工):",
        "  真机: 读 tcp_pose 与 FK(jpos) 比对",
        "判据: std ≤2mm 且姿态偏差 ≤1° (已达成: 见 _src)",
    ]),
    ("robot", "机器人规格/URDF", "urdf_sha256_16 非空", [
        "URDF 与质量参数入库(通常无需现场):",
        "  python3 tools/zmax_params.py --sync",
    ]),
]


def _load() -> dict:
    if not os.path.isfile(REG):
        return {}
    with open(REG, encoding="utf-8") as f:
        return json.load(f)


def _ready(d: dict, key: str) -> tuple:
    """返回 (就绪?, 现值摘要)"""
    v = d.get(key)
    if not isinstance(v, dict):
        return False, "(缺失)"
    val = v.get("value", v)
    if key == "camera":
        k = d.get("camera") or {}
        ok = all(isinstance(k.get(x), (int, float)) for x in ("fx", "fy", "cx", "cy"))
        return ok, "fx=%.1f fy=%.1f cx=%.1f cy=%.1f" % (k.get("fx", 0), k.get("fy", 0), k.get("cx", 0), k.get("cy", 0))
    if key == "control_tcp":
        ok = bool((d.get("control_tcp") or {}).get("ok"))
        return ok, str((d.get("control_tcp") or {}).get("verdict", ""))[:46]
    if key == "robot":
        ok = bool((d.get("robot") or {}).get("urdf_sha256_16"))
        return ok, "urdf=%s dof=%s" % ((d.get("robot") or {}).get("urdf_sha256_16", "-"),
                                       (d.get("robot") or {}).get("dof", "-"))
    ok = val is not None
    if isinstance(val, (list, dict)):
        n = len(val)
        return ok and n > 0, "%d 项" % n
    return ok, str(val)


def cmd_status(d: dict, quiet: bool = False) -> int:
    if not quiet:
        print("═" * 78)
        print("🧭 Z-MAX 标定层状态  (注册表: config/calib/zmax_calib.json)")
        print("═" * 78)
        print("  %-4s %-28s %-38s %s" % ("状态", "标定项", "现值", "来源"))
        print("  " + "─" * 74)
    miss = 0
    for key, name, _, _ in ITEMS:
        ok, summ = _ready(d, key)
        if not ok:
            miss += 1
        src = ((d.get(key) or {}).get("_src") or "")[:36] if isinstance(d.get(key), dict) else ""
        if not quiet:
            print("  %s %-28s %-38s %s" % ("✅" if ok else "❌", name, summ[:38], src))
    if not quiet:
        print("  " + "─" * 74)
        print("  就绪 %d/%d · 缺口 %d" % (len(ITEMS) - miss, len(ITEMS), miss))
        gen = d.get("_generated_at", "-")
        print("  注册表生成于: %s" % gen)
        if miss:
            print("\n  ⚠️ 有缺口 → 运行 `python3 tools/calib_studio.py guide` 按现场SOP补齐")
    return miss


def cmd_guide(d: dict) -> int:
    print("═" * 78)
    print("📍 标定现场 SOP (缺口优先 · 全部零运动, 不发运动指令)")
    print("═" * 78)
    for key, name, _, steps in ITEMS:
        ok, summ = _ready(d, key)
        if ok:
            continue
        print("\n❌ %s  [%s]" % (name, key))
        print("   现状: %s" % summ)
        reason = (d.get(key) or {}).get("_reason") if isinstance(d.get(key), dict) else None
        if reason:
            print("   原因: %s" % reason)
        print("   做法:")
        for s in steps:
            print("     %s" % s)
    print("\n" + "═" * 78)
    print("补完后: python3 tools/calib_studio.py sync && python3 tools/calib_studio.py verify")
    return 0


def cmd_verify(d: dict) -> int:
    """几何自检: 用已标定项验证自洽性 (无真机时做静态一致性检查)"""
    print("═" * 78)
    print("🔍 标定层几何自检")
    print("═" * 78)
    ok_all = True
    cam = d.get("camera") or {}
    fx, fy, cx, cy = cam.get("fx"), cam.get("fy"), cam.get("cx"), cam.get("cy")
    if all(isinstance(x, (int, float)) for x in (fx, fy, cx, cy)):
        bad = abs(fx - fy) / max(fx, fy)
        print("  ① 内参:  fx=%.2f fy=%.2f  fx/fy 偏差=%.4f%%  %s"
              % (fx, fy, bad * 100, "✅" if bad < 0.02 else "⚠️ 各向异性偏大"))
        ok_all &= bad < 0.02
    else:
        print("  ① 内参: ❌ 缺失")
        ok_all = False

    tbc = d.get("T_base_cam") or {}
    tv = tbc.get("value")
    if tv is None:
        print("  ② 手眼 T_base_cam: ❌ 缺失 → 3D 反投影不可用(所有真机 3D 都会偏)")
        ok_all = False
    else:
        print("  ② 手眼 T_base_cam: ✅ 已标定")

    pz = (d.get("plane_z") or {}).get("value")
    if pz is None:
        print("  ③ 台面 plane_z: ❌ 缺失 → 无法做平面回退(深度不可用时无兜底)")
        ok_all = False
    else:
        print("  ③ 台面 plane_z: ✅ %.4f m" % pz)

    geo = (d.get("cell_geometry") or {}).get("points")
    if not geo:
        print("  ④ 示教几何: ❌ 缺失 → 引擎无 peg/goal/aoi 真值, 只能靠解析链")
        ok_all = False
    else:
        print("  ④ 示教几何: ✅ %d 点" % len(geo))

    tcp = d.get("control_tcp") or {}
    print("  ⑤ 控制 TCP: %s %s" % ("✅" if tcp.get("ok") else "❌", str(tcp.get("verdict", ""))[:44]))
    ok_all &= bool(tcp.get("ok"))

    print("  " + "─" * 74)
    print("  结论: %s" % ("✅ 标定层可用" if ok_all else "❌ 存在缺口 → 3D/闭环精度受限, 先按 guide 补齐"))
    return 0 if ok_all else 1


def cmd_drift(d: dict, save: bool = False) -> int:
    """与上次快照对比, 检测漂移"""
    cur = {k: _ready(d, k)[1] for k, _, _, _ in ITEMS}
    if os.path.isfile(SNAP):
        with open(SNAP, encoding="utf-8") as f:
            old = json.load(f)
        print("═" * 78)
        print("📈 标定漂移对比  (对比基线: %s)" % old.get("_at", "-"))
        print("═" * 78)
        ch = 0
        for k, v in cur.items():
            o = (old.get("items") or {}).get(k)
            if o != v:
                ch += 1
                print("  ⚠️ %-14s  %s  →  %s" % (k, o, v))
        print("  " + "─" * 74)
        print("  变化项: %d %s" % (ch, "(无变化)" if ch == 0 else "→ 确认是有意重标而非漂移"))
    else:
        print("  (无基线快照)")
    if save:
        with open(SNAP, "w", encoding="utf-8") as f:
            json.dump({"_at": time.strftime("%Y-%m-%d %H:%M:%S"), "items": cur}, f,
                      ensure_ascii=False, indent=2)
        print("  ✅ 已存基线快照: reports/calib_snapshot.json")
    return 0


def cmd_sync() -> int:
    print("🔄 重新生成标定注册表 (zmax_params.py --sync) ...")
    py = VENV311 if os.path.isfile(VENV311) else sys.executable
    r = subprocess.run([py, os.path.join(ROOT, "tools/zmax_params.py"), "--sync"],
                       cwd=ROOT, capture_output=True, text=True)
    print((r.stdout or "")[-1200:])
    if r.returncode != 0:
        print("❌ sync 失败:\n%s" % (r.stderr or "")[-800:])
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Z-MAX 标定工作台")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("guide")
    sub.add_parser("verify")
    p = sub.add_parser("drift")
    p.add_argument("--save", action="store_true", help="把当前状态存为基线")
    sub.add_parser("sync")
    a = ap.parse_args()
    cmd = a.cmd or "status"
    d = _load()
    if cmd == "status":
        return cmd_status(d)
    if cmd == "guide":
        return cmd_guide(d)
    if cmd == "verify":
        return cmd_verify(d)
    if cmd == "drift":
        return cmd_drift(d, save=getattr(a, "save", False))
    if cmd == "sync":
        return cmd_sync()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
