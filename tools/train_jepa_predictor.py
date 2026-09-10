#!/usr/bin/env python3
"""🧠 train_jepa_predictor.py — 用真实化 episode 数据训练 JEPA predictor (L4 世界模型)

数据: 引擎 full/insert 轮 trace (reports/ss_episode_*.npz):
  latent_vec (潜状态 z, 引擎每帧) → 但 JEPA 预测的是 VLM z960? 
  实际: sim_real latent = 引擎融合潜状态 (低维). 训练用引擎流形真值 + latent:
  样本: x_t = latent_vec[t] (z 源) + u_exec_vec[t] (动作 a)
        y   = mani_*[t+1] (未来流形真值 6 维)
模型: LatentPredictor(z_dim, 4) → z'  → ManifoldReadout → 6 维流形
loss: MSE(预测流形, 未来真值流形) — 监督学习 (JEPA 潜空间一致性的状态空间落地)

输出: models/jepa_predictor.pt (LatentPredictor+ManifoldReadout 打包)
"""
import sys, os, glob
import numpy as np
import torch
from torch import nn

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "manifold"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

def collect_data():
    """从 episode npz 收集 (z, a, y6) 样本 — z=latent_vec, a=u_exec, y=下一帧流形真值"""
    Xz, Xa, Y = [], [], []
    n_ep = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "reports", "ss_episode_*.npz"))):
        try:
            d = np.load(f, allow_pickle=True)
        except Exception:
            continue
        if "latent_vec" not in d or "u_exec_vec" not in d:
            continue
        z = np.asarray(d["latent_vec"], dtype=np.float32)
        a = np.asarray(d["u_exec_vec"], dtype=np.float32)
        # 流形真值列 (部分 episode 可能缺 — 引擎 full 模式才有)
        need = ["mani_progress", "mani_risk", "mani_V", "mani_eta", "mani_rem", "mani_dperp"]
        if not all(k in d for k in need):
            continue
        cols = [np.asarray(d[k], dtype=np.float32).reshape(-1) for k in need]
        y = np.stack(cols, axis=1)
        T = min(len(z), len(a), len(y))
        if T < 5:
            continue
        # 样本: t → t+1 (预测未来一帧流形)
        Xz.append(z[:T - 1]); Xa.append(a[:T - 1]); Y.append(y[1:T])
        n_ep += 1
    if not Xz:
        raise RuntimeError("无可用 episode (需含 latent_vec + u_exec_vec + mani_* 6列)")
    Xz = np.concatenate(Xz); Xa = np.concatenate(Xa); Y = np.concatenate(Y)
    print(f"数据: {n_ep} episodes · {len(Y)} 样本 · z_dim={Xz.shape[1]} a_dim={Xa.shape[1]} y={Y.shape[1]}维")
    return Xz, Xa, Y, n_ep

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--z-dim", type=int, default=None, help="默认自动取数据 z 维")
    ap.add_argument("--out", default="models/jepa_predictor.pt")
    ap.add_argument("--epochs", type=int, default=30)
    args = ap.parse_args()

    Xz, Xa, Y, n_ep = collect_data()
    z_dim = args.z_dim or Xz.shape[1]
    act_dim = Xa.shape[1]

    # 归一化 y (6 维流形量纲不同: progress/risk 米, V 势, eta 0-1)
    y_mean = Y.mean(0); y_std = Y.std(0) + 1e-6
    Yn = (Y - y_mean) / y_std

    # 模型: WorldModelPredictor (LatentPredictor + ManifoldReadout 组装, 与引擎接入同款)
    from predictor_layer import WorldModelPredictor
    wm = WorldModelPredictor(z_dim=z_dim, act_dim=act_dim, manifold_dim=6,
                             hidden_dim=256, num_layers=3)
    pred, readout = wm.predictor, wm.readout
    opt = torch.optim.AdamW(wm.parameters(), lr=3e-4, weight_decay=1e-5)
    lossf = nn.MSELoss()

    # train/val split
    n = len(Yn); idx = np.random.RandomState(42).permutation(n)
    n_tr = int(n * 0.9)
    tr_i, va_i = idx[:n_tr], idx[n_tr:]

    Xzt = torch.from_numpy(Xz[tr_i]); Xat = torch.from_numpy(Xa[tr_i]); Yt = torch.from_numpy(Yn[tr_i])
    Xzv = torch.from_numpy(Xz[va_i]); Xav = torch.from_numpy(Xa[va_i]); Yv = torch.from_numpy(Yn[va_i])

    BS = 256
    for ep in range(args.epochs):
        pred.train(); readout.train()
        order = np.random.permutation(n_tr)
        tot = 0
        for b0 in range(0, n_tr, BS):
            bi = order[b0:b0 + BS]
            zb = Xzt[bi]; ab = Xat[bi]; yb = Yt[bi]
            z_pred = pred(zb, ab)
            y_pred = readout(z_pred)
            loss = lossf(y_pred, yb)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss) * len(bi)
        # val
        pred.eval(); readout.eval()
        with torch.no_grad():
            yv_p = readout(pred(Xzv, Xav))
            vloss = float(lossf(yv_p, Yv))
        if ep % 5 == 0 or ep == args.epochs - 1:
            print(f"ep {ep}: train_loss={tot / n_tr:.4f} val_loss={vloss:.4f}")

    # 保存 (含归一化参数)
    os.makedirs(os.path.dirname(os.path.join(ROOT, args.out)), exist_ok=True)
    torch.save({"model": wm.state_dict(), "z_dim": z_dim, "act_dim": act_dim,
                "y_mean": y_mean, "y_std": y_std,
                "val_loss": vloss, "episodes": n_ep, "n_samples": n},
               os.path.join(ROOT, args.out))
    print(f"✅ 已保存 {os.path.join(ROOT, args.out)} (val_loss {vloss:.4f})")

if __name__ == "__main__":
    main()
