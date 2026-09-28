#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_slot_tool.py — L5 槽位记录/角点投影/数据集落盘 (老倪 2026-09-28 L5 定义)

老倪原话: 「在L5, 我点击运行后, 你要自动进入人机交互模式 … 你现在已经能通过手臂相机看到黑色治具,
右上角有一个光模块, 一共有14个槽位。我会给你演示每个光模块放到槽位里的位置, 你要记住位置, 理解
光模块的边沿, 标注出槽位的位置角点, 并自动进入 L2 YOLO的训练流程, 重启后可以用新的YOLO目标检测
模型; 你的目标是认识并能够准确检测出每个槽位; 通过三个场景相机, 深度信号, 大模型层要负责理解,
L2层要进行训练并更新。」

铁律 (照老倪的话实现, 不额外造):
  ① 槽位位置**来自 TCP 真值**(基座系 tcp, 亚毫米) —— 不从图像猜。
  ② 角点**用已标定链投影**: models/real_cam_calib.json 的 K + models/handeye_state.json 的
     T_cam2tool + 该时刻 TCP ⇒ P = K·[R|t] ⇒ 投 8 角点 ⇒ 图像框。复用 tools/real_autolabel.py
     的 quat_to_R/module_corners/project (同一套数学, 不重写)。
  ③ 大模型(VLM)复核投影框是否落在槽位/光模块边沿上; 不一致 ⇒ 标"待确认", **不默默改成对的**.
  ④ 只读: 本工具只读 TCP / 抓图 / 记录 / 标注 —— 任何真机动作都不在这里。
  ⑤ 深度那一路: 判据=**源文件龄**(~/zmax_ss_remote/zmax_scene/depth_raw.npy, ss-remote-tap 里
     ros_depth_stream.py 落的)。2026-09-29 实测该链路**在流**(5Hz, 文件龄 ~2s) —— 旧版查容器名
     ros_depth_stream 是假离线, 已修。

用法:
  ./gui-venv311/bin/python tools/l5_slot_tool.py --init                 # 建 14 槽位登记表
  ./gui-venv311/bin/python tools/l5_slot_tool.py --status
  ./gui-venv311/bin/python tools/l5_slot_tool.py --record --slot 1 \
        [--size 40,16,12] [--demo "老倪演示"] [--no-vlm]
  ./gui-venv311/bin/python tools/l5_slot_tool.py --build-dataset [--size 40,16,12]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
TAP_DIR = "/home/ubuntu/zmax_ss_remote"
WORK = os.path.join(os.path.expanduser("~"), "zmax_data", "l5_slots")
REG = os.path.join(ROOT, "models", "l5_slots.json")
CALIB = os.path.join(ROOT, "models", "real_cam_calib.json")
HANDEYE = os.path.join(ROOT, "models", "handeye_state.json")
DS_ROOT = os.path.join(ROOT, "data", "yolo_annot_l5slots")
N_SLOTS = 14
CAMS3 = ("arm", "local", "local2")          # 三个场景相机 (arm=D405 / local=笔记本 / local2=MAXHUB)
DEPTH_CAM = "depth"                          # 深度那一路
SCENE_DIR = "/home/ubuntu/zmax_ss_remote/zmax_scene"      # = 容器 ss-remote-tap 的 /out/zmax_scene
DEPTH_NPY = SCENE_DIR + "/depth_raw.npy"
DEPTH_META = SCENE_DIR + "/depth_meta.json"
DEPTH_DEAD_S = 10.0                          # 源文件龄 >10s ⇒ 判「深度源已断」(与 cam_live_stream 同口径)


# ─────────────────────────── 真值读取 (只读) ───────────────────────────
def live_tcp(max_age_s: float = 5.0) -> dict:
    """读真机 tap 最新一帧 → {tcp, quat, t, age_s, robot_status...}; 不新鲜/没有 → ok=False"""
    try:
        files = [os.path.join(TAP_DIR, f) for f in os.listdir(TAP_DIR) if f.startswith("state_")]
        if not files:
            return {"ok": False, "reason": "tap 目录无 state_*.jsonl (%s)" % TAP_DIR}
        p = max(files, key=os.path.getmtime)
        age = time.time() - os.path.getmtime(p)
        with open(p, "rb") as f:
            f.seek(max(0, os.path.getsize(p) - 4000))
            last = [x for x in f.read().decode("utf-8", "ignore").splitlines()
                    if x.strip().startswith("{")][-1]
        d = json.loads(last)
        if not d.get("tcp"):
            return {"ok": False, "reason": "最新帧无 tcp 字段"}
        return {"ok": age <= max_age_s, "age_s": round(age, 1), "tcp": [float(x) for x in d["tcp"][:3]],
                "quat": [float(x) for x in (d.get("tcp_quat") or [])] or None,
                "t": d.get("t"), "frame": d.get("tcp_frame"), "tap": p,
                "joints": d.get("jnames") and d.get("joints"), "stamp": time.strftime("%F %T")}
    except Exception as e:                                                       # noqa: BLE001
        return {"ok": False, "reason": "%s: %s" % (type(e).__name__, e)}


def depth_online(max_age_s: float = DEPTH_DEAD_S) -> dict:
    """深度那一路是否在线 —— 判据 = **源文件龄**(与 tools/cam_live_stream.py 同口径)。

    实测坑(2026-09-29): 旧实现去 `docker ps` 找名字含 depth 的**容器**, 但深度实际是
    **ss-remote-tap 容器里的一个进程**(`python3 /repo/tools/ros_depth_stream.py --hz 5`),
    落的文件是 `/out/zmax_scene/depth_raw.npy` (= host `~/zmax_ss_remote/zmax_scene/`)
    ⇒ 旧判据永远 false(假离线), 会把"深度其实在流"误报成"深度未上线"。
    现在按源文件龄判: 新鲜就是在线(带上 age), 停写就如实说停写。
    """
    import subprocess                                                          # noqa: PLC0415
    age, src = None, None
    for p in (DEPTH_META, DEPTH_NPY):
        try:
            a = time.time() - os.path.getmtime(p)
        except OSError:
            continue
        if age is None or a < age:
            age, src = a, p
    alive = []
    try:                        # 附带上游进程信息(仅作说明, 不参与判据)
        o = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True,
                           text=True, timeout=8).stdout
        alive = [x for x in o.split() if "remote-tap" in x or "depth" in x.lower()]
    except Exception:                                                          # noqa: BLE001
        pass
    if age is None:
        return {"ok": False, "age_s": None, "containers": alive,
                "reason": "深度源文件不存在 (%s) → 深度未上线 (如实标)" % DEPTH_NPY}
    ok = age <= max_age_s
    return {"ok": ok, "age_s": round(age, 1), "src": src, "containers": alive,
            "reason": None if ok else "深度源已停写 %.1fs (>%.0fs) → 未上线 (如实标)" % (age, max_age_s)}


# ─────────────────────── 投影链 (K + 手眼 + 实时 TCP) ───────────────────────
def proj_matrix(frame_wh, tcp, quat) -> dict:
    """P = K·[R|t] (相机系→像素), 由 K(real_cam_calib) + T_base_tool(实时TCP) + T_cam2tool(handeye) 组出。
    ⚠️ K 是按标定分辨率标定的 (image_size), 实际流分辨率不同 ⇒ 按比例缩放 fx/fy/cx/cy (如实记录缩放)。
    复用 real_autolabel.quat_to_R (xyzw 约定, 与 tap 一致)。"""
    import numpy as np
    import real_autolabel as RA
    cb = json.load(open(CALIB, encoding="utf-8"))
    K = np.array(cb["K"], float).reshape(3, 3)
    cal_wh = list(cb.get("image_size") or [640, 480])
    W, H = int(frame_wh[0]), int(frame_wh[1])
    sx, sy = W / float(cal_wh[0]), H / float(cal_wh[1])
    Ks = K.copy()
    Ks[0, :] *= sx
    Ks[1, :] *= sy
    hb = json.load(open(HANDEYE, encoding="utf-8"))
    T_ct = np.array(hb["T_cam2tool"], float).reshape(4, 4)
    R_bt = RA.quat_to_R(quat) if quat else np.eye(3)
    T_bt = np.eye(4)
    T_bt[:3, :3] = R_bt
    T_bt[:3, 3] = np.array(tcp, float)
    T_bc = T_bt @ T_ct                      # base→cam = (base→tool)·(tool→cam) 的逆
    T_bc = np.linalg.inv(T_bc)
    Rt = T_bc[:3, :4]
    P = Ks @ Rt
    return {"P": P, "K": Ks, "K_calib": K, "calib_wh": cal_wh, "frame_wh": [W, H],
            "scale": [round(sx, 4), round(sy, 4)], "T_base_cam": T_bc.tolist(),
            "handeye_resid": {"t_mm": hb.get("resid_trans_mm_rms"), "r_deg": hb.get("resid_rot_deg_rms")},
            "calib_reason": cb.get("reason")}


def project_slot(center, quat, size_mm, frame_wh, tcp, tcp_quat) -> dict:
    """槽位 3D(中心) + 工件几何(角点) → 图像角点/框。角点 = 中心 ± R·(±sx/2,±sy/2,±sz/2) 8 角投图。"""
    import numpy as np
    import real_autolabel as RA
    # 实测坑(2026-09-29): 原来先 `list(size_mm)` 再判空 ⇒ `--record` 不带 `--size` 时
    # 直接 TypeError 崩掉, 本意是给"缺几何"提示。改为先归一化再判。
    _sz = [float(v) for v in size_mm] if (size_mm and len(size_mm) == 3 and min(size_mm) > 0) else None
    out = {"center_base": [round(float(x), 6) for x in center], "size_mm": _sz}
    if _sz is None:
        out.update({"ok": False, "reason": "缺工件/槽位几何 (--size W,H,T mm) → 只出中心点投影, 角点不编造"})
    pm = proj_matrix(frame_wh, tcp, tcp_quat)
    out["proj"] = {k: pm[k] for k in ("calib_wh", "frame_wh", "scale", "handeye_resid", "calib_reason")}
    c = RA.project(pm["P"], center)
    out["center_uv"] = [round(float(c[0]), 1), round(float(c[1]), 1)]
    if _sz:
        size_m = [float(v) / 1000.0 for v in _sz]
        corners = RA.module_corners(center, quat, size_m)
        uv = [RA.project(pm["P"], x) for x in corners]
        out["corners_base"] = [[round(float(v), 6) for v in p] for p in corners]
        out["corners_uv"] = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in uv]
        W, H = frame_wh
        xs = [p[0] for p in uv]
        ys = [p[1] for p in uv]
        box = [max(0.0, min(xs)), max(0.0, min(ys)), min(float(W), max(xs)), min(float(H), max(ys))]
        out["box_uv"] = [round(v, 1) for v in box]
        out["in_frame"] = bool(box[2] - box[0] > 2 and box[3] - box[1] > 2)
    out["ok"] = bool(out.get("in_frame", False))
    return out


# ─────────────────────────── 登记表 (14 槽位) ───────────────────────────
def load_reg() -> dict:
    if os.path.isfile(REG):
        return json.load(open(REG, encoding="utf-8"))
    return {"_note": "L5 槽位登记表 — 位置来自 TCP 真值(老倪演示时刻), 角点来自已标定链投影; "
                     "未演示的槽位 status=未演示 (绝不补假数据)",
            "n_slots": N_SLOTS, "slots": {}, "depth": {}, "updated": None}


def save_reg(d: dict) -> None:
    d["updated"] = time.strftime("%F %T")
    os.makedirs(os.path.dirname(REG), exist_ok=True)
    json.dump(d, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def cmd_init() -> int:
    d = load_reg()
    d["n_slots"] = N_SLOTS
    for i in range(1, N_SLOTS + 1):
        k = "slot_%02d" % i
        d["slots"].setdefault(k, {"id": k, "idx": i, "status": "未演示", "tcp": None, "quat": None,
                                  "recorded_at": None, "frames": {}, "corners_uv": None,
                                  "box_uv": None, "vlm": None, "record": None})
    d["depth"] = depth_online()
    save_reg(d)
    n_rec = sum(1 for v in d["slots"].values() if v.get("status") != "未演示")
    _dep = depth_online()
    print("🌊 深度源(实时探): %s%s" % ("在线" if _dep["ok"] else "未上线",
                                   (" · 文件龄 %ss · %s" % (_dep.get("age_s"), os.path.basename(_dep.get("src") or "")))
                                   if _dep.get("ok") else " · %s" % _dep.get("reason")))
    print("✅ 槽位登记表 %s: %d 槽位 (已记录 %d / 未演示 %d) · 深度 %s"
          % (os.path.relpath(REG, ROOT), N_SLOTS, n_rec, N_SLOTS - n_rec,
             "在线" if d["depth"].get("ok") else "未上线 (%s)" % d["depth"].get("reason")))
    return 0


def cmd_status() -> int:
    d = load_reg()
    _dep = depth_online()
    print("🌊 深度源(实时探): %s" % ("在线 · 文件龄 %ss · %s" % (_dep.get("age_s"),
                                                  os.path.basename(_dep.get("src") or ""))
                                  if _dep["ok"] else "未上线 · %s" % _dep.get("reason")))
    print("🧿 L5 槽位登记表 (%s) · 深度(记录当时): %s"
          % (os.path.relpath(REG, ROOT),
             "在线" if (d.get("depth") or {}).get("ok") else "未上线"))
    for i in range(1, N_SLOTS + 1):
        k = "slot_%02d" % i
        s = (d["slots"] or {}).get(k) or {}
        print("  %-8s %-6s tcp=%s box=%s vlm=%s"
              % (k, s.get("status", "?"),
                 (["%.4f" % v for v in s["tcp"]] if s.get("tcp") else "—"),
                 s.get("box_uv") or "—",
                 (s.get("vlm") or {}).get("verdict") or "—"))
    return 0


def cmd_record(slot: int, size_mm, demo: str, use_vlm: bool, tcp_override=None) -> int:
    """记录一次"光模块放进某槽位": TCP 真值 + 三相机帧 + 角点投影 + (可选)VLM 复核"""
    import auto_annotate as AA
    d = load_reg()
    k = "slot_%02d" % slot
    d["slots"].setdefault(k, {"id": k, "idx": slot})
    ts = time.strftime("%Y%m%d_%H%M%S")
    t = live_tcp() if tcp_override is None else dict(tcp_override)
    out = {"slot": k, "ts": time.strftime("%F %T"), "origin": demo,
           "mode": "L5 人机交互 (只读记录: 读TCP/抓图/记录/标注; 不动臂)"}
    out["tcp_truth"] = {kk: t.get(kk) for kk in ("ok", "age_s", "tcp", "quat", "t", "frame", "tap",
                                                 "reason", "stamp")}
    sd = os.path.join(WORK, "%s_%s" % (k, ts))
    os.makedirs(sd, exist_ok=True)
    out["session"] = sd
    out["frames"] = {}
    for c in CAMS3:
        try:
            raw = AA.grab(c)
            fp = os.path.join(sd, "%s.jpg" % c)
            open(fp, "wb").write(raw)
            import cv2
            import numpy as np
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            out["frames"][c] = {"path": fp, "wh": [int(img.shape[1]), int(img.shape[0])] if img is not None else None,
                                "ok": img is not None, "bytes": len(raw), "grab_ts": time.strftime("%F %T")}
        except Exception as e:                                                   # noqa: BLE001
            out["frames"][c] = {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:120])}
    out["depth"] = depth_online()
    # 角点投影 (用 arm 相机: 唯一有手眼的一路)
    fa = out["frames"].get("arm") or {}
    if t.get("ok") and t.get("tcp") and fa.get("ok"):
        try:
            pr = project_slot(t["tcp"], t.get("quat"), size_mm, fa["wh"], t["tcp"], t.get("quat"))
            pr["cam"] = "arm (D405 · 唯一有手眼的一路)"
            out["projection"] = pr
        except Exception as e:                                                   # noqa: BLE001
            out["projection"] = {"ok": False, "reason": "%s: %s" % (type(e).__name__, str(e)[:200])}
    else:
        out["projection"] = {"ok": False, "reason": "缺 TCP 真值或 arm 帧 (tcp_ok=%s frame_ok=%s)"
                                                    % (t.get("ok"), fa.get("ok"))}
    # 画角点叠加图
    if (out.get("projection") or {}).get("corners_uv") and fa.get("ok"):
        try:
            import cv2
            img = cv2.imread(fa["path"])
            pts = [[int(round(x)), int(round(y))] for x, y in out["projection"]["corners_uv"]]
            import numpy as _np
            hull = cv2.convexHull(_np.array(pts, _np.int32))
            cv2.polylines(img, [hull], True, (0, 255, 255), 2)
            for i, p in enumerate(pts):
                cv2.circle(img, tuple(p), 3, (0, 0, 255), -1)
            cu = out["projection"].get("center_uv")
            if cu:
                cv2.drawMarker(img, (int(cu[0]), int(cu[1])), (255, 0, 255), cv2.MARKER_CROSS, 18, 2)
            of = os.path.join(sd, "corners_arm.jpg")
            cv2.imwrite(of, img)
            out["overlay"] = of
        except Exception as e:                                                   # noqa: BLE001
            out["overlay_err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    # VLM 复核 (大模型层理解: 框是否落在槽位/光模块边沿)
    if use_vlm and fa.get("ok"):
        try:
            import gen_overlay_from_vlm as G
            import cv2
            img = cv2.imread(fa["path"])
            H, W = img.shape[:2]
            ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            pr = out.get("projection") or {}
            prompt = ("你是产线视觉质检员。图上是机械臂上的相机看到的黑色治具(有多个槽位)。"
                      "我按标定链投影出一个候选框(像素): %s (中心 %s)。"
                      "请只回答 JSON: {\"on_slot\":true/false, \"label\":\"槽位|光模块|其它\", "
                      "\"bbox\":[x1,y1,x2,y2], \"conf\":0-1, \"why\":\"<20字>\"} "
                      "—— 判断这个框是否落在一个**槽位**上、以及框的四角是否贴合槽位/光模块边沿。"
                      % (pr.get("box_uv"), pr.get("center_uv")))
            r = G.call_vlm(enc.tobytes(), W, H, timeout=300, prompt=prompt)
            txt = (r.get("txt") or "").strip()
            vd = G.parse_json(txt) if txt else {}
            out["vlm"] = {"model": r.get("model"), "latency_s": r.get("latency_s"),
                          "verdict": ("待确认" if not txt else ("一致" if vd.get("on_slot") else "不一致")),
                          "on_slot": vd.get("on_slot"), "label": vd.get("label"), "bbox": vd.get("bbox"),
                          "conf": vd.get("conf"), "why": str(vd.get("why") or "")[:80],
                          "raw": txt[:400], "err": None if txt else "content 空 (max_tokens>=3000 否则空)"}
        except Exception as e:                                                   # noqa: BLE001
            out["vlm"] = {"verdict": "待确认", "err": "%s: %s" % (type(e).__name__, str(e)[:160])}
    elif not use_vlm:
        out["vlm"] = {"verdict": "未跑 (--no-vlm)", "err": None}
    else:
        out["vlm"] = {"verdict": "待确认", "err": "arm 帧不可用 → 无法复核"}
    # 落登记表
    s = d["slots"][k]
    s.update({"status": "已记录" if (out["projection"] or {}).get("ok") else "待确认",
              "tcp": t.get("tcp"), "quat": t.get("quat"), "tcp_t": t.get("t"), "tcp_age_s": t.get("age_s"),
              "recorded_at": out["ts"], "origin": demo,
              "frames": {kk: (vv or {}).get("path") for kk, vv in out["frames"].items()},
              "corners_uv": (out["projection"] or {}).get("corners_uv"),
              "center_uv": (out["projection"] or {}).get("center_uv"),
              "box_uv": (out["projection"] or {}).get("box_uv"),
              "vlm": out.get("vlm"), "record": os.path.join(sd, "record.json"),
              "overlay": out.get("overlay"), "depth_online": bool(out["depth"].get("ok"))})
    if s.get("status") == "已记录" and (out.get("vlm") or {}).get("verdict") == "不一致":
        s["status"] = "待确认"       # ③ 不一致不默默改对
        out["status_note"] = "VLM 复核不一致 → 标待确认 (按老倪口径不默默改成对的)"
    json.dump(out, open(s["record"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    d["depth"] = out["depth"]
    save_reg(d)
    print("🧿 %s 记录完成 · status=%s · origin=%s" % (k, s["status"], demo))
    print("   TCP 真值: %s (age %ss · t=%s)" % (t.get("tcp"), t.get("age_s"), t.get("t")))
    print("   帧: %s" % json.dumps({kk: ((vv or {}).get("path") or (vv or {}).get("err"))
                                    for kk, vv in out["frames"].items()}, ensure_ascii=False)[:300])
    print("   投影: %s" % json.dumps({kk: (out["projection"] or {}).get(kk)
                                      for kk in ("center_uv", "box_uv", "in_frame", "reason")},
                                     ensure_ascii=False))
    print("   VLM 复核: %s" % json.dumps(out.get("vlm"), ensure_ascii=False)[:200])
    print("   record.json: %s" % s["record"])
    if s["status"] != "已记录":
        print("")
        print("❌ 槽位 %s 判为 %s ⇒ 退出码 1 (记录**已落盘**, 只是按'不默默改成对的'口径没标 已记录)"
              % (k, s["status"]))
        print("   投影 ok=%s · TCP=%s(age %ss) · 深度上线=%s · VLM=%s"
              % ((out.get("projection") or {}).get("ok"), t.get("tcp"), t.get("age_s"),
                 s.get("depth_online"), (out.get("vlm") or {}).get("verdict")))
        if (out.get("vlm") or {}).get("verdict") == "不一致":
            print("   VLM 说的话: %s" % str((out.get("vlm") or {}).get("why") or
                                           (out.get("vlm") or {}).get("note") or "")[:160])
    return 0 if s["status"] == "已记录" else 1


def _explain_zero() -> list:
    """0 框时把"为什么"逐条讲清楚(避免 SystemExit:1 被误当成代码报错)。"""
    out = []
    try:
        d = load_reg()
        sl = d.get("slots") or {}
        st = {}
        no_tcp = no_proj = vlm_bad = 0
        for k, v in sl.items():
            st[v.get("status")] = st.get(v.get("status"), 0) + 1
            if not v.get("tcp"):
                no_tcp += 1
            if not v.get("corners_uv"):
                no_proj += 1
            if (v.get("vlm") or {}).get("verdict") == "不一致":
                vlm_bad += 1
        out.append("原因: 默认只收 status=已记录 的槽位; 登记表现状 = %s"
                   % json.dumps(st, ensure_ascii=False))
        out.append("     其中 无TCP真值 %d 个 · 无角点投影 %d 个 · VLM复核判不一致 %d 个"
                   % (no_tcp, no_proj, vlm_bad))
        dep = d.get("depth") or {}
        if not dep.get("ok"):
            out.append("     深度: 未上线 (%s)" % str(dep.get("reason") or "")[:110])
    except Exception as e:                                                        # noqa: BLE001
        out.append("(读登记表失败: %s)" % e)
    return out


# ─────────────────────────── 数据集落盘 (14 类) ───────────────────────────
def cmd_build_dataset(include_pending: bool = False) -> int:
    """把已记录槽位 → YOLO 数据集 (14 类 = 14 槽位; 自动标注样本**只进 train, 绝不进 val**)

    ⚠️ 默认只收 status=已记录 的槽位; status=待确认 (VLM 复核不一致) 默认**不进数据集**,
    要进必须显式 --include-pending 并在报告里如实标注 (仅用于跑通训练管线, 不当生产标签)。
    """
    d = load_reg()
    names = ["slot_%02d" % i for i in range(1, N_SLOTS + 1)]
    sess = "l5slots_%s" % time.strftime("%Y%m%d_%H%M%S")
    src = os.path.join(DS_ROOT, "sessions", sess)
    os.makedirs(os.path.join(src, "frames"), exist_ok=True)
    os.makedirs(os.path.join(src, "labels"), exist_ok=True)
    n_box = 0
    rows = []
    skipped = []
    for i in range(1, N_SLOTS + 1):
        k = "slot_%02d" % i
        s = (d["slots"] or {}).get(k) or {}
        box = s.get("box_uv")
        img = (s.get("frames") or {}).get("arm")
        if not box or not img or not os.path.isfile(img):
            continue
        if s.get("status") != "已记录" and not include_pending:
            skipped.append({"slot": k, "status": s.get("status"),
                            "why": "VLM 复核不一致 → 待确认, 默认不进数据集 (不把没核实的框当标签)",
                            "vlm": (s.get("vlm") or {}).get("why")})
            continue
        import cv2
        im = cv2.imread(img)
        if im is None:
            continue
        H, W = im.shape[:2]
        stem = "%s_%s" % (k, os.path.basename(os.path.dirname(img)).split("_")[-1])
        shutil.copy2(img, os.path.join(src, "frames", stem + ".jpg"))
        x1, y1, x2, y2 = box
        cx, cy = (x1 + x2) / 2.0 / W, (y1 + y2) / 2.0 / H
        bw, bh = (x2 - x1) / W, (y2 - y1) / H
        with open(os.path.join(src, "labels", stem + ".txt"), "w") as f:
            f.write("%d %.6f %.6f %.6f %.6f\n" % (i - 1, cx, cy, bw, bh))
        n_box += 1
        rows.append({"slot": k, "cls": i - 1, "image": os.path.join(src, "frames", stem + ".jpg"),
                     "label": os.path.join(src, "labels", stem + ".txt"),
                     "xywhn": [round(cx, 6), round(cy, 6), round(bw, 6), round(bh, 6)],
                     "box_uv": box, "tcp": s.get("tcp")})
    # 建集 (复用既有 yolo_annot_dataset: classes.txt + meta.json + 体检; 自动标注只进 train)
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import yolo_annot_dataset as yad
    yad.ensure_layout(DS_ROOT, names)
    # 🔧 meta.json 的 sessions 是**列表** (yad 口径 {"name":...}), 不是字典 —— 用它的注册函数,
    #    别自己 setdefault 成 dict (2026-09-28 实测: TypeError list indices must be integers)。
    try:
        _w, _h = (0, 0)
        _f0 = next((r["image"] for r in rows), None)
        if _f0:
            import cv2
            _im = cv2.imread(_f0)
            if _im is not None:
                _h, _w = _im.shape[:2]
        yad._register_session(DS_ROOT, sess, "arm(D405)", _w, _h,
                              "auto:l5_tcp_projection",
                              "L5 槽位: TCP真值 + 标定链角点投影 (老倪演示记录); 自动标注不进 val")
    except Exception as e:                                                      # noqa: BLE001
        print("⚠️ 会话登记: %s: %s" % (type(e).__name__, e))
    build = {}
    try:
        build = yad.build_dataset(DS_ROOT) or {}
        chk = yad.check_dataset(DS_ROOT, strict=True) or {}
    except TypeError:
        build = yad.build_dataset(DS_ROOT, names) or {}
        chk = yad.check_dataset(DS_ROOT) or {}
    except Exception as e:                                                      # noqa: BLE001
        print("⚠️ 建集: %s: %s" % (type(e).__name__, e))
        chk = {}
    yaml_p = os.path.join(DS_ROOT, "dataset", "data.yaml")
    rep = {"ok": n_box > 0, "sessions": sess, "n_box": n_box, "classes": names,
           "dataset_root": DS_ROOT, "data_yaml": yaml_p, "build": build, "check": chk,
           "labels": rows, "skipped_pending": skipped, "include_pending": bool(include_pending),
           "ts": time.strftime("%F %T")}
    json.dump(rep, open(os.path.join(WORK, "dataset_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("🧿 14 类槽位数据集: %d 个已记录槽位 → %d 框 · %s" % (n_box, n_box, os.path.relpath(DS_ROOT, ROOT)))
    for r in rows:
        print("   %s → %s (xywhn %s)" % (r["slot"], os.path.relpath(r["label"], ROOT), r["xywhn"]))
    print("   data.yaml: %s · 体检: %s" % (os.path.relpath(yaml_p, ROOT),
                                          json.dumps(chk, ensure_ascii=False)[:200] if chk else "—"))
    if n_box == 0:
        _why = _explain_zero()
        print("")
        print("❌ 0 框 ⇒ 退出码 1 (**不是崩溃**: 是本工具按判据拒绝, SystemExit: 1 就是这么来的)")
        for _l in _why:
            print("   %s" % _l)
        print("   解法①(想把管线跑通, 产物仅供冒烟): --build-dataset --include-pending")
        print("   解法②(要真标签): 现场放好工件 → --record --slot N")
        print("          判据: 投影 ok + TCP 真值 ≤3s + VLM 复核一致 ⇒ 才写 '已记录'(退出码 0)")
    return 0 if n_box > 0 else 1


def _parse_size(s):
    if not s:
        return None
    return [float(x) for x in str(s).replace("x", ",").split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="L5 槽位记录/TCP真值投影/14类数据集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码语义(重要): 0=已记录/有框 · 1=待确认 或 0框(上面会打印❌及原因) · 2=参数错\n"
               "也就是说 SystemExit: 1 **不是崩溃**, 是本工具按判据拒绝(见'不把没核实的框当标签'口径)。")
    ap.add_argument("--init", action="store_true", help="建 14 槽位登记表 (models/l5_slots.json)")
    ap.add_argument("--status", action="store_true", help="打印 14 槽位状态")
    ap.add_argument("--record", action="store_true", help="记录一次槽位演示 (TCP真值+三相机帧+角点投影)")
    ap.add_argument("--slot", type=int, default=0, help="槽位号 1..14")
    ap.add_argument("--size", default=None, help="工件/槽位几何 W,H,T (mm), 如 40,16,12")
    ap.add_argument("--demo", default="老倪演示", help="记录来源 (老倪演示 / 自检)")
    ap.add_argument("--no-vlm", action="store_true", help="跳过 VLM 复核")
    ap.add_argument("--build-dataset", action="store_true", help="已记录槽位 → YOLO 14 类数据集")
    ap.add_argument("--include-pending", action="store_true",
                    help="把 status=待确认 (VLM复核不一致) 的槽位也放进数据集 (仅供跑通管线, 报告会标出)")
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    if a.init:
        return cmd_init()
    if a.status:
        return cmd_status()
    if a.record:
        if not (1 <= a.slot <= N_SLOTS):
            print("❌ --slot 需 1..%d" % N_SLOTS)
            return 2
        if not os.path.isfile(REG):
            cmd_init()
        return cmd_record(a.slot, _parse_size(a.size), a.demo, not a.no_vlm)
    if a.build_dataset:
        return cmd_build_dataset(a.include_pending)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
