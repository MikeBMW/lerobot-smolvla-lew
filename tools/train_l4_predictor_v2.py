#!/usr/bin/env python3
"""v2: L4 流形预测器改进 — 目标: 提 rem(28%)/dperp(48%) 短板

改进点 vs v1 (train_l4_v3.py):
1. 更多数据: 扩 seed 覆盖 (insert 16 seed + full 10 seed 含失败轨迹)
2. 分维加权损失: rem/dperp/risk 权重 3× (短板维度重点学)
3. 更大容量: hidden 512 + 4 层 (342K → ~700K 参数, 数据量够)
4. 更长训练: 400 ep + cosine
5. 评估同 v1: test seed 7/9 布局族泛化 (未见布局)
"""
import sys, os, time, json
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools/gui")
os.chdir("/home/ubuntu/lerobot-smolvla-lew/tools/gui")
import numpy as np
import torch, torch.nn as nn

def collect(seeds, mode="insert"):
    from state_space_sim_real import RealStateSpaceSim
    Z, A, M, ZN, SEED = [], [], [], [], []
    for s in seeds:
        sim = RealStateSpaceSim(seed=s, vision=False, mode=mode, log=lambda *a: None)
        tr = sim.run()
        n = len(tr["t"])
        if n < 3:
            continue
        z7s = [np.asarray(v, float).ravel() for v in tr.get("z7_vec", [])]
        if len(z7s) < n:
            print(f"  seed {s} [{mode}] 无 z7_vec 跳过"); continue
        for i in range(n - 1):
            m6 = np.array([tr["mani_progress"][i], tr["mani_risk"][i], tr["mani_V"][i],
                           tr["mani_eta"][i], tr["mani_rem"][i], tr["mani_dperp"][i]], float)
            if np.abs(m6).max() < 1e-6:
                continue
            a4 = np.asarray(tr["u_exec_vec"][i], float).ravel()[:4]
            Z.append(z7s[i]); A.append(a4 if a4.size == 4 else np.zeros(4))
            M.append(m6); ZN.append(z7s[i+1]); SEED.append(s)
        print(f"  seed {s} [{mode}] {n}步", flush=True)
    return Z, A, M, ZN, SEED

CACHE = "/tmp/mani_v2data.npz"
if not os.path.exists(CACHE):
    Z, A, M, ZN, SEED = [], [], [], [], []
    # insert 训练 seed (扩展: 含更多布局族)
    for s in [0, 1, 2, 3, 10, 11, 13, 14, 20, 21, 22, 23, 30, 31, 100, 101]:
        z, a, m, zn, sd = collect([s], "insert"); Z += z; A += a; M += m; ZN += zn; SEED += sd
    # full 训练 (含失败轨迹 4/12 + 成功 5/6/8 + 更多)
    for s in [0, 4, 5, 6, 8, 12, 50, 51, 102]:
        z, a, m, zn, sd = collect([s], "full"); Z += z; A += a; M += m; ZN += zn; SEED += sd
    np.savez(CACHE, z=np.array(Z), a=np.array(A), m=np.array(M),
             zn=np.array(ZN), seed=np.array(SEED))
else:
    d = np.load(CACHE); Z, A, M, ZN, SEED = d["z"], d["a"], d["m"], d["zn"], d["seed"]
Z, A, M, ZN, SEED = map(np.asarray, (Z, A, M, ZN, SEED))
print(f"数据 {len(Z)} 帧 · z{Z.shape} a{A.shape} m{M.shape}")

TEST_SEEDS = [7, 9]   # 未训练布局族 (泛化测试)
tr = ~np.isin(SEED, TEST_SEEDS); te = np.isin(SEED, TEST_SEEDS)
print(f"train {tr.sum()} (seed {sorted(set(SEED[tr]))}) · test {te.sum()} (seed {TEST_SEEDS})")

sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/src/lerobot/manifold")
from predictor_layer import WorldModelPredictor
from torch.utils.data import TensorDataset, DataLoader
tens = lambda x: torch.from_numpy(np.asarray(x, np.float32))
tr_dl = DataLoader(TensorDataset(tens(Z[tr]), tens(A[tr]), tens(ZN[tr]), tens(M[tr])), batch_size=256, shuffle=True)
te_dl = DataLoader(TensorDataset(tens(Z[te]), tens(A[te]), tens(ZN[te]), tens(M[te])), batch_size=1024)

TOL = np.array([0.03, 0.01, 0.01, 0.05, 0.015, 0.015])
NAMES = ["progress", "risk", "V", "eta", "rem", "dperp"]
def eval_full(wm, tag):
    wm.eval()
    with torch.no_grad():
        z = tens(Z[te]); a = tens(A[te]); m = tens(M[te])
        out = wm(z, a)
    err = (out["manifold"] - m).abs().numpy()
    ok = (err <= TOL).all(1)
    rem = M[te][:, 4]
    ins = rem < 0.06
    pd = (err <= TOL).mean(0)
    print(f"[{tag}] 成功率: {ok.mean()*100:.1f}% ({ok.sum()}/{len(ok)}) · "
          f"插入段({ins.sum()}帧): {ok[ins].mean()*100:.1f}% · 转移段: {ok[~ins].mean()*100:.1f}%")
    print(f"        分维: " + " ".join(f"{n}={pd[i]*100:.0f}%" for i, n in enumerate(NAMES)))
    print(f"        MAE: {err.mean(0).round(4)} · z'RMSE={float((out['z_pred']-tens(ZN[te])).pow(2).mean(1).sqrt().mean()):.4f}")
    return ok.mean()

# 随机基线
wm0 = WorldModelPredictor(z_dim=7, act_dim=4, manifold_dim=6, hidden_dim=512, num_layers=4)
r0 = eval_full(wm0, "随机基线")

# 训练 (v2: 更大容量 + 分维加权 + 长训)
torch.manual_seed(0)
wm = WorldModelPredictor(z_dim=7, act_dim=4, manifold_dim=6, hidden_dim=512, num_layers=4)
print(f"参数: {sum(p.numel() for p in wm.parameters()):,}")
W6 = torch.tensor([1.0, 3.0, 1.0, 1.0, 3.0, 3.0])   # rem/dperp/risk 短板加权
opt = torch.optim.AdamW(wm.parameters(), lr=1.5e-3, weight_decay=1e-5)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=400)
t0 = time.time()
for ep in range(400):
    wm.train(); tl = 0.0; nb = 0
    for z, a, zn, m in tr_dl:
        opt.zero_grad()
        out = wm(z, a)
        mw = (out["manifold"] - m).pow(2) * W6
        loss = 0.5 * nn.functional.mse_loss(out["z_pred"], zn) + mw.mean()
        loss.backward(); opt.step()
        tl += loss.item(); nb += 1
    sched.step()
    if ep % 50 == 0:
        print(f"ep {ep} loss {tl/nb:.5f} ({time.time()-t0:.0f}s)", flush=True)
torch.save(wm.state_dict(), "/tmp/mani_v2_trained.pt")
print(f"训练完成 {time.time()-t0:.0f}s · {sum(p.numel() for p in wm.parameters()):,} 参数")
r1 = eval_full(wm, "v2训练后")
print(f"\n🎯 v2 流形预测成功率: {r0*100:.1f}% → {r1*100:.1f}% (v1 基线 16.4%)")
json.dump({"base": float(r0), "trained": float(r1), "tol": TOL.tolist()}, open("/tmp/mani_v2_result.json", "w"))
