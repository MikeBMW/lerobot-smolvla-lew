# -*- coding: utf-8 -*-
"""🔬 离线回放口径下的「打不过常数基线」偏置探查 (2026-09-14)

问题: 判闸里动作头 xyz MAE 0.0420 > 常数基线 0.0325 —— 模型比「直接预测教师均值」还差 29%。
      这不是记忆通道的问题 (v5 四轮 / v6r2 三轮同样打不过)。要知道偏在哪: 是**整体偏移**、
      还是**幅度塌缩**、还是**逐维尺度/口径错**。

做法 (与 v6_judge_watch.py 完全同一采样/同一 ckpt/同一反归一化):
  1) 逐维印 教师 mean/std、模型 pred mean/std、偏置 (pred_mean - teacher_mean)
  2) 误差分解: MAE(原样) · MAE(去整体偏置后) · MAE(只把 pred 拉伸到教师 std 后) → 看谁是主项
  3) 印反归一化前的 raw chunk 统计 vs 统计文件里的 mean/std → 看模型原始输出是否缩在均值附近
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", default="/home/ubuntu/stable-wm-cache/datasets/optical_insert_v5_disturb.h5")
    ap.add_argument("--stats", default=os.path.join(ROOT, "reports", "optical_insert_v5_action_stats.json"))
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--stride", type=int, default=120)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--task", default="pusht")
    ap.add_argument("--horizon", type=int, default=8)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--goal-mode", default="ep0", choices=["ep0", "own"],
                    help="ep0 = 判闸现状 (所有帧都拿第0回合末帧当 goal) / own = 每帧用**自己所属回合**的末帧")
    ap.add_argument("--out", default="/tmp/l4_bias_probe.json")
    a = ap.parse_args()

    import h5py
    from lerobot.policies.intact.runtime.node import IntactNode
    from lerobot.policies.intact.runtime.model_adapter import IntactRuntime

    stats = json.load(open(a.stats, encoding="utf-8"))
    mean = np.asarray(stats["mean"], np.float32)
    std = np.asarray(stats["std"], np.float32)
    print(f"统计文件 {os.path.basename(a.stats)}: n_finite={stats.get('n_finite')}")
    print("  action mean:", np.round(mean, 5).tolist())
    print("  action std :", np.round(std, 5).tolist())

    f = h5py.File(a.h5, "r")
    px, act, ep_len, ep_off = f["pixels"], f["action"], f["ep_len"][:], f["ep_offset"][:]
    N = px.shape[0]
    idx = list(range(0, N, a.stride))[:a.n]
    print(f"\n回放 {os.path.basename(a.h5)} · {N} 帧 · 抽 n={len(idx)} (stride={a.stride})")

    rt = IntactRuntime(task=a.task, device=a.device)
    node = IntactNode(horizon=a.horizon, runtime=rt)
    if not node.runtime.trained:
        print(f"❌ INTACT 未就绪: {node.runtime.reason}")
        return 3
    print(f"模型: policy={os.environ.get('INTACT_POLICY','?')} · action_dim={node.action_dim} "
          f"· history={getattr(node,'obs_hist_len','?')}")
    g = px[int(ep_off[0] + ep_len[0] - 2)]
    node.set_goal(np.transpose(np.asarray(g, np.float32), (2, 0, 1)))
    # 每帧所属回合 (own 模式用) —— 口径对照: goal 是同回合自己的目标 vs 外来的第 0 回合目标
    _ep_of = np.searchsorted(np.asarray(ep_off, np.int64), np.asarray(idx, np.int64), side="right") - 1
    print(f"goal 模式: {a.goal_mode}" + ("  (每帧用自己回合末帧)" if a.goal_mode == "own" else "  (判闸现状)"))

    P, G, RAW, SK = [], [], [], []
    for i, e in zip(idx, _ep_of):
        if a.goal_mode == "own":
            gg = px[int(ep_off[e] + ep_len[e] - 2)]
            node.set_goal(np.transpose(np.asarray(gg, np.float32), (2, 0, 1)))
        fr = np.transpose(np.asarray(px[i], np.float32), (2, 0, 1))
        sk = np.asarray(f["skill_ctx"][i], np.float32)
        out = node.step(fr, obs_source="engine_render", skill_ctx=sk)
        chunk = np.asarray(out.chunk, np.float32)
        RAW.append(chunk[0])
        P.append(np.clip(chunk[0, a.slot * 4:(a.slot + 1) * 4] * std + mean, -1, 1))
        G.append(np.asarray(act[i], np.float32))
        SK.append(sk)
    node.close()
    P, G, RAW, SK = map(np.asarray, (P, G, RAW, SK))

    names = ["dx", "dy", "dz", "grip"]
    try:
        from scipy.stats import pearsonr
    except Exception:
        pearsonr = None
    print(f"\n{'dim':<6}{'教师mean':>10}{'教师std':>9}{'预测mean':>10}{'预测std':>9}"
          f"{'偏置':>9}{'MAE原样':>9}{'MAE去偏':>9}{'常数基线':>10}{'pearson':>9}")
    rows = {}
    for j, nm in enumerate(names):
        tm, ts = float(G[:, j].mean()), float(G[:, j].std())
        pm, ps = float(P[:, j].mean()), float(P[:, j].std())
        bias = pm - tm
        mae = float(np.abs(P[:, j] - G[:, j]).mean())
        mae_deb = float(np.abs((P[:, j] - bias) - G[:, j]).mean())
        const = float(np.abs(G[:, j] - tm).mean())
        r = float(pearsonr(P[:, j], G[:, j])[0]) if pearsonr is not None else float("nan")
        print(f"{nm:<6}{tm:>10.4f}{ts:>9.4f}{pm:>10.4f}{ps:>9.4f}{bias:>+9.4f}"
              f"{mae:>9.4f}{mae_deb:>9.4f}{const:>10.4f}{r:>+9.3f}")
        rows[nm] = dict(teacher_mean=tm, teacher_std=ts, pred_mean=pm, pred_std=ps, bias=bias,
                        mae=mae, mae_debiased=mae_deb, mae_const=const, pearson=r,
                        std_ratio=(ps / ts if ts else 0.0))

    # 尺度诊断: 把预测线性拉伸到教师同 mean/std 后还剩多少误差 (纯"尺度错"能解释多少)
    print(f"\n{'dim':<6}{'去偏+同尺度后MAE':>16}{'纯偏置贡献':>12}{'纯幅度贡献':>12}")
    for j, nm in enumerate(names):
        tm, ts, pm, ps = (rows[nm]["teacher_mean"], rows[nm]["teacher_std"],
                          rows[nm]["pred_mean"], rows[nm]["pred_std"])
        z = (P[:, j] - pm) / (ps if ps > 1e-9 else 1.0)
        stretched = z * ts + tm
        mae_s = float(np.abs(stretched - G[:, j]).mean())
        print(f"{nm:<6}{mae_s:>16.4f}{rows[nm]['mae'] - rows[nm]['mae_debiased']:>12.4f}"
              f"{rows[nm]['mae_debiased'] - mae_s:>12.4f}")
        rows[nm]["mae_rescaled"] = mae_s

    print(f"\nraw chunk (反归一化前, 前 4 维) 统计 vs 统计文件 mean/std:")
    for j, nm in enumerate(names):
        print(f"  {nm:<5} raw mean {RAW[:, j].mean():+.4f} / raw std {RAW[:, j].std():.4f}"
              f"   ← 统计 mean {mean[j]:+.4f} / std {std[j]:.4f}")

    # 专家动作是否分相位/幅度 --- 教师动作自身是否存在"大幅帧"被平均掉
    print(f"\n教师动作幅度分位 (解释常数基线为何容易赢):")
    for j, nm in enumerate(names):
        q = np.percentile(np.abs(G[:, j]), [50, 90, 99, 100])
        print(f"  {nm:<5} |a| 分位 50/90/99/max = {q[0]:.4f} / {q[1]:.4f} / {q[2]:.4f} / {q[3]:.4f}")

    json.dump({"ckpt": os.environ.get("INTACT_POLICY", "?"), "n": len(idx), "per_dim": rows},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
