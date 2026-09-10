#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训 target-decoder: (阶段+几何) → 期望位置 target  —— S3' decoder v1 (轻量, GPU)

双头共享主干:
  head_target: 学引擎规则意图 _stage_target()  (验证链路/回归基线)
  head_next  : 学成功轨迹的真实运动 x_{t+1}    (有增益潜力: 吸收轨迹里的技巧)

按 episode 划分 train/val (防同轨迹泄漏)。产物: outputs/target_decoder/model.pt + result.json
用法: cd repo && gui-venv311/bin/python tools/train_target_decoder.py [epochs]
"""
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn

ROOT = '/home/ubuntu/lerobot-smolvla-lew'
os.chdir(ROOT)
EPOCHS = int(sys.argv[1]) if len(sys.argv) > 1 else 150
DEV = 'cuda' if torch.cuda.is_available() else 'cpu'

d = np.load(os.path.join(ROOT, 'data', 'target_decoder_data.npz'))
X, Yt, Yn, ep = d['X'], d['Y_target'], d['Y_next'], d['episode']
print(f"① 数据: {X.shape[0]} 帧 / {len(set(ep.tolist()))} 轨迹 · 特征 {X.shape[1]}D · device={DEV}")

# 按 episode 划分
eps = sorted(set(ep.tolist()))
rng = np.random.RandomState(0)
rng.shuffle(eps)
n_val = max(1, int(len(eps) * 0.2))
val_eps = set(eps[:n_val])
m_tr = ~np.isin(ep, list(val_eps))
Xtr, Xva = X[m_tr], X[~m_tr]
Ttr, Tva = Yt[m_tr], Yt[~m_tr]
Ntr, Nva = Yn[m_tr], Yn[~m_tr]
print(f"② 划分: 训练 {Xtr.shape[0]} 帧 ({len(eps)-n_val} 轨迹) / 验证 {Xva.shape[0]} 帧 ({n_val} 轨迹)")

mu, sd = Xtr.mean(0, keepdims=True), Xtr.std(0, keepdims=True) + 1e-6
# 标签用 mm 尺度归一 (便于观察 mm 级误差); 位置量纲 m
tmu, tsd = Ttr.mean(0, keepdims=True), Ttr.std(0, keepdims=True) + 1e-6
nmu, nsd = Ntr.mean(0, keepdims=True), Ntr.std(0, keepdims=True) + 1e-6


def tt(a):
    return torch.from_numpy(a).float().to(DEV)


Xtr_t, Xva_t = tt((Xtr - mu) / sd), tt((Xva - mu) / sd)
Ttr_t, Tva_t = tt((Ttr - tmu) / tsd), tt((Tva - tmu) / tsd)
Ntr_t, Nva_t = tt((Ntr - nmu) / nsd), tt((Nva - nmu) / nsd)


class Net(nn.Module):
    def __init__(self, din, h=256):
        super().__init__()
        self.body = nn.Sequential(nn.Linear(din, h), nn.SiLU(), nn.Linear(h, h), nn.SiLU())
        self.head_t = nn.Linear(h, 3)
        self.head_n = nn.Linear(h, 3)

    def forward(self, x):
        f = self.body(x)
        return self.head_t(f), self.head_n(f)


net = Net(X.shape[1]).to(DEV)
nparam = sum(p.numel() for p in net.parameters())
print(f"③ 模型: MLP 256-256 双头 · 参数量 {nparam:,}")
opt = torch.optim.AdamW(net.parameters(), lr=3e-4, weight_decay=1e-5)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)
lossf = nn.MSELoss()
BS = 512
t0 = time.time()
best = 9e9
for ep_i in range(EPOCHS):
    net.train()
    perm = torch.randperm(Xtr_t.shape[0], device=DEV)
    tot = 0.0
    nb = 0
    for i in range(0, Xtr_t.shape[0], BS):
        idx = perm[i:i + BS]
        ot, on = net(Xtr_t[idx])
        loss = lossf(ot, Ttr_t[idx]) + lossf(on, Ntr_t[idx])
        opt.zero_grad(); loss.backward(); opt.step()
        tot += float(loss); nb += 1
    sched.step()
    if (ep_i + 1) % max(1, EPOCHS // 15) == 0 or ep_i == 0 or ep_i == EPOCHS - 1:
        net.eval()
        with torch.no_grad():
            ot, on = net(Xva_t)
            # 反归一化 → mm 误差
            pt = ot.cpu().numpy() * tsd + tmu
            pn = on.cpu().numpy() * nsd + nmu
            mae_t = float(np.abs(pt - Tva).mean() * 1000)
            mae_n = float(np.abs(pn - Nva).mean() * 1000)
            rmse_n = float(np.sqrt(((pn - Nva) ** 2).mean()) * 1000)
        print(f"  ep{ep_i+1:>4}/{EPOCHS} loss={tot/max(nb,1):.4f} | val MAE target={mae_t:.2f}mm "
              f"next={mae_n:.2f}mm rmse_next={rmse_n:.2f}mm | {time.time()-t0:.0f}s", flush=True)
        if mae_n < best:
            best = mae_n
            os.makedirs(os.path.join(ROOT, 'outputs', 'target_decoder'), exist_ok=True)
            torch.save({'state': net.state_dict(), 'mu': mu, 'sd': sd, 'tmu': tmu, 'tsd': tsd,
                        'nmu': nmu, 'nsd': nsd, 'stages': d['stages'].tolist()},
                       os.path.join(ROOT, 'outputs', 'target_decoder', 'model.pt'))

res = {'frames': int(X.shape[0]), 'episodes': len(eps), 'params': int(nparam),
       'epochs': EPOCHS, 'val_mae_next_mm': round(best, 3),
       'device': DEV, 'seconds': round(time.time() - t0, 1)}
json.dump(res, open(os.path.join(ROOT, 'outputs', 'target_decoder', 'result.json'), 'w'),
          ensure_ascii=False, indent=1)
print(f"\n✅ 完成: {res}")
