#!/usr/bin/env python3
"""标准 left_right 模型 8 seed 评估 (从 lerobot_train 产物加载, 含状态机)"""
import os, sys, numpy as np, torch
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = "/home/xspace/lerobot-smolvla-lew"
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "src"))
from lerobot.policies.left_right import LeftRightPolicy

def make_env(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False; env.set_task(mt.train_tasks[0]); env.reset(seed=seed); env._freeze_rand_vec = True
    return env

ckpt = sys.argv[1] if len(sys.argv) > 1 else "outputs/train/left_right_std/checkpoints/003000/pretrained_model"
policy = LeftRightPolicy.from_pretrained(os.path.join(ROOT, ckpt))
# 2026-08-10: 融合验证右脑 (contact 判断, 标准数据无 contact 标签)
policy.load_trained_weights(os.path.join(ROOT, "outputs", "rl_peg", "full_pipeline.pt"))
policy.eval()
lifts = ins = 0
for seed in range(8):
    env = make_env(seed)
    o = np.asarray(env._get_obs(), dtype=np.float32).ravel()
    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
    hole = env.data.site_xpos[env.model.site("hole").id]
    policy.reset(); policy.set_peg_z0(peg_z0); policy.set_env(env)
    for step in range(500):
        batch = {"observation.state": torch.from_numpy(o).float().unsqueeze(0).unsqueeze(0)}
        act = policy.select_action(batch).squeeze(0).cpu().numpy()
        env.step(np.clip(act, -1, 1))
        o = np.asarray(env._get_obs(), dtype=np.float32).ravel()
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        if np.linalg.norm(peg - hole) < 0.05:
            ins += 1
            break
    peg = env.data.site_xpos[env.model.site("pegGrasp").id]
    if peg[2] - peg_z0 > 0.05: lifts += 1
    env.close()
    print(f"  seed{seed}: 抓起={'✅' if peg[2]-peg_z0 > 0.05 else '❌'} 插入={'✅' if ins > 0 else '❌'}", flush=True)
print(f"== 标准模型: 抓起={lifts}/8 插入={ins}/8", flush=True)
