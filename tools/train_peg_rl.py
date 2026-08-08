#!/usr/bin/env python3
"""仿真强化学习 (PPO) — peg-insert-side-v3 插拔
2026-08-06 老倪要求: 仿真强化, 必须能插拔, 完不成不停
关键: 用 39 维完整 obs (含 hand/peg/hole 位置) — BC 模型只有 3D 末端位置所以学不会
Reward 设计:
  - 接近 peg: -dist(hand, pegGrasp)
  - 抓起: peg z 升高 > 5cm → +10 (一次性)
  - 插入: peg 距 hole < 5cm → +50 (一次性)
  - 步数惩罚 -0.01
"""
import os, sys, time, json
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
HIDDEN = 256
MAX_EP_STEPS = 300
GAMMA = 0.99
LAMBDA = 0.95
CLIP = 0.2
LR = 3e-4
EPOCHS = 4
BATCH = 256
STEPS_PER_ITER = 2048   # rollout 步数每轮
ITERS = 60              # 总轮数 (2048*60 ≈ 12万步仿真)

class ActorCritic(nn.Module):
    def __init__(self, obs_dim, act_dim):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(obs_dim, HIDDEN), nn.Tanh(),
                                 nn.Linear(HIDDEN, HIDDEN), nn.Tanh())
        self.mu = nn.Linear(HIDDEN, act_dim)
        self.log_std = nn.Parameter(torch.zeros(act_dim) - 0.5)  # 探索: std≈0.6
        self.critic = nn.Linear(HIDDEN, 1)
    def forward(self, x):
        h = self.net(x)
        return self.mu(h), self.log_std.exp(), self.critic(h)
    def act(self, x):
        mu, std, v = self.forward(x)
        dist = torch.distributions.Normal(mu, std)
        a = dist.sample()
        return a, dist.log_prob(a).sum(-1), v.squeeze(-1)
    def evaluate(self, x, a):
        mu, std, v = self.forward(x)
        dist = torch.distributions.Normal(mu, std)
        return dist.log_prob(a).sum(-1), dist.entropy().sum(-1), v.squeeze(-1)

def make_env(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=seed)
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array")
    env.set_task(mt.train_tasks[0])
    env._freeze_rand_vec = False
    return env, mt

def get_obs(env):
    """39 维 obs (官方策略同款, 含 hand/peg/hole)"""
    o = np.asarray(env._get_obs(), dtype=np.float32).ravel()
    return o

def compute_reward(env, prev_peg_z, prev_dist_hand_peg, prev_dist_peg_hole,
                   prev_peg_dist_hand_xy, info):
    """塑形 reward: 接近 peg + 抓取 + 插入"""
    try:
        hand = env.data.site_xpos[env.model.site("endEffector").id].copy()
        peg = env.data.site_xpos[env.model.site("pegGrasp").id].copy()
        hole = env.data.site_xpos[env.model.site("hole").id].copy()
        peg_z0 = info.get("peg_z0", peg[2])
    except Exception:
        return 0.0, info
    r = 0.0
    # 1) 接近 peg (水平为主, 有增益)
    d_hp = np.linalg.norm(hand - peg)
    r += -0.02 * d_hp
    # 2) 高度匹配 (末端到 peg 抓取高度)
    h_err = abs(hand[2] - peg[2] - 0.03)
    r += -0.05 * h_err
    # 2.5) 抓取就位: xy 对准 peg + 高度匹配 → 鼓励夹爪闭合
    d_xy = np.linalg.norm(hand[:2] - peg[:2])
    if d_xy < 0.03 and h_err < 0.02:
        r += 2.0  # 就位奖励
        info["aligned"] = True
        # 夹爪闭合奖励 (动作的夹爪维度 < 0 时)
        info["gripper_closed"] = bool(info.get("gripper_cmd", 0) < 0)
        if info.get("gripper_closed"):
            r += 3.0  # 就位 + 闭合 → 大奖励
    # 3) 抓起 peg: z 升高 > 5cm
    peg_rise = peg[2] - peg_z0
    if not info.get("grasped") and peg_rise > 0.05:
        r += 10.0
        info["grasped"] = True
    # 4) 抓起后接近 hole
    if info.get("grasped"):
        d_ph = np.linalg.norm(peg - hole)
        r += -0.03 * d_ph
        # 5) 插入成功
        if d_ph < 0.05:
            r += 50.0
            info["inserted"] = True
    # 6) 稀疏奖励 + 步数惩罚
    r -= 0.01
    info["dist_hand_peg"] = d_hp
    info["dist_peg_hole"] = np.linalg.norm(peg - hole) if info.get("grasped") else 999.0
    return r, info

def run_episode(env, model, info, render_every=None):
    """跑一个 episode 收集轨迹 — 2026-08-08 组合: 位置RL + 夹爪规则(grip_assist)"""
    obs = get_obs(env)
    states, actions, logps, rewards, values, dones = [], [], [], [], [], []
    prev_peg_z = info["peg_z0"]
    lifted = False
    for t in range(MAX_EP_STEPS):
        s_t = torch.from_numpy(obs).float().unsqueeze(0).to(DEVICE)
        with torch.no_grad():
            a, lp, v = model.act(s_t)
        a_np = a.cpu().numpy().ravel()
        # 动作缩放: 速度 [-1,1] → [-0.15, 0.15]
        act = np.zeros(4)
        act[:3] = np.clip(a_np[:3], -1, 1) * 0.15
        # 2026-08-08 grip_assist: 夹爪规则触发 (RL 不学夹爪, 解决稀疏奖励)
        hand = env.data.site_xpos[env.model.site("endEffector").id]
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        d_hp = float(np.linalg.norm(hand - peg))
        if d_hp < 0.08 and not lifted:
            act[3] = -1.0   # 接近闭合
        elif lifted:
            act[3] = 0.6    # 保持抓住
        else:
            act[3] = 0.0    # 张开
        if peg[2] - info["peg_z0"] > 0.05:
            lifted = True
        states.append(obs); actions.append(a_np); logps.append(lp.cpu()); values.append(v.cpu())
        obs, rw, term, trunc, _ = env.step(act)
        info["gripper_cmd"] = float(act[3])  # 传给 reward (夹爪闭合奖励)
        rw, info = compute_reward(env, None, None, None, None, info)
        rewards.append(rw); dones.append(term or trunc)
        if term or trunc:
            break
        obs = get_obs(env)
    return (states, actions, logps, rewards, values, dones), info

def compute_gae(rewards, values, dones):
    """GAE 优势 — values 可能是 tensor 列表"""
    values = np.array([float(v) for v in values] + [0.0], dtype=np.float32)
    rewards = np.array(rewards, dtype=np.float32)
    dones = np.array(dones, dtype=np.float32)
    adv = np.zeros_like(rewards)
    gae = 0.0
    for t in reversed(range(len(rewards))):
        delta = rewards[t] + GAMMA * values[t+1] * (1 - dones[t]) - values[t]
        gae = delta + GAMMA * LAMBDA * (1 - dones[t]) * gae
        adv[t] = gae
    return adv, adv + values[:-1]

def main():
    print(f"🧠 仿真 RL (PPO) · peg-insert-side-v3 · device={DEVICE}")
    env, mt = make_env(seed=0)
    env.reset(seed=0)
    obs_dim = len(get_obs(env))
    act_dim = 4
    print(f"  obs_dim={obs_dim} act_dim={act_dim}")
    model = ActorCritic(obs_dim, act_dim).to(DEVICE)
    opt = optim.Adam(model.parameters(), lr=LR)
    stats_log = []

    # ── Phase 0: 模仿学习 warm-start (官方专家策略, 2026-08-06) ──
    print("Phase 0: 专家模仿 warm-start (200 episodes)")
    try:
        from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
        expert = SawyerPegInsertionSideV3Policy()
        bc_buf_s, bc_buf_a = [], []
        for ep in range(200):
            env.reset(seed=ep % 50)
            obs = get_obs(env)
            for t in range(MAX_EP_STEPS):
                a = np.asarray(expert.get_action(obs.astype(np.float64)), dtype=np.float32).ravel()[:4]
                # 归一化动作到 [-1,1] (与策略输出空间一致)
                a_n = np.zeros(4); a_n[:3] = np.clip(a[:3] / 0.15, -1, 1); a_n[3] = np.clip(a[3], -1, 1)
                bc_buf_s.append(obs); bc_buf_a.append(a_n)
                obs, _, term, trunc, _ = env.step(a[:4])
                if term or trunc: break
                obs = get_obs(env)
        s_t = torch.from_numpy(np.stack(bc_buf_s)).float().to(DEVICE)
        a_t = torch.from_numpy(np.stack(bc_buf_a)).float().to(DEVICE)
        for _ in range(30):
            idx = torch.randperm(len(s_t))[:512]
            mu, std, _ = model.forward(s_t[idx])
            loss = -torch.distributions.Normal(mu, std).log_prob(a_t[idx]).mean()
            opt.zero_grad(); loss.backward(); opt.step()
        print(f"  BC warm-start 完成: {len(bc_buf_s)} 样本")
    except Exception as ex:
        print(f"  ⚠️ 专家加载失败: {ex}, 纯 RL")

    for it in range(ITERS):
        # 收集 rollout
        buf_s, buf_a, buf_lp, buf_r, buf_v, buf_d = [], [], [], [], [], []
        ep_rewards, ep_lifts, ep_inserts = [], 0, 0
        env.reset(seed=it % 20)
        info = {"peg_z0": env.data.site_xpos[env.model.site("pegGrasp").id][2],
                "grasped": False, "inserted": False}
        n_ep = 0
        while len(buf_r) < STEPS_PER_ITER:
            (s, a, lp, r, v, d), info = run_episode(env, model, info)
            buf_s += s; buf_a += a; buf_lp += lp; buf_r += r; buf_v += v; buf_d += d
            ep_rewards.append(sum(r))
            if info.get("grasped"): ep_lifts += 1
            if info.get("inserted"): ep_inserts += 1
            n_ep += 1
            env.reset(seed=(it * 20 + n_ep) % 100)
            info = {"peg_z0": env.data.site_xpos[env.model.site("pegGrasp").id][2],
                    "grasped": False, "inserted": False}
        # PPO 更新
        adv, ret = compute_gae(buf_r, buf_v, buf_d)
        s_t = torch.from_numpy(np.stack(buf_s)).float().to(DEVICE)
        a_t = torch.from_numpy(np.stack(buf_a)).float().to(DEVICE)
        adv_t = torch.from_numpy(adv).float().to(DEVICE)
        ret_t = torch.from_numpy(ret).float().to(DEVICE)
        old_lp = torch.stack(buf_lp).to(DEVICE).detach()
        for _ in range(EPOCHS):
            idx = torch.randperm(len(s_t))[:BATCH]
            lp, ent, v = model.evaluate(s_t[idx], a_t[idx])
            ratio = (lp - old_lp[idx]).exp()
            surr1 = ratio * adv_t[idx]
            surr2 = torch.clamp(ratio, 1-CLIP, 1+CLIP) * adv_t[idx]
            loss = -torch.min(surr1, surr2).mean() + 0.5 * (v - ret_t[idx]).pow(2).mean() - 0.01 * ent.mean()
            opt.zero_grad(); loss.backward(); opt.step()
        avg_r = float(np.mean(ep_rewards)) if ep_rewards else 0
        stats_log.append({"iter": it, "avg_reward": avg_r, "lifts": ep_lifts, "inserts": ep_inserts})
        print(f"[iter {it}] 平均奖励={avg_r:.1f} 抓起={ep_lifts}/{n_ep} 插入={ep_inserts}/{n_ep}", flush=True)
        if ep_inserts > 0:
            print(f"🎉 插拔成功! 保存模型", flush=True)
            break
    # 保存
    os.makedirs(os.path.join(ROOT, "outputs", "rl_peg"), exist_ok=True)
    torch.save({"model": model.state_dict(), "obs_dim": obs_dim, "act_dim": act_dim},
               os.path.join(ROOT, "outputs", "rl_peg", "ppo_peg.pt"))
    json.dump(stats_log, open(os.path.join(ROOT, "outputs", "rl_peg", "stats.json"), "w"))
    print(f"✅ 已保存: outputs/rl_peg/ppo_peg.pt (抓起次数={sum(s['lifts'] for s in stats_log)}, 插入次数={sum(s['inserts'] for s in stats_log)})")

if __name__ == "__main__":
    main()
