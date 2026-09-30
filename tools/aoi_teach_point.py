#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_teach_point.py — 📍 金手指示教点: 记住当前位置 + 一键回位 (2026-09-24 老倪需求)

老倪: 「增加一个技能, 记住这个金手指点1, 可以通过这个技能回到这个位置」

设计 (全部复用既有件, **不新写运动学/不绕收口**):
  · 位姿真值: `tools/l2_ros2_bridge.tcp_pose()` — /robot/tcp_pose (只读订阅, frame=base_link)
             多帧采样取中位 + 抖动量 (spread) 判据: 抖动大 = 机械臂还在动 → **拒绝记录**(不拿动着的位姿当示教点)
  · 点位库:   `data/skills/l2_atomic/taught_points.json` (与 aoi_gold_view/slot1/slot2/insert_pose 同一库,
             字段同名: pos/quat/desc/recorded_at/source/n_samples/spread_*)
             + `reports/aoi_points/<name>.json` 存 **AOI 上下文** (判据图裁切框 ROI / 框内指标 / 判据图快照路径 / 操作员)
  · 回位:     **走 L2 收口** —— ① FIFO `~/zmax_data/l2_cmd.fifo` 写 {"skill":"L2.goto_point","point":<name>}
             (由常驻 l2_daemon 执行: 自带闸门/限幅/日志) ② 直发 `ros2 service call /move_line …` (lite 兜底)
             ⚠️ 默认 **dry-run** (只算 Δ位置 mm + Δ姿态 角 + 打印将下发的命令), 真动必须显式 authorize=True
  · 判完成:   回读 /robot/tcp_pose 与目标比 (位置 mm / 姿态 deg) + operation_state, 不凭 service 返回码

CLI:
  python tools/aoi_teach_point.py --list
  python tools/aoi_teach_point.py --record 金手指点1 --desc "AOI 观察位"
  python tools/aoi_teach_point.py --goto 金手指点1              # 只算不发 (dry-run)
  python tools/aoi_teach_point.py --goto 金手指点1 --authorize  # ⚠️ 真动
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
if os.path.join(ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tools"))

POINTS = os.environ.get("ZMAX_TAUGHT_POINTS",
                        os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json"))
CTX_DIR = os.path.join(ROOT, "reports/aoi_points")
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
MAX_SPREAD_M = 5e-4            # 位置抖动量上限 (0.5mm): 超过 = 还在动 → 拒绝记录


# ── 位姿真值 ────────────────────────────────────────────────────────────
def parse_pose(text: str):
    """从 `ros2 topic echo --once /robot/tcp_pose` 文本里抽 pos[3]/quat[4] (x,y,z,w)。"""
    if not text or "position" not in text:
        return None
    t = re.sub(r"\s+", " ", str(text)).replace("\\n", " ")

    def _grab(seg):
        seg = seg[:400]
        out = {}
        for ax in ("x", "y", "z", "w"):
            m = re.search(r"(?:^|\s)%s:\s*(-?\d+\.?\d*(?:[eE][-+]?\d+)?)" % ax, seg)
            if m:
                out[ax] = float(m.group(1))
        return out

    i = t.find("position:")
    j = t.find("orientation:")
    p = _grab(t[i:j] if i >= 0 and j > i else "")
    q = _grab(t[j:]) if j >= 0 else {}
    if len(p) < 3 or len(q) < 4:
        return None
    return {"pos": [p["x"], p["y"], p["z"]], "quat": [q["x"], q["y"], q["z"], q["w"]]}


def read_pose(samples: int = 6, gap_s: float = 0.12, max_spread_m: float = MAX_SPREAD_M):
    """多帧采样位姿真值。返回 (pose|None, meta)。

    ⚠️ 抖动超限**不冒充真值**: pose 返回 None 并给出 spread, 让调用方如实拒绝记录。
    """
    import l2_ros2_bridge as br
    poses, raw = [], ""
    for _ in range(max(1, samples)):
        raw = br.tcp_pose()
        p = parse_pose(raw)
        if p:
            poses.append(p)
        time.sleep(gap_s)
    if not poses:
        return None, {"ok": False, "err": "读不到 /robot/tcp_pose (ROS 未起/机械臂未上电?)",
                      "raw": str(raw)[:160], "n": 0}
    pos = [statistics.median([p["pos"][i] for p in poses]) for i in range(3)]
    quat = [statistics.median([p["quat"][i] for p in poses]) for i in range(4)]
    sp_pos = max(max(abs(p["pos"][i] - pos[i]) for i in range(3)) for p in poses)
    sp_quat = max(max(abs(p["quat"][i] - quat[i]) for i in range(4)) for p in poses)
    st = br.status_line()
    meta = {"ok": sp_pos <= max_spread_m, "n": len(poses), "spread_pos_m": round(sp_pos, 8),
            "spread_quat": round(sp_quat, 8), "status": st, "frame": "base_link",
            "source": "/robot/tcp_pose (只读订阅)"}
    if not meta["ok"]:
        meta["err"] = (f"位姿在动: 位置抖动量 {sp_pos*1000:.3f}mm > {max_spread_m*1000:.1f}mm → "
                       f"停在目标位姿再记 (拒绝把动着的位姿当示教点)")
        return None, meta
    return {"pos": [round(v, 7) for v in pos], "quat": [round(v, 7) for v in quat]}, meta


# ── 点位库 ──────────────────────────────────────────────────────────────
def load_points() -> dict:
    try:
        with open(POINTS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                  # noqa: BLE001
        return {"version": "v1", "frame": "base_link", "points": {}}


def list_points() -> dict:
    d = load_points()
    out = {}
    for k, v in (d.get("points") or {}).items():
        out[k] = {"pos": v.get("pos"), "desc": v.get("desc", ""), "recorded_at": v.get("recorded_at"),
                  "spread_pos_m": v.get("spread_pos_m"), "n_samples": v.get("n_samples"),
                  "has_ctx": os.path.isfile(os.path.join(CTX_DIR, f"{k}.json"))}
    return out


def record(name: str, desc: str = "", samples: int = 6, roi=None, judge_png: str = "",
           judge_stats: dict | None = None, operator: str = "engineer", dry_pose=None) -> dict:
    """记住当前位姿为示教点 (name 如 '金手指点1')。位姿读不到/在动 → **拒绝写库** (如实回报)。"""
    if dry_pose is not None:                       # 测试用: 直接给位姿 (不打机械臂)
        pose, meta = dry_pose, {"ok": True, "n": 1, "spread_pos_m": 0.0, "spread_quat": 0.0,
                                "source": "dry_pose (注入)", "status": {}, "frame": "base_link"}
    else:
        pose, meta = read_pose(samples=samples)
    if pose is None:
        return {"ok": False, "err": meta.get("err", "位姿不可用"), "meta": meta}
    d = load_points()
    pts = d.setdefault("points", {})
    # 🗂 更新前留痕 (可回滚): 旧值追加进 reports/aoi_points/<name>.history.jsonl
    old = pts.get(name)
    if old:
        try:
            os.makedirs(CTX_DIR, exist_ok=True)
            with open(os.path.join(CTX_DIR, f"{name}.history.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"replaced_at": time.strftime("%F %T"), "old": old,
                                    "new_pos": pose["pos"], "new_quat": pose["quat"],
                                    "by": operator, "reason": "update"}, ensure_ascii=False) + "\n")
        except Exception:                                              # noqa: BLE001
            pass
    pts[name] = {"pos": pose["pos"], "quat": pose["quat"],
                 "desc": desc or f"AOI 示教点 ({name})",
                 "recorded_at": time.strftime("%F %T"), "source": meta["source"],
                 "n_samples": meta["n"], "spread_pos_m": meta["spread_pos_m"],
                 "spread_quat": meta["spread_quat"], "frame": "base_link"}
    d["frame"] = "base_link"
    os.makedirs(os.path.dirname(POINTS), exist_ok=True)
    with open(POINTS, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    # AOI 上下文 (判据图口径/框选 ROI/快照) —— 位姿与"当时看到的画面"一起存, 回位后可复核
    os.makedirs(CTX_DIR, exist_ok=True)
    ctx = {"name": name, "recorded_at": time.strftime("%F %T"), "operator": operator,
           "pose": pose, "roi": list(roi) if roi else None, "judge_png": judge_png,
           "judge_stats": judge_stats or {}, "spread": {"pos_m": meta["spread_pos_m"],
                                                       "quat": meta["spread_quat"]},
           "status_at_record": meta.get("status", {})}
    with open(os.path.join(CTX_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=1)
    return {"ok": True, "name": name, "pose": pose, "meta": meta,
            "fifo_cmd": fifo_cmd(name), "ros_cmd": ros_cmd(name),
            "ctx": os.path.join(CTX_DIR, f"{name}.json")}


# ── 回位 ────────────────────────────────────────────────────────────────
def fifo_cmd(name: str) -> str:
    """L2 收口命令 (常驻执行器自带闸门/限幅/日志) —— 可直接粘到终端执行。"""
    return ("echo '%s' > %s" % (json.dumps({"skill": "L2.goto_point", "point": name},
                                           ensure_ascii=False), FIFO))


def ros_cmd(name: str, speed: int = 30) -> str:
    """直发服务的等价命令 (dry-run 时给人看, 也可复制到终端; 需机械臂已解锁)。"""
    import l2_ros2_bridge as br
    p = (load_points().get("points") or {}).get(name)
    if not p:
        return ""
    return "ssh tashan@192.168.23.66 bash -lc '%s'" % br.cmd_move(p, speed)


def quat_angle_deg(q1, q2) -> float:
    dot = min(1.0, abs(sum(a * b for a, b in zip(q1, q2))))
    return math.degrees(2.0 * math.acos(dot))


def goto(name: str, authorize: bool = False, speed: int = 30, ros_cmd_override: str = "") -> dict:
    """回到示教点。默认 **dry-run**: 只算 Δ 并打印将下发的命令, 不发运动。

    authorize=True 才真动: 优先走 **L2 收口 FIFO** (daemon 执行), 无 FIFO 才直发服务;
    完成后**回读真值**比对 (位置 mm / 姿态 deg) —— 不凭 service 返回码判成功。
    """
    pts = (load_points().get("points") or {})
    if name not in pts:
        return {"ok": False, "err": f"点位不存在: {name}", "have": list(pts.keys())}
    tgt = {"pos": list(pts[name]["pos"]), "quat": list(pts[name]["quat"])}
    cur, cmeta = read_pose(samples=3)
    out = {"ok": True, "name": name, "dry_run": not authorize, "target": tgt, "current": cur,
           "fifo_cmd": fifo_cmd(name), "ros_cmd": ros_cmd(name, speed),
           "recorded_at": pts[name].get("recorded_at"), "desc": pts[name].get("desc", "")}
    if cur:
        import l2_ros2_bridge as br                                   # noqa: F401
        d = [tgt["pos"][i] - cur["pos"][i] for i in range(3)]
        out["delta_mm"] = [round(v * 1000, 2) for v in d]
        out["delta_norm_mm"] = round(math.sqrt(sum(v * v for v in d)) * 1000, 2)
        out["delta_deg"] = round(quat_angle_deg(tgt["quat"], cur["quat"]), 3)
    else:
        out["pose_err"] = cmeta.get("err")
    if not authorize:
        out["note"] = "dry-run: 未下发任何运动 (真动加 authorize=True 或窗口勾『真执行』)"
        return out
    # ── 真动 (收口优先) ──
    gate_ok, st = True, {}
    try:
        import l2_ros2_bridge as br
        gate_ok, st = br.gate()
    except Exception as e:                                             # noqa: BLE001
        gate_ok, st = False, {"err": f"{type(e).__name__}: {e}"}
    out["gate"] = {"ok": gate_ok, "status": st}
    if not gate_ok:
        out.update({"ok": False, "err": f"闸门未过 (power_state/错误态): {st}"})
        return out
    phase = ""
    try:
        if os.path.exists(FIFO):
            with open(FIFO, "w") as f:
                f.write(json.dumps({"skill": "L2.goto_point", "point": name}, ensure_ascii=False))
            phase = "fifo(L2 收口)"
        else:
            import l2_ros2_bridge as br
            br.sh(br.cmd_move(tgt, speed), timeout=120)
            phase = "direct(ros2 service /move_line)"
    except Exception as e:                                             # noqa: BLE001
        out.update({"ok": False, "err": f"下发失败: {type(e).__name__}: {e}"})
        return out
    time.sleep(3.0)
    after, _ = read_pose(samples=3)
    out["phase"] = phase
    out["after"] = after
    if after:
        d = [tgt["pos"][i] - after["pos"][i] for i in range(3)]
        out["err_mm"] = [round(v * 1000, 2) for v in d]
        out["err_norm_mm"] = round(math.sqrt(sum(v * v for v in d)) * 1000, 2)
        out["err_deg"] = round(quat_angle_deg(tgt["quat"], after["quat"]), 3)
        out["ok"] = out["err_norm_mm"] <= 2.0 and out["err_deg"] <= 2.0
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="金手指示教点 (默认 dry-run; --authorize 才真动)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--record", default="")
    ap.add_argument("--desc", default="")
    ap.add_argument("--goto", default="")
    ap.add_argument("--authorize", action="store_true")
    ap.add_argument("--speed", type=int, default=30)
    ap.add_argument("--samples", type=int, default=6)
    a = ap.parse_args()
    if a.list:
        print(json.dumps(list_points(), ensure_ascii=False, indent=1)); raise SystemExit(0)
    if a.record:
        print(json.dumps(record(a.record, a.desc, samples=a.samples), ensure_ascii=False, indent=1))
        raise SystemExit(0)
    if a.goto:
        r = goto(a.goto, authorize=a.authorize, speed=a.speed)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        raise SystemExit(0 if r.get("ok") else 1)
    ap.print_help()
