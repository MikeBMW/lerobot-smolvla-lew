#!/usr/bin/env python3
"""抓取点学习专项 — 2026-08-10 老倪: 抓取点精确对位 + 夹爪力控时序
方案:
  ① 数据: 专家轨迹 → 每帧 (obs, hand, pegGrasp抓握点)
  ② 抓取点 MLP: obs → 手到抓握点的期望 delta (精确对位, 不是整体peg距离)
  ③ 力控时序 (评估): 
     d_grasp > 0.03  → 张开, 向抓握点移动 (MLP 精确对位)
     d_grasp < 0.03  → 减速接近 (力控)
     d_grasp < 0.015 → 夹持力递增 0.3→0.6 (轻触→稳夹)
     peg 跟随 (z升高) → 锁定位置 + 保持 0.6
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

class GraspPointMLP(nn.Module):
    """抓取点 MLP: 39D obs → 手到抓握点的期望 delta (3D 位置, 夹爪由力控时序控制)"""
    def __init__(self, obs_dim=39, out_dim=3):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(),
            nn.Linear(HIDDEN, out_dim))
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

def grasp_target(env, hand):
    """抓握点目标: pegGrasp site + 抓握偏移 (夹爪张开对准抓握点上方 2cm)"""
    try:
        pg = env.data.site_xpos[env.model.site("pegGrasp").id]
    except Exception:
        pg = env.data.site_xpos[env.model.site("pegHead").id]
    target = pg + np.array([0.0, 0.0, 0.02])  # 抓握点上方 2cm (夹爪对准)
    return target, pg

def collect_grasp_data(n_eps=60):
    """专家轨迹 → 抓取点学习数据: obs → 手到抓握点 delta"""
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    expert = SawyerPegInsertionSideV3Policy()
    obs_list, del_list = [], []
    for ep in range(n_eps):
        env = make_env(ep)
        o = get_obs(env)
        for _ in range(300):
            o_expert = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            a = np.asarray(expert.get_action(o_expert), dtype=np.float32)[:4]
            hand = env.data.site_xpos[env.model.site("endEffector").id]
            target, pg = grasp_target(env, hand)
            delta = target - hand  # 期望手到抓握点的移动
            obs_list.append(o); del_list.append(delta)
            env.step(a)
            o = get_obs(env)
            peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
            if np.linalg.norm(env.data.site_xpos[env.model.site("pegGrasp").id] - env.data.site_xpos[env.model.site("hole").id]) < 0.05:
                break
        env.close()
    return np.stack(obs_list), np.stack(del_list)

def main():
    print(f"🎯 抓取点学习专项 · {DEVICE}", flush=True)
    obs_t, del_t = collect_grasp_data(n_eps=50)
    n = len(obs_t)
    print(f"  📦 数据: {n}帧 (obs → 抓握点delta)", flush=True)
    xm, xs = obs_t.mean(0), obs_t.std(0) + 1e-6
    dm, ds = del_t.mean(0), del_t.std(0) + 1e-6
    model = GraspPointMLP(39, 3).to(DEVICE)
    opt = optim.Adam(model.parameters(), lr=1e-3)
    obs_n = torch.from_numpy((obs_t - xm) / xs).float().to(DEVICE)
    del_n = torch.from_numpy((del_t - dm) / ds).float().to(DEVICE)
    for ep in range(800):
        idx = torch.randperm(n, device=DEVICE)[:256]
        pred = model(obs_n[idx])
        loss = nn.functional.mse_loss(pred, del_n[idx])
        opt.zero_grad(); loss.backward(); opt.step()
        if ep % 200 == 0:
            print(f"  iter{ep}: loss={loss.item():.4f}", flush=True)
    print(f"  ✅ 抓取点 MLP 训练完成 (loss={loss.item():.4f})", flush=True)
    os.makedirs(os.path.join(ROOT, "outputs", "rl_peg"), exist_ok=True)
    torch.save({"model": model.state_dict(), "xm": xm, "xs": xs, "dm": dm, "ds": ds},
               os.path.join(ROOT, "outputs", "rl_peg", "grasp_point_mlp.pt"))
    print(f"  💾 保存: outputs/rl_peg/grasp_point_mlp.pt", flush=True)

    # 评估: 抓取点精确对位 + 力控时序
    print("\n🧪 评估: 抓取点MLP + 力控时序 (8 seed)", flush=True)
    model.eval()
    lifts = ins = 0
    for seed in range(8):
        env = make_env(seed)
        o = get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        hand = env.data.site_xpos[env.model.site("endEffector").id]
        grasp_force = -1.0  # 张开
        locked = False
        lifted = False
        for step in range(300):
            hand = env.data.site_xpos[env.model.site("endEffector").id]
            target, pg = grasp_target(env, hand)
            d_grasp = float(np.linalg.norm(target - hand))  # 到抓握点距离
            xin = torch.from_numpy((o - xm) / xs).float().to(DEVICE)
            with torch.no_grad():
                pred = model(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
            delta = pred * ds + dm  # 期望移动
            # 力控时序: 距离分段控制 (2026-08-10: 先水平对位再垂直下降, 防推走peg)
            if d_grasp > 0.10:
                # 远: 满速朝抓握点
                act = np.zeros(4, dtype=np.float32)
                if np.linalg.norm(delta) > 1e-4:
                    act[:3] = (delta / np.linalg.norm(delta)) * 1.0
                act[3] = -1.0
                grasp_force = -1.0
            elif d_grasp > 0.03:
                # 中: 半速 (减速接近)
                act = np.zeros(4, dtype=np.float32)
                if np.linalg.norm(delta) > 1e-4:
                    act[:3] = (delta / np.linalg.norm(delta)) * 0.5
                act[3] = -1.0
                grasp_force = -1.0
            elif d_grasp > 0.015:
                # 近: 垂直下降 (2026-08-10: 先水平对齐→垂直下到抓握点, 不推peg)
                h_delta = np.array([delta[0], delta[1], 0.0])  # 水平分量
                h_dist = np.linalg.norm(h_delta)
                if h_dist > 0.02:
                    # 水平还没对齐 (容差 2cm, peg 直径级): 只动水平
                    act[:3] = np.clip((h_delta / max(h_dist, 1e-4)) * 0.4, -1, 1)
                else:
                    # 水平对齐: 垂直下降 (缓慢, 防压peg)
                    act[:3] = [0.0, 0.0, np.clip(delta[2] * 1.0, -0.5, 0.5)]
                act[3] = -1.0  # 仍张开
            elif not locked:
                # 到达抓握点: 轻触→稳夹 (力控时序)
                act = np.zeros(4, dtype=np.float32)
                act[:3] = np.clip(delta * 0.3, -1, 1)  # 微调
                grasp_force = min(grasp_force + 0.3, 0.6)  # 力递增 0→0.3→0.6
                act[3] = grasp_force
                if grasp_force >= 0.6:
                    locked = True  # 稳定夹持
            else:
                # 已稳定夹持: 锁定位置 + 保持
                act = np.zeros(4, dtype=np.float32)
                act[:3] = np.clip(delta * 0.1, -1, 1) * 0.1
                act[3] = 0.6
            env.step(np.clip(act, -1, 1))
            o = get_obs(env)
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            if peg[2] - peg_z0 > 0.05: lifted = True
            if np.linalg.norm(peg - hole) < 0.05: ins += 1; break
        if lifted: lifts += 1
        env.close()
        print(f"  seed{seed}: 抓起={'✅' if lifted else '❌'} 插入={'✅' if ins > 0 else '❌'}", flush=True)
    print(f"== 抓取点专项: 抓起={lifts}/8 插入={ins}/8", flush=True)

if __name__ == "__main__":
    main()
