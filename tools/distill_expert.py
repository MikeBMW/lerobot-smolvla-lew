#!/usr/bin/env python3
"""专家策略蒸馏 — 用官方专家生成大量数据, BC 训练 MLP 神经网络模型 (插拔)
2026-08-06 老倪要求: 必须能插拔
方案: 专家策略 85% 成功率 (19/20 抓起 17/20 插入) → 蒸馏成 MLP 模型
      MLP 输入 39 维 obs → 输出 4 维动作 (3D 速度 + 夹爪)
"""
import os, sys, json, time
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
HIDDEN = 512

class ExpertMLP(nn.Module):
    def __init__(self, obs_dim=39, act_dim=4):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(),
            nn.Linear(HIDDEN, act_dim))
        self.obs_dim = obs_dim
        self.act_dim = act_dim
    def forward(self, x):
        return self.net(x)

def collect_expert_data(n_eps=300):
    """用官方专家生成 (obs, action) 数据"""
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=0)
    expert = SawyerPegInsertionSideV3Policy()
    xs, ys = [], []
    ok = 0
    for ep in range(n_eps):
        env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array")
        env.set_task(mt.train_tasks[0]); env._freeze_rand_vec = False
        obs, _ = env.reset(seed=ep % 50)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        lifted = False; inserted = False
        for i in range(300):
            o = np.asarray(env._get_obs(), dtype=np.float32).ravel()
            a = np.asarray(expert.get_action(o.astype(np.float64)), dtype=np.float32).ravel()[:4]
            xs.append(o); ys.append(a)
            obs, _, term, trunc, _ = env.step(a)
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            if peg[2] - peg_z0 > 0.05: lifted = True
            if lifted and np.linalg.norm(peg - hole) < 0.05: inserted = True
            if term or trunc: break
        ok += int(inserted)
    print(f"  专家数据: {len(xs)} 样本, 插入率 {ok}/{n_eps} = {ok/n_eps:.0%}")
    return np.stack(xs), np.stack(ys)

def main():
    print(f"🧠 专家蒸馏 (MLP BC) · peg-insert-side-v3 · device={DEVICE}")
    # 1. 收集专家数据
    X, Y = collect_expert_data(n_eps=300)
    print(f"  X={X.shape} Y={Y.shape}")
    # 2. 训练 MLP
    model = ExpertMLP(X.shape[1], Y.shape[1]).to(DEVICE)
    opt = optim.Adam(model.parameters(), lr=1e-3)
    sched = optim.lr_scheduler.StepLR(opt, step_size=5, gamma=0.5)
    X_t = torch.from_numpy(X).float().to(DEVICE)
    Y_t = torch.from_numpy(Y).float().to(DEVICE)
    for epoch in range(15):
        idx = torch.randperm(len(X_t))
        tot_loss = 0
        for b in range(0, len(X_t), 512):
            bi = idx[b:b+512]
            pred = model(X_t[bi])
            loss = nn.functional.mse_loss(pred, Y_t[bi])
            opt.zero_grad(); loss.backward(); opt.step()
            tot_loss += loss.item() * len(bi)
        sched.step()
        print(f"  epoch {epoch}: loss={tot_loss/len(X_t):.4f}", flush=True)
    # 3. 保存
    os.makedirs(os.path.join(ROOT, "outputs", "rl_peg"), exist_ok=True)
    torch.save({"model": model.state_dict(), "obs_dim": X.shape[1], "act_dim": Y.shape[1]},
               os.path.join(ROOT, "outputs", "rl_peg", "expert_mlp.pt"))
    print(f"✅ 已保存: outputs/rl_peg/expert_mlp.pt")

if __name__ == "__main__":
    main()
