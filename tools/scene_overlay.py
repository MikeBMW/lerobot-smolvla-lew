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
    "meas": ((230, 0, 230), "实测长方体"),          # 紫(2026-09-28 深度实测的 3D 长方体: 光模块)
    "plan": ((255, 255, 255), "规划路径"),          # 亮白(2026-09-28 规划的末端位姿轨迹: 路点+连�)
    "trace": ((0, 255, 255), "实测轨迹"),           # 黄(2026-09-29 真机 TCP 实测轨迹: 人拖/控制台走出来的真实路径)
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
# 🎨 面染色总开关 (A/B 取证用): 本机近乎正俯视 ⇒ 只画线框读不出体积, 见 draw_overlay 里说明。
#    留这个开关是为了**同帧 A/B**: 同一输入帧渲染两遍(开/关)做差, 才能证明染色真的落笔
#    (跨帧比对会被机械臂运动淹没; 2026-09-28 外部复核就吃过这个亏)。
_FILL_ON = os.environ.get("ZMAX_FILL", "1") != "0"
FILL_ALPHA = float(os.environ.get("ZMAX_FILL_ALPHA", "0.22"))    # 整体轮廓
FILL_TOP_ALPHA = float(os.environ.get("ZMAX_FILL_TOP_ALPHA", "0.32"))  # 顶面加浓(俯视必见 ⇒ 体积感来源)

# ── 管道渲染 (2026-09-29): 把 origin=plan/trace 的 path3d 路点画成"能读出三维"的立体管道 ──
#   老倪口径: 细折线看不出"管子/进深", 必须 ①线宽随投影深度(近粗远细) ②每隔几站画截面环
#   ③明暗双色(管体主色+高光/暗边)勾出圆柱感 ④端点圆帽。几何仍走既有的 K+手眼投影
#   (base_to_cam/cam_to_px), 这里只做 2D 成像 —— 不碰标定, 不改 spec 字段语义。
TUBE_W_MIN = float(os.environ.get("ZMAX_TUBE_WMIN", "3"))            # 远端管径(px)
TUBE_W_MAX = float(os.environ.get("ZMAX_TUBE_WMAX", "14"))           # 近端管径(px)
TUBE_RING_EVERY = int(os.environ.get("ZMAX_TUBE_RING_EVERY", "10"))  # 每隔几个路点画一个截面环
TUBE_SHADE = 0.55                                                    # 管体主色 = origin 色 × 该系数(暗面)
TUBE_DARK = 0.22                                                     # 暗边/轮廓
TUBE_EDGE_PX = int(os.environ.get("ZMAX_TUBE_EDGE_PX", "2"))         # 暗边描边粗细
# 🧭 前进意图装饰(2026-09-29): 起点实心点 + 末端箭头 + 沿程渐变。纯渲染开关(env 可关, 便于同帧 A/B 取证)
INTENT_ON = os.environ.get("ZMAX_INTENT", "1") != "0"
INTENT_START_DOT = os.environ.get("ZMAX_INTENT_START_DOT", "1") != "0"
INTENT_ARROW = os.environ.get("ZMAX_INTENT_ARROW", "1") != "0"


def _cscale(col, k):
    """origin 色 × 明暗系数 → 合法 BGR 三元组"""
    return tuple(int(max(0, min(255, round(float(c) * k)))) for c in col)


def _unit2(dx, dy):
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-9 else (0.0, 0.0)


def tube_widths(zc, wmin, wmax):
    """相机系深度(米) → 每点管径(px)。近(z 小)粗、远(z 大)细。

    以**本段路径自身**的深度跨度归一化; 跨度极小(近乎等深)时退回中值宽度,
    免得把"本来就等深"的一段画出假透视。
    """
    z = np.asarray(zc, float)
    zmin, zmax = float(np.min(z)), float(np.max(z))
    if zmax - zmin < 1e-3:
        return np.full(len(z), (wmin + wmax) / 2.0)
    t = (zmax - z) / (zmax - zmin)                # 0=最远 → 1=最近
    return wmin + (wmax - wmin) * t


def draw_path_tube(img, uv, zc, col, W, H, base_w=4.0, ring_every=None,
                   wmin=TUBE_W_MIN, wmax=TUBE_W_MAX, intent=False,
                   is_first=False, is_last=False):
    """沿图像折线 uv 画一根立体管道(原地, BGR)。返回 (段数, (最小管径, 最大管径))。

    uv:(N,2) px   zc:(N,) 相机系深度(m)   col: origin 色(BGR)   base_w: 规格 width(管径缩放档)
    三要素都在这里: ①逐段四边形填充(宽度随深度) ②每隔 ring_every 点一个截面环
    ③暗边+内侧高光带 ④端点圆帽。

    intent=True(2026-09-29 老倪: 「必须能看出**前进意图**」)时额外加三样**纯渲染**装饰 ——
    **不改任何数据结构**(仍只读 kind/pts3d/width/origin 这些既有字段):
      · 管体+截面环**沿程深浅渐变**(起点暗 → 终点亮) ⇒ 一眼看出往哪头走
      · **起点实心圆点**(带暗边) ⇒ 起点在哪
      · **末端箭头/楔形**(沿末段切向, 实心 + 暗边) ⇒ 终点方向 = 前进意图
    """
    import cv2
    P = np.asarray(uv, float)
    z = np.asarray(zc, float)
    N = len(P)
    if N < 2:
        return 0, (0.0, 0.0)
    scale = max(0.5, min(2.0, float(base_w) / 4.0))   # width 仍是"粗细档", 只改成缩放管径(≤2×)
    wmin, wmax = wmin * scale, wmax * scale
    wid = tube_widths(z, wmin, wmax)
    full = tuple(int(c) for c in col)                 # origin 原色(高光带/圆帽)
    body = _cscale(col, TUBE_SHADE)                   # 管体主色(暗面)
    dark = _cscale(col, TUBE_DARK)                    # 暗边/轮廓
    ring_c = _cscale(col, 0.80)                       # 截面环
    # 沿程渐变系数(0=起点 1=终点): 管体 0.34→0.80 × TUBE_SHADE · 环 0.45→1.0
    _t = (np.linspace(0.0, 1.0, N) if (intent and INTENT_ON) else np.zeros(N))
    _bf = [_cscale(col, TUBE_SHADE * (0.34 + 0.46 * float(v))) if intent and INTENT_ON else body
           for v in _t]
    _rf = [_cscale(col, 0.45 + 0.55 * float(v)) if intent and INTENT_ON else ring_c for v in _t]

    # 每点局部切向 → 法向(把有宽度的管壁撑开)
    nrm = []
    for i in range(N):
        a, b = P[max(0, i - 1)], P[min(N - 1, i + 1)]
        tx, ty = _unit2(b[0] - a[0], b[1] - a[1])
        nrm.append((-ty, tx))
    nrm = np.asarray(nrm, float)

    def off(i, s):                                    # 沿法向偏移 s 个半管径的像素点(管壁)
        w = wid[i] / 2.0
        return (int(round(P[i, 0] + nrm[i, 0] * w * s)),
                int(round(P[i, 1] + nrm[i, 1] * w * s)))

    def sh(i, f):                                     # 沿法向偏移 f*wid[i] 的像素点(高光带)
        return (int(round(P[i, 0] + nrm[i, 0] * wid[i] * f)),
                int(round(P[i, 1] + nrm[i, 1] * wid[i] * f)))

    # ① 管体: 逐段填充"左右边缘"四边形 ⇒ 段宽=两端深度插值出的管径(近粗远细)
    #    intent ⇒ 逐段用沿程渐变色(_bf): 起点暗、终点亮, 方向一眼可读
    n_seg = 0
    for i in range(N - 1):
        q = np.array([off(i, -1), off(i + 1, -1), off(i + 1, 1), off(i, 1)], np.int32)
        _c = _bf[i + 1] if (intent and INTENT_ON) else body
        if abs(cv2.contourArea(q)) >= 1.0:
            cv2.fillConvexPoly(img, q, _c, cv2.LINE_AA)
        else:                                         # 退化段(两端几乎重合)⇒ 退化成粗线
            cv2.line(img, off(i, 0), off(i + 1, 0), _c,
                     max(1, int(round(min(wid[i], wid[i + 1]) / 2.0))), cv2.LINE_AA)
        n_seg += 1
    for i in range(N):                                # 关节圆头: 拐弯处不留缝
        cv2.circle(img, (int(round(P[i, 0])), int(round(P[i, 1]))),
                   max(1, int(round(wid[i] / 2.0))),
                   (_bf[i] if (intent and INTENT_ON) else body), -1, cv2.LINE_AA)

    # ③ 明暗双色: 暗边(+法向轮廓) + 内侧高光带(-法向) ⇒ 圆柱受光感
    for i in range(N - 1):
        cv2.line(img, off(i, 1), off(i + 1, 1), dark, TUBE_EDGE_PX, cv2.LINE_AA)
    hi_th = max(1, int(round(float(np.mean(wid)) * 0.22)))
    for i in range(N - 1):
        cv2.line(img, sh(i, -0.32), sh(i + 1, -0.32), full, hi_th, cv2.LINE_AA)

    # ② 截面环: 每隔 ring_every 点画一个切面椭圆(沿切向压扁) + 法向十字刻度
    re = max(1, int(ring_every if ring_every else TUBE_RING_EVERY))
    for i in list(range(0, N, re)) + ([N - 1] if (N - 1) % re else []):
        half = max(2, int(round(wid[i] / 2.0)))
        ang = math.degrees(math.atan2(nrm[i, 1], nrm[i, 0]))
        cv2.ellipse(img, (int(round(P[i, 0])), int(round(P[i, 1]))),
                    (half, max(1, int(round(half * 0.38)))), ang, 0, 360,
                    (_rf[i] if (intent and INTENT_ON) else ring_c), 1, cv2.LINE_AA)
        for s in (-1, 1):                             # 管壁刻度(法向两端)
            cv2.line(img, off(i, s * 0.55), off(i, s * 0.98),
                     (_rf[i] if (intent and INTENT_ON) else ring_c), 1, cv2.LINE_AA)

    # ④ 端点圆帽: 首末点实心圆 + 暗边 ⇒ 看得到"管口"
    for i in (0, N - 1):
        c = (int(round(P[i, 0])), int(round(P[i, 1])))
        r = max(2, int(round(wid[i] / 2.0)))
        cv2.circle(img, c, r, full, -1, cv2.LINE_AA)
        cv2.circle(img, c, r, dark, 1, cv2.LINE_AA)

    # ⑤ 🧭 前进意图装饰(纯渲染, 不改数据): 起点实心圆点 + 末端箭头/楔形
    if intent and INTENT_ON:
        if INTENT_START_DOT and is_first:
            _p0 = (int(round(P[0, 0])), int(round(P[0, 1])))
            r0 = max(4, int(round(wid[0] * 0.85)))
            cv2.circle(img, _p0, r0, full, -1, cv2.LINE_AA)          # 实心点(原点色)
            cv2.circle(img, _p0, r0, dark, max(1, TUBE_EDGE_PX), cv2.LINE_AA)
            cv2.circle(img, _p0, max(2, int(r0 * 0.35)), dark, -1, cv2.LINE_AA)   # 中心暗点(像"起点")
        if INTENT_ARROW and is_last:
            d = _unit2(P[-1, 0] - P[max(0, N - 3), 0], P[-1, 1] - P[max(0, N - 3), 1])
            if d != (0.0, 0.0):
                nx, ny = -d[1], d[0]
                L = max(12.0, 3.4 * float(wid[-1]))                  # 箭头长
                HW = max(5.0, 0.95 * float(wid[-1]))                 # 半宽
                tip = (P[-1, 0] + d[0] * L * 0.18, P[-1, 1] + d[1] * L * 0.18)
                base = (P[-1, 0] - d[0] * L * 0.82, P[-1, 1] - d[1] * L * 0.82)
                tri = np.array([[int(round(tip[0])), int(round(tip[1]))],
                                [int(round(base[0] + nx * HW)), int(round(base[1] + ny * HW))],
                                [int(round(base[0] - nx * HW)), int(round(base[1] - ny * HW))]], np.int32)
                cv2.fillConvexPoly(img, tri, full, cv2.LINE_AA)      # 楔形箭头(实心)
                cv2.polylines(img, [tri], True, dark, max(1, TUBE_EDGE_PX), cv2.LINE_AA)

    return n_seg, (float(wid.min()), float(wid.max()))


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
    # 2026-09-29: 临时文件名**必须每进程/每次唯一** —— 现场有多个写方(实时检测 2s 一轮 / 轨迹发布壳
    # 2s 一轮 / 参考点 marker / L5 校正环)同写这一个 spec; 共用 overlay_spec.tmp 时, 谁先 replace
    # 谁就把别人的 tmp 搬走, 另一个报 FileNotFoundError 并**静默丢掉这次写入**(实测踩到)。
    tmp = SPEC_PATH.with_name("%s.tmp.%d.%d" % (SPEC_PATH.name, os.getpid(), time.time_ns() % 1000000))
    try:
        tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(SPEC_PATH)
    except Exception:                                                        # noqa: BLE001
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


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

    # 🧩 管道叠放次序(仅渲染层, 不动数据): 点多的长轨迹(实测)先铺底、点少的短路径(规划段)后画 ⇒
    #    短的规划管道不会被长的实测管道整条盖死(2026-09-29 实测: trace 403 点会盖掉 plan 7 点)。
    #    只重排 path3d 之间的先后, 其余框(3D盒/2D框)的相对次序与索引不变。
    _pidx = [i for i, b in enumerate(boxes) if b.get("pts3d")]
    if len(_pidx) > 1:
        _plist = sorted((boxes[i] for i in _pidx), key=lambda b: -len(b.get("pts3d") or []))
        boxes = list(boxes)
        for _k, _i in enumerate(_pidx):
            boxes[_i] = _plist[_k]

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

        # ── 3D 管道(路径/轨迹): 逐段投影后画成一根**立体管道**(可读出三维), 不是一条线 ──
        #    规格元素: {"kind":"path3d", "pts3d":[[x,y,z],...], "width":3, "origin":...}
        #    2026-09-29: 从细线改为管道 —— ①管径随投影深度(近粗远细) ②每隔若干路点一个截面环
        #    ③明暗双色(管体+高光/暗边) ④端点圆帽; 几何仍沿用既有 base_to_cam/cam_to_px 投影。
        if b.get("pts3d"):
            if not he_ok:
                skipped.append((label, "无手眼/TCP")); continue
            try:
                P = np.asarray(b["pts3d"], float).reshape(-1, 3)
            except Exception:
                skipped.append((label, "折线点解析失败")); continue
            if len(P) < 2:
                skipped.append((label, "折线点不足 2")); continue
            Pcam = base_to_cam(P, he["X"], tcp7)
            zc = Pcam[:, 2]
            uv = cam_to_px(Pcam, K)
            # 投影合理性限幅: 贴近相机的点会投到画面外"极远处", 连线会糊满整帧(实测曾糊 64% 画面) ⇒ 必须限幅
            good = (np.isfinite(uv).all(1) & (zc > 0.12) &
                    (uv[:, 0] > -1.5 * W) & (uv[:, 0] < 2.5 * W) &
                    (uv[:, 1] > -1.5 * H) & (uv[:, 1] < 2.5 * H))
            pts, nseg = [], 0
            _w0 = float(b.get("width", 4))           # 保留 width 字段: 现在是"管径粗细档"(缩放 ≤2×)
            _dmax = float(np.hypot(W, H)) * 1.2      # 单段像素长上限(防"视锥外投影"拉出横贯全帧的长条)
            okseg = []
            for i in range(len(P) - 1):
                if not (good[i] and good[i + 1]):
                    okseg.append(False); continue
                if float(np.hypot(uv[i][0] - uv[i + 1][0], uv[i][1] - uv[i + 1][1])) > _dmax:
                    skipped.append((label, "折线段超长(投影出画面)已跳过")); okseg.append(False); continue
                okseg.append(True)
            # 连续可用段 → 连续折线(run): 断开处各画一根管道, 绝不跨界连线
            runs, cur = [], []
            for i in range(len(P) - 1):
                if okseg[i]:
                    cur = [i, i + 1] if not cur else cur + [i + 1]
                elif cur:
                    runs.append(cur); cur = []
            if cur:
                runs.append(cur)
            w_lo, w_hi = 1e9, 0.0
            # 🧭 前进意图: origin=plan(规划/意图路径)默认开; 元素也可显式给 intent 覆盖。
            #    **只影响渲染**, 数据结构不变(kind/pts3d/width/origin 语义原样)。
            _intent = bool(b.get("intent", str(b.get("origin")) == "plan"))
            _nmarks = 0
            for run in runs:
                if len(run) < 2:
                    continue
                ns, (wl, wh) = draw_path_tube(img, uv[run], zc[run], col, W, H, base_w=_w0,
                                              intent=_intent,
                                              is_first=(run[0] == 0), is_last=(run[-1] == len(P) - 1))
                nseg += ns
                if _intent:
                    if INTENT_START_DOT and run[0] == 0:
                        _nmarks += 1
                    if INTENT_ARROW and run[-1] == len(P) - 1:
                        _nmarks += 1
                w_lo, w_hi = min(w_lo, wl), max(w_hi, wh)
                for k in run:                        # 记像素范围(供页面/取证)
                    pts.append((int(round(float(uv[k, 0]))), int(round(float(uv[k, 1])))))
            if nseg == 0:
                skipped.append((label, "折线整段在视锥外")); continue
            A = np.asarray(pts, float)
            info.update(kind="path3d", corners=None, z_mm=None, n_seg=int(nseg),
                        tube_px=[round(w_lo, 1), round(w_hi, 1)] if w_hi >= w_lo else None,
                        intent=_intent, n_intent_marks=_nmarks,
                        xyxy=[float(A[:, 0].min()), float(A[:, 1].min()),
                              float(A[:, 0].max()), float(A[:, 1].max())],
                        clipped=bool(((A[:, 0] < 0) | (A[:, 0] > W) | (A[:, 1] < 0) | (A[:, 1] > H)).any()))

        # ── 3D 盒: 画真三维线框(12 条棱), 近粗远细 ⇒ 人眼能看出进深 ──
        elif b.get("box3d"):
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
            if _FILL_ON and len(pts_all) >= 4:
                # 大盒(台面 429×653mm ≈ 14 万 px)按面积自动减淡: 否则整屏糊成一块绿, 反而看不清东西
                _area = float(cv2.contourArea(cv2.convexHull(pts_all)))
                _k = 1.0 if _area < 8000.0 else max(0.45, 8000.0 / _area)
                _a1, _a2 = FILL_ALPHA * _k, FILL_TOP_ALPHA * _k
                _ov = img.copy()
                cv2.fillConvexPoly(_ov, cv2.convexHull(pts_all),
                                   tuple(int(v * 0.55) for v in col), cv2.LINE_AA)
                cv2.addWeighted(_ov, _a1, img, 1.0 - _a1, 0, img)
                _quad = [1, 3, 7, 5]
                if all(fin[q] for q in _quad):
                    _tp = np.array([[int(round(uv[q, 0])), int(round(uv[q, 1]))] for q in _quad], np.int32)
                    _ov2 = img.copy()
                    cv2.fillConvexPoly(_ov2, _tp, tuple(int(v * 0.8) for v in col), cv2.LINE_AA)
                    cv2.addWeighted(_ov2, _a2, img, 1.0 - _a2, 0, img)
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
                        # 🏷 标签要放盒子**外面**(它是不透明底片, 压上去就把染色和棱线全盖死 ——
                        #    2026-09-28 实测: 小盒凸包内 100% 被自己的标签盖住 ⇒ 体积感白做)。
                        #    这里只报几何, 具体放上/放下由下面的贴标签代码决定。
                        _anchor=None,
                        _box=[round(float((xs.min() + xs.max()) / 2.0), 1),
                              round(float(ys.min()), 1), round(float(ys.max()), 1)])
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

        if b.get("no_label"):                 # 纯几何元素(路径插值段等)不打标签芯片, 否则白底黑字糊满画面
            info.pop("_box", None); info.pop("_anchor", None)
            drawn.append({"id": bid, "label": label, "origin": b.get("origin"),
                          "xyxy": info["xyxy"], "clipped": info["clipped"], "kind": info["kind"]})
            out_boxes.append(info)
            continue
        tag = "%s%s" % (label, (" %.2f" % b["conf"]) if b.get("conf") is not None else "")
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        _bx = info.pop("_box", None)
        if _bx:                                   # 3D 盒: 标签放盒子外(上/下) + 引线
            _cx, _ytop, _ybot = _bx
            ax = max(2.0, min(W - tw - 8.0, _cx - tw / 2.0))
            _xc = int(ax + tw / 2.0)
            if _ytop > th + 14.0:                 # 上方有地方 ⇒ 放上面(底片底边 = ay)
                ay = float(_ytop) - 5.0
                cv2.line(img, (_xc, int(ay)), (_xc, int(_ytop)), col, 1, cv2.LINE_AA)
            else:                                 # 顶到画面边(末端/TCP 常在 y≈0) ⇒ 放下面
                ay = min(float(H) - 2.0, _ybot + th + 7.0)
                cv2.line(img, (_xc, int(ay) - th - 6), (_xc, int(_ybot)), col, 1, cv2.LINE_AA)
        else:
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
    band.append("框: 仿真=%s 量测=%s 大模型=%s 检测=%s (共%d)"
                % (sum(1 for d in drawn if d["origin"] == "sim"),
                   sum(1 for d in drawn if d["origin"] == "meas"),
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
