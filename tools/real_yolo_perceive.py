#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_yolo_perceive.py — 真机 YOLO 感知 (仿真同源代码, 换源即换世界)

老倪 2026-09-17: 「引入真机 realsense → YOLO 感知真实机器人环境; 仿真跑完无缝移植真机」。

一条链路, 四个源, 同一份检测+反投影代码 (yolo_state_aligner.estimate_3d):
    sim (metaworld) · ros (ROS2 话题, Orin 本机或 4060 侧 Docker 只读订阅)
    uvc (直读 /dev/videoN, RealSense 免装 SDK/驱动) · file (录制的帧回放)

39D 契约 (与仿真逐段相同):
    [0:3]=hand [4:7]=光模块 [7:11]=peg_quat [18:21]=prev_hand [22:25]=prev_peg [36:39]=hole
    · 真机 hand 取 /robot/tcp_pose 真值 (R1 契约: 末端=编码器, 视觉只测工件) —— --hand-from tcp
    · 光模块/hole 取 YOLO 检测
不编造: 缺内参/外参/深度 → 打印 gaps 并只给能给的量 (真机未标定时 3D 在相机系, 显式标注)。

用法:
  gui-venv311/bin/python tools/real_yolo_perceive.py --source file:/path/imgs --frames 5
  gui-venv311/bin/python tools/real_yolo_perceive.py --source uvc:2 --frames 20 --out reports/real_perceive
  gui-venv311/bin/python tools/real_yolo_perceive.py --source ros --frames 20
"""
import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

W_DEF = os.path.join(ROOT, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt")
DW_DEF = os.path.join(ROOT, "outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt")


def build_source(spec: str, args):
    import frame_source as fs
    if spec == "sim":
        import metaworld
        mt = metaworld.MT1("peg-insert-side-v3")
        env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
        env._freeze_rand_vec = False
        env.set_task(mt.train_tasks[0])
        env.reset(seed=0)
        env._freeze_rand_vec = True
        return fs.SimFrameSource(env)
    if spec == "ros":
        return fs.RosFrameSource(domain_id=args.domain_id, calib_path=args.calib,
                                 timeout=args.timeout)
    if spec.startswith("uvc"):
        dev = int(spec.split(":")[1]) if ":" in spec else 2
        return fs.UvcFrameSource(device=dev, width=args.width, height=args.height,
                                 calib_path=args.calib)
    if spec.startswith("file:"):
        return fs.FileFrameSource(spec.split(":", 1)[1], calib_path=args.calib)
    raise ValueError(f"未知 --source: {spec}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="file:/home/ubuntu/zmax_data/real_cam/orin_d405")
    ap.add_argument("--frames", type=int, default=5)
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--weights", default=W_DEF)
    ap.add_argument("--depth-weights", default=DW_DEF if os.path.isfile(DW_DEF) else None)
    ap.add_argument("--out", default=os.path.join(ROOT, "reports/real_perceive"))
    ap.add_argument("--calib", default=None, help="真机相机标定 json (K/T_base_cam/plane_z)")
    ap.add_argument("--hand-from", choices=["auto", "vision", "tcp"], default="auto",
                    help="hand 来源: tcp=/robot/tcp_pose 真值 (真机推荐), vision=YOLO hand, auto")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--domain-id", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--annotate", action="store_true", default=True)
    a = ap.parse_args()

    from yolo_state_aligner import YoloStateAligner
    src = build_source(a.source, a)
    aligner = YoloStateAligner(a.weights, env=getattr(src, "env", None),
                               depth_weights=a.depth_weights, source=src)
    os.makedirs(a.out, exist_ok=True)
    print(f"[real] 源={src.name} 朝向口径 train_rot_k={src.train_rot_k} rgb_order={src.rgb_order} "
          f"深度米制={src.depth_metric} 坐标系={src.frame}")
    print(f"[real] 标定: {os.path.basename(a.calib) if a.calib else '(默认路径 models/real_cam_calib.json)'}")

    recs, t_all = [], []
    for i in range(a.frames):
        t0 = time.time()
        frame = src.grab()
        det3d, meta = aligner.estimate_3d(frame, conf=a.conf)
        dt = time.time() - t0
        t_all.append(dt)
        # hand: 真机优先用 tcp_pose 真值 (R1 契约)
        hand_src, hand = "vision", det3d.get("hand")
        if a.hand_from in ("auto", "tcp") and hasattr(src, "tcp"):
            tcp = src.tcp()
            if tcp is not None:
                hand_src, hand = "tcp_pose(真值)", tcp["p"]
        obs39 = np.full(39, np.nan)
        if hand is not None:
            obs39[0:3] = hand
            obs39[18:21] = hand
        if "光模块" in det3d:
            obs39[4:7] = det3d["光模块"]
            obs39[22:25] = det3d["光模块"]
        if "hole" in det3d:
            obs39[36:39] = det3d["hole"]
        rec = {"i": i, "dt_s": round(dt, 3), "n_det": len(det3d), "hand_src": hand_src,
               "det3d": {k: [round(float(q), 5) for q in v] for k, v in sorted(det3d.items())},
               "obs39_filled": [None if np.isnan(x) else round(float(x), 5) for x in obs39],
               "meta": meta, "frame_shape": list(frame.rgb.shape) if frame.rgb is not None else None}
        recs.append(rec)
        print(f"[real] #{i} {dt:.2f}s 检出={rec['n_det']} {rec['det3d']} "
              f"| depth={meta['depth_src']} K={meta['K_src']} ext={meta['ext_src']} "
              f"frame={meta['frame']} gaps={len(meta['gaps'])}")
        for g in meta["gaps"]:
            print(f"      ⚠️ gap: {g}")
        if a.annotate and frame.rgb is not None and aligner._last_res is not None:
            try:
                import cv2
                img = aligner._last_img_rot if aligner._last_img_rot is not None else frame.rgb
                outp = os.path.join(a.out, f"annot_{i:03d}.jpg")
                cv2.imwrite(outp, aligner._last_res.plot())
            except Exception as e:                                         # noqa: BLE001
                print(f"      (标注图失败: {e})")

    js = os.path.join(a.out, "perceive.json")
    json.dump({"source": a.source, "n": len(recs), "conf": a.conf, "weights": os.path.basename(a.weights),
               "mean_dt_s": round(float(np.mean(t_all)), 3) if t_all else None,
               "fps": round(1.0 / float(np.mean(t_all)), 2) if t_all and np.mean(t_all) > 0 else None,
               "frames": recs}, open(js, "w"), ensure_ascii=False, indent=1)
    n_det = sum(r["n_det"] for r in recs)
    print(f"\n[real] 完成: {len(recs)} 帧 · 总检出 {n_det} · 平均 {np.mean(t_all):.2f}s/帧 "
          f"({1.0/np.mean(t_all):.2f} FPS) → {js}")
    if n_det == 0:
        print("[real] ⚠️ 0 检出 — 先看是不是域差: 仿真权重在真机图上无信号 (见 probe_sim2real_domain_gap), "
              "需要真机数据微调; 校验类名/权重路径/朝向口径后仍为 0 即确认域差。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
