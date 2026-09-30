#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_dataset.py — 把 gs_capture 采集会话做成 3DGS 数据集 (位姿已知, 不用 COLMAP/SfM)

链路(每一环都有真源, 不猜):
  图像  = 臂上 D405 的 Orin 高速 JPEG 通道 (640x480 bgr8)
  内参  = models/real_cam_calib.json (ROS camera_info 出厂内参 K + 5 参畸变; 去畸变用 getOptimalNewCameraMatrix(alpha=0))
  外参  = T_base_cam = T_base_tcp · T_cam2tool
            · T_base_tcp 逐帧来自 rokae_sdk/tcp_out/latest.json (ROKAE SDK 直读 endInRef, 页面同源)
            · T_cam2tool 来自 handeye_state.json (TSAI, 残差 0.06mm/0.0046° RMS)
  选帧  = 6D 位姿最远点贪心(平移+朝向都要分散) —— 上万帧里大量是同一视角连拍, 全喂进去只是白烧 GPU

输出: <out>/images/*.jpg(去畸变) + <out>/cameras.json(每帧 4x4 T_cam2world + 内参, OpenCV 光学系 x右y下z前)
      + <out>/transforms.json(nerfstudio 风格, 供别的工具读) + <out>/meta.json

用法:
  python3 tools/gs_dataset.py --session ~/zmax_data/gs_scan/scan_XXXX --out ~/zmax_data/gs_data/scan_XXXX \
      [--max-frames 300] [--min-gap-ms 40] [--undistort-keep-all]
"""
from __future__ import annotations
import argparse, json, math, os, shutil, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB = os.path.join(ROOT, "models/real_cam_calib.json")
HANDEYE = os.path.expanduser("~/zmax_data/handeye_state.json")


def quat_to_R(x, y, z, w):
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], float)


def T_of(pos, quat):
    T = np.eye(4)
    T[:3, :3] = quat_to_R(*quat)
    T[:3, 3] = pos
    return T


def load_frames(session, min_gap_ms):
    fp = os.path.join(os.path.expanduser(session), "frames.jsonl")
    out = []
    for ln in open(fp, encoding="utf-8"):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if not r.get("file"):
            continue
        t_img = r.get("t_mono_fetch1") or 0.0
        p = r.get("pose_after") or r.get("pose_before")
        if not (isinstance(p, dict) and all(k in p for k in ("x", "y", "z", "qx", "qy", "qz", "qw"))):
            continue
        tw = r.get("t_wall") or [0.0]
        gap_ms = abs(float(tw[0]) - float(p.get("ts") or tw[0])) * 1000.0   # 位姿龄(wall 钟, 与取图同轮)
        if gap_ms > min_gap_ms:
            continue
        out.append({"file": r["file"], "t": t_img,
                    "pos": [float(p["x"]), float(p["y"]), float(p["z"])],
                    "quat": [float(p[k]) for k in ("qx", "qy", "qz", "qw")],
                    "gap_ms": round(gap_ms, 2), "ts": p.get("ts")})
    return out


def select(frames, T_tool_cam, max_frames):
    """6D 最远点贪心: 先挑位姿离群最远的, 再逐步挑离已选集合最远的。"""
    if max_frames <= 0 or len(frames) <= max_frames:
        return list(range(len(frames)))
    C = []
    for f in frames:
        T = T_of(np.array(f["pos"]), f["quat"]) @ T_tool_cam
        C.append(T)
    pos = np.array([T[:3, 3] for T in C])
    fwd = np.array([T[:3, :3] @ np.array([0, 0, 1.0]) for T in C])     # 光轴方向
    ctr = pos.mean(0)
    score = np.linalg.norm(pos - ctr, axis=1)
    sel = [int(np.argmax(score))]
    dmin = np.full(len(C), 1e9)
    while len(sel) < max_frames:
        i = sel[-1]
        dp = np.linalg.norm(pos - pos[i], axis=1)
        da = 1.0 - np.clip(fwd @ fwd[i], -1, 1)          # 朝向差(0~2)
        d = dp + 0.15 * da
        dmin = np.minimum(dmin, d)
        nxt = int(np.argmax(dmin))
        if dmin[nxt] <= 0:
            break
        sel.append(nxt)
    return sorted(sel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-frames", type=int, default=300)
    ap.add_argument("--min-gap-ms", type=float, default=40.0)
    ap.add_argument("--jpeg-quality", type=int, default=95)
    args = ap.parse_args()

    import cv2
    calib = json.load(open(CALIB, encoding="utf-8"))
    K = np.array(calib["K"], float).reshape(3, 3)
    dist = np.array(calib["dist"], float).reshape(-1)
    W, H = int(calib["image_size"][0]), int(calib["image_size"][1])
    he = json.load(open(HANDEYE, encoding="utf-8"))
    T_tool_cam = np.array(he["T_cam2tool"], float).reshape(4, 4)      # cam→tool
    print("内参 K fx=%.2f fy=%.2f cx=%.2f cy=%.2f · dist=%s · %dx%d" % (K[0, 0], K[1, 1], K[0, 2], K[1, 2], list(np.round(dist, 5)), W, H))
    print("手眼 T_cam2tool 残差 %.3fmm / %.4f° (session %s)" % (he.get("resid_trans_mm_rms", -1), he.get("resid_rot_deg_rms", -1), he.get("session")))

    frames = load_frames(args.session, args.min_gap_ms)
    if not frames:
        print("❌ 会话里没有可用帧"); return 2
    p = np.array([f["pos"] for f in frames])
    print("会话 %s: 可用帧 %d · 位姿跨度 x%.1fmm y%.1fmm z%.1fmm"
          % (os.path.basename(os.path.normpath(args.session)), len(frames),
             np.ptp(p[:, 0]) * 1000, np.ptp(p[:, 1]) * 1000, np.ptp(p[:, 2]) * 1000))

    sel = select(frames, T_tool_cam, args.max_frames)
    print("选帧: %d → %d (6D 位姿最远点贪心)" % (len(frames), len(sel)))

    out = os.path.expanduser(args.out)
    idir = os.path.join(out, "images")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(idir, exist_ok=True)
    Knew, roi = cv2.getOptimalNewCameraMatrix(K, dist, (W, H), 0, (W, H))
    print("去畸变后内参 fx=%.2f fy=%.2f cx=%.2f cy=%.2f · 有效区 %s" % (Knew[0, 0], Knew[1, 1], Knew[0, 2], Knew[1, 2], roi))
    src = os.path.join(os.path.expanduser(args.session), "frames")
    recs = []
    n_bad = 0
    for n, i in enumerate(sel):
        f = frames[i]
        img = cv2.imread(os.path.join(src, f["file"]))
        if img is None:
            n_bad += 1
            continue
        und = cv2.undistort(img, K, dist, None, Knew)
        name = "img_%05d.jpg" % n
        cv2.imwrite(os.path.join(idir, name), und, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
        T = T_of(np.array(f["pos"]), f["quat"]) @ T_tool_cam        # T_cam2world(base)
        recs.append({"file": name, "src": f["file"], "t": f["t"],
                     "T_cam2world": [list(map(float, row)) for row in T],
                     "pos": list(map(float, T[:3, 3]))})
    json.dump({"convention": "T_cam2world (base_link) · OpenCV 光学系 x右 y下 z前 · 未转 nerfstudio 的 OpenGL 系",
               "K": [list(map(float, r)) for r in Knew], "width": W, "height": H,
               "dist_removed": True, "frames": recs},
              open(os.path.join(out, "cameras.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # nerfstudio 风格(OpenGL 系: y 上, z 后) —— 给别的工具用
    flip = np.diag([1.0, -1.0, -1.0, 1.0])
    nsf = {"fl_x": float(Knew[0, 0]), "fl_y": float(Knew[1, 1]), "cx": float(Knew[0, 2]), "cy": float(Knew[1, 2]),
           "w": W, "h": H, "k1": 0.0, "k2": 0.0, "p1": 0.0, "p2": 0.0, "camera_model": "PINHOLE",
           "frames": [{"file_path": "images/" + r["file"],
                       "transform_matrix": [list(map(float, row)) for row in
                                            (np.array(r["T_cam2world"]) @ flip)]} for r in recs]}
    json.dump(nsf, open(os.path.join(out, "transforms.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    q = np.array([r["pos"] for r in recs])
    meta = {"session": os.path.abspath(os.path.expanduser(args.session)), "n_frames_used": len(recs),
            "n_bad_images": n_bad, "max_frames": args.max_frames, "K": [list(map(float, r)) for r in Knew],
            "handeye_session": he.get("session"), "resid_trans_mm_rms": he.get("resid_trans_mm_rms"),
            "bbox_min": [float(v) for v in q.min(0)], "bbox_max": [float(v) for v in q.max(0)],
            "spread_mm": [float(v) for v in ((q.max(0) - q.min(0)) * 1000)],
            "note": "位姿已知重建(无 SfM); 视差基线 = 上表 spread_mm —— 太小则只能重建出浅浮雕, 做不出完整环境资产"}
    json.dump(meta, open(os.path.join(out, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 数据集 → %s" % out)
    print("   images/ %d 张(去畸变) · cameras.json · transforms.json · meta.json" % len(recs))
    print("   相机位姿包围盒 %s mm (视差基线)" % [round(v, 1) for v in meta["spread_mm"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
