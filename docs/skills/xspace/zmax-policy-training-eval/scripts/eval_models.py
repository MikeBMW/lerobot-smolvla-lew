#!/usr/bin/env python3
"""统一多模型评估循环 (2026-08-08 实测模式, 每次换数据版本重训后都用).

用法:
  DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python -u tools/eval_models.py [model1 model2 ...]

前置 (每次必做, 缺了 load_policy 直接 FileNotFoundError/形状错):
  1. reports/train_curve_<policy>.json 必须存在且含 "ckpt" 键:
       {"ckpt": "outputs/train/<dir>/checkpoints", "train_src": "本地4060"}
     load_policy 从该 json 读 ckpt_base, 再 sorted(glob(ckpt_base/*/pretrained_model)) 取最新的。
  2. eval_insert.py 的 _load_stats 里 _by_policy 候选列表**最新训练目录放最前** —
     旧 checkpoint 的 preprocessor 若维度不同 (如 39D vs 45D, 2D vs 45D) 会抢先匹配
     → `operands could not be broadcast (45,) vs (2,)` 假失败。改完候选重跑。
  3. 改了 meta 后 rm -rf ~/.cache/huggingface/datasets, 训练/评估用
     HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=1 (OFFLINE=1 时数据集 refs 解析报错)。

输出: reports/eval_grab6_5model.json + stdout 每 seed 一行 (评估慢模型如 SmolVLA
每 episode ~3 分钟, 8 seed × 5 模型约 40 分钟, 后台 + notify_on_complete 跑)。
"""
import sys, os, json, numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from eval_insert import load_policy, run_episode  # noqa: E402

DEFAULT_MODELS = ["act", "smolvla", "smolvla_lew", "vla_touch", "awe_zflow"]
SEEDS = 8
OUT = "reports/eval_grab6_5model.json"


def main():
    models = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_MODELS
    results = {}
    for name in models:
        # 前置校验: train_curve json 是否存在 (load_policy 依赖)
        curve = os.path.join("reports", f"train_curve_{name}.json")
        if not os.path.exists(curve):
            print(f"== {name}: 跳过 — 缺 {curve} (先建 {{'ckpt': 'outputs/train/.../checkpoints'}})", flush=True)
            continue
        try:
            pol, _ = load_policy(name)
            lifts = ins = 0
            dists = []
            for seed in range(SEEDS):
                r = run_episode(pol, seed, grip_assist=True, policy_name=name)
                lifts += int(r["lifted"])
                ins += int(r["inserted"])
                dists.append(r["dist_hole"])
                print(f"  {name} seed{seed}: 抓起={r['lifted']} 插入={r['inserted']} 距孔={r['dist_hole']:.3f}", flush=True)
            results[name] = {"lifts": lifts, "ins": ins, "mean_dist": float(np.mean(dists))}
            print(f"== {name}: 抓起={lifts}/{SEEDS} 插入={ins}/{SEEDS} 距孔={np.mean(dists):.3f}", flush=True)
        except Exception as e:
            print(f"== {name}: 评估失败 {str(e)[:100]}", flush=True)
    os.makedirs("reports", exist_ok=True)
    json.dump(results, open(OUT, "w"), indent=2)
    print(f"ALL_EVAL_DONE → {OUT}", flush=True)


if __name__ == "__main__":
    main()
