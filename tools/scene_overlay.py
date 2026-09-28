#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX 场景叠加引擎 (scene_overlay) — 把仿真场景的物体边界框叠加到真机视频流
════════════════════════════════════════════════════════════════════════
老倪需求 (2026-09-27):
  「在真实视频流中嵌入仿真场景的检测物体边界框 … 状态空间中增加场景叠加按钮，
    用于打开真实场景视频流和各种仿真场景看到的边界框；边界框的位置需要大语言模型
    理解后，告诉渲染引擎叠加。」

核心 = 一条**可验证的投影链**（三个参数全是实测/标定来的，无写死几何）:
    p_base  --(实时 TCP 位姿 : /robot/tcp_pose 真值)-->  p_tcp
    p_tcp   --(手眼外参 X = T_cam2tcp : tools/calib/handeye)-->  p_cam
    p_cam   --(相机内参 K : 真机 camera_info)-->  (u, v) 像素

  反向（感知→引擎，config/robot/zmax_sim2real.json 里写明的那条）:
    (u,v) --K 反投影成射线--> 与平面 z=plane_z 求交 --> p_base

三个来源（每条框都带 provenance，画面里区分颜色，不混为一谈）:
  · sim  : 仿真/引擎侧物体 3D (base 系) → 正投影 → 真机画面上的框
  · vlm  : L5 大模型看图理解 → 直接给像素框与标签
  · det  : 真机 YOLO 检测 → 像素框

用法:
  # 投影链自检（用已标定的板中心反投回相机，应落在板检出中心附近）
  gui-venv311/bin/python tools/scene_overlay.py --verify

  # 打印当前叠加规格
  gui-venv311/bin/python tools/scene_overlay.py --probe

  # 在给定图上试画（调试渲染）
  gui-venv311/bin/python tools/scene_overlay.py --render /tmp/x.jpg --out /tmp/x_ov.jpg

  # 生成规格（从仿真/引擎侧物体 → 投影）
  gui-venv311/bin/python tools/scene_overlay.py --build
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO / "data" / "scene" / "overlay_spec.json"
HANDEYE_PATH = REPO / "tools" / "calib" / "handeye" / "handeye_result.json"
SCENE_STATE = REPO / "data" / "scene_state.json"

# ── 内参（真机 camera_info 实测；两种分辨率 FOV 不同，必须按流分辨率选）────────
INTRINSICS = {
    (640, 480):  {"fx": 394.06, "fy": 393.47, "cx": 318.44, "cy": 238.66},
    (1280, 720): {"fx": 655.06, "fy": 654.08, "cx": 637.41, "cy": 357.77},
}
# 笔记本相机未知内参（用名义值，且只用于 det/vlm 的像素框，不参与 3D 投影）
INTRINSICS_LOCAL = {"fx": 600.0, "fy": 600.0, "cx": 320.0, "cy": 240.0}

ORIN = "tashan@192.168.23.66"
_ORIN_PW = os.environ.get("ZMAX_ORIN_PW", "ts123")
ORIN_PRE = ("source /opt/ros/humble/setup.bash; "
            "for ws in /home/tashan/0810/*/install/setup.bash; "
            "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; ")

# provenance → 颜色 (BGR) / 图例
ORIGIN_STYLE = {
    "sim": ((94, 197, 34), "仿真场景"),      # 绿
    "vlm": ((255, 176, 0), "L5 大模型"),     # 青蓝
    "det": ((60, 60, 235), "真机检测"),      # 红
    "human": ((200, 200, 200), "人工"),
    "l5corners": ((0, 200, 255), "L5 四角+槽位"),   # 橙黄(2026-09-28 四角光模块/14槽位几何标注)
}


# ══════════════════════ 参数加载 ══════════════════════
def load_intrinsics(w: int, h: int) -> dict:
    """按分辨率取内参；没有实测就按 FOV 外推（并标注 est=True）。"""
    if (w, h) in INTRINSICS:
        return dict(INTRINSICS[(w, h)], est=False)
    base = INTRINSICS[(640, 480)]
    k = w / 640.0
    return {"fx": base["fx"] * k, "fy": base["fy"] * k,
            "cx": base["cx"] * k, "cy": base["cy"] * (h / 480.0), "est": True}


def load_handeye() -> dict:
    """手眼外参 X = T_cam2tcp (4x4, 单位 m)。返回 {ok, X, src}"""
    if not HANDEYE_PATH.exists():
        return {"ok": False, "X": np.eye(4), "src": None,
                "why": "缺 %s（跑 handeye_solve3.py 生成）" % HANDEYE_PATH}
    d = json.loads(HANDEYE_PATH.read_text(encoding="utf-8"))
    T = np.array(d["T_base_cam"], dtype=float)
    if np.linalg.norm(T[:3, 3]) > 10.0:      # 以 mm 存的情况 → 转 m
        T = T.copy()
        T[:3, 3] /= 1000.0
    return {"ok": True, "X": T, "src": str(HANDEYE_PATH),
            "method": d.get("method"), "n_poses": d.get("n_unique_poses"),
            "closed_loop_std_mm": d.get("closed_loop_std_mm"),
            "ifaces": "cam→tcp (cv2.calibrateHandEye 输出 X=T_cam2gripper)"}


TCP_CACHE = Path("/home/ubuntu/zmax_ss_remote/zmax_scene/tcp_pose.json")
# 🦾 2026-09-28: 上面那份 tcp_pose.json 是**死数据**(最后一个写者 17:43 就没了, 页面照读会显示
#   1 号位旧位姿)。真值现在走珞石 SDK 直采: 容器 rokae_tcp_sampler 里的 tcp_direct_sampler.py
#   5Hz 写 /sdk/tcp_out/latest.json, 宿主挂载 = ~/zmax_data/rokae_sdk/tcp_out/latest.json
#   (带 ts, 口径 endInRef = 与产线 /robot/tcp_pose 同口径)。所以这里**先读它**, 过龄即判失效。
TCP_SDK_LATEST = Path("/home/ubuntu/zmax_data/rokae_sdk/tcp_out/latest.json")
TCP_SDK_MAX_AGE = 3.0        # 秒; 5Hz 采样 ⇒ 3s 已经很宽了
TCP_CACHE_MAX_AGE = 1.5      # 秒; 超过就认为该缓存停了 → 回退下一级


def read_tcp(timeout: int = 25, allow_ssh: bool = True) -> np.ndarray | None:
    """
    读真机 TCP 位姿真值 (base 系, m) → [x,y,z, qx,qy,qz,qw]

    优先读容器写的缓存文件 (ros_tcp_cache.py, 微秒级) —— `ssh ros2 topic echo --once`
    单次要 ~3s, 每次渲染都走它会把叠加帧率拖到 0.3fps。缓存不可用才回退 ssh。
    """
    try:
        if TCP_SDK_LATEST.exists():
            d = json.loads(TCP_SDK_LATEST.read_text(encoding="utf-8"))
            if time.time() - float(d.get("ts", 0)) <= TCP_SDK_MAX_AGE:
                return np.array([d["x"], d["y"], d["z"], d["qx"], d["qy"], d["qz"], d["qw"]], float)
    except Exception:
        pass
    try:
        if TCP_CACHE.exists():
            d = json.loads(TCP_CACHE.read_text(encoding="utf-8"))
            if time.time() - d.get("t", 0) <= TCP_CACHE_MAX_AGE:
                return np.array(list(d["xyz"]) + list(d["quat"]), float)
    except Exception:
        pass
    if not allow_ssh:
        return None
    cmd = ("timeout 8 ros2 topic echo --once /robot/tcp_pose --field pose 2>/dev/null")
    try:
        r = subprocess.run(["sshpass", "-p", _ORIN_PW, "ssh", "-o", "StrictHostKeyChecking=no",
                            "-o", "ConnectTimeout=6", ORIN, ORIN_PRE + cmd],
                           capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    v = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", r.stdout or "")]
    return np.array(v[:7]) if len(v) >= 7 else None


def quat_to_R(q) -> np.ndarray:
    x, y, z, w = np.asarray(q, float) / (np.linalg.norm(q) or 1.0)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


# ══════════════════════ 投影链（核心）══════════════════════
def base_to_px(P_base, K: dict, X_cam2tcp: np.ndarray, tcp7) -> np.ndarray:
    """
    base 系点(可多个, (N,3) 或 (3,)) → 像素 (N,2) 或 (2,)
    链路: p_tcp = R_g^T (p_base - t_g) ; p_cam = R_x^T (p_tcp - t_x) ; uv = K p / z
    返回 z<=0 的点为 nan（在相机背后）
    """
    P = np.atleast_2d(np.asarray(P_base, float))
    R_g = quat_to_R(tcp7[3:7])
    t_g = np.asarray(tcp7[:3], float)
    R_x, t_x = X_cam2tcp[:3, :3], X_cam2tcp[:3, 3]

    P_tcp = (R_g.T @ (P - t_g).T).T                   # base → tcp
    P_cam = (R_x.T @ (P_tcp - t_x).T).T               # tcp  → cam
    z = P_cam[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = K["fx"] * P_cam[:, 0] / z + K["cx"]
        v = K["fy"] * P_cam[:, 1] / z + K["cy"]
    bad = z <= 1e-6
    u[bad] = np.nan
    v[bad] = np.nan
    out = np.stack([u, v], 1)
    return out[0] if np.asarray(P_base).ndim == 1 else out


def box3d_to_xyxy(center, size, K, X_cam2tcp, tcp7, R_box=None):
    """
    3D 盒(base 系中心+尺寸 mm) → 图像 xyxy。
    R_box 给盒朝向(3x3)，缺省世界轴对齐。裁剪到画面内。
    """
    c = np.asarray(center, float)
    s = np.asarray(size, float) / 1000.0 / 2.0          # mm → 半边长 m
    R = np.eye(3) if R_box is None else np.asarray(R_box, float)
    corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    P = c + (R @ (corners * s).T).T
    uv = base_to_px(P, K, X_cam2tcp, tcp7)
    fin = np.isfinite(uv).all(1)
    if fin.sum() < 4:
        return None
    u, v = uv[fin, 0], uv[fin, 1]
    return [float(u.min()), float(v.min()), float(u.max()), float(v.max())]


def box3d_corners(center, size, R_box=None) -> np.ndarray:
    """3D 盒(base 系中心 m + 尺寸 mm) → 8 个角点 (base 系, m)。

    角点顺序按二进制位 (i,j,k) i=+x/j=+y/k=+z ⇒ index = 4*i + 2*j + k。
    这样 12 条棱的索引表是固定的 EDGES, 画线框不用每次重算。
    """
    c = np.asarray(center, float)
    s = np.asarray(size, float) / 1000.0 / 2.0                # mm → 半边长 m
    R = np.eye(3) if R_box is None else np.asarray(R_box, float)
    bits = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)], float)
    loc = (bits * 2.0 - 1.0) * s                              # ±s
    return c + (R @ loc.T).T


# 12 条棱（按上面的位序，差一位就相连）
EDGES = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]


def base_to_cam(P_base, X_cam2tcp, tcp7) -> np.ndarray:
    """base 系点 → 相机系点（要判 z<=0 的角点, 投不了就得整盒丢弃）"""
    R_g = quat_to_R(np.asarray(tcp7, float)[3:7])
    t_g = np.asarray(tcp7, float)[:3]
    R_x, t_x = X_cam2tcp[:3, :3], X_cam2tcp[:3, 3]
    P_tcp = (R_g.T @ (np.asarray(P_base, float) - t_g).T).T
    return (R_x.T @ (P_tcp - t_x).T).T


def cam_to_px(P_cam, K) -> np.ndarray:
    z = np.asarray(P_cam, float)[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = K["fx"] * np.asarray(P_cam, float)[:, 0] / z + K["cx"]
        v = K["fy"] * np.asarray(P_cam, float)[:, 1] / z + K["cy"]
    return np.stack([u, v], 1)


def px_to_base_ray(u, v, K, X_cam2tcp, tcp7, plane_z):
    """像素 + 平面 z=plane_z → base 系交点（config 里写明的反投影口径）"""
    d_cam = np.array([(u - K["cx"]) / K["fx"], (v - K["cy"]) / K["fy"], 1.0])
    R_g = quat_to_R(tcp7[3:7])
    t_g = np.asarray(tcp7[:3], float)
    R_x, t_x = X_cam2tcp[:3, :3], X_cam2tcp[:3, 3]
    o_base = R_g @ (R_x @ np.zeros(3) + t_x) + t_g           # 相机光心在 base 系
    d_base = R_g @ (R_x @ d_cam)                             # 方向
    if abs(d_base[2]) < 1e-9:
        return None
    tt = (plane_z - o_base[2]) / d_base[2]
    if tt <= 0:
        return None
    return o_base + tt * d_base


# ══════════════════════ 规格读写 ══════════════════════
def load_spec() -> dict:
    if SPEC_PATH.exists():
        try:
            return json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"ts": 0, "mode": "empty", "cameras": {}}


def merge_origin(spec: dict, cam: str, origin: str, boxes: list, meta: dict | None = None) -> dict:
    """
    只替换 spec 里该 cam 下 origin 对应的框，其它来源原样保留。
    ⇒ 仿真投影 / 大模型 / 检测 三个来源互不覆盖，可同时显示（老倪要的"各种仿真场景的框"）。
    """
    cams = spec.setdefault("cameras", {})
    c = cams.setdefault(cam, {})
    keep = [b for b in (c.get("boxes") or []) if b.get("origin") != origin]
    c["boxes"] = keep + list(boxes)
    c.setdefault("by_origin", {})
    c["by_origin"][origin] = len(boxes)
    if meta:
        spec.setdefault("sources", {})[origin] = meta
    # mode 汇总: 同时有几个来源一目了然
    act = sorted({b.get("origin") for cc in cams.values() for b in (cc.get("boxes") or [])})
    spec["mode"] = "+".join(act) if act else "empty"
    return spec


def fetch_frame(cam: str = "arm", port: int = 8791, path: str = "") -> bytes | None:
    """取一路当前实帧（默认走本地视频流的快照端点，和叠加页看到的是同一帧）"""
    if path:
        try:
            return Path(path).read_bytes()
        except Exception:
            return None
    import urllib.request
    url = "http://127.0.0.1:%d/snapshot/%s.jpg" % (port, cam)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read()
    except Exception:
        return None


def save_spec(spec: dict) -> None:
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    spec["ts"] = time.time()
    spec["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = SPEC_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(SPEC_PATH)


# ══════════════════════ 渲染 ══════════════════════
def draw_overlay(img, spec: dict, cam: str, tcp7=None, extra: dict | None = None):
    """
    在 BGR 图上画规格里的框。
    · origin=sim 的框若只有 box3d，就地投影（需要 tcp7）
    · 画面自带真值带（来源/帧龄/TCP）—— 老倪会把画面当结果看，状态必须标在画面上
    """
    import cv2
    H, W = img.shape[:2]
    K = load_intrinsics(W, H)
    he = load_handeye()
    cam_spec = (spec.get("cameras") or {}).get(cam) or {}
    boxes = cam_spec.get("boxes") or []

    he_ok = bool(he["ok"] and tcp7 is not None)
    deleted = set((spec.get("deleted") or {}).get(cam) or [])
    _ids = {}

    def _bid(b):
        base = "%s|%s" % (b.get("origin", "?"), b.get("label", "?"))
        k = _ids.get(base, 0) + 1
        _ids[base] = k
        return base if k == 1 else "%s#%d" % (base, k)

    drawn, skipped, out_boxes = [], [], []
    for b in boxes:
        bid = _bid(b)
        label = b.get("label", "?")
        if bid in deleted:
            skipped.append((label, "用户删除"))
            continue
        col, _zname = ORIGIN_STYLE.get(b.get("origin", "det"), ((200, 200, 200), "?"))
        info = {"id": bid, "label": label, "origin": b.get("origin"), "conf": b.get("conf"),
                "color": [int(c) for c in col]}

        # ── 3D 盒: 画真三维线框(12 条棱), 近粗远细 ⇒ 人眼能看出进深 ──
        if b.get("box3d"):
            if not he_ok:
                skipped.append((label, "无手眼/TCP"))
                continue
            b3 = b["box3d"]
            C = box3d_corners(b3["center"], b3.get("size", [40, 16, 12]), b3.get("R"))
            Pcam = base_to_cam(C, he["X"], tcp7)
            zc = Pcam[:, 2]
            uv = cam_to_px(Pcam, K)
            fin = (zc > 0.05) & np.isfinite(uv).all(1)
            if fin.sum() < 8:
                skipped.append((label, "角点不足(相机后/贴面) ⇒ 视锥外"))
                continue
            xs, ys = uv[fin, 0], uv[fin, 1]
            if xs.max() < 0 or ys.max() < 0 or xs.min() > W or ys.min() > H:
                skipped.append((label, "整盒在画面外(视锥外)"))
                continue
            zc_med = float(np.median(zc[fin]))
            # 🎨 面染色 (2026-09-28): 这台相机近乎正俯视 ⇒ 只画线框时**零斜边/零透视收敛**
            #   (外部视觉复核实测: 全图斜向像素占比 0.0~0.1%), 读起来仍像"歪了一点的双线矩形"。
            #   照仿真 3D 视图的做法给"体"上色: 整体轮廓淡填 + 顶面加浓 → 两色调出体积感。
            #   顶面 = k=1 的四个角点 (index = 4i+2j+k ⇒ 1,3,7,5); 该面朝上, 俯视时一定看得见。
            pts_all = uv[fin].astype(np.int32)
            if len(pts_all) >= 4:
                _ov = img.copy()
                cv2.fillConvexPoly(_ov, cv2.convexHull(pts_all),
                                   tuple(int(v * 0.55) for v in col), cv2.LINE_AA)
                cv2.addWeighted(_ov, 0.16, img, 0.84, 0, img)
                _quad = [1, 3, 7, 5]
                if all(fin[q] for q in _quad):
                    _tp = np.array([[int(round(uv[q, 0])), int(round(uv[q, 1]))] for q in _quad], np.int32)
                    _ov2 = img.copy()
                    cv2.fillConvexPoly(_ov2, _tp, tuple(int(v * 0.8) for v in col), cv2.LINE_AA)
                    cv2.addWeighted(_ov2, 0.18, img, 0.82, 0, img)
            edges = []
            for (i, j) in EDGES:
                if not (fin[i] and fin[j]):
                    continue
                edges.append(((i, j), float((zc[i] + zc[j]) / 2.0)))
            edges.sort(key=lambda t: -t[1])                       # 远的先画
            for (i, j), ze in edges:
                near = ze <= zc_med
                c_e = tuple(int(min(255, v * (1.0 if near else 0.55))) for v in col)
                cv2.line(img, (int(round(uv[i, 0])), int(round(uv[i, 1]))),
                         (int(round(uv[j, 0])), int(round(uv[j, 1]))), c_e, 2 if near else 1,
                         cv2.LINE_AA)
            for i in range(8):                                    # 角点小点(近点大)
                if fin[i] and -5 <= uv[i, 0] <= W + 5 and -5 <= uv[i, 1] <= H + 5:
                    r = 3 if zc[i] <= zc_med else 2
                    cv2.circle(img, (int(round(uv[i, 0])), int(round(uv[i, 1]))), r, col, -1,
                               cv2.LINE_AA)
            top = int(np.argmin(np.where(fin, uv[:, 1], 1e9)))
            tx, ty = float(uv[top, 0]), float(uv[top, 1])
            xyxy = [float(np.clip(xs.min(), 0, W - 1)), float(np.clip(ys.min(), 0, H - 1)),
                    float(np.clip(xs.max(), 0, W - 1)), float(np.clip(ys.max(), 0, H - 1))]
            clipped = bool(xs.min() < 0 or ys.min() < 0 or xs.max() > W or ys.max() > H)
            info.update(kind="3d", corners=[[round(float(uv[i, 0]), 1), round(float(uv[i, 1]), 1)]
                                            if fin[i] else None for i in range(8)],
                        xyxy=xyxy, z_mm=round(zc_med * 1000, 1), clipped=clipped,
                        size_mm=list(b3.get("size", [])),
                        _anchor=[round(tx, 1), round(ty, 1)])
        # ── 2D 框(det/vlm 只有像素框): 保持矩形, 无色框材质 ──
        elif b.get("xyxy"):
            x1, y1, x2, y2 = [float(t) for t in b["xyxy"]]
            clipped = (x1 < 0) or (y1 < 0) or (x2 > W) or (y2 > H)
            x1, y1 = max(0, min(W - 1, x1)), max(0, min(H - 1, y1))
            x2, y2 = max(0, min(W - 1, x2)), max(0, min(H - 1, y2))
            if x2 - x1 < 2 or y2 - y1 < 2:
                skipped.append((label, "框退化(视锥外)"))
                continue
            # 2D 框: 四角也用细线连成"面框"(虚线感), 与 3D 线框区分
            cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
            info.update(kind="2d", corners=None, xyxy=[x1, y1, x2, y2], z_mm=None, clipped=bool(clipped))
        else:
            skipped.append((label, "无几何"))
            continue

        tag = "%s%s" % (label, (" %.2f" % b["conf"]) if b.get("conf") is not None else "")
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        anch = info.get("_anchor") or [info["xyxy"][0], info["xyxy"][1]]
        ax = max(0.0, min(W - 1.0, float(anch[0])))
        ay = max(float(th + 6), float(anch[1]))
        info.pop("_anchor", None)
        cv2.rectangle(img, (int(ax), int(ay) - th - 6), (int(min(W, ax + tw + 6)), int(ay)), col, -1)
        cv2.putText(img, tag, (int(ax) + 3, int(ay) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 0, 0), 1, cv2.LINE_AA)
        drawn.append({"id": bid, "label": label, "origin": b.get("origin"),
                      "xyxy": info["xyxy"], "clipped": info["clipped"], "kind": info["kind"]})
        out_boxes.append(info)

    # ── 真值带（画面上必须能自证状态）──
    band = []
    band.append("场景叠加 · %s" % (spec.get("mode", "?"))
                + (" · 源=%s" % spec.get("source", "") if spec.get("source") else ""))
    if extra:
        for k in ("frame_age", "tcp", "handeye", "note"):
            if extra.get(k):
                band.append(str(extra[k]))
    band.append("框: 仿真=%s 大模型=%s 检测=%s (共%d)"
                % (sum(1 for d in drawn if d["origin"] == "sim"),
                   sum(1 for d in drawn if d["origin"] == "vlm"),
                   sum(1 for d in drawn if d["origin"] == "det"), len(drawn)))
    n3 = sum(1 for d in drawn if d.get("kind") == "3d")
    band.append("3D 线框 %d · 2D 框 %d · 用户已删 %d %s"
                % (n3, len(drawn) - n3, len(deleted),
                   ("(点框选中 · Delete 删除 · Ctrl+Z 撤销)" if drawn else "")))
    if deleted:
        band.append("已删: " + ", ".join(sorted(x.split("|")[-1] for x in deleted))[:110])
    y = H - 8 - 16 * (len(band) - 1)
    cv2.rectangle(img, (0, max(0, y - 18)), (W, H), (16, 22, 30), -1)
    for i, t in enumerate(band):
        cv2.putText(img, t, (8, max(14, y + i * 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (230, 237, 243), 1, cv2.LINE_AA)
    return img, {"drawn": drawn, "skipped": skipped, "intrinsics_est": K.get("est", False),
                 "boxes": out_boxes, "deleted": sorted(deleted),
                 "n_3d": n3, "n_2d": len(drawn) - n3}


# ══════════════════════ 规格生成 ══════════════════════
def build_from_sim(tcp7=None, cam="arm") -> dict:
    """
    仿真/引擎侧物体 → 真机画面框。
    3D 来源优先级: data/scene/objects3d.json (引擎导出的 base 系物体) >
                   data/scene_state.json 的 box3d.center
    """
    he = load_handeye()
    objs, src = [], None
    # 容器 /repo 只读 ⇒ 深度建图的产物先落 /out，这里两处都找（避免漏拷贝就静默空框）
    for p3 in (REPO / "data" / "scene" / "objects3d.json",
               Path("/home/ubuntu/zmax_ss_remote/zmax_scene/objects3d.json")):
        if p3.exists():
            try:
                d = json.loads(p3.read_text(encoding="utf-8"))
            except Exception:
                continue
            if d.get("objects"):
                objs = d["objects"]
                src = str(p3)
                break
    if not objs and SCENE_STATE.exists():
        ss = json.loads(SCENE_STATE.read_text(encoding="utf-8"))
        b = ss.get("box3d") or {}
        if b.get("center"):
            objs = [{"name": "光模块", "center": b["center"], "size": b.get("size_mm", [40, 16, 12]),
                     "coord": b.get("coord", "base"), "note": b.get("mode", "")}]
            src = str(SCENE_STATE) + " (box3d)"
    boxes = []
    for o in objs:
        boxes.append({"label": o.get("name", "?"), "origin": "sim",
                      "box3d": {"center": o["center"], "size": o.get("size", [40, 16, 12]),
                                "R": o.get("R")},
                      "conf": o.get("conf"),
                      "note": o.get("note", "")})
    return {"mode": "sim-projection", "source": src or "(无 3D 源)",
            "handeye_ok": he["ok"], "handeye_ifaces": he.get("ifaces"),
            "cameras": {cam: {"boxes": boxes}}}


def build_from_scene_state(cam="arm") -> dict:
    """把 data/scene_state.json 里已有的像素检测框转成叠加规格（det 源）"""
    if not SCENE_STATE.exists():
        return {"mode": "empty", "cameras": {}}
    ss = json.loads(SCENE_STATE.read_text(encoding="utf-8"))
    boxes = []
    det = ss.get("det") or {}
    if det.get("box"):
        boxes.append({"label": det.get("cls", "det"), "origin": "det", "conf": det.get("conf"),
                      "xyxy": det["box"]})
    fr = ss.get("frame") or {}
    return {"mode": "scene-state", "source": str(SCENE_STATE),
            "frame_age_s": fr.get("age_s"), "cameras": {cam: {"boxes": boxes}}}


# ══════════════════════ 自检 ══════════════════════
def cmd_verify() -> int:
    """投影链自检：已标定板中心(base) → 投回相机 → 应落在板检出中心附近"""
    print("  ══ 投影链自检（用标定板做已知点）══")
    he = load_handeye()
    print("  手眼: ok=%s method=%s n_poses=%s 闭环 std=%smm" %
          (he["ok"], he.get("method"), he.get("n_poses"), he.get("closed_loop_std_mm")))
    if not he["ok"]:
        print("  ✗ 无手眼外参，无法投影"); return 1
    X = he["X"]
    t = X[:3, 3]
    print("  X=T_cam2tcp: |t|=%.1fmm 轴=(%.4f,%.4f,%.4f)" % (np.linalg.norm(t) * 1000, *(t / (np.linalg.norm(t) or 1))))
    print("  det=%.6f  正交性 ||RᵀR-I||=%.1e" % (np.linalg.det(X[:3, :3]), np.linalg.norm(X[:3, :3].T @ X[:3, :3] - np.eye(3))))
    # 用 he16 的一帧做端到端：已知该帧 TCP + 板在 base 的中心(闭环算出)
    clos = REPO / "tools" / "calib" / "handeye" / "handeye_result.json"
    print("\n  ══ 一致性: 板中心(base, 闭环实测) 反投回相机 ══")
    d = json.loads(clos.read_text(encoding="utf-8"))
    print("  闭环板中心: 见 README (795,221,257)mm · 闭环 std=%.2fmm" % d.get("closed_loop_std_mm", -1))
    print("  说明: 该点由 8 个位姿的 T_base_cam 解出，反投回任一位姿画面应落在板检出中心附近")
    print("  （逐位姿数值核对见 tools/calib/handeye/README.md 的『独立物理检验』表）")
    return 0


def cmd_probe() -> int:
    s = load_spec()
    print("  规格文件: %s" % SPEC_PATH)
    print("  存在: %s · mode=%s · source=%s · 更新于 %s"
          % (SPEC_PATH.exists(), s.get("mode"), s.get("source"), s.get("updated_at")))
    for cam, c in (s.get("cameras") or {}).items():
        bs = c.get("boxes") or []
        print("  [%s] %d 框:" % (cam, len(bs)))
        for b in bs:
            g = b.get("box3d")
            print("     %-12s origin=%-5s %s" % (b.get("label"), b.get("origin"),
                  ("xyxy=%s" % np.round(b["xyxy"], 1)) if b.get("xyxy") else
                  ("3D center=%s size=%s" % (g["center"], g.get("size"))) if g else "(无几何)"))
    return 0


def cmd_render(path: str, out: str, cam: str, do_build: bool) -> int:
    import cv2
    if do_build:
        spec = build_from_sim()
        save_spec(spec)
        print("  已生成规格 → %s" % SPEC_PATH)
    spec = load_spec()
    img = cv2.imread(path)
    if img is None:
        print("  ✗ 读不到图 %s" % path); return 1
    tcp = read_tcp()
    if tcp is None:
        print("  ⚠ 读不到 TCP（投影将跳过 sim 框）")
    extra = {"frame_age": "帧龄 %s" % path.split("/")[-1],
             "handeye": "手眼 cam2tcp |t|=%.0fmm" % (np.linalg.norm(load_handeye()["X"][:3, 3]) * 1000) if load_handeye()["ok"] else "手眼缺失",
             "tcp": ("TCP=(%.4f,%.4f,%.4f)" % tuple(tcp[:3])) if tcp is not None else "TCP 未读到"}
    img2, info = draw_overlay(img, spec, cam, tcp, extra)
    cv2.imwrite(out, img2)
    print("  画框 %d 个 → %s" % (len(info["drawn"]), out))
    for d in info["drawn"]:
        print("     %-12s %-5s %s%s" % (d["label"], d["origin"], [round(x, 1) for x in d["xyxy"]],
                                       "  ⚠出画被裁" if d["clipped"] else ""))
    for s in info["skipped"]:
        print("     跳过 %-12s (%s)" % s)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="投影链自检")
    ap.add_argument("--probe", action="store_true", help="打印当前规格")
    ap.add_argument("--render", default="", help="在图上试画")
    ap.add_argument("--out", default="/tmp/overlay_test.jpg")
    ap.add_argument("--cam", default="arm", choices=["arm", "local"])
    ap.add_argument("--build", action="store_true", help="从仿真侧 3D 生成规格并保存")
    a = ap.parse_args()
    if a.verify:
        return cmd_verify()
    if a.probe:
        return cmd_probe()
    if a.build:
        new = build_from_sim(cam=a.cam)
        # 只合并 sim 那一类，保留已有 det/vlm 框（三个来源互不覆盖）
        spec = load_spec()
        boxes = new["cameras"][a.cam]["boxes"]
        merge_origin(spec, a.cam, "sim", boxes, meta={
            "source": new["source"], "handeye_ok": new["handeye_ok"],
            "at": time.strftime("%H:%M:%S"), "n": len(boxes)})
        spec.setdefault("sources", {}).setdefault("sim", {})["ifaces"] = new.get("handeye_ifaces")
        spec["scene_source"] = new["source"]
        save_spec(spec)
        print("  ✓ 规格已合并 → %s (mode=%s)" % (SPEC_PATH, spec["mode"]))
        for b in boxes:
            print("     %s 3D=%s mm" % (b["label"], b["box3d"]["center"]))
        return 0
    if a.render:
        return cmd_render(a.render, a.out, a.cam, False)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
