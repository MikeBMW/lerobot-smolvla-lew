#!/usr/bin/env python3
"""
Orin 数据包 (relay json) → npz 训练数据 (2026-08-02)
解码 camera_b64 → 图像数组, 输出 npz (observations/states/actions) 供 npz_to_lerobot 转换

用法:
  .venv/bin/python tools/orin_pkg_to_npz.py pkg.json --out data/orin_real.npz --img 64
"""
import argparse
import base64
import json

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pkg")
    ap.add_argument("--out", default="data/orin_real.npz")
    ap.add_argument("--img", type=int, default=64)
    args = ap.parse_args()

    pkg = json.load(open(args.pkg, encoding="utf-8"))
    frames = pkg.get("frames", [])
    if not frames:
        print("❌ 无 frames")
        raise SystemExit(1)

    states, actions, imgs = [], [], []
    import cv2
    for f in frames:
        st = f.get("observation.state") or f.get("joint")
        ac = f.get("action")
        if st is None or ac is None:
            continue
        states.append(np.asarray(st, dtype=np.float32))
        actions.append(np.asarray(ac, dtype=np.float32))
        b64 = f.get("camera_b64")
        if b64:
            jpg = base64.b64decode(b64)
            arr = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if arr is not None:
                arr = cv2.resize(arr, (args.img, args.img))
                imgs.append(arr.astype(np.float32) / 255.0)  # HWC 0-1
        else:
            imgs.append(np.zeros((args.img, args.img, 3), dtype=np.float32))

    states = np.stack(states)
    actions = np.stack(actions)
    imgs_arr = np.stack(imgs).transpose(0, 3, 1, 2)  # CHW
    np.savez_compressed(args.out,
                        observations=imgs_arr.astype(np.float32),
                        states=states, actions=actions,
                        task_name=np.array(pkg.get("meta", {}).get("source", "orin")),
                        fps=np.array(30))
    n = len(states)
    print(f"✅ {args.out}: {n}帧 · state{states.shape[1]}D · action{actions.shape[1]}D · img{imgs_arr.shape[1:]}")
    print(f"   state范围 {states.min():.3f}~{states.max():.3f} · action范围 {actions.min():.3f}~{actions.max():.3f}")


if __name__ == "__main__":
    main()
