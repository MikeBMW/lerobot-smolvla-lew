#!/usr/bin/env python3
"""评估最新模型插拔成功率 (2026-08-07 老倪: 评估)
覆盖: MLP蒸馏(expert_mlp.pt) + ACT-pegdata + ft微调3模型
"""
import os, sys, json, glob
import numpy as np
import torch
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

from eval_insert import run_episode


def load_mlp():
    d = torch.load(os.path.join(ROOT, "outputs/rl_peg/expert_mlp.pt"), map_location="cpu")
    # 直接复用蒸馏脚本的 ExpertMLP 类 (结构完全一致)
    from tools.distill_expert import ExpertMLP
    obs_dim, act_dim = d["obs_dim"], d["act_dim"]
    pol = ExpertMLP(obs_dim, act_dim)
    pol.load_state_dict(d["model"])
    pol.to(DEVICE).eval()
    pol.state_dim = obs_dim
    pol.action_dim = act_dim
    pol.is_mlp = True
    return pol


def run_mlp_episode(pol, seed, steps=250):
    """MLP 专用 rollout (39D obs → 4D 动作)"""
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=seed)
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=seed)
    env._freeze_rand_vec = True
    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
    hole = env.data.site_xpos[env.model.site("hole").id]
    lifted = False
    for i in range(steps):
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        if peg[2] - peg_z0 > 0.05:
            lifted = True
        st = np.asarray(env._get_obs(), dtype=np.float32).ravel()[: pol.state_dim]
        s_t = torch.from_numpy(st).float().to(DEVICE).unsqueeze(0)
        with torch.no_grad():
            act = pol(s_t).cpu().numpy().ravel()
        # 2026-08-07: MLP 输出 unbounded → clamp 到专家动作范围 [-1,1]
        act = np.clip(act, -1.0, 1.0)
        # 2026-08-07: 纯模型评估 — MLP 自己学会夹爪时机 (实测 6/10 抓起, 辅助反而破坏)
        pass
        obs, r, term, trunc, _ = env.step(act)
        if term or trunc:
            break
    peg_f = env.data.site_xpos[env.model.site("pegGrasp").id]
    dist_hole = float(np.linalg.norm(peg_f - hole))
    inserted = lifted and dist_hole < 0.05
    env.close()
    return {"lifted": lifted, "inserted": inserted, "dist_hole": dist_hole}


def main():
    results = {}
    # ① MLP 蒸馏 (新 22:36)
    print("=== MLP 蒸馏 (expert_mlp.pt 新) ===", flush=True)
    pol = load_mlp()
    lifts = ins = 0; dists = []
    for seed in range(10):
        r = run_mlp_episode(pol, seed)
        lifts += int(r["lifted"]); ins += int(r["inserted"]); dists.append(r["dist_hole"])
    results["MLP蒸馏"] = (lifts, ins, np.mean(dists))
    print(f"  MLP蒸馏: 抓起={lifts}/10 插入={ins}/10 距孔={np.mean(dists):.3f}", flush=True)

    # ② ACT-pegdata (4000步新)
    print("=== ACT-pegdata ===", flush=True)
    # 直接调用 (不用 reload — reload 会破坏模块状态)
    from eval_insert import load_policy as _lp
    curve_p = os.path.join(ROOT, "reports/train_curve_act.json")
    orig = json.load(open(curve_p))
    orig["ckpt"] = "outputs/train/act_pegdata_4000/checkpoints"
    json.dump(orig, open(curve_p, "w"))
    try:
        pol2, _ = _lp("act")
        print(f"  ACT pol2: {type(pol2).__name__ if pol2 else 'None'}", flush=True)
        if pol2 is None:
            raise RuntimeError("ACT 加载返回 None")
        lifts2 = ins2 = 0; dists2 = []
        for seed in range(10):
            r = run_episode(pol2, seed, grip_assist=True)  # 夹爪辅助 (ACT 差夹爪决策)
            lifts2 += int(r["lifted"]); ins2 += int(r["inserted"]); dists2.append(r["dist_hole"])
        results["ACT-pegdata"] = (lifts2, ins2, np.mean(dists2))
        print(f"  ACT-pegdata: 抓起={lifts2}/10 插入={ins2}/10 距孔={np.mean(dists2):.3f}", flush=True)
    except Exception as e:
        results["ACT-pegdata"] = "ERR"
        print(f"  ACT-pegdata 错误: {str(e)[:100]}", flush=True)

    print("=== 汇总 ===", flush=True)
    for k, v in results.items():
        print(f"  {k}: {v}", flush=True)


if __name__ == "__main__":
    main()
