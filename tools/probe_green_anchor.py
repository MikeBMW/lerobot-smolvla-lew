#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绿锚双视探测: 同刻取 臂上相机帧 + 深度 + 笔记本相机帧 + TCP 真值,
在两边各找"高饱和绿"斑块, 臂侧用 深度+手眼 反算 base 3D ⇒ 这就是一对 3D↔2D 对应点候选。
只读, 不动任何设备。用于判定"笔记本相机 AR 标定能否自动采点"。
"""
import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_overlay as SO  # noqa: E402

SCENE = "/home/ubuntu/zmax_ss_remote/zmax_scene"
TCP_JSON = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")


def snap(name):
    u = "http://127.0.0.1:8791/snapshot/%s.jpg?_=%f" % (name, time.time())
    with urllib.request.urlopen(u, timeout=12) as r:
        return cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)


def green_mask(f):
    b, g, r = f[:, :, 0].astype(np.int16), f[:, :, 1].astype(np.int16), f[:, :, 2].astype(np.int16)
    return ((g - r) > 25) & ((g - b) > 20) & (g > 60)


def blobs(mask, min_area=25, topn=4):
    mm = cv2.morphologyEx((mask * 255).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    nl, lab, st, ce = cv2.connectedComponentsWithStats(mm, 8)
    idx = [i for i in range(1, nl) if st[i, 4] >= min_area]
    idx.sort(key=lambda i: -st[i, 4])
    return [{"area": int(st[i, 4]), "uv": (float(ce[i][0]), float(ce[i][1])),
             "bbox": [int(v) for v in st[i, :4]]} for i in idx[:topn]]


def main():
    # 同刻取一帧臂图 + 深度 + 笔记本图 + TCP
    arm = snap("arm")
    loc = snap("local")
    tcp = json.load(open(TCP_JSON))
    dep = np.load(os.path.join(SCENE, "depth_raw.npy"))
    meta = json.load(open(os.path.join(SCENE, "depth_meta.json")))
    he = SO.load_handeye()
    X = np.asarray(he.get("X"), float)
    if X.shape != (4, 4):
        print("手眼矩阵形状异常:", X.shape, list(he)); return 1
    cam_calib = json.load(open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "models", "real_cam_calib.json")))
    Kf = cam_calib["K"]
    K = {"fx": Kf[0], "fy": Kf[4], "cx": Kf[2], "cy": Kf[5]}
    print("K(640x480): fx=%.1f fy=%.1f cx=%.1f cy=%.1f" % (K["fx"], K["fy"], K["cx"], K["cy"]))
    print("手眼闭环 std=%.2fmm" % float(he.get("closed_loop_std_mm") or -1))
    print("TCP(base) = [%.4f %.4f %.4f]  ts=%s  age=%.2fs" % (
        tcp["x"], tcp["y"], tcp["z"], tcp.get("t"), time.time() - float(tcp["ts"])))

    tcp7 = [tcp["x"], tcp["y"], tcp["z"], tcp["qx"], tcp["qy"], tcp["qz"], tcp["qw"]]
    R_g, t_g = SO.quat_to_R(tcp7[3:7]), np.asarray(tcp7[:3], float)

    ga, gl = green_mask(arm), green_mask(loc)
    print("臂视图: %s  绿像素=%d" % (arm.shape, int(ga.sum())))
    for b in blobs(ga):
        u, v = b["uv"]
        x0, y0 = int(u), int(v)
        win = dep[max(0, y0 - 3):y0 + 4, max(0, x0 - 3):x0 + 4].astype(np.float32)
        ok = win[(win > 0) & (win < 65535)]
        if ok.size < 3:
            print("   绿斑 area=%d uv=(%.0f,%.0f) 深度无效(窗口内 %d 个有效)" % (b["area"], u, v, ok.size))
            continue
        z = float(np.median(ok)) * float(meta.get("depth_scale", 1e-4))
        p_cam = np.array([(u - K["cx"]) / K["fx"] * z, (v - K["cy"]) / K["fy"] * z, z])
        R_x, t_x = X[:3, :3], X[:3, 3]
        p_tcp = R_x @ p_cam + t_x
        p_base = R_g @ p_tcp + t_g
        print("   绿斑 area=%d uv=(%.0f,%.0f) z=%.3fm → base=(%.3f, %.3f, %.3f)" % (
            b["area"], u, v, z, p_base[0], p_base[1], p_base[2]))
    print("笔记本视图: %s 绿像素=%d" % (loc.shape, int(gl.sum())))
    for b in blobs(gl):
        print("   绿斑 area=%d uv=(%.0f,%.0f) bbox=%s" % (b["area"], b["uv"][0], b["uv"][1], b["bbox"]))
    cv2.imwrite("/tmp/ar_probe_arm.jpg", arm)
    cv2.imwrite("/tmp/ar_probe_local.jpg", loc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
