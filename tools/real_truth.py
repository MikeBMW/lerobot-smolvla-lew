#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_truth.py — 真机位姿真值 (单一来源) + 与 metaworld 39D 口径对齐

老倪 2026-09-17:「训练的时候要有光模块距离/位置等信息。你要记录当前光模块的 x y z 值,
这些数值都在机器人的位姿中, 你要读出这些真值, 对齐 metaworld 的数据,
这样就可以复用在仿真数据集的 yolo 模型了。」

真值来源 (**只读本机落盘, 零下行, 不碰 Orin**):
  $SS_OUT/state_YYYYMMDD.jsonl  原始感知流最后一行 (tcp/tcp_quat/jpos/jvel/ft) ← 首选
  $SS_OUT/status.json           采集器实时快照 (tcp/发布者计数/几何状态)         ← 兜底
两者都是 4060 侧 Docker 只读订阅 Orin `/robot/tcp_pose`(≈50Hz 真值) 写出来的。

metaworld 39D 段位口径 (权威 = src/lerobot/policies/yolo_3d/yolo_state_aligner.py:317-328):
  [0:3]=hand(末端) · [4:7]=光模块(peg) · [7:11]=peg_quat · [18:21]=prev_hand · [22:25]=prev_peg · [36:39]=hole
真机 → 39D 对齐规则:
  hand      = /robot/tcp_pose 真值        (R1 契约: 末端取编码器真值, 视觉只测工件)
  光模块     = TCP + R(quat)·offset        (offset = 模块中心相对 TCP 的夹具偏移, 标定得来;
              未标定 → null + 原因, **绝不编造** —— 此时可先用 TCP 真值当"手/头"项)
  peg_quat  = /robot/tcp_pose 四元数 (x,y,z,w)
  hole      = 现场几何示教的 goal 点 (未示教 → null + 原因)

为什么这样就能"复用仿真 YOLO 模型": 仿真数据集 data/yolo_peg 的标签是**真值 3D 投影**自动生成的;
真机只要也逐帧记下 3D 真值, 就有同口径的 (图, 3D真值, 2D框) 三元组 → 要么拿真值投影做自动标注
(需 K + 手眼外参), 要么直接做域适应微调 (tools/yolo_annot_train.py --base auto)。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

OUT_DEFAULT = os.environ.get("SS_OUT", os.path.expanduser("~/zmax_ss_remote"))
GEOM_DEFAULT = os.environ.get("SS_GEOM_PATH", os.path.join(OUT_DEFAULT, "real_cell_geometry.json"))
FRESH_S = 5.0            # 真值新鲜度窗口 (秒): 超了就当"无实时真值", 不拿旧值冒充


def _out(out=None) -> str:
    return os.path.expanduser(out or os.environ.get("SS_OUT", OUT_DEFAULT))


def read_latest_state(out=None) -> dict:
    """读原始感知流最后一行 (tcp/tcp_quat/jpos/jvel/ft/时间戳); 无 → {}"""
    o = _out(out)
    try:
        cands = sorted([f for f in os.listdir(o) if f.startswith("state_") and f.endswith(".jsonl")])
    except OSError:
        return {}
    if not cands:
        return {}
    p = os.path.join(o, cands[-1])
    last = None
    try:
        with open(p, "rb") as f:                     # 从尾部读, 别整文件 load (文件可达几百 MB)
            f.seek(0, os.SEEK_END)
            size = f.tell()
            back = min(size, 65536)
            f.seek(size - back)
            buf = f.read().decode("utf-8", "ignore")
        for ln in reversed(buf.splitlines()):
            ln = ln.strip()
            if ln.startswith("{"):
                last = ln
                break
    except OSError:
        return {}
    if not last:
        return {}
    try:
        d = json.loads(last)
    except ValueError:
        return {}
    d["_src_file"] = p
    return d


def read_status(out=None) -> dict:
    """读采集器实时快照 status.json (兜底来源)"""
    p = os.path.join(_out(out), "status.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:                                # noqa: BLE001
        return {}
    d["_src_file"] = p
    return d


def load_geom(path=None) -> tuple:
    """现场示教几何 (与采集器同一文件/同一口径) → ({'peg_head':[x,y,z], 'goal':[x,y,z]} | None, 说明)

    查找顺序: 显式 path / $SS_GEOM_PATH → 采集器输出 real_cell_geometry.json
              → **全系统标定注册表** config/calib/zmax_calib.json 的 cell_geometry.points (单一真源)。
    """
    cands = [os.path.expanduser(path or os.environ.get("SS_GEOM_PATH", GEOM_DEFAULT))]
    last = "无示教几何 — 相关项拒填, 不编造"
    try:                                                  # 单一真源兜底 (2026-09-22 统一参数接口)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import zmax_params as _zp                          # noqa: PLC0415
        reg = _zp.calib()
        pts = (reg.get("cell_geometry") or {}).get("points")
        if pts:
            need = all(k in pts for k in ("peg_head", "goal"))
            if need:
                return ({"peg_head": [pts["peg_head"][k] for k in "xyz"],
                         "goal": [pts["goal"][k] for k in "xyz"]},
                        f"标定注册表 cell_geometry ({os.path.relpath(_zp.CALIB, _zp.ROOT)})")
    except Exception:                                     # noqa: BLE001
        pass
    for p in cands:
        try:
            d = json.load(open(p, encoding="utf-8"))
            if not d.get("validated"):
                return None, f"几何未通过校验({p})"
            pts = d["points"]
            return ({"peg_head": [pts["peg_head"][k] for k in "xyz"],
                     "goal": [pts["goal"][k] for k in "xyz"]},
                    f"示教几何 {d.get('updated_at')} @ {p}")
        except Exception as e:                           # noqa: BLE001
            last = f"无示教几何({type(e).__name__}) @ {p} — 相关项拒填, 不编造"
    return None, last


def quat_to_R(q):
    """四元数 (x,y,z,w) → 3x3 旋转矩阵 (真机 TCP 姿态 → base_link 方向)"""
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def peg_tool_offset():
    """模块中心相对 TCP 的夹具偏移 (米, base_link 下的固定工具偏移) — 由标定给出, 没有就 None。
    来源优先级: 环境变量 SS_PEG_TOOL_OFFSET='x,y,z' > 几何文件字段 peg_tool_offset
              > **全系统标定注册表** config/calib/zmax_calib.json 的 cell_geometry.peg_tool_offset > 无。"""
    ev = os.environ.get("SS_PEG_TOOL_OFFSET", "").strip()
    if ev:
        try:
            v = [float(t) for t in ev.replace(" ", "").split(",")]
            if len(v) == 3:
                return v, "env SS_PEG_TOOL_OFFSET"
        except ValueError:
            pass
    p = os.path.expanduser(os.environ.get("SS_GEOM_PATH", GEOM_DEFAULT))
    try:
        d = json.load(open(p, encoding="utf-8"))
        v = d.get("peg_tool_offset")
        if v and len(v) == 3:
            return [float(t) for t in v], f"几何文件字段 @ {p}"
    except Exception:                                # noqa: BLE001
        pass
    try:                                             # 单一真源兜底 (2026-09-22)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import zmax_params as _zp                     # noqa: PLC0415
        pts = (_zp.calib().get("cell_geometry") or {}).get("points") or {}
        v = pts.get("peg_tool_offset")
        if v and len(v) == 3:
            return [float(t) for t in v], f"标定注册表 cell_geometry.peg_tool_offset"
    except Exception:                                # noqa: BLE001
        pass
    return None, "未标定夹具偏移 (模块中心≠TCP) → 光模块项填 null, 只用 TCP 真值, 不编造"


def snapshot(out=None, geom_path=None, fresh_s=FRESH_S) -> dict:
    """抓一次真机真值快照 (标注保存/实时显示都用这一个入口 — 单一来源)"""
    st, sd = read_latest_state(out), read_status(out)
    src = st or sd
    tcp = src.get("tcp")
    quat = src.get("tcp_quat")
    ts = src.get("t") or src.get("frame_ts") or src.get("saved")
    age = (time.time() - float(ts)) if ts else None
    rec = {"ts": ts, "age_s": round(age, 3) if age is not None else None,
           "fresh": bool(age is not None and age <= fresh_s),
           "frame": src.get("tcp_frame") or "base_link",
           "tcp": [round(float(v), 6) for v in tcp] if tcp else None,
           "tcp_quat": [round(float(v), 6) for v in quat] if quat else None,
           "joints": src.get("jpos"), "jvel": src.get("jvel"), "ft": src.get("ft"),
           "src_file": src.get("_src_file", "")}
    geom, geom_note = load_geom(geom_path)
    rec["geom_state"] = geom_note
    off, off_note = peg_tool_offset()
    rec["peg_offset_state"] = off_note
    # ── 与 metaworld 39D 对齐 ──
    seg = {"hand": rec["tcp"], "peg": None, "peg_quat": rec["tcp_quat"],
           "prev_hand": None, "prev_peg": None, "hole": (geom or {}).get("goal")}
    if rec["tcp"] and off:
        R = quat_to_R(rec["tcp_quat"]) if rec["tcp_quat"] else [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        seg["peg"] = [round(rec["tcp"][i] + sum(R[i][j] * off[j] for j in range(3)), 6) for i in range(3)]
    rec["obs39_segments"] = seg
    # ── 距离/高度 (老倪要的"光模块距离、位置") ──
    dist = {"z_m": rec["tcp"][2] if rec["tcp"] else None,
            "tcp_to_goal_m": None, "tcp_to_peg_head_m": None,
            "peg_to_goal_m": None, "dist_src": "TCP 真值 (base_link)"}
    if rec["tcp"] and geom:
        dist["tcp_to_goal_m"] = round(math.dist(rec["tcp"], geom["goal"]), 6)
        dist["tcp_to_peg_head_m"] = round(math.dist(rec["tcp"], geom["peg_head"]), 6)
    if seg.get("peg") and geom:
        dist["peg_to_goal_m"] = round(math.dist(seg["peg"], geom["goal"]), 6)
    rec["dist"] = dist
    notes = {}
    if not seg["peg"]:
        notes["peg"] = off_note
    if not seg["hole"]:
        notes["hole"] = geom_note
    rec["notes"] = notes
    return rec


def as_train_record(rec: dict, stem: str, box_px=None) -> dict:
    """给训练用的一条 (图 stem, 2D框, 3D真值) 三元组 —— 与仿真 data/yolo_peg 同口径"""
    return {"stem": stem, "box_px": box_px,
            "hand_xyz": rec.get("obs39_segments", {}).get("hand"),
            "peg_xyz": rec.get("obs39_segments", {}).get("peg"),
            "peg_quat": rec.get("obs39_segments", {}).get("peg_quat"),
            "hole_xyz": rec.get("obs39_segments", {}).get("hole"),
            "dist": rec.get("dist"), "age_s": rec.get("age_s"),
            "frame": rec.get("frame"), "missing": rec.get("notes", {})}


if __name__ == "__main__":
    r = snapshot()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print("\n[判读] 真值新鲜:", r["fresh"], "· age_s =", r["age_s"])
    print("  TCP(末端真值) =", r["tcp"], r["frame"])
    print("  光模块(peg)   =", r["obs39_segments"]["peg"], "|", r["notes"].get("peg", "已对齐"))
    print("  hole(孔口)    =", r["obs39_segments"]["hole"], "|", r["notes"].get("hole", "已对齐"))
    print("  距离/高度     =", r["dist"])
