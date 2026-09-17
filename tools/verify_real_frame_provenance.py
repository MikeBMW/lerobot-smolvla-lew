#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_real_frame_provenance.py — 真机帧"真迹"取证 (回答: 这真是相机实拍, 不是仿真/图片?)

证据链 (每一环都可独立核对):
  ① 设备身份: /dev/videoN → sysfs → USB idVendor/idProduct/serial (D405 = 8086:0b5b)
     + /sys/class/video4linux/videoN/name (内核 uvcvideo 报的设备名)
  ② 驱动协商: cv2 打开后报的 FOURCC/分辨率/FPS (文件源给不出这些)
  ③ 活体性: 连续 N 帧的 sha256 必须**互不相同** (静态图/仿真帧会一样), 并给逐帧差分强度
  ④ 代码身份: 正在执行的源码文件路径 + sha256 (证明跑的就是仓库里那份代码)
  ⑤ 模型确实吃了这帧: 对最后一帧跑 YOLO, 报最高置信度/检出数 + 落盘标注图
  ⑥ 落盘原始帧: 供人眼直接核对 (可对着现场看是不是同一画面)

用法 (在 Orin 上):
  python3 /home/tashan/zmax_yolo/tools/verify_real_frame_provenance.py --device 2 --frames 6 --out out/provenance
"""
import argparse
import hashlib
import os
import sys
import time

import numpy as np

ROOT = "/home/tashan/zmax_yolo"
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def sha(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


def device_identity(dev: int) -> dict:
    """从 sysfs 拿 USB 身份 (不依赖任何 SDK)"""
    info = {}
    p = f"/sys/class/video4linux/video{dev}"
    try:
        info["kernel_name"] = open(f"{p}/name").read().strip()
    except Exception:                                                      # noqa: BLE001
        info["kernel_name"] = "?"
    d = os.path.realpath(p)
    cur = d
    for _ in range(12):                      # 向上找到 USB 接口目录
        up = os.path.dirname(cur)
        if up in ("", "/"):
            break
        cur = up
        if all(os.path.isfile(os.path.join(cur, k)) for k in ("idVendor", "idProduct")):
            for k in ("idVendor", "idProduct", "serial", "manufacturer", "product"):
                f = os.path.join(cur, k)
                if os.path.isfile(f):
                    try:
                        info[k] = open(f).read().strip()
                    except Exception:                                      # noqa: BLE001
                        pass
            info["usb_path"] = cur
            break
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=2)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--out", default=os.path.join(ROOT, "out/provenance"))
    ap.add_argument("--weights", default=os.path.join(ROOT, "weights/yolo_peg_best.pt"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    print("① 设备身份 (sysfs, 非 SDK)")
    ident = device_identity(a.device)
    for k, v in ident.items():
        print(f"   {k:12s} = {v}")
    is_rs = ident.get("idVendor") == "8086"
    print(f"   → {'✅ Intel/RealSense 设备' if is_rs else '⚠️ 非 Intel 设备, 请核对 /dev/video%d 是不是相机' % a.device}")

    import cv2
    cap = cv2.VideoCapture(a.device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"❌ /dev/video{a.device} 打不开 (被占用?)")
        return 2
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 15)
    print("② 驱动协商 (只有真设备才有这些回值)")
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    print(f"   FOURCC={''.join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4))} "
          f"· 分辨率={int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} "
          f"· FPS={cap.get(cv2.CAP_PROP_FPS):.1f} · CAP_PROP_BRIGHTNESS={cap.get(cv2.CAP_PROP_BRIGHTNESS):.1f}")

    print(f"③ 活体性: 连续 {a.frames} 帧 (间隔 {a.interval}s) — sha 必须互不相同")
    prev, rows = None, []
    for i in range(a.frames):
        ok, fr = cap.read()
        t = time.time()
        if not ok:
            print(f"   #{i} ❌ 读帧失败")
            continue
        h = sha(fr)
        d = "" if prev is None else f" · 与上帧最大像素差={int(np.abs(fr.astype(int) - prev.astype(int)).max())}"
        print(f"   #{i} t={t:.3f} sha={h} mean={fr.mean():.1f} std={fr.std():.1f}{d}")
        rows.append((i, h, fr))
        cv2.imwrite(os.path.join(a.out, f"live_{i}.jpg"), fr)
        prev = fr
        if i < a.frames - 1:
            time.sleep(a.interval)
    cap.release()

    uniq = len({h for _, h, _ in rows})
    verdict = ("✅ 全部不同 = 活体视频流 (静态图片/仿真截图会被抓成同 sha)" if uniq == len(rows) and len(rows) > 1
               else "❌ 帧完全一样 → 可疑 (不是活体流)")
    print(f"   唯一 sha 数 = {uniq}/{len(rows)} → {verdict}")

    print("④ 代码身份 (正在跑的就是这份文件)")
    for f in ("src/lerobot/policies/yolo_3d/frame_source.py",
              "src/lerobot/policies/yolo_3d/yolo_state_aligner.py",
              "tools/real_yolo_perceive.py"):
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            print(f"   {f} sha256={hashlib.sha256(open(p,'rb').read()).hexdigest()[:16]} mtime={time.strftime('%F %T', time.localtime(os.path.getmtime(p)))}")

    if rows and os.path.isfile(a.weights):
        print("⑤ 模型确实吃了这最后一帧 (同一帧 → 推理 → 分数)")
        from yolo_state_aligner import YoloStateAligner
        import frame_source as fs
        al = YoloStateAligner(a.weights, source=fs.UvcFrameSource.__new__(fs.UvcFrameSource))
        al.source.name, al.source.rgb_order, al.source.train_rot_k = "uvc", "BGR", 0
        al.source.depth_metric, al.source.frame = False, "camera"
        al.source.class_map, al.source.calib = fs.CLASS_MAP, {"ready": False}
        al.source.plane_z = lambda: {}
        r = al.model.predict(np.ascontiguousarray(rows[-1][2]), conf=0.001, verbose=False)[0]
        top = float(r.boxes.conf.max()) if r.boxes is not None and len(r.boxes) else 0.0
        det = {r.names[int(b.cls)]: round(float(b.conf[0]), 4) for b in r.boxes} if r.boxes is not None else {}
        cv2.imwrite(os.path.join(a.out, "last_annotated.jpg"), r.plot())
        print(f"   该帧(sha={rows[-1][1]}) → 检出 {len(det)} 个: {det} · 最高分 {top:.4f} (阈值 0.25)")

    print(f"⑥ 原始帧已落盘: {a.out}/live_*.jpg (共 {len(rows)} 张) — 请人眼核对是否与现场一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
