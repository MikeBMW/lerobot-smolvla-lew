#!/usr/bin/env python3
"""Z-MAX ACT 基线对比评估 · 自动迭代对比工具
在同一 metaworld_mt50 数据上对比 基线模型 vs 新模型:
  - 动作 MSE (预测 vs 专家动作)
  - 成功率 (动作误差 < 阈值)
  - 推理延迟

用法:
  python3 tools/act_compare.py --baseline outputs/train/act_metaworld/checkpoints/000300/pretrained_model \
    --candidate outputs/train/act_closed_loop_v110/checkpoints/002000/pretrained_model \
    --report docs/CICD_COMPARE_v1.1.0.html
"""
import argparse, json, time, torch
import numpy as np
from pathlib import Path

torch.set_grad_enabled(False)


def load_policy(ckpt_path):
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies import make_pre_post_processors
    policy = ACTPolicy.from_pretrained(ckpt_path).cuda().eval()
    # 用已加载 policy 的 config 构造处理器 (含归一化统计)
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=policy.config, pretrained_path=str(ckpt_path))
    return policy, postprocessor


def load_test_data(dataset_root, n_eps=10, frames_per_ep=20, max_frames=100):
    """用 LeRobotDataset 加载 (与训练一致的管道, 自动生成缺失图像)"""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds = LeRobotDataset("lerobot/pusht", root=dataset_root)
    n = len(ds)
    step = max(1, n // max_frames)
    idxs = list(range(0, n, step))[:max_frames]
    states, actions, imgs = [], [], []
    for i in idxs:
        item = ds[i]
        states.append(item["observation.state"].numpy().astype(np.float32))
        actions.append(item["action"].numpy().astype(np.float32))
        imgs.append(item["observation.image"].numpy().astype(np.float32))
    states = np.stack(states)
    actions = np.stack(actions)
    imgs = np.stack(imgs)
    print(f"  测试数据: {len(idxs)}帧 (LeRobotDataset管道) · state{states.shape[1]}D action{actions.shape[1]}D img{imgs.shape}")
    return states, actions, imgs


def eval_model(policy, postprocessor, dataset_root, tag, device="cuda", n_eps=10, frames_per_ep=20):
    """评估: 状态→预测动作(反归一化) vs 专家动作"""
    states, gt_actions, imgs = load_test_data(dataset_root, n_eps, frames_per_ep)
    has_img = bool(imgs is not None and policy.config.image_features)
    mses, lats = [], []
    hits = 0
    for i in range(len(states)):
        batch = {"observation.state": torch.from_numpy(states[i]).float().cuda().unsqueeze(0)}
        if has_img:
            batch["observation.image"] = torch.from_numpy(imgs[i]).float().cuda().unsqueeze(0)
        gt = gt_actions[i]
        t0 = time.time()
        out = policy.select_action(batch)
        # 反归一化 (unnormalizer)
        out = postprocessor(out)
        lat = (time.time() - t0) * 1000
        pred = out[0].cpu().numpy() if isinstance(out, (list, tuple)) else out.cpu().numpy()
        pred = np.asarray(pred).flatten()[: len(gt)]
        mse = float(np.mean((pred - gt) ** 2))
        mses.append(mse)
        lats.append(lat)
        if mse < 0.05:
            hits += 1
    n = len(mses)
    result = {
        "tag": tag, "frames": n,
        "action_mse": float(np.mean(mses)),
        "mse_std": float(np.std(mses)),
        "success_rate": hits / n,
        "latency_ms": float(np.mean(lats)),
    }
    print(f"📊 {tag}: MSE={result['action_mse']:.4f}±{result['mse_std']:.4f} "
          f"| 成功率={result['success_rate']*100:.1f}% | 延迟={result['latency_ms']:.1f}ms")
    return result


def make_report(base, cand, out):
    if base["action_mse"] == 0:
        mse_improve = 0
    else:
        mse_improve = (base["action_mse"] - cand["action_mse"]) / base["action_mse"] * 100
    succ_improve = cand["success_rate"] - base["success_rate"]
    verdict = "✅ 提升" if mse_improve > 0 else "❌ 未提升 (需改进重训)"
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>ACT 基线对比 v1.1.0</title>
<style>body{{font-family:Consolas,monospace;background:#0d1117;color:#c9d1d9;padding:32px}}
h1{{color:#58a6ff}} table{{border-collapse:collapse;width:100%;margin:12px 0}}
td,th{{border:1px solid #30363d;padding:10px 14px;text-align:left}}
.up{{color:#2ea043}} .down{{color:#f85149}}</style></head><body>
<h1>🤖 ACT 模型对比评估 <span style="background:#1f6feb;color:#fff;padding:2px 8px;border-radius:4px">v1.1.0</span></h1>
<p>数据集: metaworld_mt50 · 测试帧: {cand['frames']} · 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
<table><tr><th>指标</th><th>基线 (act_metaworld)</th><th>候选 (v1.1.0)</th><th>提升</th></tr>
<tr><td>动作 MSE</td><td>{base['action_mse']:.4f}</td><td>{cand['action_mse']:.4f}</td>
<td class="{'up' if mse_improve>0 else 'down'}">{mse_improve:+.1f}%</td></tr>
<tr><td>成功率 (&lt;0.05)</td><td>{base['success_rate']*100:.1f}%</td><td>{cand['success_rate']*100:.1f}%</td>
<td class="{'up' if succ_improve>0 else 'down'}">{succ_improve*100:+.1f}pp</td></tr>
<tr><td>推理延迟</td><td>{base['latency_ms']:.1f}ms</td><td>{cand['latency_ms']:.1f}ms</td>
<td class="{'up' if base['latency_ms']>cand['latency_ms'] else 'down'}">{cand['latency_ms']-base['latency_ms']:+.1f}ms</td></tr>
</table>
<h2 style="color:{'#2ea043' if mse_improve>0 else '#f85149'}">结论: {verdict}</h2>
<p>模型提升路径: 基线(300步) → 更多数据 → 更长训练(2000步) → 超参调优 → 架构升级(SmolVLA)</p>
</body></html>"""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(html, encoding="utf-8")
    print(f"📄 报告: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--dataset", default="data/metaworld_mt50")
    ap.add_argument("--report", default="docs/CICD_COMPARE_v1.1.0.html")
    ap.add_argument("--n-eps", type=int, default=10)
    args = ap.parse_args()

    print(f"=== ACT 基线对比: {args.baseline} vs {args.candidate} ===")
    base_p, base_pp = load_policy(args.baseline)
    cand_p, cand_pp = load_policy(args.candidate)
    base = eval_model(base_p, base_pp, args.dataset, "基线", n_eps=args.n_eps)
    cand = eval_model(cand_p, cand_pp, args.dataset, "候选v1.1.0", n_eps=args.n_eps)
    make_report(base, cand, args.report)
    # 输出对比 JSON (供 CICD 自动判断)
    result = {"baseline": base, "candidate": cand,
              "mse_improve_pct": round((base["action_mse"] - cand["action_mse"]) / max(base["action_mse"], 1e-9) * 100, 2)}
    Path("docs/CICD_COMPARE_v1.1.0.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("📊 JSON:", json.dumps(result["mse_improve_pct"]))
