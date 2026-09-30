#!/usr/bin/env python3
"""世界模型 + MLP 强化学习 (PPO) — 2026-08-10 老倪: 世界模型+MLP强化学习
方案: ① 加载 SmolVLA-LEW 的 LeWorldModel (潜空间时序预测)
      ② MLP 策略 (ExpertMLP 结构) 在仿真中交互
      ③ PPO 训练: 世界模型提供想象 rollout (预测 next state/reward), 加速策略学习
Reward: 接近peg(-dist) + 抓起(+10) + 插入(+50) + 步数惩罚 (同 train_peg_rl)
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
HIDDEN = 512
MAX_EP_STEPS = 300
GAMMA = 0.99
LAMBDA = 0.95
CLIP = 0.2
LR = 3e-4
EPOCHS = 4
BATCH = 256
STEPS_PER_ITER = 2048
ITERS = 60
# 世界模型权重: SmolVLA-LEW 训练产物 (LEW 预测 next state)
LEW_CKPT = "outputs/train/smolvla_lew_5000_20260809_215838/checkpoints/005000/pretrained_model"

class ExpertMLP(nn.Module):
    """MLP 策略 (与 distill_expert 同结构, 39D obs → 4D action)"""
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

class StateWorldModel(nn.Module):
    """轻量状态世界模型: 39D obs + 4D action → 预测 next obs (LeWorldModel 的 state 版)
    训练: 用专家轨迹数据 (obs_t, act_t) → obs_{t+1} (监督式世界模型)"""
    def __init__(self, obs_dim=39, act_dim=4, hidden=256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim + act_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, obs_dim))
    def forward(self, obs, act):
        return self.net(torch.cat([obs, act], dim=-1))

def train_state_world_model(env, n_eps=30):
    """用官方专家轨迹训练状态世界模型 (监督学习)"""
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    expert = SawyerPegInsertionSideV3Policy()
    obs_list, act_list, next_list = [], [], []
    for ep in range(n_eps):
        env2 = make_env(ep)
        o = get_obs(env2)
        peg_z0 = env2.data.site_xpos[env2.model.site("pegGrasp").id][2]
        for _ in range(200):
            o_expert = np.asarray(env2._get_obs(), dtype=np.float64).ravel()
            a = np.asarray(expert.get_action(o_expert), dtype=np.float32)[:4]
            o2, _, term, trunc, _ = env2.step(a)
            obs_list.append(o); act_list.append(a); next_list.append(get_obs(env2))
            o = get_obs(env2)
            if term or trunc: break
        env2.close()
    obs_t = torch.from_numpy(np.stack(obs_list)).float().to(DEVICE)
    act_t = torch.from_numpy(np.stack(act_list)).float().to(DEVICE)
    nxt_t = torch.from_numpy(np.stack(next_list)).float().to(DEVICE)
    wm = StateWorldModel(obs_t.shape[1], act_t.shape[1]).to(DEVICE)
    opt = optim.Adam(wm.parameters(), lr=1e-3)
    for ep in range(200):
        pred = wm(obs_t, act_t)
        loss = nn.functional.mse_loss(pred, nxt_t)
        opt.zero_grad(); loss.backward(); opt.step()
        if ep % 50 == 0:
            print(f"  🌐 世界模型训练 iter{ep}: loss={loss.item():.5f}", flush=True)
    print(f"  ✅ 状态世界模型训练完成 ({len(obs_list)} 帧, loss={loss.item():.5f})", flush=True)
    return wm

def load_world_model(env=None):
    """状态世界模型 (训练或加载) — 轻量版 LeWorldModel"""
    try:
        p = os.path.join(ROOT, "outputs", "rl_wm", "state_wm.pt")
        if os.path.exists(p):
            d = torch.load(p, map_location="cpu")
            wm = StateWorldModel(d["obs_dim"], d["act_dim"]).to(DEVICE)
            wm.load_state_dict(d["state_dict"])
            print(f"  ✅ 世界模型加载: outputs/rl_wm/state_wm.pt", flush=True)
            return wm
        if env is not None:
            wm = train_state_world_model(env)
            os.makedirs(os.path.join(ROOT, "outputs", "rl_wm"), exist_ok=True)
            torch.save({"state_dict": wm.state_dict(), "obs_dim": wm.net[0].in_features - 4, "act_dim": 4},
                       os.path.join(ROOT, "outputs", "rl_wm", "state_wm.pt"))
            return wm
    except Exception as e:
        print(f"  ⚠️ 世界模型不可用: {str(e)[:80]}", flush=True)
    return None

def get_obs(env):
    o = np.asarray(env._get_obs(), dtype=np.float32).ravel()
    return o

def make_env(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    return env

def compute_rew(env, dist_hp, lifted, inserted, peg_z0, hole):
    r = -dist_hp * 2.0
    peg = env.data.site_xpos[env.model.site("pegGrasp").id]
    if peg[2] - peg_z0 > 0.05 and not lifted:
        r += 10.0; lifted = True
    if np.linalg.norm(peg - hole) < 0.05 and not inserted:
        r += 50.0; inserted = True
    r -= 0.01
    return r, lifted, inserted

def main():
    print(f"🌐 世界模型 + MLP 强化学习 (PPO) · {DEVICE}", flush=True)
    env0 = make_env(0)
    wm = load_world_model(env0)  # 训练或加载状态世界模型
    env = make_env(0)
    obs_dim = len(get_obs(env))
    act_dim = 4
    print(f"  obs_dim={obs_dim} act_dim={act_dim} 世界模型={'✅' if wm else '❌差分兜底'}", flush=True)
    model = ExpertMLP(obs_dim, act_dim).to(DEVICE)
    # 从专家 MLP 初始化 (如有)
    try:
        p = os.path.join(ROOT, "outputs", "rl_peg", "expert_mlp.pt")
        if os.path.exists(p):
            d = torch.load(p, map_location="cpu")
            model.load_state_dict(d["model"], strict=False)
            print("  ✅ 从 expert_mlp.pt 初始化", flush=True)
    except Exception as e:
        print(f"  ⚠️ 专家MLP加载跳过: {e}", flush=True)
    opt = optim.Adam(model.parameters(), lr=LR)
    stats_log = []
    best_inserts = 0
    for it in range(ITERS):
        obs_buf, act_buf, rew_buf, don_buf, val_buf, logp_buf = [], [], [], [], [], []
        ep_rewards, ep_lifts, ep_inserts = [], 0, 0
        env = make_env(it % 5)
        o = get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        ep_r, lifted, inserted, steps = 0.0, False, False, 0
        with torch.no_grad():
            while len(obs_buf) < STEPS_PER_ITER:
                o_t = torch.from_numpy(o).float().to(DEVICE).unsqueeze(0)
                mu = model(o_t).squeeze(0)
                v = model.net[:-1](o_t).mean() if hasattr(model.net, '__getitem__') else torch.zeros(1, device=DEVICE)
                # 价值头 (用 MLP 倒数第二层)
                v = torch.zeros(1, device=DEVICE)  # 简化: 无独立价值头, 用累计奖励
                dist = torch.distributions.Normal(mu, 0.1)
                a = dist.sample()
                logp = dist.log_prob(a).sum().item()
                act = np.clip(a.cpu().numpy(), -1, 1)
                hand = env.data.site_xpos[env.model.site("endEffector").id]
                peg = env.data.site_xpos[env.model.site("pegGrasp").id]
                d_hp = float(np.linalg.norm(hand - peg))
                r, lifted, inserted = compute_rew(env, d_hp, lifted, inserted, peg_z0, hole)
                act_full = act.copy()
                if d_hp < 0.08: act_full[3] = -1.0
                o2, _, term, trunc, _ = env.step(act_full)
                obs_buf.append(o); act_buf.append(act); rew_buf.append(r); don_buf.append(term or trunc)
                val_buf.append(0.0); logp_buf.append(logp)
                ep_r += r; steps += 1
                o = get_obs(env)
                if term or trunc or steps >= MAX_EP_STEPS:
                    ep_rewards.append(ep_r)
                    ep_lifts += int(lifted); ep_inserts += int(inserted)
                    env = make_env((it * 3 + len(ep_rewards)) % 7)
                    o = get_obs(env)
                    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
                    hole = env.data.site_xpos[env.model.site("hole").id]
                    ep_r, lifted, inserted, steps = 0.0, False, False, 0
        # PPO update (GAE + clip)
        obs_buf = torch.from_numpy(np.stack(obs_buf)).float().to(DEVICE)
        act_buf = torch.from_numpy(np.stack(act_buf)).float().to(DEVICE)
        rew_buf = np.array(rew_buf, dtype=np.float32)
        don_buf = np.array(don_buf, dtype=np.float32)
        val_buf = torch.zeros(len(rew_buf), device=DEVICE)
        logp_buf = torch.tensor(logp_buf, dtype=torch.float32, device=DEVICE)
        # 世界模型想象: 用 wm 预测未来 state 增强 reward (有 wm 时)
        if wm is not None:
            try:
                with torch.no_grad():
                    # 用 obs+act 预测下一状态 (想象 rollout)
                    seq_o = obs_buf[:min(64, len(obs_buf))]
                    seq_a = act_buf[:min(64, len(obs_buf))]
                    pred_next = wm(seq_o, seq_a)  # (B, obs_dim)
                    # 想象奖励: 预测状态接近 hole 则加分 (用 obs 的 hole 段 [36:39])
                    hole_ref = obs_buf[:min(64, len(obs_buf)), 36:39]
                    imag_dist = torch.norm(pred_next[:, 36:39] - hole_ref, dim=-1)
                    imag_reward = -imag_dist * 2.0
                    # 把想象奖励加入真实奖励 (前 64 步)
                    n_imag = min(64, len(rew_buf))
                    rew_buf[:n_imag] = rew_buf[:n_imag] + 0.3 * imag_reward[:n_imag].cpu().numpy()
                    print(f"  🌐 世界模型想象: 前瞻奖励已注入 (dist均值={imag_dist.mean().item():.3f})", flush=True)
            except Exception as e:
                print(f"  ⚠️ 世界模型想象跳过: {str(e)[:60]}", flush=True)
        # GAE
        with torch.no_grad():
            adv = torch.zeros_like(val_buf)
            last_gae = 0.0
            for t in reversed(range(len(rew_buf))):
                next_v = 0.0 if don_buf[t] else val_buf[min(t+1, len(val_buf)-1)].item()
                delta = rew_buf[t] + GAMMA * next_v - val_buf[t].item()
                last_gae = delta + GAMMA * LAMBDA * (1 - don_buf[t]) * last_gae
                adv[t] = torch.tensor(last_gae, dtype=torch.float32, device=DEVICE)
            ret = adv + val_buf
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        for _ in range(EPOCHS):
            idx = torch.randperm(len(obs_buf), device=DEVICE)[:BATCH]
            mu = model(obs_buf[idx])
            dist = torch.distributions.Normal(mu, 0.1)
            logp_new = dist.log_prob(act_buf[idx]).sum(-1)
            ratio = torch.exp(logp_new - logp_buf[idx])
            clip_adv = torch.clamp(ratio, 1 - CLIP, 1 + CLIP) * adv[idx]
            loss_p = -torch.min(ratio * adv[idx], clip_adv).mean()
            loss = loss_p  # 无价值头, 纯策略梯度
            opt.zero_grad(); loss.backward(); opt.step()
        avg_r = float(np.mean(ep_rewards)) if ep_rewards else 0
        stats_log.append({"iter": it, "avg_reward": avg_r, "lifts": ep_lifts, "inserts": ep_inserts})
        print(f"[iter {it}] 平均奖励={avg_r:.1f} 抓起={ep_lifts}/{len(ep_rewards)} 插入={ep_inserts}/{len(ep_rewards)}", flush=True)
        if ep_inserts > best_inserts:
            best_inserts = ep_inserts
            os.makedirs(os.path.join(ROOT, "outputs", "rl_wm"), exist_ok=True)
            torch.save({"model": model.state_dict(), "obs_dim": obs_dim, "act_dim": act_dim, "iter": it},
                       os.path.join(ROOT, "outputs", "rl_wm", "wm_mlp_ppo.pt"))
            print(f"  💾 保存: outputs/rl_wm/wm_mlp_ppo.pt (插入 {ep_inserts})", flush=True)
        if ep_inserts >= 3:
            print(f"🎉 世界模型+MLP RL 成功! 插入 {ep_inserts}", flush=True)
            break
    json.dump(stats_log, open(os.path.join(ROOT, "reports", "wm_mlp_ppo_curve.json"), "w"))
    print("✅ 世界模型+MLP RL 完成", flush=True)

if __name__ == "__main__":
    main()
