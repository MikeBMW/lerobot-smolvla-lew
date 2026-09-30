#!/usr/bin/env python3
"""AWE + 强化学习 (PPO) — 2026-08-10 老倪: AWE也增加强化学习
方案: ① 加载 AWE-zFlow 预训练权重 (AWEZFlowModel encoder)
      ② AWE 编码器提取状态特征 (39D obs + 触觉 → 潜表示)
      ③ PPO 微调策略头 (AWE 潜空间上 RL)
Reward: 接近peg + 抓起(+10) + 插入(+50) + 步数惩罚
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
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
HIDDEN = 256
MAX_EP_STEPS = 300
GAMMA = 0.99
LAMBDA = 0.95
CLIP = 0.2
LR = 1e-4
EPOCHS = 4
BATCH = 256
STEPS_PER_ITER = 2048
ITERS = 60
AWE_CKPT = "outputs/train/awe_zflow_20260809_225958/checkpoints/000050/pretrained_model"

def load_awe():
    """加载 AWE-zFlow 预训练模型 (encoder 特征提取)"""
    from importlib import util
    spec = util.spec_from_file_location("az", os.path.join(ROOT, "tools", "train_awe_zflow.py"))
    mod = util.module_from_spec(spec); spec.loader.exec_module(mod)
    ckpt = os.path.join(ROOT, AWE_CKPT)
    data = torch.load(os.path.join(ckpt, "model.pt"), map_location="cpu")
    cfg = data["config"]
    dz = cfg.get("d_z", [128, 128, 64])
    model = mod.AWEZFlowModel(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                              cfg["vis_dim"], dz[0], dz[1], dz[2], cfg.get("hidden", 256)).to(DEVICE)
    model.load_state_dict(data["state_dict"])
    model.eval()
    print(f"  📂 AWE 加载: state{cfg['state_dim']}D tac{cfg['tactile_dim']}D vis{cfg['vis_dim']}D", flush=True)
    return model, cfg

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
    print(f"🧿 AWE + 强化学习 (PPO) · {DEVICE}", flush=True)
    awe, cfg = load_awe()
    state_dim = int(cfg["state_dim"])
    tac_dim = int(cfg["tactile_dim"])
    # 冻结 AWE 编码器 + 世界模型, 只训练策略头
    for p in awe.parameters():
        p.requires_grad = False
    # 策略头: AWE 潜空间 (320D = 128+128+64) → 4D 动作
    latent_dim = sum(awe.latent_dims)
    policy_head = nn.Sequential(
        nn.Linear(latent_dim, HIDDEN), nn.ReLU(),
        nn.Linear(HIDDEN, HIDDEN), nn.ReLU(),
        nn.Linear(HIDDEN, 4)).to(DEVICE)
    opt = optim.Adam(policy_head.parameters(), lr=LR)
    env = make_env(0)
    obs_dim = len(get_obs(env))
    print(f"  obs={obs_dim}D → AWE(state{state_dim}+tac{tac_dim}) → 策略头 → 4D", flush=True)
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
                # AWE 特征: state (49D: 39D obs + 触觉差分 4D + rel 补全) — 与 AWE 训练同构
                st_full = np.concatenate([o[:39], np.zeros(6, dtype=np.float32), np.zeros(4, dtype=np.float32)])[:49]
                st_in = torch.from_numpy(st_full).float().to(DEVICE).unsqueeze(0)
                # 触觉 (4D 差分近似)
                tac_in = torch.zeros(1, tac_dim, device=DEVICE)
                z = awe.encoder(st_in, tac_in)  # AWE 潜表示
                zf = z if isinstance(z, torch.Tensor) else torch.cat([z[i] for i in range(len(z))], dim=-1)
                if zf.ndim > 2: zf = zf.mean(dim=1)
                mu = policy_head(zf).squeeze(0)
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
        obs_buf = torch.from_numpy(np.stack(obs_buf)).float().to(DEVICE)
        act_buf = torch.from_numpy(np.stack(act_buf)).float().to(DEVICE)
        rew_buf = np.array(rew_buf, dtype=np.float32)
        don_buf = np.array(don_buf, dtype=np.float32)
        val_buf = torch.zeros(len(rew_buf), device=DEVICE)
        logp_buf = torch.tensor(logp_buf, dtype=torch.float32, device=DEVICE)
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
            with torch.no_grad():
                # state 补全 49D (39D obs + rel 6 + tac 4)
                st_b = obs_buf[idx, :39]
                pad_b = torch.zeros(len(idx), 10, device=DEVICE)
                st_in = torch.cat([st_b, pad_b], dim=-1)
                tac_in = torch.zeros(len(idx), tac_dim, device=DEVICE)
                z = awe.encoder(st_in, tac_in)
                zf = z if isinstance(z, torch.Tensor) else torch.cat([z[i] for i in range(len(z))], dim=-1)
                if zf.ndim > 2: zf = zf.mean(dim=1)
            mu = policy_head(zf)
            dist = torch.distributions.Normal(mu, 0.1)
            logp_new = dist.log_prob(act_buf[idx]).sum(-1)
            ratio = torch.exp(logp_new - logp_buf[idx])
            clip_adv = torch.clamp(ratio, 1 - CLIP, 1 + CLIP) * adv[idx]
            loss_p = -torch.min(ratio * adv[idx], clip_adv).mean()
            opt.zero_grad(); loss_p.backward(); opt.step()
        avg_r = float(np.mean(ep_rewards)) if ep_rewards else 0
        stats_log.append({"iter": it, "avg_reward": avg_r, "lifts": ep_lifts, "inserts": ep_inserts})
        print(f"[iter {it}] 平均奖励={avg_r:.1f} 抓起={ep_lifts}/{len(ep_rewards)} 插入={ep_inserts}/{len(ep_rewards)}", flush=True)
        if ep_inserts > best_inserts:
            best_inserts = ep_inserts
            os.makedirs(os.path.join(ROOT, "outputs", "rl_awe"), exist_ok=True)
            torch.save({"policy_head": policy_head.state_dict(), "awe_ckpt": AWE_CKPT, "iter": it},
                       os.path.join(ROOT, "outputs", "rl_awe", "awe_rl_ft.pt"))
            print(f"  💾 保存: outputs/rl_awe/awe_rl_ft.pt (插入 {ep_inserts})", flush=True)
        if ep_inserts >= 3:
            print(f"🎉 AWE RL 成功! 插入 {ep_inserts}", flush=True)
            break
    json.dump(stats_log, open(os.path.join(ROOT, "reports", "awe_rl_curve.json"), "w"))
    print("✅ AWE RL 完成", flush=True)

if __name__ == "__main__":
    main()
