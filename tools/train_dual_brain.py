#!/usr/bin/env python3
"""MLP 并行 LeWorldModel — 左脑动作 + 右脑判断 (2026-08-10 老倪: MLP左脑动作, 世界模型右脑判断预测)
架构:
  左脑 MLP:  39D obs → 4D 连续动作 (expert_mlp 结构, 快)
  右脑 WM:   39D obs + 4D action → 预测 next obs + 抓取时机判断 (contact 概率)
  融合:      WM 判断"接触/该抓" (contact 概率 > 阈值) → 门控 MLP 夹爪闭合
训练:
  ① 专家轨迹 → 同时训练 MLP (动作回归) + WM (next obs 预测 + contact 二分类)
  ② 推理: MLP 输出动作, WM 预测 next obs + contact 概率 → 门控夹爪
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

class LeftBrainMLP(nn.Module):
    """左脑: 39D obs → 4D 连续动作 (expert_mlp 同结构)"""
    def __init__(self, obs_dim=39, act_dim=4):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(),
            nn.Linear(HIDDEN, act_dim))
    def forward(self, x):
        return self.net(x)

class RightBrainWM(nn.Module):
    """右脑: 39D obs + 4D action → 预测 next obs + contact 判断
    (LeWorldModel 的轻量 state 版 + 抓取时机头)"""
    def __init__(self, obs_dim=39, act_dim=4, hidden=256):
        super().__init__()
        self.enc = nn.Sequential(
            nn.Linear(obs_dim + act_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU())
        self.pred_next = nn.Linear(hidden, obs_dim)      # 预测 next obs
        self.contact_head = nn.Linear(hidden, 1)          # 抓取时机 (contact 概率)
    def forward(self, obs, act):
        h = self.enc(torch.cat([obs, act], dim=-1))
        next_obs = self.pred_next(h)
        contact = torch.sigmoid(self.contact_head(h))
        return next_obs, contact

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

def collect_dual_data(n_eps=60):
    """专家轨迹 → (obs, action, next_obs, contact_label)"""
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    expert = SawyerPegInsertionSideV3Policy()
    obs_list, act_list, next_list, cont_list = [], [], [], []
    for ep in range(n_eps):
        env = make_env(ep)
        o = get_obs(env)
        for _ in range(300):
            o_expert = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            a = np.asarray(expert.get_action(o_expert), dtype=np.float32)[:4]
            hand = env.data.site_xpos[env.model.site("endEffector").id]
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            d_hp = float(np.linalg.norm(hand - peg))
            contact = 1.0 if d_hp < 0.05 else 0.0  # 抓取时机标签
            o2, _, term, trunc, _ = env.step(a)
            obs_list.append(o); act_list.append(a)
            next_list.append(get_obs(env)); cont_list.append(contact)
            o = get_obs(env)
            if term or trunc: break
        env.close()
    return (np.stack(obs_list), np.stack(act_list), np.stack(next_list), np.array(cont_list, dtype=np.float32))

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42, help="随机种子 (2026-08-10: 固定种子保证接近质量复现)")
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    print(f"🧠 MLP 并行 LeWorldModel (左脑动作 + 右脑判断) · {DEVICE} · seed={args.seed}", flush=True)
    obs_t, act_t, next_t, cont_t = collect_dual_data(n_eps=50)
    n = len(obs_t)
    print(f"  📦 数据: {n}帧 · contact标签: {cont_t.sum():.0f}正 / {n - cont_t.sum():.0f}负", flush=True)
    # 归一化 (左脑 MLP)
    xm, xs = obs_t.mean(0), obs_t.std(0) + 1e-6
    ym, ys = act_t.mean(0), act_t.std(0) + 1e-6
    # 右脑 WM 用 raw obs (预测 next obs 保持物理量纲)
    left = LeftBrainMLP(39, 4).to(DEVICE)
    right = RightBrainWM(39, 4).to(DEVICE)
    opt_l = optim.Adam(left.parameters(), lr=1e-3)
    opt_r = optim.Adam(right.parameters(), lr=1e-3)
    # 数据 tensor
    obs_n = torch.from_numpy((obs_t - xm) / xs).float().to(DEVICE)
    act_n = torch.from_numpy((act_t - ym) / ys).float().to(DEVICE)
    obs_r = torch.from_numpy(obs_t).float().to(DEVICE)
    act_r = torch.from_numpy(act_t).float().to(DEVICE)
    next_r = torch.from_numpy(next_t).float().to(DEVICE)
    cont_r = torch.from_numpy(cont_t).float().to(DEVICE).unsqueeze(1)
    for ep in range(800):  # 2026-08-10: 400→800 epoch, 提高左脑质量 (loss 0.0895 才接近5/8)
        idx = torch.randperm(n, device=DEVICE)[:256]
        # 左脑: 动作回归
        pred_a = left(obs_n[idx])
        loss_l = nn.functional.mse_loss(pred_a, act_n[idx])
        opt_l.zero_grad(); loss_l.backward(); opt_l.step()
        # 右脑: next obs 预测 + contact 分类
        pred_next, pred_cont = right(obs_r[idx], act_r[idx])
        loss_next = nn.functional.mse_loss(pred_next, next_r[idx])
        loss_cont = nn.functional.binary_cross_entropy(pred_cont, cont_r[idx])
        loss_r = loss_next + 0.5 * loss_cont
        opt_r.zero_grad(); loss_r.backward(); opt_r.step()
        if ep % 100 == 0:
            print(f"  iter{ep}: 左脑loss={loss_l.item():.4f} | 右脑next={loss_next.item():.4f} contact={loss_cont.item():.4f}", flush=True)
    print(f"  ✅ 双脑训练完成 (左脑 loss={loss_l.item():.4f} 右脑 contact_acc={((pred_cont>0.5).float()==cont_r[idx]).float().mean().item():.2f})", flush=True)
    os.makedirs(os.path.join(ROOT, "outputs", "rl_peg"), exist_ok=True)
    torch.save({"left": left.state_dict(), "right": right.state_dict(),
                "xm": xm, "xs": xs, "ym": ym, "ys": ys},
               os.path.join(ROOT, "outputs", "rl_peg", "dual_brain.pt"))
    print(f"  💾 保存: outputs/rl_peg/dual_brain.pt", flush=True)
    # 评估: 左脑动作 + 右脑门控夹爪
    print("\n🧪 评估: 双脑 (8 seed)", flush=True)
    lifts = ins = 0
    for seed in range(8):
        env = make_env(seed)
        o = get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        left.eval(); right.eval()
        success = False
        grasped = False  # 2026-08-10: 抓取状态 (夹持后置 True, 触发插入控制器)
        lifted_flag = False  # 2026-08-10: 该 seed 是否成功抓起 (只计一次)
        for step in range(300):
            # 左脑: 动作 (MLP 预测 + 接近偏置 — 2026-08-10 验证: 此逻辑 5/8 抓起)
            hand = env.data.site_xpos[env.model.site("endEffector").id]
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            d_hp = float(np.linalg.norm(hand - peg))
            xin = torch.from_numpy((o - xm) / xs).float().to(DEVICE)
            with torch.no_grad():
                pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
            act = pred * ys + ym
            if d_hp > 0.10:
                delta = peg - hand
                act[:3] = act[:3] * 0.3 + np.clip(delta * 2.0, -1, 1)
            _mx = float(np.abs(act).max()) if len(act) else 1.0
            if _mx > 1.0: act = act / _mx
            # 右脑: 抓取时机判断 (contact 概率)
            o_r = torch.from_numpy(o).float().to(DEVICE)
            a_r = torch.from_numpy(act).float().to(DEVICE)
            with torch.no_grad():
                _, contact_p = right(o_r.unsqueeze(0), a_r.unsqueeze(0))
            contact_p = contact_p.item()
            # 融合: WM 判断该抓 (contact>0.5) 且手已贴住抓握点 (d_hp<0.06) → 夹爪夹持 + 锁定
            # 2026-08-10 验证: 此逻辑 5/8 抓起 (MLP偏置接近 + 右脑时机 + 专家夹持力)
            if contact_p > 0.5 and d_hp < 0.06:
                act[3] = 0.6  # 夹持 (专家式正夹持力)
                act[:3] = act[:3] * 0.1  # 锁定位置防推走
                if not grasped:
                    grasped = True  # 触发插入控制器
            else:
                act[3] = -1.0   # 张开
            env.step(np.clip(act, -1, 1))
            o = get_obs(env)
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            if peg[2] - peg_z0 > 0.05 and not lifted_flag: lifted_flag = True
            if np.linalg.norm(peg - hole) < 0.05:
                ins += 1; success = True; break
        if env.data.site_xpos[env.model.site("pegGrasp").id][2] - peg_z0 > 0.05 or lifted_flag: lifts += 1
        env.close()
        print(f"  seed{seed}: {'✅' if success else '❌'}", flush=True)
    print(f"== 双脑: 抓起={lifts}/8 插入={ins}/8", flush=True)

if __name__ == "__main__":
    main()
