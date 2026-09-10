#!/usr/bin/env python3
"""条件时序控制 MLP — 2026-08-10 老倪: 增加条件时序控制改造
方案 (层级策略落地): MLP 输入 = 39D obs + 条件时序向量 (阶段onehot 4D + 时序上下文 2D) = 45D
  阶段: 0接近 1抓取 2抬起 3插入 (W2-CoT 标注)
  时序上下文: [阶段内进度, 总进度] (0~1)
训练: 专家轨迹 → 按阶段标注 (W2-CoT) → 条件 MLP 学 "阶段条件动作"
推理: 决策器 (规则/MLP) 选阶段 → 条件 MLP 输出该阶段动作
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
STAGE_NAMES = ["接近", "抓取", "抬起", "插入"]

class CondTimingMLP(nn.Module):
    """条件时序控制 MLP: 39D obs + 4D阶段onehot + 2D时序上下文 = 45D → 4D 动作"""
    def __init__(self, obs_dim=39, act_dim=4, cond_dim=6):
        super().__init__()
        self.obs_dim = obs_dim
        self.act_dim = act_dim
        self.cond_dim = cond_dim
        self.net = nn.Sequential(
            nn.Linear(obs_dim + cond_dim, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(),
            nn.Linear(HIDDEN, act_dim))
    def forward(self, x):
        return self.net(x)

def make_env(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    return env

def get_obs(env):
    return np.asarray(env._get_obs(), dtype=np.float32).ravel()

def compute_stage(env, peg_z0, hole, lifted_prev):
    """条件时序阶段判定 (同 W2-CoT): 0接近 1抓取 2抬起 3插入"""
    hand = env.data.site_xpos[env.model.site("endEffector").id]
    peg = env.data.site_xpos[env.model.site("pegGrasp").id]
    d_hp = float(np.linalg.norm(hand - peg))
    d_ph = float(np.linalg.norm(peg - hole))
    lifted = float(peg[2]) - peg_z0 > 0.02
    if lifted:
        return 3 if d_ph < 0.15 else 2, lifted
    return 1 if d_hp < 0.08 else 0, lifted

def cond_vec(stage, prog_in_stage, total_prog):
    """条件时序向量: 阶段onehot 4D + 时序上下文 2D"""
    oh = np.zeros(4, dtype=np.float32)
    oh[stage] = 1.0
    return np.concatenate([oh, [prog_in_stage, total_prog]]).astype(np.float32)

def collect_stage_data(n_eps=60):
    """用官方专家采集带阶段标注的数据"""
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    expert = SawyerPegInsertionSideV3Policy()
    X, Y, S = [], [], []  # obs, action, stage
    for ep in range(n_eps):
        env = make_env(ep)
        o = get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        lifted = False
        n_steps = 0
        for _ in range(300):
            o_expert = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            a = np.asarray(expert.get_action(o_expert), dtype=np.float32)[:4]
            stage, lifted = compute_stage(env, peg_z0, hole, lifted)
            X.append(o); Y.append(a); S.append(stage)
            env.step(a)
            o = get_obs(env)
            n_steps += 1
            if env.data.site_xpos[env.model.site("pegGrasp").id][2] - peg_z0 > 0.05 and \
               np.linalg.norm(env.data.site_xpos[env.model.site("pegGrasp").id] - hole) < 0.05:
                break  # 插入成功
        env.close()
    return np.stack(X), np.stack(Y), np.array(S)

def main():
    print(f"⏱ 条件时序控制 MLP · {DEVICE}", flush=True)
    X, Y, S = collect_stage_data(n_eps=40)
    print(f"  📦 数据: {len(X)}帧 · 阶段分布: "
          + " ".join(f"{STAGE_NAMES[i]}={np.sum(S==i)}" for i in range(4)), flush=True)
    # 条件时序向量: 阶段 onehot + 阶段内进度 + 总进度
    Xc = []
    for i in range(len(X)):
        # 阶段内进度: 连续同阶段帧计数
        prog = 0.0
        if i > 0 and S[i] == S[i-1]:
            prog = getattr(main, "_last_prog", 0.0) + 1.0 / 50.0
        else:
            prog = 0.0
        main._last_prog = prog
        total = i / max(1, len(X))
        Xc.append(np.concatenate([X[i], cond_vec(S[i], min(prog, 1.0), total)]))
    Xc = np.stack(Xc).astype(np.float32)
    # 归一化
    x_mean, x_std = Xc.mean(0), Xc.std(0) + 1e-6
    y_mean, y_std = Y.mean(0), Y.std(0) + 1e-6
    Xn = (Xc - x_mean) / x_std
    Yn = (Y - y_mean) / y_std
    model = CondTimingMLP(39, 4, 6).to(DEVICE)
    opt = optim.Adam(model.parameters(), lr=1e-3)
    Xt = torch.from_numpy(Xn).float().to(DEVICE)
    Yt = torch.from_numpy(Yn).float().to(DEVICE)
    for ep in range(300):
        idx = torch.randperm(len(Xt), device=DEVICE)[:256]
        pred = model(Xt[idx])
        loss = nn.functional.mse_loss(pred, Yt[idx])
        opt.zero_grad(); loss.backward(); opt.step()
        if ep % 50 == 0:
            print(f"  iter{ep}: loss={loss.item():.5f}", flush=True)
    print(f"  ✅ 条件时序 MLP 训练完成 (loss={loss.item():.5f})", flush=True)
    os.makedirs(os.path.join(ROOT, "outputs", "rl_peg"), exist_ok=True)
    torch.save({"model": model.state_dict(), "obs_dim": 39, "act_dim": 4, "cond_dim": 6,
                "x_mean": x_mean, "x_std": x_std, "y_mean": y_mean, "y_std": y_std},
               os.path.join(ROOT, "outputs", "rl_peg", "cond_timing_mlp.pt"))
    print(f"  💾 保存: outputs/rl_peg/cond_timing_mlp.pt", flush=True)

    # 评估: 规则决策器选阶段 → 条件 MLP 执行
    print("\n🧪 评估: 规则决策器 + 条件时序 MLP", flush=True)
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    lifts = ins = 0
    for seed in range(8):
        env = make_env(seed)
        o = get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        lifted = False
        model.eval()
        for step in range(300):
            stage, lifted = compute_stage(env, peg_z0, hole, lifted)
            cvec = cond_vec(stage, min(step/50.0, 1.0), step/300.0)
            xin = torch.from_numpy(np.concatenate([o, cvec]).astype(np.float32)).to(DEVICE)
            xin_n = (xin - torch.from_numpy(x_mean).float().to(DEVICE)) / torch.from_numpy(x_std).float().to(DEVICE)
            with torch.no_grad():
                pred = model(xin_n.unsqueeze(0)).squeeze(0).cpu().numpy()
            act = pred * y_std + y_mean
            # 夹爪控制: 接近/抓取阶段渐闭, 抬起/插入闭合
            d_hp = float(np.linalg.norm(env.data.site_xpos[env.model.site("endEffector").id] -
                                        env.data.site_xpos[env.model.site("pegGrasp").id]))
            if stage >= 1 and d_hp < 0.10: act[3] = -1.0
            elif stage < 1: act[3] = 1.0
            env.step(np.clip(act, -1, 1))
            o = get_obs(env)
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            if peg[2] - peg_z0 > 0.05: lifted = True
            if np.linalg.norm(peg - hole) < 0.05:
                ins += 1; break
        if lifted: lifts += 1
        env.close()
        print(f"  seed{seed}: {'✅' if ins else '❌'}", flush=True)
    print(f"== 条件时序MLP: 抓起={lifts}/8 插入={ins}/8", flush=True)

if __name__ == "__main__":
    main()
