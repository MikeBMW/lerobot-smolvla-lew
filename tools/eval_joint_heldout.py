#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📏 联合集训留出集评估 —— 用 L5 生成的新变体当**留出集**(域迁移), 不拿训练 loss 说事

老倪 2026-09-23: "加大力度集训" (训练 loss 0.0007 ≈ 记忆训练集, 必须用留出集判有效性)

设计:
  训练集 = v6_disturb + v5_disturb (真机/引擎历史轨迹, 236k 帧)
  留出集 = **l5_gen_v2.h5** (L5 规划器生成的新方向变体, 150 变体) ← 未见过的方向
  → 在留出集上比: ① 联合集训产物 joint_full_v6  ② 在役 intact_l4_current (未联合训练)
  指标: 动作 MAE (L3 状态调度质量) + 观测预测 MAE (L4 认知预测质量) + 潜空间一致性 (L2 反馈)

诚实判据:
  · 若 A(联合) 留出 MAE < B(在役) → **训练有效** (泛化到新方向)
  · 若 A ≈ B 或更差 → 坦白"训练只在训练集上有效, 泛化无改善"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import torch
import torch.nn.functional as F

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
INTACT = "/home/ubuntu/INTACT-JEPA"
SWM = "/home/ubuntu/stable-wm-cache"
CKPT = f"{SWM}/checkpoints/intact_l4_current"
sys.path.insert(0, INTACT)
sys.path.insert(0, f"{ROOT}/tools")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def build_joint(ckpt_dir, dev, jepa_cfg_dir):
    """建四层联合模型并加载指定 ckpt 的 L4 权重。"""
    import json as _j
    from hydra.utils import instantiate
    from joint_train_full import JointFull, to_img_batch  # noqa

    cfg = _j.load(open(f"{jepa_cfg_dir}/config.json"))
    jepa = instantiate(cfg)
    w = os.path.join(ckpt_dir, "weights.pt")
    if os.path.isfile(w):
        sd = torch.load(w, map_location="cpu", weights_only=False)
        if isinstance(sd, dict) and "state_dict" in sd:
            sd = sd["state_dict"]
        miss, unexp = jepa.load_state_dict(sd, strict=False)
        print(f"    载入 L4: missing={len(miss)} unexpected={len(unexp)}")
    else:
        print(f"    ⚠️ 无 weights.pt → L4 用随机(未训)基线")
    # 联合头: 若产物里有 joint_full.pt 则载入 (训练过的 L2/L3/记忆头)
    m = JointFull(jepa, act_enc_dim=8)
    jp = os.path.join(ckpt_dir, "joint_full.pt")
    if os.path.isfile(jp):
        sd2 = torch.load(jp, map_location="cpu", weights_only=False)
        m.load_state_dict(sd2, strict=False)
        print(f"    载入联合头: {len(sd2)} 项 (L2/L3/记忆/认知预测)")
    else:
        print(f"    ⚠️ 无 joint_full.pt → L2/L3/记忆头为随机(未训)基线")
    return m.to(dev).eval()


@torch.no_grad()
def evaluate(model, h5, dev, batch=64, limit=6000, seed=0):
    import h5py
    f = h5py.File(h5, "r")
    total = int(f["observation"].shape[0])
    n = min(total, limit)
    idx = np.sort(np.random.default_rng(seed).choice(total, size=n, replace=False))  # h5py 要求升序
    mem = torch.zeros(13, device=dev)
    a_err, o_err, l2_err, cnt = 0.0, 0.0, 0.0, 0
    for i in range(0, n, batch):
        b = idx[i:i + batch]
        if len(b) < 2:
            continue
        obs = torch.tensor(np.asarray(f["observation"][b]), dtype=torch.float32, device=dev)
        act = torch.tensor(np.asarray(f["action"][b]), dtype=torch.float32, device=dev)
        goal = torch.tensor(np.asarray(f["goal"][b]), dtype=torch.float32, device=dev)
        px = torch.tensor(np.asarray(f["pixels"][b]))
        from joint_train_full import to_img_batch  # noqa
        img = to_img_batch(px).to(dev)
        out = model(img, obs, act, mem.unsqueeze(0).repeat(len(b), 1), goal)
        a_err += F.l1_loss(out["u"], act.unsqueeze(1).repeat(1, out["u"].shape[1], 1), reduction="sum").item()
        o_err += F.l1_loss(out["obs_hat"], goal, reduction="sum").item()
        l2_err += F.l1_loss(F.normalize(out["l2_fb"], dim=-1), F.normalize(out["z_l2"], dim=-1),
                            reduction="sum").item()
        cnt += len(b)
    f.close()
    return (a_err / max(1, cnt) / out["u"].shape[1], o_err / max(1, cnt), l2_err / max(1, cnt), cnt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heldout", default=f"{SWM}/datasets/l5_gen_v2.h5")
    ap.add_argument("--limit", type=int, default=6000)
    ap.add_argument("--batch", type=int, default=64)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    if not os.path.isfile(a.heldout):
        raise SystemExit(f"❌ 留出集不存在: {a.heldout}")
    print(f"📏 留出集评估 (域迁移: 训练用 v5/v6, 测试用 L5 新变体)")
    print(f"   留出集: {a.heldout} · 上限 {a.limit} 帧 · batch {a.batch}")

    arms = [("A 联合集训 joint_full_v6", f"{SWM}/checkpoints/joint_full_v6"),
            ("B 在役(未联合) intact_l4_current", CKPT)]
    res = {}
    for name, d in arms:
        print(f"\n── {name} ──")
        if not os.path.isdir(d):
            print(f"    ⚠️ 目录不存在: {d}")
            continue
        m = build_joint(d, dev, CKPT)
        am, om, lm, cnt = evaluate(m, a.heldout, dev, a.batch, a.limit)
        print(f"    留出集 n={cnt} | **动作 MAE {am:.5f}** | 观测预测 MAE {om:.5f} | L2 一致性 {lm:.4f}")
        res[name] = {"action_mae": am, "obs_mae": om, "l2_cons": lm, "n": cnt}
        del m
        torch.cuda.empty_cache()

    print("\n" + "=" * 78)
    if len(res) == 2:
        (na, ra), (nb, rb) = list(res.items())
        dA = (rb["action_mae"] - ra["action_mae"]) / max(1e-9, rb["action_mae"]) * 100
        dO = (rb["obs_mae"] - ra["obs_mae"]) / max(1e-9, rb["obs_mae"]) * 100
        print(f"动作 MAE : A {ra['action_mae']:.5f} vs B {rb['action_mae']:.5f}  → A 相对 B {'改善' if dA>0 else '退化'} {abs(dA):.1f}%")
        print(f"观测 MAE : A {ra['obs_mae']:.5f} vs B {rb['obs_mae']:.5f}  → A 相对 B {'改善' if dO>0 else '退化'} {abs(dO):.1f}%")
        ok = dA > 0
        print(f"判定: 留出集上 {'✅ 联合集训**有提升**(泛化到新方向)' if ok else '❌ 联合集训未显示泛化提升'}")
    print("=" * 78)
    json.dump(res, open(f"{ROOT}/reports/joint_heldout_eval.json", "w"), indent=1)
    print(f"取证: {ROOT}/reports/joint_heldout_eval.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
