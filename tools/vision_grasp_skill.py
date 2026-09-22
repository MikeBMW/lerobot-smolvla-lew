#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vision_grasp_skill.py — 视觉引导抓取技能 (注册 id: **L2.grasp_vision**)

老倪 (2026-09-22): 「你能判断一号位或二号位哪个有光模块, 并进行抓取么?」
                  → 「先把这个动作编写成一个**视觉引导**的技能, 保存数据, 小版本迭代;
                     等我确认安全了再实际发送。」

本文件 = 这条技能的两件事:
  ① **视觉判据** (只读, 可单独调用): 判 slot1/slot2 哪个槽里有光模块 —— **双路独立证据**,
     两路一致才认账, 否则一律不出结论 (宁缺勿假):
       · 路 A 模型: YOLO peg 框 (与 cam_rs.png 同帧) 的**框底心** ↔ 槽位示教点的手眼投影对账
                  判据: 横向 |Δx| ≤ 12px (两槽横向差 ~46px) 且 框底-投影 ∈ [-5, +25]px (咬合高度带)
       · 路 B 像素 (不依赖任何模型): 模块所在竖直带内「竖直棱边能量」列剖面找峰列,
                  峰列与哪个槽的手眼投影重合 (≤20px) 就归哪个槽
  ② **编排 + 守卫** (执行仍由 L2 收口): 把判定结果喂给注册表里的技能
     `L2.grasp_vision` (视觉门 + 两阶段回槽位 + 合爪 + 抬升), 由常驻执行器 l2_daemon 执行。

红线 (与整机一致):
  · **默认 dry-run, 不下发任何指令**; 真发必须显式 `--apply` (老倪确认安全后才用)。
  · 判据不达标 / 帧不新鲜 (负帧龄或 >5s) / 夹爪不是张开位 / 位姿读不到 → **拒发**, 不猜。
  · 判完成只看真值: 任务后复判 (槽位应变空) + 夹爪回执 curr_pos (空爪≈21 · 夹住模块≈185)。
  · 视觉门在**执行器内**再判一次 (fail-closed): 注册表条目带 `vision_gate`, 执行器不支持时
    阶段点 slot_vision 解析不到 → 直接拒发, 不会盲动。

用法:
  gui-venv311/bin/python tools/vision_grasp_skill.py            # 只做判定 + 计划 (dry, 零下发)
  gui-venv311/bin/python tools/vision_grasp_skill.py --apply    # 真发 (需现场确认; 走 FIFO → l2_daemon)
  gui-venv311/bin/python tools/vision_grasp_skill.py --fake-dir <目录>   # 离线自检 (合成输入, 不碰真机)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

REPO = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(REPO, "tools"))

CALIB = os.path.join(REPO, "models", "real_cam_calib.json")
STATE = os.path.join(REPO, "models", "handeye_state.json")
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
DET = os.path.expanduser("~/zmax_data/ss_bypass/yolo_detections.json")
FRAME = os.path.expanduser("~/zmax_ss_remote/cam_rs.png")
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
DAEMON_LOG = os.path.expanduser("~/zmax_data/l2_daemon.log")
EVID_DIR = os.path.expanduser("~/zmax_data/vision_grasp")
ROBOT_IP = "192.168.23.160"
TAP = "ss-remote-tap"
SKILL_ID = "L2.grasp_vision"

# 判据常数 (与 slot_occupy.py 同口径)
TOL_DX_PX = 12.0
DY_BAND = (-5.0, 25.0)
EDGE_PEAK_TOL_PX = 20.0
MAX_FRAME_AGE_S = 5.0
GRIP_OPEN_POS = 1000.0            # 夹爪张开指令位 (回执口径)
GRIP_EMPTY, GRIP_HOLDING = 21.0, 185.0    # 产线口径: 空爪≈21 · 夹住模块≈185


# ─────────────────────────── 只读取数 ───────────────────────────
def _sh(cmd: list[str], timeout: int = 25) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                            # noqa: BLE001
        return "ERR %s" % e


def tcp_pose(timeout: int = 25):
    """当前 TCP 位姿 (与 slot_occupy 同源: docker tap → /robot/tcp_pose, 只读订阅)"""
    import re
    out = _sh(["sudo", "docker", "exec", TAP, "bash", "-lc",
               "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
               "timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose"], timeout)
    v = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", out)]
    if len(v) < 7:
        return None, None, out[-160:]
    return v[:3], v[3:7], "live"


def gripper_pos(timeout: int = 20):
    """夹爪当前位 (回执口径): /gripper_pos 有 Float32/Float64 两种类型, 必须显式指定类型"""
    out = _sh(["sudo", "docker", "exec", TAP, "bash", "-lc",
               "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
               "timeout 6 ros2 topic echo --once /gripper_pos std_msgs/msg/Float32"], timeout)
    import re
    m = re.search(r"data:\s*(-?\d+\.?\d*)", out)
    return (float(m.group(1)) if m else None), out[-160:]


def power_state(timeout: int = 40):
    """控制器电源/模式/状态 (SDK 直连, 只读) — 上电闸门前置"""
    py = ("import sys;sys.path.insert(0,'/sdk');import xcoresdk_python as x;"
          "r=x.xMateRobot();r.connectToRobot('%s');"
          "print('POWER',r.powerState({}));print('MODE',r.operateMode({}));"
          "print('OPST',r.operationState({}));r.disconnectFromRobot({})" % ROBOT_IP)
    out = _sh(["sudo", "docker", "run", "--rm", "--network", "host",
               "-v", "/home/ubuntu/zmax_data/rokae_sdk:/sdk", "-w", "/sdk",
               "ros:humble-ros-base", "python3", "-c", py], timeout)
    d = {}
    for ln in out.splitlines():
        p = ln.split()
        if len(p) >= 2 and p[0] in ("POWER", "MODE", "OPST"):
            d[p[0].lower()] = p[1]
    return d, out[-200:]


# ─────────────────────────── 路 A: YOLO 框 + 手眼投影对账 ───────────────────────────
def load_geom():
    cal = json.load(open(CALIB, encoding="utf-8"))
    k = cal["K"]
    K = np.array([[k[0], 0, k[2]], [0, k[4], k[5]], [0, 0, 1]], float)
    dist = np.array(cal.get("dist") or [0, 0, 0, 0, 0], float)
    X = np.array(json.load(open(STATE, encoding="utf-8"))["T_cam2tool"], float)
    slots = json.load(open(PTS, encoding="utf-8")).get("points", {})
    return K, dist, X, slots


def _R_from_quat(q):
    x, y, z, w = [float(v) for v in q]
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def project_slots(pos, quat, K, dist, X, slots, names=("slot1", "slot2")):
    G = np.eye(4)
    G[:3, :3] = _R_from_quat(quat)
    G[:3, 3] = pos
    T_cam_base = np.linalg.inv(G @ X)
    out = {}
    for nm in names:
        ent = slots.get(nm)
        p = (ent or {}).get("pos") if isinstance(ent, dict) else ent
        if not p:
            continue
        pc = T_cam_base @ np.array([p[0], p[1], p[2], 1.0])
        if pc[2] <= 0.05:
            continue
        uv, _ = cv2.projectPoints(np.array([[0.0, 0.0, 0.0]]), np.zeros(3),
                                  pc[:3].reshape(3, 1), K, dist)
        uv = uv.reshape(2)
        out[nm] = (float(uv[0]), float(uv[1]), float(pc[2]))
    return out


def verdict_by_box(dets, proj):
    """路 A: 每个检出框底心 → 离哪个槽投影最近且满足判据"""
    res = {}
    for d in dets or []:
        x1, y1, x2, y2 = d["xyxy"]
        cx, cy_b = (x1 + x2) / 2.0, y2
        hit = None
        for nm, (u, v, _dd) in proj.items():
            dx, dy = abs(cx - u), cy_b - v
            ok = dx <= TOL_DX_PX and DY_BAND[0] <= dy <= DY_BAND[1]
            res.setdefault(nm, []).append({"conf": d.get("conf"), "dx": dx, "dy": dy, "hit": bool(ok)})
            if ok and hit is None:
                hit = nm
        if hit:
            res["_box_slot"] = hit
    return res


# ─────────────────────────── 路 B: 像素棱边列剖面 (模型无关) ───────────────────────────
def verdict_by_pixels(img_gray, proj, half_w=22, rh=150):
    vmin = min(v for _u, v, _d in proj.values())
    vmax = max(v for _u, v, _d in proj.values())
    y0, y1 = max(0, int(vmin) - 140), min(img_gray.shape[0], int(vmax) + 8)
    band = img_gray[y0:y1, :].astype(np.float32)
    prof = np.abs(np.diff(band, axis=1)).sum(axis=0)
    prof_s = np.convolve(prof, np.ones(25) / 25, mode="same")
    top = np.argsort(prof_s)[::-1]
    peaks: list[int] = []
    for c in top:
        if all(abs(int(c) - p) > 30 for p in peaks):
            peaks.append(int(c))
        if len(peaks) == 3:
            break
    out = {"band_y": [y0, y1], "peaks": peaks, "per_slot": {}}
    for nm, (u, v, _d) in proj.items():
        near = min((abs(p - u), p) for p in peaks)
        x0, x1 = int(max(0, u - half_w)), int(min(img_gray.shape[1], u + half_w))
        yy1, yy0 = int(min(img_gray.shape[0], v + 10)), int(max(0, v + 10 - rh))
        roi = img_gray[yy0:yy1, x0:x1].astype(np.float32)
        gx = float(np.abs(np.diff(roi, axis=1)).mean()) if roi.size else 0.0
        out["per_slot"][nm] = {"nearest_peak": near[1], "peak_dist_px": near[0],
                               "edge_energy": gx, "roi": [x0, yy0, x1, yy1]}
    cand = [nm for nm, s in out["per_slot"].items() if s["peak_dist_px"] <= EDGE_PEAK_TOL_PX]
    out["slot"] = cand[0] if len(cand) == 1 else None
    out["ambiguous"] = (len(cand) > 1)
    return out


# ─────────────────────────── 判定总入口 (双路一致才认) ───────────────────────────
def judge_slot(verbose: bool = True, _geom=None, _det=None, _img=None, _tcp=None) -> dict:
    """返回 {ok, slot, reason, evidence}. `_*` 入参仅供离线自检注入口径一致的合成输入。"""
    K, dist, X, slots = (_geom or load_geom())
    pos, quat, src = (_tcp or tcp_pose())
    if not pos:
        return {"ok": False, "slot": None, "reason": "位姿读不到(直连 tap 未就绪)", "evidence": {"tcp_src": src}}
    proj = project_slots(pos, quat, K, dist, X, slots)
    if len(proj) < 2:
        return {"ok": False, "slot": None, "reason": "候选槽位投影不足(%d)" % len(proj), "evidence": {"proj": proj}}

    det = _det if _det is not None else json.load(open(DET, encoding="utf-8"))
    age = float(det.get("frame_age_s", -1))
    imgp = _img if _img is not None else FRAME
    img = cv2.imread(imgp, cv2.IMREAD_GRAYSCALE) if isinstance(imgp, str) else imgp
    if img is None:
        return {"ok": False, "slot": None, "reason": "读不到帧 %s" % imgp, "evidence": {"proj": proj}}

    ev = {"tcp": [round(v, 6) for v in pos], "tcp_src": src, "frame_age_s": age,
          "frame": (imgp if isinstance(imgp, str) else "<in-memory>"),
          "proj": {k: [round(v[0], 1), round(v[1], 1), round(v[2], 4)] for k, v in proj.items()},
          "n_det": int(det.get("n", 0))}
    # 帧新鲜度红线 (负帧龄=时钟异常 → 拒用)
    if age < 0 or age > MAX_FRAME_AGE_S:
        return {"ok": False, "slot": None,
                "reason": "帧不新鲜(age=%.2fs, 允许 [0, %.0fs])" % (age, MAX_FRAME_AGE_S), "evidence": ev}
    A = verdict_by_box(det.get("detections") or [], proj)
    B = verdict_by_pixels(img, proj)
    ev["routeA_box"] = A
    ev["routeB_pixel"] = B
    a_slot, b_slot = A.get("_box_slot"), B.get("slot")
    if a_slot and b_slot and a_slot == b_slot:
        return {"ok": True, "slot": a_slot, "reason": "双路一致(YOLO框+像素棱边峰)", "evidence": ev}
    if not a_slot and not b_slot:
        return {"ok": False, "slot": None, "reason": "两路都判不出槽位", "evidence": ev}
    if a_slot and b_slot != a_slot:
        return {"ok": False, "slot": None,
                "reason": "两路冲突: YOLO=%s vs 像素=%s → 不猜, 人工看画面" % (a_slot, b_slot), "evidence": ev}
    return {"ok": False, "slot": None,
            "reason": "仅单路有信号(YOLO=%s 像素=%s) → 不足以下发" % (a_slot, b_slot), "evidence": ev}


# ─────────────────────────── 前置闸门 (执行前逐条, 任何一条不过就拒发) ───────────────────────────
def preflight(judge: dict, require_slot: bool = True) -> dict:
    chk: dict[str, str] = {}
    st, raw = power_state()
    chk["power_on"] = "PASS" if str(st.get("power", "")).endswith("on") else "FAIL(%s)" % st.get("power")
    chk["opstate_idle"] = "PASS" if str(st.get("opst", "")).endswith("idle") else "WARN(%s)" % st.get("opst")
    gp, _graw = gripper_pos()
    chk["gripper_open"] = ("PASS(%.1f)" % gp if gp is not None and gp >= GRIP_OPEN_POS - 3
                           else ("FAIL(%.1f)" % gp if gp is not None else "FAIL(读不到)"))
    chk["frame_fresh"] = ("PASS(%.2fs)" % judge["evidence"].get("frame_age_s", -1)
                          if judge.get("evidence", {}).get("frame_age_s", -1) is not None
                          and 0 <= float(judge["evidence"].get("frame_age_s", -1)) <= MAX_FRAME_AGE_S
                          else "FAIL")
    chk["vision"] = "PASS(%s)" % judge["slot"] if judge.get("ok") else "FAIL(%s)" % judge.get("reason")
    if require_slot and not judge.get("ok"):
        chk["vision"] = "FAIL(无可用槽位判定)"
    ok = all(str(v).startswith(("PASS", "WARN")) for v in chk.values())
    return {"ok": bool(ok), "checks": chk, "power_raw": raw}


# ─────────────────────────── 编排: 生成 / 展示 / (可选)下发 ───────────────────────────
def build_spec(slot: str, **kw) -> dict:
    s = {"skill": SKILL_ID, "point": slot}
    s.update(kw)
    return s


def show_plan(slot: str, reg_path: str = REG) -> list[str]:
    reg = json.load(open(reg_path, encoding="utf-8"))
    sk = next((s for s in reg["skills"] if s["id"] == SKILL_ID), None)
    lines = []
    if not sk:
        return ["❌ 注册表里没有 %s (先跑 tools/register_vision_grasp_skill.py)" % SKILL_ID]
    for i, st in enumerate(sk.get("steps") or [], 1):
        if st.get("op") == "gripper":
            lines.append("  阶段%d %s → 夹爪 pos=%.0f force=%.0f" % (i, st.get("note", ""), st.get("pos", 0.0), st.get("force", 0.0)))
        elif st.get("op") == "service":
            lines.append("  阶段%d %s → 服务 %s" % (i, st.get("note", ""), st.get("srv")))
        else:
            tgt = st.get("to", "?")
            if tgt == "slot_vision":
                tgt = "slot_vision(→%s 由视觉门解析)" % slot
            lines.append("  阶段%d %s → %s dz=%+.0fmm tol=%.1f" % (i, st.get("note", ""), tgt,
                                                              float(st.get("dz_mm", 0.0)), float(st.get("tol_mm", 2.0))))
    return lines


def send_via_fifo(spec: dict, timeout_s: float = 240.0) -> dict:
    """把 spec 写进常驻执行器的 FIFO, 然后**等日志里出现本次受理结果** (判完成只看真值/真实回执)。"""
    if not os.path.exists(FIFO):
        return {"sent": False, "reason": "FIFO 不存在: %s (l2_daemon 没在跑)" % FIFO}
    n0 = 0
    try:
        with open(DAEMON_LOG, encoding="utf-8", errors="ignore") as f:
            n0 = sum(1 for _ in f)
    except Exception:                                                     # noqa: BLE001
        pass
    line = json.dumps(spec, ensure_ascii=False)
    try:
        with open(FIFO, "w", encoding="utf-8") as f:                      # open 会阻塞到有读端(daemon)
            f.write(line + "\n")
    except Exception as e:                                                # noqa: BLE001
        return {"sent": False, "reason": "写 FIFO 失败: %s" % e}
    t0 = time.time()
    done = None
    while time.time() - t0 < timeout_s:
        time.sleep(1.0)
        try:
            with open(DAEMON_LOG, encoding="utf-8", errors="ignore") as f:
                ls = f.readlines()
        except Exception:                                                 # noqa: BLE001
            continue
        for ln in ls[n0:]:
            if "受理:" in ln or "🛑" in ln or "🛡" in ln or "拒绝" in ln:
                done = ln.strip()
        if done and ("全部 %d 阶段完成" in done or "阶段完成" in done or done.startswith(("🛑", "🛡"))):
            break
    return {"sent": True, "result": done, "elapsed_s": round(time.time() - t0, 1)}


def post_verify(slot: str, pre_judge: dict) -> dict:
    """事后验收 (只看真值): ① 槽位应已变空 ② 夹爪回执应为"夹住模块"而非空爪"""
    gp, _raw = gripper_pos()
    j = judge_slot(verbose=False)
    out = {"gripper_pos": gp,
           "gripper_verdict": ("夹住模块" if gp is not None and abs(gp - GRIP_HOLDING) <= 25
                               else ("空爪" if gp is not None and abs(gp - GRIP_EMPTY) <= 15 else "未知")),
           "slot_now": j.get("slot"), "slot_now_ok": j.get("ok"),
           "slot_now_reason": j.get("reason")}
    out["slot_became_empty"] = bool(j.get("ok") and j.get("slot") != slot)
    out["pass"] = bool(out["gripper_verdict"] == "夹住模块")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真下发 (需现场确认; 默认 dry-run 零下发)")
    ap.add_argument("--fake-dir", default="", help="离线自检: 用该目录下的合成输入, 不碰真机")
    ap.add_argument("--no-post", action="store_true", help="跳过事后验收")
    a = ap.parse_args()

    ts = time.strftime("%m%d_%H%M%S")
    outdir = os.path.join(EVID_DIR, ts)
    os.makedirs(outdir, exist_ok=True)

    if a.fake_dir:            # ── 离线自检路径 (合成输入, 零真机接触)
        det = json.load(open(os.path.join(a.fake_dir, "yolo_detections.json"), encoding="utf-8"))
        tcp = json.load(open(os.path.join(a.fake_dir, "tcp.json"), encoding="utf-8"))
        img = cv2.imread(os.path.join(a.fake_dir, "frame.png"), cv2.IMREAD_GRAYSCALE)
        judge = judge_slot(_det=det, _tcp=(tcp["pos"], tcp["quat"], "fake"), _img=img)
    else:
        judge = judge_slot()

    print("═" * 78)
    print("视觉引导抓取技能 %s · %s" % (SKILL_ID, "APPLY(真发)" if a.apply else "DRY-RUN(零下发)"))
    print("═" * 78)
    print("① 视觉判定: %s" % ("✅ %s 有光模块" % judge["slot"] if judge.get("ok") else "❌ %s" % judge["reason"]))
    ev = judge.get("evidence", {})
    for nm, v in (ev.get("proj") or {}).items():
        print("   %s 投影 像素(%.0f,%.0f) 距相机 %.3fm" % (nm, v[0], v[1], v[2]))
    for nm, rows in (ev.get("routeA_box") or {}).items():
        if nm.startswith("_"):
            continue
        for r in rows:
            print("   路A %s: conf=%.2f Δx=%.1fpx 框底-投影=%+.1fpx → %s" % (nm, r["conf"], r["dx"], r["dy"], "✅" if r["hit"] else "✗"))
    B = ev.get("routeB_pixel") or {}
    if B:
        print("   路B 棱边峰列 %s · 各槽最近峰距 %s" % (
            B.get("peaks"), {k: round(v["peak_dist_px"], 1) for k, v in B["per_slot"].items()}))

    print("\n② 前置闸门:")
    pf = preflight(judge, require_slot=not a.fake_dir)
    for k, v in pf["checks"].items():
        print("   %-14s %s" % (k, v))
    print("   → 总闸: %s" % ("✅ 通过" if pf["ok"] else "🛑 拒绝(不满足, 零下发)"))

    slot = judge.get("slot") or "<未判定>"
    print("\n③ 动作序列 (执行由 L2 收口, 逐阶段真值到位才进下一段):")
    for ln in show_plan(slot):
        print(ln)
    spec = build_spec(slot) if judge.get("slot") else None
    print("\n④ 将写入常驻执行器的指令: %s" % (json.dumps(spec, ensure_ascii=False) if spec else "<无>"))

    result: dict = {"ts": time.strftime("%F %T"), "skill": SKILL_ID, "apply": bool(a.apply),
                    "judge": judge, "preflight": pf, "spec": spec}
    if a.apply:
        if not (pf["ok"] and judge.get("ok")):
            print("\n🛑 未通过视觉/前置闸门 → **不下发**")
            result["sent"] = {"sent": False, "reason": "闸门未过"}
        else:
            print("\n⑤ 真下发 → FIFO")
            result["sent"] = send_via_fifo(spec)
            print("   结果: %s" % result["sent"])
            if not a.no_post:
                result["post"] = post_verify(judge["slot"], judge)
                print("⑥ 事后验收: %s" % json.dumps(result["post"], ensure_ascii=False))
    else:
        print("\n⑤ DRY-RUN: 未写 FIFO, 未下发任何指令 (真发请加 --apply, 需现场确认)")
    with open(os.path.join(outdir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("\n证据: %s" % outdir)
    return 0 if (judge.get("ok") or not a.apply) else 3


if __name__ == "__main__":
    raise SystemExit(main())
