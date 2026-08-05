#!/usr/bin/env python3
"""⚔️ ACT vs SmolVLA 对比评估 — 统一 metaworld 数据集 (2026-08-04 老倪需求)

对比维度 (模型设计师口径):
  - 训练速度: 从 reports/train_curve_<policy>.json 读训练时实测 step/s (两模型同机同数据)
  - 精确度:   动作 MSE (预测 vs 专家) + 成功率 (MSE < 0.05)
  - 鲁棒性:   同一状态重复推理 5 次 → 预测动作标准差 (小 = 决策稳定)
  - 推理延迟: 单次 select_action 平均 ms (4060 CUDA)

用法: .venv/bin/python tools/compare_models.py [--frames 120]
输出: reports/model_compare_<ts>.json (供「📊 对比评估 Scope」读取绘图)
"""
import argparse, glob, json, os, sys, time
import numpy as np
import torch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def find_ckpt(policy):
    """读 reports/train_curve_<policy>.json → 最新 checkpoint 目录 + 训练速度 + loss曲线"""
    p = ROOT / "reports" / f"train_curve_{policy}.json"
    if not p.exists():
        return None, 0.0, [], None
    d = json.load(open(p))
    cands = sorted(glob.glob(str(ROOT / d.get("ckpt", "")) + "/*/pretrained_model"),
                   key=os.path.getmtime)
    return (cands[-1] if cands else None), d.get("step_s", 0.0), d.get("curve", []), d.get("ts")


def load_act(ckpt):
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies import make_pre_post_processors
    policy = ACTPolicy.from_pretrained(ckpt).to(DEVICE).eval()
    _, post = make_pre_post_processors(policy_cfg=policy.config, pretrained_path=str(ckpt))
    return policy, post


def load_smolvla(ckpt):
    from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
    policy = SmolVLALewPolicy.from_pretrained(ckpt).to(DEVICE).eval()
    post = getattr(policy, "postprocessor", None)
    return policy, post


def load_data(max_frames=120):
    """用 LeRobotDataset 加载 (与训练同管道 — info.json 定义 state/action 维度, 2026-08-05 实测:
    metaworld_act 的 info.json 是 2D (pusht 模板残留), 训练出的两模型 checkpoint 均为 action[2];
    npz 是 4D 不能直接用 → 必须走 LeRobotDataset 与训练对齐)
    同时返回 action 归一化统计 (mean/std, 全量帧) — 评估在归一化空间进行:
    模型输出即归一化空间, gt 用同统计归一化, 两模型同标准公平对比。"""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds = LeRobotDataset("lerobot/pusht", root=ROOT / "data" / "metaworld_act")
    n = len(ds)
    step = max(1, n // max_frames)
    idxs = list(range(0, n, step))[:max_frames]
    states, actions, imgs = [], [], []
    for i in idxs:
        item = ds[i]
        states.append(item["observation.state"].numpy().astype(np.float32))
        actions.append(item["action"].numpy().astype(np.float32))
        imgs.append(item["observation.image"].numpy().astype(np.float32))
    obs, st, act = np.stack(imgs), np.stack(states), np.stack(actions)
    # 归一化统计: 全量帧 (与训练 stats 同源, 采样帧近似即可 — 60 帧样本足够稳定)
    act_mean = act.mean(axis=0)
    act_std = act.std(axis=0) + 1e-6
    print(f"📦 统一测试集: {len(st)} 帧 · state{st.shape[1]}D · action{act.shape[1]}D · img{obs.shape}"
          f" · act_mean{np.round(act_mean,1)} std{np.round(act_std,1)} (归一化空间评估)")
    return obs, st, act, act_mean, act_std


def _post(post, out):
    if post is not None:
        try:
            return post(out)
        except Exception:
            pass
    return out


def _flat(out, n_act):
    pred = out[0].cpu().numpy() if isinstance(out, (list, tuple)) else out.cpu().numpy()
    return np.asarray(pred).flatten()[:n_act]


def eval_policy(policy, post, obs, st, act, act_mean, act_std, tag, is_act=True, n_repeat=5):
    mses, lats, robust = [], [], []
    hits = 0
    traj_pred, traj_gt = [], []   # 逐帧动作轨迹 (归一化空间) — 轨迹对比图数据源
    frame_err = []                # 逐帧 MSE — 误差曲线数据源
    with torch.no_grad():
        for i in range(len(st)):
            if not is_act:
                policy.reset()  # SmolVLA select_action 有状态队列 → 每帧清空保证独立预测
            # 图像统一 NCHW 0-1 (与训练同管道: LeRobotDataset 图像 (C,H,W);
            # tensor_to_pil 内部 *255+permute(1,2,0), 2026-08-05 实测传 NHWC 会 KeyError |u1)
            batch = {
                "observation.state": torch.from_numpy(st[i]).float().to(DEVICE).unsqueeze(0),
                "observation.image": torch.from_numpy(obs[i] / 255.0).float().to(DEVICE).unsqueeze(0),
            }
            # 归一化空间评估: gt 用同统计归一化, 模型输出即归一化空间 (不反归一化, 两模型同标准)
            gt = (act[i] - act_mean) / act_std
            t0 = time.time()
            out = policy.select_action(batch)
            lat = (time.time() - t0) * 1000
            pred = _flat(out, len(gt))  # 两模型统一: 原始输出 (归一化空间), 不反归一化
            mse = float(np.mean((pred - gt) ** 2))
            mses.append(mse)
            lats.append(lat)
            if mse < 0.05:
                hits += 1
            traj_pred.append(pred.tolist())
            traj_gt.append(gt.tolist())
            frame_err.append(mse)
            # 鲁棒性: 同一状态重复推理 → 动作 std (小=稳定, 归一化空间)
            stds = []
            for _ in range(n_repeat):
                o2 = policy.select_action(batch)
                stds.append(_flat(o2, len(gt)))
            robust.append(float(np.mean(np.std(np.stack(stds), axis=0))))
    n = len(mses)
    # 🔬 性能扩展维度 (2026-08-05 老倪: "除了loss曲线, 还有什么能对比模型性能"):
    # 轨迹/逐帧误差/误差分布/收敛指标 — 存进结果供 Scope 图表展示
    errs = np.array(mses)
    mse_p50 = float(np.percentile(errs, 50)) if n else 0.0
    mse_p90 = float(np.percentile(errs, 90)) if n else 0.0
    # 平滑度: 相邻预测动作差分 std (小=动作平稳, 真机抖动小)
    smooth = 0.0
    if len(traj_pred) > 1:
        diff = np.diff(np.array(traj_pred), axis=0)
        smooth = float(np.mean(np.std(diff, axis=0)))
    res = {
        "tag": tag, "frames": n,
        "action_mse": float(np.mean(mses)), "mse_std": float(np.std(mses)),
        "mse_p50": mse_p50, "mse_p90": mse_p90,      # 误差分布: 中位/长尾
        "success_rate": hits / n, "latency_ms": float(np.mean(lats)),
        "robustness_std": float(np.mean(robust)),
        "smoothness": smooth,                          # 动作平滑度
        "traj_pred": traj_pred[:120], "traj_gt": traj_gt[:120],  # 轨迹对比 (限120帧)
        "frame_err": frame_err[:120],                  # 逐帧误差曲线
    }
    print(f"📊 {tag}: MSE={res['action_mse']:.4f}±{res['mse_std']:.4f} | "
          f"成功率={res['success_rate']*100:.1f}% | 延迟={res['latency_ms']:.1f}ms | "
          f"鲁棒性={res['robustness_std']:.4f} | P90={mse_p90:.4f} | 平滑度={smooth:.4f}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    print(f"🔬 ACT / SmolVLA / SmolVLA+LEW 三模型对比评估 · 统一 metaworld_act · {DEVICE}")
    # 三策略: act / smolvla (纯动作, 无LEW) / smolvla_lew (串行世界模型)
    policies = [("act", "ACT"), ("smolvla", "SmolVLA"), ("smolvla_lew", "SmolVLA+LEW")]
    ckpts = {p: find_ckpt(p) for p, _ in policies}
    if not any(c[0] for c in ckpts.values()):
        print("❌ 无训练产物 — 先在控制台 ▶ 运行对比模板 (ACT + SmolVLA + SmolVLA+LEW 各训练一次)")
        return 1
    obs, st, act, act_mean, act_std = load_data(args.frames)

    results = {}
    for pol, tag in policies:
        ckpt, spd, curve, ts = ckpts[pol]
        if not ckpt:
            print(f"⏭️ {tag} 无 checkpoint, 跳过")
            continue
        print(f"✅ 加载 {tag}: {ckpt}")
        p, post = load_smolvla(ckpt) if pol != "act" else load_act(ckpt)
        results[pol] = eval_policy(p, post, obs, st, act, act_mean, act_std, tag,
                                   is_act=(pol == "act"), n_repeat=args.repeat)
        results[pol]["step_s"] = spd
        results[pol]["curve"] = curve
        results[pol]["ts"] = ts

    os.makedirs(ROOT / "reports", exist_ok=True)
    out = ROOT / "reports" / f"model_compare_{time.strftime('%Y%m%d_%H%M%S')}.json"
    json.dump({"ts": time.strftime("%Y%m%d_%H%M%S"), "dataset": "metaworld_act",
               "frames": len(st), "models": results}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"✅ 对比结果已存: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
