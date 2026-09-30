# -*- coding: utf-8 -*-
"""掩膜 → base 系 3D (只对**臂上相机**成立)

口径 (缺一环就**如实拒答**, 不猜不填):
  掩膜内有效深度像素 → 中位深度 z → 相机系反投影(RealSense 深度 = 沿光轴 z)
  → 相机→末端(手眼 X) → 末端→base(实时 TCP 真值) → base 中心/足印(长宽/朝向)/z 分位

依赖链: 深度源(容器 ros_depth_stream 落的 depth_raw.npy + depth_meta.json, 验新鲜度)
        · 手眼标定(tools/calib/handeye/handeye_result.json)
        · TCP 真值(珞石 SDK 直采 latest.json)
任一处不在位/不新鲜 → 返回 {ok: False, reason: ...}(调用方负责原样显示)。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

DEPTH_NPY = Path(os.environ.get("ZMAX_DEPTH_NPY", "/home/ubuntu/zmax_ss_remote/zmax_scene/depth_raw.npy"))
DEPTH_META = Path(os.environ.get("ZMAX_DEPTH_META", "/home/ubuntu/zmax_ss_remote/zmax_scene/depth_meta.json"))
DEPTH_DEAD_S = float(os.environ.get("ZMAX_DEPTH_DEAD_S", "20"))
Z_MIN, Z_MAX = 0.05, 3.0          # 有效深度带(m)
MIN_DEPTH_PX = 30                 # 掩膜内至少这么多有效深度像素才解 3D


def _scene_overlay():
    """复用既有真源 (投影/手眼/TCP/内参 都在 tools/scene_overlay.py 一处维护, 别各写一份)"""
    import sys
    root = Path(__file__).resolve().parents[3]
    tp = str(root / "tools")
    if tp not in sys.path:
        sys.path.insert(0, tp)
    import scene_overlay
    return scene_overlay


def depth_status() -> dict:
    """深度源是否在线 (页面/报告都用这一份判断)"""
    if not (DEPTH_NPY.exists() and DEPTH_META.exists()):
        return {"ok": False, "reason": "深度源文件不在位: %s" % DEPTH_NPY}
    try:
        meta = json.loads(DEPTH_META.read_text())
    except Exception as e:                                                  # noqa: BLE001
        return {"ok": False, "reason": "depth_meta.json 读不了: %s" % e}
    age = time.time() - float(meta.get("t", 0))
    ok = age <= DEPTH_DEAD_S
    return {"ok": ok, "age_s": round(age, 1), "dead_s": DEPTH_DEAD_S,
            "shape": [meta.get("h"), meta.get("w")], "depth_scale": meta.get("depth_scale"),
            "reason": None if ok else "深度源不新鲜: 龄 %.1fs > %.0fs (容器 ros_depth_stream 未常驻)"
                                      % (age, DEPTH_DEAD_S)}


def mask_3d(mask: np.ndarray, cam: str = "arm", depth_max_age_s: float = DEPTH_DEAD_S) -> dict:
    """掩膜 → base 系中心/尺寸/朝向; 失败给可查原因"""
    import cv2
    so = _scene_overlay()
    if cam != "arm":
        return {"ok": False, "reason": "本机相机(%s)无手眼外参 ⇒ 3D 掩膜只对臂上 D405 成立" % cam}

    st = depth_status()
    if not st.get("ok"):
        return {"ok": False, "reason": st.get("reason")}

    meta = json.loads(DEPTH_META.read_text())
    dep = np.load(str(DEPTH_NPY))
    Z = dep.astype(np.float32) * float(meta.get("depth_scale", 0.0001))
    h, w = Z.shape[:2]
    if mask.shape[:2] != (h, w):
        mask = cv2.resize(mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)

    he = so.load_handeye()
    if not he.get("ok"):
        return {"ok": False, "reason": "手眼标定不可用: %s" % (he.get("why") or he.get("reason") or "未标定")}
    tcp7 = so.read_tcp()
    if tcp7 is None:
        return {"ok": False, "reason": "TCP 真值读不到 (容器 rokae_tcp_sampler / latest.json)"}

    K = so.load_intrinsics(w, h)
    ys, xs = np.nonzero(mask)
    zs = Z[ys, xs]
    good = np.isfinite(zs) & (zs > Z_MIN) & (zs < Z_MAX)
    if int(good.sum()) < MIN_DEPTH_PX:
        return {"ok": False, "reason": "掩膜内有效深度像素不足 (%d/阈 %d)" % (int(good.sum()), MIN_DEPTH_PX)}
    xs, ys, zs = xs[good], ys[good], zs[good]

    Pc = np.stack([(xs - K["cx"]) / K["fx"] * zs, (ys - K["cy"]) / K["fy"] * zs, zs], 1)
    R_g, t_g = so.quat_to_R(tcp7[3:7]), np.asarray(tcp7[:3], float)
    R_x, t_x = he["X"][:3, :3], he["X"][:3, 3]
    Pb = (R_g @ ((R_x @ Pc.T).T + t_x).T).T + t_g
    c = np.median(Pb, 0)

    xy = Pb[:, :2].astype(np.float32)
    (rw, rh), ang = cv2.minAreaRect(xy)[1], cv2.minAreaRect(xy)[2]
    if rh > rw:                                    # minAreaRect 只有"宽边方向"才是 angle
        rw, rh, ang = rh, rw, ang + 90.0
    return {"ok": True, "center_base": [float(v) for v in c], "z_mm": float(np.median(zs)) * 1000.0,
            "z_p20_p80_mm": [float(np.percentile(Pb[:, 2], 20) * 1000), float(np.percentile(Pb[:, 2], 80) * 1000)],
            "xy_size_mm": [float(rw) * 1000, float(rh) * 1000], "yaw_deg": float(ang % 180.0),
            "n_px": int(len(xs)),
            "extent_mm": [float((Pb[:, i].max() - Pb[:, i].min()) * 1000) for i in range(3)],
            "depth_age_s": round(st.get("age_s", -1), 1),
            "handeye_closed_loop_std_mm": he.get("closed_loop_std_mm")}
