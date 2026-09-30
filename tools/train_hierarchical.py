#!/usr/bin/env python3
"""层级策略 (W2-CoT 4阶段 MLP + 决策器) — 2026-08-10 老倪: 训练4个阶段MLP + 决策器
方案:
  ① 专家轨迹 → W2-CoT 阶段标注 (0接近 1抓取 2抬起 3插入)
  ② 4 个阶段 MLP: 每阶段一个 ExpertMLP (39D obs → 4D action), 用该阶段数据训练
  ③ 决策器: 规则 (阶段判定逻辑: d_hp/d_ph/peg高度) 选阶段 → 对应 MLP 执行
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
HIDDEN = 256
STAGES = ["接近", "抓取", "抬起", "插入"]

class StageMLP(nn.Module):
    """单阶段 MLP: 39D obs → 4D action"""
    def __init__(self, obs_dim=39, act_dim=4):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, HIDDEN), nn.ReLU(),
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

def compute_stage(env, peg_z0, hole):
    """W2-CoT 阶段判定: 0接近 1抓取 2抬起 3插入"""
    hand = env.data.site_xpos[env.model.site("endEffector").id]
    peg = env.data.site_xpos[env.model.site("pegGrasp").id]
    d_hp = float(np.linalg.norm(hand - peg))
    d_ph = float(np.linalg.norm(peg - hole))
    lifted = float(peg[2]) - peg_z0 > 0.02
    if lifted:
        return 3 if d_ph < 0.15 else 2
    return 1 if d_hp < 0.08 else 0

def collect_stage_data(n_eps=60):
    """专家轨迹 + 阶段标注 (W2-CoT)"""
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    expert = SawyerPegInsertionSideV3Policy()
    data = {s: {"X": [], "Y": []} for s in range(4)}
    for ep in range(n_eps):
        env = make_env(ep)
        o = get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        for _ in range(300):
            o_expert = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            a = np.asarray(expert.get_action(o_expert), dtype=np.float32)[:4]
            stage = compute_stage(env, peg_z0, hole)
            data[stage]["X"].append(o)
            data[stage]["Y"].append(a)
            env.step(a)
            o = get_obs(env)
            if env.data.site_xpos[env.model.site("pegGrasp").id][2] - peg_z0 > 0.05 and \
               np.linalg.norm(env.data.site_xpos[env.model.site("pegGrasp").id] - hole) < 0.05:
                break
        env.close()
    return data

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-only", action="store_true", help="跳过训练, 直接加载已保存模型评估")
    args = ap.parse_args()
    print(f"🧬 层级策略 (W2-CoT 4阶段 MLP + 决策器) · {DEVICE}", flush=True)
    if args.eval_only:
        d = torch.load(os.path.join(ROOT, "outputs", "rl_peg", "hierarchical_policy.pt"), map_location="cpu")
        models = {s: StageMLP(39, 4).to(DEVICE) for s in d["models"]}
        for s, sd in d["models"].items():
            models[s].load_state_dict(sd); models[s].eval()
        stats = {s: [np.array(v, dtype=np.float32) for v in st] for s, st in d["stats"].items()}
        print("  📂 加载已训练模型", flush=True)
    else:
        data = collect_stage_data(n_eps=50)
        for s in range(4):
            print(f"  阶段{s}({STAGES[s]}): {len(data[s]['X'])}帧", flush=True)
        # 训练 4 个阶段 MLP
        models = {}
        stats = {}
        for s in range(4):
            X = np.stack(data[s]["X"]).astype(np.float32)
            Y = np.stack(data[s]["Y"]).astype(np.float32)
            if len(X) < 10:
                print(f"  ⚠️ 阶段{s}({STAGES[s]}) 数据不足 ({len(X)}帧), 跳过", flush=True)
                continue
            xm, xs = X.mean(0), X.std(0) + 1e-6
            ym, ys = Y.mean(0), Y.std(0) + 1e-6
        Xn = (X - xm) / xs
        Yn = (Y - ym) / ys
        m = StageMLP(39, 4).to(DEVICE)
        opt = optim.Adam(m.parameters(), lr=1e-3)
        Xt = torch.from_numpy(Xn).float().to(DEVICE)
        Yt = torch.from_numpy(Yn).float().to(DEVICE)
        for ep in range(300):
            idx = torch.randperm(len(Xt), device=DEVICE)[:min(256, len(Xt))]
            pred = m(Xt[idx])
            loss = nn.functional.mse_loss(pred, Yt[idx])
            opt.zero_grad(); loss.backward(); opt.step()
        models[s] = m
        stats[s] = (xm, xs, ym, ys)
        print(f"  ✅ 阶段{s}({STAGES[s]}) MLP 训练完成 loss={loss.item():.5f}", flush=True)
    # 保存
    os.makedirs(os.path.join(ROOT, "outputs", "rl_peg"), exist_ok=True)
    torch.save({"models": {s: m.state_dict() for s, m in models.items()},
                "stats": {s: [v.tolist() for v in st] for s, st in stats.items()},
                "obs_dim": 39, "act_dim": 4},
               os.path.join(ROOT, "outputs", "rl_peg", "hierarchical_policy.pt"))
    print(f"  💾 保存: outputs/rl_peg/hierarchical_policy.pt", flush=True)
    # 评估: 决策器 (规则) + 阶段 MLP
    print("\n🧪 评估: 规则决策器 + 阶段MLP (8 seed)", flush=True)
    lifts = ins = 0
    for seed in range(8):
        env = make_env(seed)
        o = get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        success = False
        stage_hold = 0  # 当前阶段持续帧数 (2026-08-10: 抓取超时强制转抬起)
        stage_prev = -1
        d_hp_prev = 1.0
        for step in range(300):
            stage = compute_stage(env, peg_z0, hole)
            # 抓取阶段卡死处理: 夹爪闭合 d_hp<0.08 持续 30 帧 → 强制转抬起 (光模块 已抓)
            if stage == 1 and stage_hold > 30 and d_hp_prev < 0.08:
                stage = 2
            if stage == stage_prev:
                stage_hold += 1
            else:
                stage_hold = 1
            stage_prev = stage
            if stage == 0:
                # 2026-08-10: 接近阶段用解析控制器 (hand→光模块 直接移动, 比学专家轨迹可靠)
                hand = env.data.site_xpos[env.model.site("endEffector").id]
                peg = env.data.site_xpos[env.model.site("pegGrasp").id]
                delta = peg - hand
                delta[2] = min(delta[2], 0.05)  # 略降一点抓握
                act = np.zeros(4, dtype=np.float32)
                act[:3] = np.clip(delta * 3.0, -1, 1)
                act[3] = 1.0  # 夹爪张开
            elif stage not in models:
                act = np.array([0, 0, 0, 1], dtype=np.float32)
            else:
                m = models[stage]
                xm, xs, ym, ys = [torch.from_numpy(np.array(v)).float().to(DEVICE) for v in stats[stage]]
                xin = torch.from_numpy(o).float().to(DEVICE)
                xin_n = (xin - xm) / xs
                with torch.no_grad():
                    pred = m(xin_n.unsqueeze(0)).squeeze(0).cpu().numpy()
                act = pred * np.array(ys.cpu()) + np.array(ym.cpu())
                # 2026-08-10: 动作爆炸修复 — 保持方向缩放 (超界时按最大分量归一)
                _mx = float(np.abs(act).max()) if len(act) else 1.0
                if _mx > 1.0:
                    act = act / _mx
            # 夹爪: 接近阶段张开, 抓取/抬起/插入闭合 (2026-08-10: 抓取提前闭合+保持, 防滑走)
            d_hp = float(np.linalg.norm(env.data.site_xpos[env.model.site("endEffector").id] -
                                        env.data.site_xpos[env.model.site("pegGrasp").id]))
            if stage >= 1 and d_hp < 0.12: act[3] = -1.0
            elif stage >= 2: act[3] = -1.0  # 抬起/插入保持闭合
            elif stage < 1: act[3] = 1.0
            env.step(np.clip(act, -1, 1))
            o = get_obs(env)
            d_hp_prev = d_hp  # 2026-08-10: 更新上帧距离 (抓取超时判定用)
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            if peg[2] - peg_z0 > 0.05: lifts = lifts  # 抓取成功判定
            if np.linalg.norm(peg - hole) < 0.05:
                ins += 1; success = True; break
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        if peg[2] - peg_z0 > 0.05: lifts += 1
        env.close()
        print(f"  seed{seed}: {'✅ 插入' if success else '❌'}", flush=True)
    print(f"== 层级策略: 抓起={lifts}/8 插入={ins}/8", flush=True)

if __name__ == "__main__":
    main()
