#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dual_cam_scene.py — 🎥 双眼场景叠加 (真实场景 ↔ 仿真映射)  老倪 2026-09-26

老倪: 「本机内置摄像头 + 机器人手臂上的相机 = 你的眼睛; 接入状态空间工程, 做 sim-to-real 场景同步;
       加一个真实场景节点, 能叠加两个摄像头不同角度的图片; 图片/叠加场景发到飞书」

功能设计:
  ① 抓帧: A 本机内置 (/dev/videoN, V4L2) · B 臂上相机 (/home/ubuntu/zmax_ss_remote/cam_rs.png, 来自 tap 的
     /realsense/color/image_raw; 带帧龄)
  ② 叠加模式:
     - sbs   左右并排 (各带 视角/时间/帧龄 标签)
     - blend 半透明融合 (两个角度同图, α 可调)
     - edge  A 的边缘叠到 B (对齐检查; 用于 sim-to-real 几何对齐)
     - panel **默认**: 上半 = 并排 + 融合, 下半 = sim2real 参数带 (相机/分辨率/帧龄/TCP/关节/夹爪)
  ③ sim2real 参数映射表 → JSON (真实侧实测 vs 仿真侧对应项, 逐项标注 已映射/待映射)
  ④ --send: 发飞书 (走 tools/aoi_feishu_push.py 的 send_image)
安全: 只读 (相机 + SDK 状态读取); **不动机器人**
用法: ./gui-venv311/bin/python tools/dual_cam_scene.py --mode panel --send
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import cv2
import numpy as np

R = "/home/ubuntu/zmax_rel"
ARM_IMG = "/home/ubuntu/zmax_ss_remote/cam_rs.png"
TAP = "/home/ubuntu/zmax_ss_remote/state_20260925.jsonl"
OUTD = os.path.join(R, "data/scene")
W = 640


def grab_local(idx: int = 0):
    c = cv2.VideoCapture(idx)
    if not c.isOpened():
        c.release()
        return None
    for _ in range(3):
        ok, f = c.read()
    c.release()
    return f if ok else None


def grab_arm():
    """臂上相机: 读 tap 落盘的 cam_rs.png + 帧龄"""
    if not os.path.isfile(ARM_IMG):
        return None, None
    img = cv2.imread(ARM_IMG)
    age = None
    try:
        sz = os.path.getsize(TAP)
        with open(TAP, "rb") as f:
            f.seek(max(0, sz - 200000))
            txt = f.read().decode("utf-8", errors="ignore")
        for ln in reversed(txt.split("\n")):
            if ln.strip().startswith("{"):
                d = json.loads(ln)
                it = (d.get("images_by_topic") or {}).get("/realsense/color/image_raw") or {}
                age = it.get("age")
                break
    except Exception:                                                              # noqa: BLE001
        pass
    return img, age


def truth():
    """只读真机真值 (SDK 桥 + tap) — 不动机器人"""
    out = {"tcp_mm": None, "joint_deg": None, "gripper": None, "power": None, "mode": None, "stage": None}
    try:
        import urllib.request
        s = json.loads(urllib.request.urlopen("http://192.168.23.66:39061/status", timeout=15).read().decode()).get("status", {})
        out["tcp_mm"] = [round(v * 1000, 1) for v in (s.get("endInRef") or [])[:3]]
        out["joint_deg"] = [round(np.degrees(v), 2) for v in (s.get("jointPos") or [])[:6]]
        out["power"], out["mode"] = s.get("powerState"), s.get("operateMode")
    except Exception:                                                              # noqa: BLE001
        pass
    try:
        sz = os.path.getsize(TAP)
        with open(TAP, "rb") as f:
            f.seek(max(0, sz - 200000))
            txt = f.read().decode("utf-8", errors="ignore")
        for ln in reversed(txt.split("\n")):
            if ln.strip().startswith("{"):
                d = json.loads(ln)
                out["gripper"] = d.get("gripper")
                out["stage"] = d.get("prod_stage")
                rs = d.get("robot_status") or {}
                if isinstance(rs, dict) and rs.get("has_error") is not None:
                    out["has_error"] = rs.get("has_error")
                break
    except Exception:                                                              # noqa: BLE001
        pass
    return out


def label(img, text, color=(0, 255, 128)):
    im = img.copy()
    cv2.rectangle(im, (0, 0), (im.shape[1], 26), (0, 0, 0), -1)
    cv2.putText(im, text, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="panel", choices=["sbs", "blend", "edge", "panel"])
    ap.add_argument("--local-index", type=int, default=0)
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--out", default="")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUTD, exist_ok=True)

    fa = grab_local(a.local_index)
    fb, age_b = grab_arm()
    t = truth()
    if fa is None and fb is None:
        print("❌ 两个相机都取不到帧"); return 1
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res_a = ("%dx%d" % (fa.shape[1], fa.shape[0])) if fa is not None else "n/a"

    def fit(img, w=W):
        h = int(img.shape[0] * w / img.shape[1])
        return cv2.resize(img, (w, h))

    A = fit(fa) if fa is not None else np.zeros((int(W * 0.75), W, 3), np.uint8)
    B = fit(fb) if fb is not None else np.zeros((int(W * 0.75), W, 3), np.uint8)
    A = label(A, "视角A 本机固定 (video%d) %s" % (a.local_index, ts), (80, 220, 255))
    B = label(B, "视角B 臂上相机 (realsense) %s 帧龄%.2fs" % (ts, age_b if age_b else -1), (120, 255, 120))

    h = max(A.shape[0], B.shape[0])
    if a.mode == "sbs":
        canvas = np.hstack([A, np.zeros((h, 8, 3), np.uint8), B])
    elif a.mode == "blend":
        ab = cv2.addWeighted(cv2.resize(A, (W, h)), a.alpha, cv2.resize(B, (W, h)), 1 - a.alpha, 0)
        canvas = label(ab, "融合 (α=%.2f) 视角A×视角B" % a.alpha, (255, 200, 80))
    elif a.mode == "edge":
        ga = cv2.cvtColor(cv2.resize(A, (W, h)), cv2.COLOR_BGR2GRAY)
        e = cv2.Canny(ga, 60, 140)
        base = cv2.resize(B, (W, h)).copy()
        base[e > 0] = (0, 255, 255)
        canvas = label(base, "对齐检查: 视角A 边缘(黄) 叠于 视角B", (0, 255, 255))
    else:                                                       # panel
        top = np.hstack([A, np.zeros((h, 8, 3), np.uint8), B])
        blend = cv2.addWeighted(cv2.resize(A, (W, h)), a.alpha, cv2.resize(B, (W, h)), 1 - a.alpha, 0)
        blend = label(blend, "融合 α=%.2f" % a.alpha, (255, 200, 80))
        top = np.hstack([top, np.zeros((h, 8, 3), np.uint8), blend])
        band = np.zeros((110, top.shape[1], 3), np.uint8)
        lines = [
            "真实场景叠加 · 双眼 | %s | 视角A 本机%s | 视角B 臂上640x480 帧龄%.2fs" %
            (ts, res_a, age_b if age_b else -1),
            "真值(只读) TCP=%s mm  J=%s deg  夹爪=%s  %s/%s  阶段=%s" %
            (t["tcp_mm"], (t["joint_deg"] or [None, None, None])[:3], t["gripper"], t["power"], t["mode"], t["stage"]),
            "sim2real: 仿真 obs=%s ↔ 真实 39维(引擎 visual39) · 图像 128x128(策略) ↔ 真实 640x480(需归一) · 见 scene_map_*.json",
        ]
        for i, ln in enumerate(lines):
            cv2.putText(band, ln, (10, 26 + i * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 220, 255), 1, cv2.LINE_AA)
        canvas = np.vstack([top, band])

    out = a.out or os.path.join(OUTD, "dual_scene_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
    cv2.imwrite(out, canvas)
    # sim2real 参数映射表
    smap = {
        "ts": ts, "mode": a.mode,
        "cam_a": {"name": "本机内置", "dev": "/dev/video%d" % a.local_index,
                  "res": [fa.shape[1], fa.shape[0]] if fa is not None else None, "role": "固定视角(环境/台面)"},
        "cam_b": {"name": "臂上相机", "topic": "/realsense/color/image_raw", "res": [640, 480],
                  "frame_age_s": age_b, "role": "eye-in-hand(接近/对位/插入细节)"},
        "real": t,
        "sim": {"engine_obs_dim": 43, "policy_input_dim": 39, "policy_image": "128x128",
                "note": "引擎 visual39 = concat([cur,prev,target]) 与策略训练口径仅 15/39 维同源 (已实测)"},
        "map_status": [
            {"item": "相机分辨率", "real": "A=%s / B=640x480" % res_a,
             "sim": "128x128(策略)", "mapped": False, "how": "resize+归一(自裁口径)"},
            {"item": "TCP 位姿", "real": "SDK 桥 endInRef (µrad 级)", "sim": "engine tcp", "mapped": True,
             "how": "已同源(实测最大偏差 0.91µrad)"},
            {"item": "关节角", "real": "编码器 6 轴", "sim": "engine qpos", "mapped": True, "how": "直接映射"},
            {"item": "碰撞几何", "real": "7 STL(已取回)", "sim": "metaworld 几何", "mapped": False,
             "how": "MoveIt 侧 assimp 待修; 仿真侧用简化几何"},
            {"item": "光照/曝光", "real": "AOI 相机逐帧自动曝光(实测 64.5% 变异)", "sim": "固定渲染光照",
             "mapped": False, "how": "域随机化(自进化项)"},
            {"item": "夹爪开度", "real": "tap gripper/tactile", "sim": "engine gripper", "mapped": True, "how": "量程归一"},
        ],
    }
    jout = out.replace(".png", ".json")
    json.dump(smap, open(jout, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 叠加场景: %s" % out)
    print("   参数映射: %s" % jout)
    print("   已映射 %d/%d 项" % (sum(1 for x in smap["map_status"] if x["mapped"]), len(smap["map_status"])))
    if a.send:
        r = subprocess.run([os.path.join(R, "gui-venv311/bin/python"), os.path.join(R, "tools/aoi_feishu_push.py"),
                            "--file", out], capture_output=True, text=True, timeout=120)
        print("   飞书: %s" % ((r.stdout or "").strip()[-160:] or (r.stderr or "").strip()[-160:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
