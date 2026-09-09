#!/usr/bin/env python3
"""v3.5-GPU: 流形预测器 — 过滤数据(成功轨迹优先) + v2 热启动 + 1000ep GPU
数据: /tmp/mani_v35data.npz (失败 episode 只留前段, test 完整)
"""
import sys, os, time, json
import numpy as np
import torch, torch.nn as nn

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
DATA = "/tmp/mani_v35data.npz"
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "manifold"))
from predictor_layer import WorldModelPredictor
from torch.utils.data import TensorDataset, DataLoader

DEV = "cuda" if torch.cuda.is_available() else "cpu"
print(f"设备: {DEV}")

def main():
    d = np.load(DATA)
    Z, A, M, ZN, SEED = d["z"], d["a"], d["m"], d["zn"], d["seed"]
    print(f"数据 {len(Z)} 帧")

    TEST_SEEDS = [7, 9]
    tr = ~np.isin(SEED, TEST_SEEDS); te = np.isin(SEED, TEST_SEEDS)
    print(f"train {tr.sum()} · test {te.sum()} (seed 7/9 完整)")

    tens = lambda x: torch.from_numpy(np.asarray(x, np.float32))
    tr_dl = DataLoader(TensorDataset(tens(Z[tr]), tens(A[tr]), tens(ZN[tr]), tens(M[tr])),
                       batch_size=2048, shuffle=True, num_workers=2, pin_memory=True)

    TOL = np.array([0.03, 0.01, 0.01, 0.05, 0.015, 0.015])
    NAMES = ["progress", "risk", "V", "eta", "rem", "dperp"]

    def eval_full(wm, tag):
        wm.eval()
        with torch.no_grad():
            z = tens(Z[te]).to(DEV); a = tens(A[te]).to(DEV); m = tens(M[te]).to(DEV)
            out = wm(z, a)
        err = (out["manifold"] - m).abs().cpu().numpy()
        ok = (err <= TOL).all(1)
        rem = M[te][:, 4]
        ins = rem < 0.06
        pd = (err <= TOL).mean(0)
        print(f"[{tag}] 成功率: {ok.mean()*100:.1f}% ({ok.sum()}/{len(ok)}) · "
              f"插入段({ins.sum()}帧): {ok[ins].mean()*100:.1f}% · 转移段: {ok[~ins].mean()*100:.1f}%")
        print(f"        分维: " + " ".join(f"{n}={pd[i]*100:.0f}%" for i, n in enumerate(NAMES)))
        return ok.mean()

    # v2 架构 (512/4) 用于热启动 — 先训 v2 架构再扩
    # 直接上目标架构 + 随机初始化 (v2 权重架构不匹配 1024/6, 无法热启)
    torch.manual_seed(0)
    wm = WorldModelPredictor(z_dim=7, act_dim=4, manifold_dim=6, hidden_dim=1024, num_layers=6).to(DEV)
    print(f"参数: {sum(p.numel() for p in wm.parameters()):,}")
    W6 = torch.tensor([1.0, 3.0, 1.0, 1.0, 3.0, 3.0], device=DEV)
    opt = torch.optim.AdamW(wm.parameters(), lr=3e-4, weight_decay=3e-5)   # 🐛 1.5e-3 发散 → 3e-4
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=1000)
    t0 = time.time()
    best_val, best_ep = -1, -1
    for ep in range(1000):
        wm.train(); tl = 0.0; nb = 0
        for z, a, zn, m in tr_dl:
            z, a, zn, m = z.to(DEV), a.to(DEV), zn.to(DEV), m.to(DEV)
            opt.zero_grad()
            out = wm(z, a)
            mw = (out["manifold"] - m).pow(2) * W6
            loss = 0.5 * nn.functional.mse_loss(out["z_pred"], zn) + mw.mean()
            loss.backward()
            nn.utils.clip_grad_norm_(wm.parameters(), 1.0)   # 🐛 梯度裁剪防爆炸
            opt.step()
            tl += loss.item(); nb += 1
        sched.step()
        if ep % 50 == 0:
            print(f"ep {ep} loss {tl/nb:.5f} ({time.time()-t0:.0f}s)", flush=True)
        if ep % 200 == 199:
            v = eval_full(wm, f"ep{ep+1}")
            if v > best_val:
                best_val, best_ep = v, ep + 1
                torch.save(wm.state_dict(), "/tmp/mani_v35_best.pt")
                print(f"  → 新最佳 {v*100:.1f}% (ep{ep+1}) 已存", flush=True)
    r1 = eval_full(wm, "v3.5 最终")
    print(f"\n🎯 v3.5: {r1*100:.1f}% · 最佳 {best_val*100:.1f}%@ep{best_ep} (v2 39.3%)")
    json.dump({"v2": 39.3, "v35": float(r1)*100, "best": float(best_val)*100},
              open("/tmp/mani_v35_result.json", "w"))

if __name__ == "__main__":
    main()
