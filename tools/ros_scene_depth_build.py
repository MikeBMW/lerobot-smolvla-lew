#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ros_scene_depth_build.py — 真实场景深度建图 [容器 ss-remote-tap 内跑]
════════════════════════════════════════════════════════════════════
老倪需求: 「利用L5层大模型的理解能力，你来建立深度地图」

链路（全部实测参数，无写死几何）:
    深度像素 (u,v) + z=深度值×0.1mm
      → p_cam  = ((u-cx)/fx·z, (v-cy)/fy·z, z)          [真 camera_info 内参]
      → p_tcp  = R_x·p_cam + t_x                         [手眼 X=T_cam2tcp]
      → p_base = R_g·p_tcp + t_g                         [实时 /robot/tcp_pose 真值]
      → 体素/占据栅格（X-Y 俯视）+ 语义物体 3D

产出（写 /out，即宿主机 ~/zmax_ss_remote）:
    depth_map/depth_raw.npy      原始深度帧 (16UC1)
    depth_map/depth_vis.png      深度伪彩可视化（含遮挡/无效区）
    depth_map/topview.png        base 系 X-Y 占据栅格俯视图（含刀尖位置）
    depth_map/stats.json         深度统计（有效率/量程/平面高度）
    zmax_scene/objects3d.json    语义物体 base 系 3D（喂给叠加引擎做仿真投影）

用法:
  sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
    export ROS_DOMAIN_ID=0 && python3 /repo/tools/ros_scene_depth_build.py --secs 3'
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image
from geometry_msgs.msg import PoseStamped

OUT = Path("/out")
REPO = Path("/repo")
DEPTH_SCALE = 0.0001          # D405: 0.1mm/单位（SDK 直读实测）
SPEC = REPO / "data" / "scene" / "overlay_spec.json"


def _q(d=5):
    return QoSProfile(depth=d, reliability=ReliabilityPolicy.BEST_EFFORT,
                      history=HistoryPolicy.KEEP_LAST)


class DepthMap(Node):
    def __init__(self):
        super().__init__("zmax_scene_depth", enable_rosout=False)
        self.depth = None
        self.info = None
        self.tcp = None
        self.create_subscription(Image, "/realsense/depth/image_rect_raw", self._d, _q())
        self.create_subscription(CameraInfo, "/realsense/color/camera_info", self._k, _q())
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self._t, _q())

    def _d(self, m: Image):
        a = np.frombuffer(m.data, np.uint16)
        if a.size >= m.height * m.width:
            self.depth = a[:m.height * m.width].reshape(m.height, m.width).copy()

    def _k(self, m: CameraInfo):
        self.info = {"fx": m.k[0], "fy": m.k[4], "cx": m.k[2], "cy": m.k[5],
                     "w": m.width, "h": m.height}

    def _t(self, m: PoseStamped):
        p = m.pose
        self.tcp = np.array([p.position.x, p.position.y, p.position.z,
                             p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w])


def quat_to_R(q):
    x, y, z, w = np.asarray(q, float) / (np.linalg.norm(q) or 1.0)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def load_handeye():
    p = REPO / "tools" / "calib" / "handeye" / "handeye_result.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    T = np.array(d["T_base_cam"], float)
    if np.linalg.norm(T[:3, 3]) > 10.0:
        T = T.copy()
        T[:3, 3] /= 1000.0
    return T, d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=3.0, help="采集时长")
    ap.add_argument("--stride", type=int, default=6, help="点云降采样步长")
    a = ap.parse_args()

    rclpy.init()
    n = DepthMap()
    t0 = time.time()
    while time.time() - t0 < a.secs and rclpy.ok():
        rclpy.spin_once(n, timeout_sec=0.2)
    if n.depth is None or n.info is None or n.tcp is None:
        print("  ✗ 缺数据: depth=%s info=%s tcp=%s" % (n.depth is not None,
                                                      n.info is not None, n.tcp is not None))
        n.destroy_node(); rclpy.shutdown(); return 1
    dep, K, tcp = n.depth, n.info, n.tcp
    n.destroy_node(); rclpy.shutdown()

    X, he = load_handeye()
    R_x, t_x = X[:3, :3], X[:3, 3]
    R_g, t_g = quat_to_R(tcp[3:7]), tcp[:3]
    H, W = dep.shape

    # ── 深度帧统计（先看清楚相机到底看到了什么）──
    valid = dep > 0
    z_m = dep[valid].astype(np.float32) * DEPTH_SCALE
    st = {"shape": [int(H), int(W)], "valid_frac": round(float(valid.mean()), 4),
          "z_min_mm": round(float(z_m.min() * 1000), 1) if z_m.size else None,
          "z_p50_mm": round(float(np.median(z_m) * 1000), 1) if z_m.size else None,
          "z_max_mm": round(float(z_m.max() * 1000), 1) if z_m.size else None,
          "depth_scale_mm_per_unit": DEPTH_SCALE * 1000,
          "intrinsics": K, "tcp": [round(float(v), 6) for v in tcp],
          "handeye": {"method": he.get("method"), "n_poses": he.get("n_unique_poses"),
                      "closed_loop_std_mm": he.get("closed_loop_std_mm"),
                      "X_t_mm": [round(float(v) * 1000, 2) for v in t_x]},
          "ts": time.time(), "at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # ── 点云: 深度 → base 系（体素降采样）──
    vs, us = np.mgrid[0:H:a.stride, 0:W:a.stride]
    zz = dep[::a.stride, ::a.stride].astype(np.float32) * DEPTH_SCALE
    ok = zz > 0.05
    P_cam = np.stack([(us[ok] - K["cx"]) / K["fx"] * zz[ok],
                      (vs[ok] - K["cy"]) / K["fy"] * zz[ok], zz[ok]], 1)
    P_tcp = (R_x @ P_cam.T).T + t_x
    P_base = (R_g @ P_tcp.T).T + t_g
    st["points"] = int(P_base.shape[0])
    if P_base.size:
        st["bbox_base_mm"] = {"x": [round(float(P_base[:, 0].min() * 1000), 1), round(float(P_base[:, 0].max() * 1000), 1)],
                              "y": [round(float(P_base[:, 1].min() * 1000), 1), round(float(P_base[:, 1].max() * 1000), 1)],
                              "z": [round(float(P_base[:, 2].min() * 1000), 1), round(float(P_base[:, 2].max() * 1000), 1)]}

    # ── 语义物体: 用规格里已检测到的框，取框心深度 → base 3D ──
    objs = []
    try:
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        for b in (spec.get("cameras", {}).get("arm", {}).get("boxes") or []):
            if not b.get("xyxy") or b.get("origin") == "sim":
                continue      # sim 框本身就是 3D 投影出来的，避免自我循环
            x1, y1, x2, y2 = [float(v) for v in b["xyxy"]]
            # 框中区采样: 物体表面深度近似恒定 ⇒ 取中位，天然抗单点噪声与边缘空洞
            cx0, cx1 = int(max(0, x1)), int(min(W, x2))
            cy0, cy1 = int(max(0, y1)), int(min(H, y2))
            if cx1 - cx0 < 4 or cy1 - cy0 < 4:
                continue
            patch = dep[cy0:cy1, cx0:cx1]
            pv = patch[patch > 0]
            if pv.size < 20:
                continue
            z = float(np.median(pv)) * DEPTH_SCALE
            u, v = (cx0 + cx1) / 2.0, (cy0 + cy1) / 2.0
            p_cam = np.array([(u - K["cx"]) / K["fx"] * z, (v - K["cy"]) / K["fy"] * z, z])
            p_base = R_g @ (R_x @ p_cam + t_x) + t_g
            objs.append({"name": b.get("label", "obj"), "origin_det": b.get("origin"),
                         "conf": b.get("conf"), "center": [round(float(q), 4) for q in p_base],
                         "coord": "base", "source": "深度实测 (框心中位深度 × 手眼 × TCP 真值)",
                         "depth_mm": round(z * 1000, 1), "n_depth_px": int(pv.size),
                         "size": [40, 16, 12],
                         "note": "尺寸用标称值；物体基座平面法向未估(世界轴对齐盒)"})
    except Exception as e:
        st["object_error"] = str(e)[:200]
    st["objects"] = len(objs)

    # ── 落盘 ──
    dm = OUT / "depth_map"
    dm.mkdir(parents=True, exist_ok=True)
    np.save(dm / "depth_raw.npy", dep)
    (dm / "stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "zmax_scene").mkdir(parents=True, exist_ok=True)
    (OUT / "zmax_scene" / "objects3d.json").write_text(
        json.dumps({"objects": objs, "coord": "base", "source": "ros_scene_depth_build.py",
                    "handeye": he.get("method"), "ts": time.time()}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    # ── 可视化: 深度伪彩 + base 系俯视占据 ──
    try:
        import cv2
        d8 = np.zeros((H, W), np.uint8)
        if z_m.size:
            lo, hi = np.percentile(z_m, 2), np.percentile(z_m, 98)
            d8 = np.clip((dep.astype(np.float32) * DEPTH_SCALE - lo) / max(1e-6, hi - lo) * 255,
                         0, 255).astype(np.uint8)
        cv2.imwrite(str(dm / "depth_vis.png"), cv2.applyColorMap(255 - d8, cv2.COLORMAP_TURBO))
        if P_base.size:
            x0, x1 = np.percentile(P_base[:, 0], [0.5, 99.5])
            y0, y1 = np.percentile(P_base[:, 1], [0.5, 99.5])
            sc = min(880.0 / max(1e-3, x1 - x0), 880.0 / max(1e-3, y1 - y0))
            img = np.zeros((960, 960, 3), np.uint8)
            img[:] = (22, 27, 34)
            ix = ((P_base[:, 0] - x0) * sc + 60).astype(int)
            iy = (960 - ((P_base[:, 1] - y0) * sc + 60)).astype(int)
            m = (ix >= 0) & (ix < 960) & (iy >= 0) & (iy < 960)
            img[iy[m], ix[m]] = (90, 200, 120)
            tx = int((tcp[0] - x0) * sc + 60)
            ty = int(960 - ((tcp[1] - y0) * sc + 60))
            cv2.drawMarker(img, (tx, ty), (60, 60, 240), cv2.MARKER_CROSS, 26, 3)
            cv2.putText(img, "X [mm] %.0f..%.0f (1px=%.1fmm)" % (x0 * 1000, x1 * 1000, 1 / sc * 1000),
                        (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (200, 200, 200), 1, cv2.LINE_AA)
            cv2.putText(img, "base X-Y occupancy  points=%d   cross=TCP" % P_base.shape[0],
                        (16, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (200, 200, 200), 1, cv2.LINE_AA)
            cv2.imwrite(str(dm / "topview.png"), img)
    except Exception as e:
        st["vis_error"] = str(e)[:200]

    print("  ✓ 深度图 %dx%d 有效 %.1f%% 量程 %.1f~%.1fmm 中位 %.1fmm"
          % (H, W, st["valid_frac"] * 100, st["z_min_mm"] or -1, st["z_max_mm"] or -1,
             st["z_p50_mm"] or -1))
    print("  ✓ 点云 %d 点 · base 包围盒 x%s y%s z%s mm"
          % (st["points"], st["bbox_base_mm"]["x"], st["bbox_base_mm"]["y"], st["bbox_base_mm"]["z"]))
    for o in objs:
        print("  ✓ 物体 %-10s base=(%.1f, %.1f, %.1f)mm 深度 %.0fmm (%d 像素)"
              % (o["name"], o["center"][0] * 1000, o["center"][1] * 1000, o["center"][2] * 1000,
                 o["depth_mm"], o["n_depth_px"]))
    print("  → /out/depth_map/{depth_raw.npy,depth_vis.png,topview.png,stats.json}")
    print("  → /out/zmax_scene/objects3d.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
