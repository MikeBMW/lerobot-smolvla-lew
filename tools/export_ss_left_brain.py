#!/usr/bin/env python3
"""export_ss_left_brain.py — 导出训练好的状态空间左脑 MLP 为 numpy npz
供 GUI (gui-venv311 无 torch) 用 numpy 推理加载。

用法: /root/lerobot-venv/bin/python tools/export_ss_left_brain.py [ckpt_dir]
      默认从 reports/train_curve_state_space.json 读最新 ckpt。
"""
import os
import sys
import json
import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "models", "ss_left_brain.npz")


def resolve_ckpt():
    """从 train_curve_state_space.json 读最新训练 ckpt 目录"""
    curve = os.path.join(ROOT, "reports", "train_curve_state_space.json")
    if os.path.exists(curve):
        d = json.load(open(curve, encoding="utf-8"))
        ckpt = d.get("ckpt")
        if ckpt:
            return os.path.join(ROOT, ckpt)
    return None


def main(ckpt_dir=None):
    ckpt_dir = ckpt_dir or resolve_ckpt()
    if not ckpt_dir:
        print("❌ 未找到训练模型 — 先训练或指定 ckpt 目录")
        return 1
    pt = os.path.join(ckpt_dir, "pretrained_model", "model.pt")
    if not os.path.isfile(pt):
        # train_curve 的 ckpt 字段可能不含 last → 补 last/pretrained_model
        pt2 = os.path.join(ckpt_dir, "last", "pretrained_model", "model.pt")
        if os.path.isfile(pt2):
            pt = pt2
        else:
            print(f"❌ model.pt 不存在: {pt} 或 {pt2}")
            return 1
    sd = torch.load(pt, map_location="cpu", weights_only=False)
    left = sd["left"]
    W, b = [], []
    for k in sorted(left.keys()):
        if k.endswith(".weight"):
            W.append(left[k].numpy().astype(np.float32))
        elif k.endswith(".bias"):
            b.append(left[k].numpy().astype(np.float32))
    if len(W) != 4:
        print(f"❌ 期望 4 层 Linear, 实际 {len(W)} 层")
        return 1
    # 归一化参数重算 (同 ss_verify_trained.py, 训练用 dataset.stats)
    import pandas as pd
    parquet = os.path.join(ROOT, "data", "ss_insert_lerobot", "data", "chunk-000", "file-000.parquet")
    df = pd.read_parquet(parquet)
    S = np.stack(df["observation.state"].values).astype(np.float32)
    A = np.stack(df["action"].values).astype(np.float32)
    sm = S.mean(0).astype(np.float32)
    ss = S.std(0).astype(np.float32) + np.float32(1e-8)
    am = A.mean(0).astype(np.float32)
    astd = A.std(0).astype(np.float32) + np.float32(1e-8)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez(OUT,
             **{f"W{i}": W[i] for i in range(4)},
             **{f"b{i}": b[i] for i in range(4)},
             sm=sm, ss=ss, am=am, astd=astd,
             obs_dim=int(sd["obs_dim"]), act_dim=int(sd["act_dim"]))
    shapes = " → ".join(str(w.shape[1]) for w in W)
    print(f"✅ 导出完成: {OUT}")
    print(f"   MLP {sd['obs_dim']}D {shapes} {sd['act_dim']}D (4层 Linear)")
    print(f"   归一化: state {sm.shape[0]}D / action {am.shape[0]}D")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
