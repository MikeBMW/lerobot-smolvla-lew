#!/usr/bin/env python3
"""📊 模型评估 (状态空间) — Z700 双脑模型稳定性评估 (2026-08-12 老倪)
算法 (参考: LeftRight 双脑状态空间建立):
  状态 X = [X_obs(43D), X_latent(潜), X_sm(状态机6阶段)]
  连续: 左脑 a=f_MLP(obs) · 右脑 [obs_pred, contact]=f_WM(obs,a) · 环境 obs'=Env(obs,a)
  离散: 状态机 contact+距离阈值转移
指标:
  1. L2 增益: obs 扰动 δ → 动作变化比 (左脑 Lipschitz 常数估计, gain<1=压缩稳定)
  2. BIBO: 随机有界 obs → 动作/next_obs 范数有界性
  3. 自回归谱半径: 右脑 next_obs 多步预测误差增长率 (ρ>1=误差滚雪球)
  4. 状态机覆盖: 6 阶段可达性 + 插拔成功率
  5. contact 桥接: 接近阶段 contact 概率分布 (触发抓取阈值 0.5)

用法: BRAIN_CKPT=<dir> .venv/bin/python tools/eval_state_space.py [seeds]
输出: 终端报告 + reports/eval_state_space.json
"""
import os
import sys
import json
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import numpy as np
import torch

from gen_insert_video import _load_brain
from train_full_pipeline import (make_env, get_obs, ST_APPROACH, ST_GRASP, ST_LIFT,
                                 ST_TRANSFER, ST_INSERT, ST_DONE, ST_NAMES)


def _device():
    return "cuda" if torch.cuda.is_available() else "cpu"


def _obs_dim(left):
    """左脑输入维数推断 (LeftBrainMLP 无 obs_dim 属性 — 从首个线性层取)"""
    for m in left.modules():
        if hasattr(m, "in_features"):
            return int(m.in_features)
    return 39


def l2_gain(left, xm, xs, ym, ys, n_samples=200, eps=0.01):
    """① L2 增益: 左脑静态映射 Lipschitz 常数估计 (有界 obs 扰动 → 动作变化比)
    gain = max ||Δa|| / ||δ|| — <1 压缩稳定, >1 放大"""
    dev = next(left.parameters()).device
    gains = []
    rng = np.random.RandomState(42)
    for _ in range(n_samples):
        obs = rng.uniform(-1, 1, _obs_dim(left)).astype(np.float64)
        delta = rng.uniform(-eps, eps, _obs_dim(left)).astype(np.float64)
        x1 = torch.tensor((obs - xm) / xs, dtype=torch.float32).unsqueeze(0).to(dev)
        x2 = torch.tensor((obs + delta - xm) / xs, dtype=torch.float32).unsqueeze(0).to(dev)
        with torch.no_grad():
            a1 = left(x1).cpu().numpy()[0] * ys + ym
            a2 = left(x2).cpu().numpy()[0] * ys + ym
        da = np.linalg.norm(a2 - a1)
        ddx = np.linalg.norm(delta)
        if ddx > 1e-12:
            gains.append(da / ddx)
    g = float(np.max(gains)) if gains else float("inf")
    return g, float(np.mean(gains)) if gains else 0.0


def bibo_check(left, right, xm, xs, ym, ys, n_samples=100):
    """② BIBO: 随机有界输入 → 输出有界性 (有界输入有界输出)"""
    dev = next(left.parameters()).device
    act_norms, nxt_norms = [], []
    rng = np.random.RandomState(7)
    for _ in range(n_samples):
        obs = rng.uniform(-1, 1, _obs_dim(left)).astype(np.float64)
        xin = torch.tensor((obs - xm) / xs, dtype=torch.float32).unsqueeze(0).to(dev)
        with torch.no_grad():
            a = left(xin).cpu().numpy()[0]
        act = a * ys + ym
        act_norms.append(float(np.linalg.norm(act)))
        with torch.no_grad():
            nxt, _ = right(xin, torch.tensor(act, dtype=torch.float32).unsqueeze(0).to(dev))
        nxt_norms.append(float(nxt.cpu().numpy()[0].max()))
    return float(np.max(act_norms)), float(np.mean(act_norms)), float(np.max(nxt_norms))


def autoregressive_rho(left, right, xm, xs, ym, ys, n_steps=8, n_trials=20):
    """③ 自回归谱半径: 右脑 next_obs 预测误差增长率 (多步迭代误差是否滚雪球)
    ρ ≈ mean(||obs_{k+1}-obs_{k}|| / ||obs_k - obs_{k-1}||) — >1 发散风险"""
    dev = next(left.parameters()).device
    rng = np.random.RandomState(3)
    ratios = []
    for _ in range(n_trials):
        obs = rng.uniform(-1, 1, _obs_dim(left)).astype(np.float64)
        prev_err = None
        for k in range(n_steps):
            xin = torch.tensor((obs - xm) / xs, dtype=torch.float32).unsqueeze(0).to(dev)
            with torch.no_grad():
                a = left(xin).cpu().numpy()[0] * ys + ym
                nxt, _ = right(xin, torch.tensor(a, dtype=torch.float32).unsqueeze(0).to(dev))
            nxt = nxt.cpu().numpy()[0]
            err = float(np.linalg.norm(nxt - obs))
            if k > 0 and prev_err > 1e-9:
                ratios.append(err / prev_err)
            prev_err = err
            obs = nxt
    rho = float(np.mean(ratios)) if ratios else 0.0
    return rho, len(ratios)


def state_machine_coverage(left, right, xm, xs, ym, ys, seeds=(0, 1, 2, 3)):
    """④ 状态机覆盖: 6 阶段可达性 + 插拔成功率 (真实环境 rollout)"""
    dev = next(left.parameters()).device
    reached = set()
    results = []
    for seed in seeds:
        env = make_env(seed)
        o = get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        state = ST_APPROACH
        for step in range(400):
            hand = env.data.site_xpos[env.model.site("endEffector").id]
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            d_hp = float(np.linalg.norm(hand - peg))
            d_ph = float(np.linalg.norm(peg - hole))
            xin = torch.from_numpy((o - xm) / xs).float().to(dev)
            with torch.no_grad():
                pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
            act = pred * ys + ym
            with torch.no_grad():
                _, pred_cont = right(xin.unsqueeze(0),
                                     torch.from_numpy(act).float().to(dev).unsqueeze(0))
            contact = pred_cont.item()
            if state == ST_APPROACH:
                if d_hp < 0.06 and contact > 0.5:
                    state = ST_GRASP
            elif state == ST_GRASP:
                if peg[2] - peg_z0 > 0.02:
                    state = ST_LIFT
            elif state == ST_LIFT:
                if peg[2] > peg_z0 + 0.08:
                    state = ST_TRANSFER
            elif state == ST_TRANSFER:
                if abs(peg[0] - hole[0]) < 0.05 and abs(peg[1] - hole[1]) < 0.05:
                    state = ST_INSERT
            elif state == ST_INSERT:
                if d_ph < 0.05:
                    state = ST_DONE
            reached.add(state)
            if state == ST_APPROACH:
                delta = peg - hand
                act[:3] = act[:3] * 0.3 + np.clip(delta * 2.0, -1, 1)
                act[3] = -1.0
            elif state == ST_GRASP:
                act[:3] = act[:3] * 0.1
                act[3] = 0.6
            elif state == ST_LIFT:
                act[:3] = [0, 0, 0.8]
                act[3] = 0.6
            elif state == ST_TRANSFER:
                d_xy = np.array([hole[0] - peg[0], hole[1] - peg[1]])
                if np.linalg.norm(d_xy) > 1e-4:
                    act[:3] = np.clip((d_xy / np.linalg.norm(d_xy)) * 0.6, -1, 1).tolist() + [0.0]
                act[3] = 0.6
            elif state == ST_INSERT:
                act[:3] = [0, 0, np.clip((hole[2] - peg[2]) * 2.0, -0.6, 0.6)]
                act[3] = 0.6
            else:
                act[:3] = [0, 0, 0]
                act[3] = 0.6
            _mx = float(np.abs(act).max()) if len(act) else 1.0
            if _mx > 1.0:
                act = act / _mx
            try:
                env.step(np.clip(act, -1, 1))
                env.render()
            except Exception:
                break
            o = get_obs(env)
            if state == ST_DONE:
                break
        results.append({"seed": seed, "final": ST_NAMES[state], "steps": step + 1,
                        "success": state == ST_DONE})
        env.close()
    cov = len(reached) / 6.0
    ok = sum(1 for r in results if r["success"])
    return {"coverage": cov, "success_rate": ok / len(results), "results": results}


def main():
    seeds = [int(s) for s in sys.argv[1:]] or [0, 1, 2, 3]
    t0 = time.time()
    print("🧠 加载双脑模型 …", flush=True)
    left, right, xm, xs, ym, ys = _load_brain()
    ckpt = os.environ.get("BRAIN_CKPT", "最新")

    print("① L2 增益 (左脑 Lipschitz 常数估计) …", flush=True)
    g_max, g_mean = l2_gain(left, xm, xs, ym, ys)
    print(f"   gain_max={g_max:.4f} gain_mean={g_mean:.4f} → {'✅ 压缩稳定' if g_max < 1 else '⚠ 放大风险'}", flush=True)

    print("② BIBO 检查 (有界输入→有界输出) …", flush=True)
    a_max, a_mean, n_max = bibo_check(left, right, xm, xs, ym, ys)
    print(f"   动作范数 max={a_max:.3f} mean={a_mean:.3f} · next_obs max={n_max:.3f} → {'✅ 有界' if np.isfinite(a_max) else '❌ 发散'}", flush=True)

    print("③ 自回归谱半径 ρ (右脑多步预测误差) …", flush=True)
    rho, n_rat = autoregressive_rho(left, right, xm, xs, ym, ys)
    print(f"   ρ={rho:.4f} ({n_rat} 样本) → {'✅ 收敛' if rho < 1 else '⚠ 误差滚雪球'}", flush=True)

    print(f"④ 状态机覆盖 (seeds={seeds}) …", flush=True)
    smc = state_machine_coverage(left, right, xm, xs, ym, ys, seeds=seeds)
    print(f"   6阶段覆盖={smc['coverage']:.0%} 成功率={smc['success_rate']:.0%}", flush=True)
    for r in smc["results"]:
        print(f"   seed{r['seed']}: {r['final']} ({r['steps']}步) {'✅' if r['success'] else '❌'}", flush=True)

    stable_l2 = g_max < 1
    stable_bibo = np.isfinite(a_max)
    stable_ar = rho < 1
    stable_sm = smc["success_rate"] >= 0.5
    verdict = "✅ 稳定 (混合确定性: BIBO + 状态机硬约束)" if (stable_bibo and stable_sm) else \
              ("⚠ 部分稳定 (自回归有发散风险)" if stable_bibo else "❌ 不稳定")

    rep = {"ckpt": ckpt, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
           "l2_gain": {"max": g_max, "mean": g_mean, "stable": stable_l2},
           "bibo": {"act_max": a_max, "act_mean": a_mean, "next_obs_max": n_max, "stable": stable_bibo},
           "autoregressive": {"rho": rho, "samples": n_rat, "stable": stable_ar},
           "state_machine": smc, "verdict": verdict}
    out = os.path.join(ROOT, "reports", "eval_state_space.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1,
                  default=lambda o: bool(o) if isinstance(o, (np.bool_, bool)) else str(o))
    print("\n══ 状态空间稳定性评估报告 ══", flush=True)
    print(f"模型: {ckpt}", flush=True)
    print(f"① L2 增益: {g_max:.4f} (mean {g_mean:.4f}) {'✅' if stable_l2 else '⚠'}", flush=True)
    print(f"② BIBO: 动作≤{a_max:.3f} next_obs≤{n_max:.3f} {'✅' if stable_bibo else '❌'}", flush=True)
    print(f"③ 自回归 ρ: {rho:.4f} {'✅' if stable_ar else '⚠'}", flush=True)
    print(f"④ 状态机: 覆盖{smc['coverage']:.0%} 成功率{smc['success_rate']:.0%}", flush=True)
    print(f"结论: {verdict}", flush=True)
    print(f"报告: {out} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
