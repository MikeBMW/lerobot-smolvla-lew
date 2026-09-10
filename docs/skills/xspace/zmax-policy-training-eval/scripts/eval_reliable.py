#!/usr/bin/env python3
"""可靠性评估: 每 seed 重复 N 次, 模型 vs 解析链 同口径对照。

为什么必须这样跑 (2026-09-10 实测): metaworld 布局**每进程漂移** → 单次评估是随机抽样。
本 session 单跑得到"模型 5/6", 多重复复核却是 **0/15**, 而解析链同口径 **15/15 且步数逐次完全一致**。
单次结果一律不能作为"模型有提升"的依据。

用法 (两条命令, 同一脚本 = 同口径):
    # A. 模型 (xyz 由模型出, gripper 由状态机管)
    MUJOCO_GL=egl SS_MUSCLE=0 EVAL_MODE=model EVAL_SEEDS="104,0,6,101,7" EVAL_REPS=3 \
      SS_L3=1 SS_L3_CK="outputs/train/<dir>/checkpoints/last/pretrained_model" \
      gui-venv311/bin/python -u eval_reliable.py

    # B. 对照组: 解析链 (只改 EVAL_MODE)
    MUJOCO_GL=egl SS_MUSCLE=0 EVAL_MODE=analytic EVAL_SEEDS="104,0,6,101,7" EVAL_REPS=3 \
      gui-venv311/bin/python -u eval_reliable.py

注意:
- REPO 路径按需改 (默认 Z-MAX 仓库根)。
- 每次 run() 都新建 sim 实例 = 新布局 = 真正的"多次尝试" (复用同一实例不算)。
- 汇报必须给逐 seed 分布 (wins/reps), 不是只给总数百分比。
"""
import os
import sys

REPO = os.environ.get("REPO", "/home/ubuntu/lerobot-smolvla-lew")
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
os.chdir(os.path.join(REPO, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ["SS_MUSCLE"] = "0"

from state_space_sim_real import RealStateSpaceSim  # noqa: E402

MODE = os.environ.get("EVAL_MODE", "model")        # model | analytic
seeds = [int(x) for x in os.environ.get("EVAL_SEEDS", "104,0,6,101,7").split(",")]
reps = int(os.environ.get("EVAL_REPS", "3"))
max_steps = int(os.environ.get("EVAL_MAX_STEPS", "600"))

if MODE == "model":
    os.environ["SS_L3"] = "1"                      # xyz 由模型出 (SS_L3_CK 指定 checkpoint)
else:
    os.environ.pop("SS_L3", None)                  # 对照组: 纯解析链

res = {}
for sd in seeds:
    wins, steps_ok = 0, []
    for _ in range(reps):
        try:
            sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *a: None)
            tr = sim.run(max_steps=max_steps)
            d = bool(tr["done"][-1]) if tr.get("done") else False
            wins += d
            if d:
                steps_ok.append(len(tr["t"]))
        except Exception as e:
            print(f"  seed {sd}: 异常 {e}", flush=True)
    res[sd] = (wins, reps)
    print(f"seed {sd}: {wins}/{reps} 成功" + (f" (成功步数 {steps_ok})" if steps_ok else ""),
          flush=True)

tot_w = sum(v[0] for v in res.values())
tot = len(seeds) * reps
print(f"\n🎯 [{MODE}] 总成功率: {tot_w}/{tot} = {tot_w / tot * 100:.0f}%  (每 seed ×{reps} 重复)")
print("⚠️ 报结论前: 对照组必须在本脚本同口径下跑过, 否则不构成对比。")
