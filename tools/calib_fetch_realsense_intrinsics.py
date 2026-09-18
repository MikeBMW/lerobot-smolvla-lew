#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_fetch_realsense_intrinsics.py — 从 ROS 话题取 D405 **出厂内参** 写进 models/real_cam_calib.json

为什么: 「2D 检测框 → 3D 边界框」最贵的一步是相机模型。D405 的彩色内参 K 在
  /realsense/color/camera_info 里**现成** (出厂标定), 不必靠自监督去解 11 个自由度的投影矩阵 ——
  有了 K, 剩下的只是**手眼外参 (R,t) 6 个自由度**, 而且尺度被米制锚定 (不再和尺寸/偏移退化)。

红线: 只订阅, 零发布, 只在 4060 侧容器里跑 → Orin 侧零改动、零自启。写文件只写本机 models/。

用法:
  python3 tools/calib_fetch_realsense_intrinsics.py            # 跑容器探针 → 更新 real_cam_calib.json
  python3 tools/calib_fetch_realsense_intrinsics.py --dry-run  # 只看, 不写
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
CALIB = os.path.join(_REPO, "models", "real_cam_calib.json")
CONTAINER = os.environ.get("ZMAX_TAP_CONTAINER", "ss-remote-tap")
PROBE = "/repo/tools/ros_camera_info_probe.py"


def run_probe(docker_prefix="sudo"):
    cmd = (f'{docker_prefix} docker exec {CONTAINER} bash -lc '
           f'"source /opt/ros/humble/setup.bash && timeout 45 python3 {PROBE}"')
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
    out = p.stdout
    i = out.find("{")
    if i < 0:
        raise RuntimeError(f"探针无 JSON 输出 (rc={p.returncode}): {out[-400:]}{p.stderr[-400:]}")
    return json.loads(out[i:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    probe = run_probe()
    ci = probe.get("camera_info") or {}
    if not ci.get("K"):
        print("❌ 拿不到 /realsense/color/camera_info (驱动没跑? 话题没发?)")
        return 1
    K = [float(v) for v in ci["K"]]
    d = {}
    if os.path.exists(CALIB):
        d = json.load(open(CALIB, encoding="utf-8"))
    d["K"] = K
    d["dist"] = [float(v) for v in (ci.get("D") or [0.0] * 5)]
    d["distortion_model"] = ci.get("distortion_model") or "plumb_bob"
    d["image_size"] = [ci.get("w"), ci.get("h")]
    d["K_src"] = ("真机出厂内参 · /realsense/color/camera_info (ROS camera_info, 只读订阅) · "
                  f"采集于 {__import__('time').strftime('%F %T')}")
    d["fx_fy_cx_cy"] = [K[0], K[4], K[2], K[5]]
    # 还没有的项保持 None 并说明 (不许编): 手眼外参 / 台面高度
    for k, note in (("T_base_cam", "手眼外参未标定: 可①棋盘格 tools/calib_real_cam.py --handeye ②"
                                   "由 (框,TCP) 自监督解手眼 box3d_live_box.py --collect"),
                    ("plane_z", "台面高度未标定: 用夹爪或塞尺量一次")):
        if d.get(k) is None:
            d.setdefault("_todo", {})[k] = note
    d["ready"] = bool(d.get("K"))
    d["reason"] = ("内参已成 (K 来自 ROS camera_info)。3D 仍需: 手眼 T_base_cam"
                   + ("" if d.get("T_base_cam") else " (缺)") + " / 台面 plane_z"
                   + ("" if d.get("plane_z") else " (缺)"))
    if a.dry_run:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    os.makedirs(os.path.dirname(CALIB), exist_ok=True)
    tmp = CALIB + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, CALIB)
    print(f"✅ 已写 {CALIB}: fx={K[0]:.2f} fy={K[4]:.2f} cx={K[2]:.2f} cy={K[5]:.2f} "
          f"({ci.get('w')}x{ci.get('h')}) · ready={d['ready']}")
    print(f"   仍缺: " + ", ".join(k for k in ("T_base_cam", "plane_z") if not d.get(k)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
