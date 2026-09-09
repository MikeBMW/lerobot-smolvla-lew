#!/usr/bin/env python3
"""L4 流形预测器 v4: v2(512/4层+分维加权) × v3(CY 一致性正则+干扰数据) 融合
目标: clean 与 干扰 双高 (v2 clean 39.3% / v3 抗干扰 29.5%)"""
import sys, os, time, json
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools/gui")
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/src/lerobot/manifold")
os.chdir("/home/ubuntu/lerobot-smolvla-lew/tools/gui")
import numpy as np
import torch, torch.nn as nn

torch.manual_seed(0); np.random.seed(0)
d1 = np.load("/tmp/mani_v3.npz"); d2 = np.load("/tmp/mani_jitter.npz")
Z = np.concatenate([d1["z"], d2["z"]]); A = np.concatenate([d1["a"], d2["a"]])
M = np.concatenate([d1["m"], d2["m"]]); ZN = np.concatenate([d1["zn"], d2["zn"]])
SD = np.concatenate([d1["seed"], d2["seed"]])
print(f"数据 {len(Z)} (clean {len(d1['z'])} + jitter {len(d2['z'])})")
TEST_CLEAN = [7, 9]; TEST_JIT = [901]
te_clean = np.isin(SD, TEST_CLEAN); te_jit = np.isin(SD, TEST_JIT)
tr_mask = ~(te_clean | te_jit)
print(f"train {tr_mask.sum()} · test_clean {te_clean.sum()} · test_jit {te_jit.sum()}")

from predictor_layer import WorldModelPredictor, cy_consistency_loss
from torch.utils.data import TensorDataset, DataLoader
tens = lambda x: torch.from_numpy(np.asarray(x, np.float32))
tr_dl = DataLoader(TensorDataset(tens(Z[tr_mask]), tens(A[tr_mask]), tens(ZN[tr_mask]),
                                 tens(M[tr_mask])), batch_size=256, shuffle=True)

W6 = torch.tensor([1.0, 3.0, 1.0, 1.0, 3.0, 3.0])   # risk/rem/dperp ×3 (v2 分维加权)
TOL = np.array([0.03, 0.01, 0.01, 0.05, 0.015, 0.015])
def evaluate(wm, tag):
    wm.eval()
    with torch.no_grad():
        out = wm(tens(Z), tens(A))
    err = (out["manifold"] - tens(M)).abs().numpy()
    r = {}
    for key, sel in (("clean", te_clean), ("jit", te_jit)):
        e = err[sel]; ok = (e <= TOL).all(1); rem = M[sel][:, 4]
        ins = rem < 0.06
        r[key] = {"succ": float(ok.mean()),
                  "ins": float(ok[ins].mean()) if ins.sum() else None}
        print(f"[{tag}·{key}] 成功率 {ok.mean()*100:.1f}% · 插拔段 {ok[ins].mean()*100:.1f}%")
    return r

# v4: 512/4 层 + 分维加权 + CY 正则 + 干扰数据
wm = WorldModelPredictor(z_dim=7, act_dim=4, manifold_dim=6, hidden_dim=512, num_layers=4)
opt = torch.optim.AdamW(wm.parameters(), lr=1.5e-3, weight_decay=1e-5)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=350)
keep = np.zeros(len(Z), bool); keep[:-1] = SD[:-1] == SD[1:]
pairs = np.stack([np.where(keep)[0], np.where(keep)[0] + 1], 1)
pairs = pairs[tr_mask[pairs[:, 0]]]
print(f"CY 对 {len(pairs)}")
t0 = time.time()
for ep in range(350):
    wm.train(); tl = 0.0; nb = 0
    for z, a, zn, m in tr_dl:
        opt.zero_grad()
        out = wm(z, a)
        mw = (out["manifold"] - m).pow(2) * W6
        loss = 0.5 * nn.functional.mse_loss(out["z_pred"], zn) + mw.mean()
        idx = np.random.choice(len(pairs), min(64, len(pairs)), replace=False)
        za = torch.from_numpy(Z[pairs[idx, 0]].astype(np.float32))
        aa = torch.from_numpy(A[pairs[idx, 0]].astype(np.float32))
        zb = torch.from_numpy(Z[pairs[idx, 1]].astype(np.float32))
        ab = torch.from_numpy(A[pairs[idx, 1]].astype(np.float32))
        # 🐛 2026-09-09 修正 (消融实锤): 原 oa/ob detached → CY 梯度恒 0 = 摆设!
        #   CY 必须约束模型输出 → 梯度流经 oa/ob (Lipschitz 正则真正生效)
        oa = wm(za, aa)["manifold"]; ob = wm(zb, ab)["manifold"]
        cy = cy_consistency_loss(za, aa, oa, zb, ob)
        loss = loss + 0.3 * cy
        loss.backward(); opt.step()
        tl += loss.item(); nb += 1
    sched.step()
    if ep % 50 == 0:
        print(f"ep {ep} loss {tl/nb:.5f} cy={cy.item():.5f} ({time.time()-t0:.0f}s)", flush=True)
torch.save(wm.state_dict(), "/tmp/mani_v4cy_trained.pt")
print(f"训练完成 {time.time()-t0:.0f}s · {sum(p.numel() for p in wm.parameters()):,} 参数")
r = evaluate(wm, "v4-CY修复")
json.dump({"v4-CY修复": r}, open("/tmp/mani_v4_result.json", "w"), ensure_ascii=False, indent=1)
print(f"\n🎯 v4: clean {r['clean']['succ']*100:.1f}% · 抗干扰 {r['jit']['succ']*100:.1f}%")
print(f"   对照: v3 clean 33.6/抗扰 29.5 · v2 clean 39.3")
