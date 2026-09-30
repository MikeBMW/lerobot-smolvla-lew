#!/usr/bin/env python3
"""train_ss_right_brain_mw.py — 真实 metaworld 多布局重训右脑 WorldModel (2026-09-06)

数据: data/ss_mw_raw/*.npz (collect_mw_teacher_data.py, 解析教师 × 真实 metaworld 多布局)
标签真实性升级 (对比引擎域版):
  - next_obs = 同 episode 下一帧 obs[:,:39] (真 mujoco 物理转移)
  - contact  = **真实触觉 force_norm > 0.05** (mj_contactForce 真接触力, 非手-peg 距离代理)
网络: RightBrainWM(39,4,256) 结构不变 → npz 管道兼容 (dynamics.rb_ff_forward 加载)
归一化: sm/ss 从训练数据自算并内嵌 npz — 推理现场 (R0/R1 多布局) 同分布 → 域内生效
用法: ~/lerobot-venv/bin/python tools/train_ss_right_brain_mw.py
"""
import glob
import os
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
OUT = os.path.join(ROOT, "models", "ss_right_brain.npz")
CKPT = os.path.join(ROOT, "outputs", "rl_peg", "ss_right_brain_best.pt")
RAW = os.path.join(ROOT, "data", "ss_mw_raw")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
FORCE_D = 0.05          # 真实触觉标签: 环境接触力归一化 > 0.05 (mj_contactForce/F_REF)
EPOCHS = 400
BATCH = 512
LR = 1e-3


def load_data():
    npzs = sorted(glob.glob(os.path.join(RAW, "*.npz")))
    if not npzs:
        print(f"❌ 无数据: {RAW} (先跑 tools/collect_mw_teacher_data.py)")
        sys.exit(1)
    S, A, Sn, lab = [], [], [], []
    for npz in npzs:
        d = np.load(npz, allow_pickle=True)
        meta = d["meta"][0]
        if not meta.get("success"):
            continue
        obs = np.asarray(d["obs"], dtype=np.float32)[:, :39]
        # 动作输入 = 实际下发 u_exec (与推理端 act4=上一步真正下发的控制量同构;
        #   不能用 u_ff 教师建议 — 两者量级差 ~3 倍, 09-06 实锤)
        u_exec = np.asarray(d["u_exec_vec"], dtype=np.float32)
        act = np.concatenate([u_exec[:, :3], np.zeros((len(u_exec), 1))], axis=1).astype(np.float32)
        force = np.asarray(d["force"], dtype=np.float32)
        u = np.asarray(d["u_ff_vec"], dtype=np.float32)
        n = len(obs)
        keep = np.arange(n - 1)  # next = 下一帧
        S.append(obs[keep]); A.append(act[keep])
        Sn.append(obs[keep + 1])
        lab.append((force[keep] > FORCE_D).astype(np.float32))
        print(f"  ✅ s{meta.get('seed')}: {n-1}帧 · contact正样本 "
              f"{(force[keep] > FORCE_D).mean():.1%}")
    S = np.concatenate(S).astype(np.float32)
    A = np.concatenate(A).astype(np.float32)
    Sn = np.concatenate(Sn).astype(np.float32)
    lab = np.concatenate(lab).astype(np.float32)
    sm = S.mean(0).astype(np.float32)
    ss = S.std(0).astype(np.float32) + 1e-8
    return S, A, Sn, lab, sm, ss


def main():
    torch.manual_seed(42)
    np.random.seed(42)
    from lerobot.policies.left_right.modeling_left_right import RightBrainWM
    print(f"🧠 真实 metaworld 多布局重训右脑 WorldModel · {DEVICE}", flush=True)
    S, A, Sn, lab, sm, ss = load_data()
    n = len(S)
    print(f"  📦 数据: {n}帧 · contact 正样本 {lab.mean():.1%} · 布局 {n // 600}+", flush=True)
    perm = np.random.permutation(n)
    nv = int(n * 0.1)
    val_i, tr_i = perm[:nv], perm[nv:]
    S_n = (S - sm) / ss
    Sn_n = (Sn - sm) / ss

    rb = RightBrainWM(39, 4, 256).to(DEVICE)
    opt = optim.Adam(rb.parameters(), lr=LR)
    best_val = 1e9
    if os.path.exists(CKPT) and "--retrain" not in sys.argv:
        print(f"⏭️  --resume: 载入已有 best ({CKPT}), 直接评估导出 (加 --retrain 强制重训)")
        rb.load_state_dict(torch.load(CKPT, map_location="cpu"))
        rb.eval()
        with torch.no_grad():
            pn, pc = rb(torch.from_numpy(S[val_i]).to(DEVICE), torch.from_numpy(A[val_i]).to(DEVICE))
            pn = pn.cpu().numpy(); pc = pc.cpu().numpy().ravel()
        err_pos = np.abs(pn[:, :3] * ss[:3] + sm[:3] - Sn[val_i][:, :3]).mean(axis=0)
        acc = float(((pc > 0.5).astype(float) == lab[val_i]).mean())
        print(f"✅ resume best: next位置误差(cm)={np.round(err_pos * 100, 1)} "
              f"contact acc={acc:.3f} 触={pc[lab[val_i] == 1].mean():.2f} "
              f"空={pc[lab[val_i] == 0].mean():.2f}", flush=True)
        sd = rb.state_dict()
        W = {}
        for key, name in [("enc.0.weight", "W_e0"), ("enc.0.bias", "b_e0"),
                          ("enc.2.weight", "W_e1"), ("enc.2.bias", "b_e1"),
                          ("pred_next.weight", "W_p"), ("pred_next.bias", "b_p"),
                          ("contact_head.weight", "W_c"), ("contact_head.bias", "b_c")]:
            W[name] = sd[key].detach().cpu().numpy().astype(np.float32)
        np.savez(OUT, **W, next_raw=False, sm=sm, ss=ss, obs_dim=39, act_dim=4)
        print(f"💾 导出: {OUT} (sm/ss = 真实多布局统计)")
        return

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
        rb.eval()
        with torch.no_grad():
            ln, lc, pcv, cv = run_batch(val_i, False)
        acc = float(((pcv > 0.5).astype(float) == cv).mean())
        v = ln + 0.5 * lc
        if ep % 50 == 0 or v < best_val:
            print(f"  ep{ep}: val next={ln:.5f} contact={lc:.4f} acc={acc:.3f}"
                  f" 触={pcv[cv == 1].mean():.2f} 空={pcv[cv == 0].mean():.2f}", flush=True)
        if v < best_val:
            best_val = v
            torch.save(rb.state_dict(), CKPT)
    rb.load_state_dict(torch.load(CKPT, map_location="cpu"))
    rb.eval()
    with torch.no_grad():
        pn, pc = rb(torch.from_numpy(S[val_i]).to(DEVICE), torch.from_numpy(A[val_i]).to(DEVICE))
        pn = pn.cpu().numpy(); pc = pc.cpu().numpy().ravel()
    err_pos = np.abs(pn[:, :3] * ss[:3] + sm[:3] - Sn[val_i][:, :3]).mean(axis=0)
    acc = float(((pc > 0.5).astype(float) == lab[val_i]).mean())
    print(f"\n✅ best: next位置误差(cm)={np.round(err_pos * 100, 1)} contact acc={acc:.3f}"
          f" 触={pc[lab[val_i] == 1].mean():.2f} 空={pc[lab[val_i] == 0].mean():.2f}", flush=True)
    sd = rb.state_dict()
    W = {}
    for key, name in [("enc.0.weight", "W_e0"), ("enc.0.bias", "b_e0"),
                      ("enc.2.weight", "W_e1"), ("enc.2.bias", "b_e1"),
                      ("pred_next.weight", "W_p"), ("pred_next.bias", "b_p"),
                      ("contact_head.weight", "W_c"), ("contact_head.bias", "b_c")]:
        W[name] = sd[key].detach().cpu().numpy().astype(np.float32)
    np.savez(OUT, **W, next_raw=False, sm=sm, ss=ss, obs_dim=39, act_dim=4)
    print(f"💾 导出: {OUT} (sm/ss = 真实多布局统计)")


if __name__ == "__main__":
    main()
