#!/usr/bin/env python3
"""P3 验证: left_right select_action 动作级指标量测 — 8 seed 跑通 + metrics 打印
2026-08-10 静静 · 大屏监督方案 P3"""
import os, sys, numpy as np, torch
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = "/home/xspace/lerobot-smolvla-lew"
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "src"))
from lerobot.policies.left_right import LeftRightPolicy
from importlib import util
_spec = util.spec_from_file_location("tfp", os.path.join(ROOT, "tools", "train_full_pipeline.py"))
_tfp = util.module_from_spec(_spec); _spec.loader.exec_module(_tfp)

p = LeftRightPolicy()
p.load_trained_weights(os.path.join(ROOT, "outputs/rl_peg/full_pipeline.pt"))
p.eval()

lifts = ins = 0
all_metrics = []
for seed in range(8):
    env = _tfp.make_env(seed)
    o = _tfp.get_obs(env)
    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
    hole = env.data.site_xpos[env.model.site("hole").id]
    p.reset(); p.set_peg_z0(peg_z0); p.set_env(env)
    for step in range(500):
        batch = {"observation.state": torch.from_numpy(o).float().unsqueeze(0).unsqueeze(0)}
        act = p.select_action(batch).squeeze(0).cpu().numpy()
        env.step(np.clip(act, -1, 1))
        o = _tfp.get_obs(env)
        if p.state == 7:  # DONE
            ins += 1; break
    peg = env.data.site_xpos[env.model.site("pegGrasp").id]
    if peg[2] - peg_z0 > 0.05: lifts += 1
    # 收集该 seed 的指标样本
    m = p.metrics
    all_metrics.append(m)
    log_n = len(p.action_log)
    env.close()
    print(f"  seed{seed}: 抓起={'✅' if peg[2]-peg_z0 > 0.05 else '❌'} 插入={'✅' if ins > 0 else '❌'} 阶段={m.get('stage')} actionLog={log_n}条", flush=True)

print(f"== P3 指标量测验证: 抓起={lifts}/8 插入={ins}/8", flush=True)
# 打印一个成功 seed 的完整指标
for m in all_metrics:
    if m.get("metrics"):
        print(f"\n最后阶段 {m.get('stage')} ({m.get('stageIdx')}/8) 指标:", flush=True)
        for x in m["metrics"]:
            print(f"  {x['name']}: {x['v']}{x['unit']} (目标 {x['target']}{x['unit']}) {'✅' if x['pass'] else '❌'}", flush=True)
        break
