#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX metaworld 数据 → LeRobot ACT 训练格式
parquet (observation.state/action/image) → npz (observations/states/actions)
输出: data/metaworld_act/train.npz + val.npz
用法: .venv/bin/python tools/ci/prepare_metaworld.py [--data-dir ...] [--val-split 0.2]
"""
import os, sys, json, argparse
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "metaworld_mt50", "data", "chunk-000")
OUT = os.path.join(ROOT, "data", "metaworld_act")
IMG_SIZE = 128  # 小尺寸, 4060 8G 跑得动


def load_frames(parquet_files):
    """读取多个分片, 返回 (images, states, actions, ep_ids)"""
    images, states, actions, eps = [], [], [], []
    for pf in parquet_files:
        df = pd.read_parquet(pf)
        for _, row in df.iterrows():
            img = row["observation.image"]
            # parquet 图像: {'bytes': PNG bytes} 或直接 bytes
            if isinstance(img, dict) and "bytes" in img:
                img = img["bytes"]
            if isinstance(img, bytes):
                import io
                from PIL import Image
                try:
                    im = Image.open(io.BytesIO(img)).convert("RGB").resize((IMG_SIZE, IMG_SIZE))
                    arr = np.asarray(im, dtype=np.float32) / 255.0
                except Exception:
                    continue
            elif isinstance(img, (list, tuple)):
                arr = np.asarray(img, dtype=np.float32)
                if arr.ndim == 3 and arr.shape[-1] == 3:
                    from PIL import Image
                    arr = np.asarray(Image.fromarray((arr * 255).astype(np.uint8))
                                     .resize((IMG_SIZE, IMG_SIZE)), dtype=np.float32) / 255.0
                elif arr.ndim == 4 and arr.shape[0] == 1:
                    arr = arr[0]
            else:
                continue
            images.append(arr.transpose(2, 0, 1) if arr.shape[-1] == 3 else arr)
            states.append(np.asarray(row["observation.state"], dtype=np.float32))
            actions.append(np.asarray(row["action"], dtype=np.float32))
            eps.append(int(row["episode_index"]))
    return np.stack(images), np.stack(states), np.stack(actions), np.array(eps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=DATA)
    ap.add_argument("--out-dir", default=OUT)
    ap.add_argument("--val-split", type=float, default=0.2)
    ap.add_argument("--max-files", type=int, default=2)
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.data_dir) if f.endswith(".parquet"))[:args.max_files]
    paths = [os.path.join(args.data_dir, f) for f in files]
    print(f"读取 {len(paths)} 个分片: {[os.path.basename(p) for p in paths]}")

    images, states, actions, eps = load_frames(paths)
    n = len(images)
    print(f"总帧数: {n} | 图像 {images.shape} | 状态 {states.shape} | 动作 {actions.shape}")

    # 按 episode 划分 train/val
    ep_ids = np.unique(eps)
    n_val = max(1, int(len(ep_ids) * args.val_split))
    rng = np.random.RandomState(42)
    val_eps = set(rng.choice(ep_ids, n_val, replace=False))
    val_mask = np.isin(eps, list(val_eps))

    os.makedirs(args.out_dir, exist_ok=True)
    for name, mask in [("train", ~val_mask), ("val", val_mask)]:
        if mask.sum() == 0:
            continue
        np.savez_compressed(
            os.path.join(args.out_dir, f"{name}.npz"),
            observations=images[mask].astype(np.float32),
            states=states[mask].astype(np.float32),
            actions=actions[mask].astype(np.float32),
            task_name="zmax_metaworld",
            fps=80,
        )
        print(f"  {name}: {mask.sum()} 帧 -> {args.out_dir}/{name}.npz")

    print("DONE")


if __name__ == "__main__":
    main()
