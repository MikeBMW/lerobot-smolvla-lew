#!/usr/bin/env python3
"""评估蒸馏 MLP 模型的插拔成功率"""
import os, sys, numpy as np, torch
os.environ.setdefault("DISPLAY", ":0"); os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def load_mlp(path):
    from distill_expert import ExpertMLP
    d = torch.load(path, map_location="cpu")
    m = ExpertMLP(d["obs_dim"], d["act_dim"])
    m.load_state_dict(d["model"]); m.eval()
    return m, d

def main():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    m, d = load_mlp(os.path.join(ROOT, "outputs", "rl_peg", "expert_mlp.pt"))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    m = m.to(dev)
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=0)
    lifts = ins = 0
    dists = []
    for seed in range(20):
        env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
        env.set_task(mt.train_tasks[0]); env._freeze_rand_vec = False
        obs, _ = env.reset(seed=seed)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        lifted = False; inserted = False
        for i in range(300):
            o = np.asarray(env._get_obs(), dtype=np.float32).ravel()
            with torch.no_grad():
                a = m(torch.from_numpy(o).float().unsqueeze(0).to(dev)).cpu().numpy().ravel()
            obs, _, term, trunc, _ = env.step(a[:4])
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            if peg[2] - peg_z0 > 0.05: lifted = True
            if lifted and np.linalg.norm(peg - hole) < 0.05: inserted = True
            if term or trunc: break
        lifts += int(lifted); ins += int(inserted)
        dists.append(float(np.linalg.norm(env.data.site_xpos[env.model.site("pegGrasp").id] - hole)))
        if seed < 8:
            print(f"  seed{seed}: 抓起={lifted} 插入={inserted} 距孔={dists[-1]:.3f}", flush=True)
    print(f"📊 蒸馏MLP 20次: 抓起={lifts}/20 插入={ins}/20 平均距孔={np.mean(dists):.3f}", flush=True)

if __name__ == "__main__":
    main()
