#!/usr/bin/env python3
"""train_ss_right_brain.py — 引擎域重训右脑 WorldModel (RightBrainWM) 并直接导出 npz

背景 (2026-09-06 实测): state_space_20260904 ckpt 的右脑未训好 (lerobot 标准训练只优化
left action loss) — contact acc 0.721 无区分度 (近peg 0.519 vs 远 0.511), pred_next 位置
误差 6cm。重训: 引擎仿真数据 (data/ss_insert_lerobot, 与引擎/画布同域同 obs 结构)。

数据/标签:
- next_obs = 同 episode 下一帧 observation.state (输出训归一化空间, npz next_raw=False)
- contact = 手(obs[0:3])-peg(obs[7:10]) 距离 < 0.05 (引擎 obs 结构; 该闭爪了吗)
网络: RightBrainWM(39,4,256) 结构不变 (enc 2×256 + pred_next + contact_head) — npz 管道兼容。
用法: ~/lerobot-venv/bin/python tools/train_ss_right_brain.py
"""
import os
import sys
import json
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
OUT = os.path.join(ROOT, "models", "ss_right_brain.npz")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
CONTACT_D = 0.05      # 接触标签: 手-peg 距离阈值 (同 train_dual_brain 语义, 引擎 obs 结构)
EPOCHS = 400
BATCH = 512
LR = 1e-3


def load_data():
    import pandas as pd
    parquet = os.path.join(ROOT, "data", "ss_insert_lerobot", "data", "chunk-000", "file-000.parquet")
    df = pd.read_parquet(parquet)
    S = np.stack(df["observation.state"].values).astype(np.float32)
    A = np.stack(df["action"].values).astype(np.float32)
    ep = df["episode_index"].values
    # next = 同 episode 下一帧 (帧序 = 行序; 最后帧丢弃)
    keep = np.ones(len(S), dtype=bool)
    keep[:-1] = ep[:-1] == ep[1:]
    keep[-1] = False
    idx = np.where(keep)[0]
    S, A, Sn = S[idx], A[idx], S[idx + 1]
    # 归一化参数 (obs/next 同统计; 输出归一化空间)
    st = json.load(open(os.path.join(ROOT, "data", "ss_insert_lerobot", "meta", "stats.json"), encoding="utf-8"))
    sm = np.array(st["observation.state"]["mean"], dtype=np.float32)
    ss = np.array(st["observation.state"]["std"], dtype=np.float32) + 1e-8
    lab = (np.linalg.norm(S[:, 0:3] - S[:, 7:10], axis=1) < CONTACT_D).astype(np.float32)
    return S, A, Sn, lab, sm, ss


def main():
    torch.manual_seed(42)
    np.random.seed(42)
    from lerobot.policies.left_right.modeling_left_right import RightBrainWM
    print(f"🧠 引擎域重训右脑 WorldModel · {DEVICE}", flush=True)
    S, A, Sn, lab, sm, ss = load_data()
    n = len(S)
    print(f"  📦 数据: {n}帧 · contact 正样本 {lab.mean():.1%}", flush=True)
    # 按 9:1 随机分 train/val (帧级; 同 episode 相邻帧轻微泄漏可接受 — 验证只作监控)
    perm = np.random.permutation(n)
    nv = int(n * 0.1)
    val_i, tr_i = perm[:nv], perm[nv:]
    S_n = (S - sm) / ss
    Sn_n = (Sn - sm) / ss  # 输出目标: 归一化空间

    rb = RightBrainWM(39, 4, 256).to(DEVICE)
    opt = optim.Adam(rb.parameters(), lr=LR)
    best_val = 1e9

    def run_batch(i, train=True):
        o = torch.from_numpy(S[i]).to(DEVICE)
        a = torch.from_numpy(A[i]).to(DEVICE)
        sn = torch.from_numpy(Sn_n[i]).to(DEVICE)
        c = torch.from_numpy(lab[i]).to(DEVICE).unsqueeze(1)
        pn, pc = rb(o, a)
        loss_n = nn.functional.mse_loss(pn, sn)
        loss_c = nn.functional.binary_cross_entropy(pc, c)
        loss = loss_n + 0.5 * loss_c
        if train:
            opt.zero_grad(); loss.backward(); opt.step()
        return loss_n.item(), loss_c.item(), pc.detach().cpu().numpy().ravel(), c.cpu().numpy().ravel()

    for ep in range(EPOCHS):
        rb.train()
        np.random.shuffle(tr_i)
        for b0 in range(0, len(tr_i), BATCH):
            run_batch(tr_i[b0:b0 + BATCH], True)
        # 验证
        rb.eval()
        with torch.no_grad():
            ln, lc, pcv, cv = run_batch(val_i, False)
        acc = float(((pcv > 0.5).astype(float) == cv).mean())
        v = ln + 0.5 * lc
        if ep % 50 == 0 or v < best_val:
            print(f"  ep{ep}: val next={ln:.5f} contact={lc:.4f} acc={acc:.3f}"
                  f" 近peg均值={pcv[cv==1].mean():.2f} 远={pcv[cv==0].mean():.2f}", flush=True)
        if v < best_val:
            best_val = v
            torch.save(rb.state_dict(), os.path.join(ROOT, "outputs", "rl_peg", "ss_right_brain_best.pt"))
    # 载入 best 评估
    rb.load_state_dict(torch.load(os.path.join(ROOT, "outputs", "rl_peg", "ss_right_brain_best.pt"), map_location="cpu"))
    rb.eval()
    with torch.no_grad():
        pn, pc = rb(torch.from_numpy(S[val_i]).to(DEVICE), torch.from_numpy(A[val_i]).to(DEVICE))
        pn = pn.cpu().numpy(); pc = pc.cpu().numpy().ravel()
    err_pos = np.abs(pn * ss[:3] + sm[:3] - Sn[val_i][:, :3]).mean(axis=0)
    acc = float(((pc > 0.5).astype(float) == lab[val_i]).mean())
    print(f"\n✅ best: next位置误差(cm)={np.round(err_pos * 100, 1)} contact acc={acc:.3f}"
          f" 近={pc[lab[val_i] == 1].mean():.2f} 远={pc[lab[val_i] == 0].mean():.2f}", flush=True)
    # 导出 npz (结构同 export_ss_right_brain.py)
    sd = rb.state_dict()
    W = {}
    for key, name in [("enc.0.weight", "W_e0"), ("enc.0.bias", "b_e0"),
                      ("enc.2.weight", "W_e1"), ("enc.2.bias", "b_e1"),
                      ("pred_next.weight", "W_p"), ("pred_next.bias", "b_p"),
                      ("contact_head.weight", "W_c"), ("contact_head.bias", "b_c")]:
        W[name] = sd[key].numpy().astype(np.float32)
    np.savez(OUT, **W, next_raw=False, sm=sm, ss=ss, obs_dim=39, act_dim=4)
    print(f"💾 导出: {OUT}")


if __name__ == "__main__":
    sys.exit(main())
