# -*- coding: utf-8 -*-
"""🔁 离线回放检验 (原项目自己的评法): 数据集真帧 → 模型 → 预测动作 vs 教师动作

原项目 eval.py 做的就是这件事: 拿数据集里的真帧喂模型, 把它输出的 action 与数据集里的
action 列比。这里用同口径在本域数据 (zmax_insert.h5) 上跑, 回答一个判决性问题:
    **微调后的模型, 在它自己的训练分布内, 能不能输出本任务可用的动作?**
  · 若不能 (误差大/相关≈0) → 直驱 0% 的根因是"模型还没学会本任务动作" (训练量/数据量),
    不是接线问题;
  · 若能   → 根因在闭环侧 (状态分布漂移/目标帧/历史动作), 继续查闭环。

用法:
  ./gui-venv311/bin/python tools/intact_replay_check.py --n 120 --stride 120 --device cuda
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(TOOLS, "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("STABLEWM_HOME", _CACHE)
os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
IMG = 224


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", default=os.path.join(_CACHE, "datasets", "zmax_insert.h5"))
    ap.add_argument("--n", type=int, default=120, help="抽样帧数")
    ap.add_argument("--stride", type=int, default=150, help="采样间隔 (帧)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--task", default="pusht")
    ap.add_argument("--horizon", type=int, default=8)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    import h5py, hdf5plugin                                    # noqa: F401,PLC0415
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime   # noqa: PLC0415
    stats = json.load(open(os.path.join(ROOT, "reports", "zmax_action_stats.json"),
                           encoding="utf-8"))
    a_mean = np.asarray(stats["mean"], np.float32)
    a_std = np.asarray(stats["std"], np.float32)

    f = h5py.File(a.h5, "r")
    px, act, ep_len, ep_off = f["pixels"], f["action"], f["ep_len"][:], f["ep_offset"][:]
    N = px.shape[0]
    print(f"═══ 离线回放检验 (原项目评法) · {os.path.basename(a.h5)} · {N} 帧 ═══")
    print(f"   抽样 n={a.n} stride={a.stride} · 逆归一化 a_raw = z·std + mean (n={stats['n_finite']})")

    idx = list(range(0, N, a.stride))[:a.n]
    rt = IntactRuntime(task=a.task, device=a.device)
    node = IntactNode(horizon=a.horizon, runtime=rt)
    if not node.runtime.trained:
        print(f"❌ INTACT 未就绪: {node.runtime.reason}")
        return 3
    print(f"   模型: policy={os.environ.get('INTACT_POLICY', '?')} · "
          f"runtime={os.environ.get('INTACT_RUNTIME', 'auto')} · action_dim={node.action_dim}")

    # goal: 用第 0 个回合的末帧 (任务完成态) —— 与原项目"给定 goal 图"一致
    _g = px[int(ep_off[0] + ep_len[0] - 2)]
    node.set_goal(np.transpose(np.asarray(_g, np.float32), (2, 0, 1)))

    preds, gts, t0 = [], [], time.time()
    for k, i in enumerate(idx):
        fr = np.transpose(np.asarray(px[i], np.float32), (2, 0, 1))
        out = node.step(fr, obs_source="engine_render")
        chunk = np.asarray(out.chunk, np.float32)
        raw = chunk[0, a.slot * 4:(a.slot + 1) * 4]
        preds.append(np.clip(raw * a_std + a_mean, -1, 1))
        gts.append(np.asarray(act[i], np.float32))
        if (k + 1) % 30 == 0:
            print(f"   [{k+1}/{len(idx)}] {time.time()-t0:.0f}s", flush=True)
    node.close()
    P, G = np.asarray(preds, np.float32), np.asarray(gts, np.float32)

    from scipy.stats import spearmanr, pearsonr
    print(f"\n═══ 预测动作 vs 教师动作 (n={len(P)}) ═══")
    names = ["dx", "dy", "dz", "grip"]
    for j, nm in enumerate(names):
        mae = float(np.abs(P[:, j] - G[:, j]).mean())
        rho = spearmanr(P[:, j], G[:, j])[0]
        r = pearsonr(P[:, j], G[:, j])[0]
        print(f"   {nm:<5} MAE={mae:.4f} · pearson={r:+.3f} · spearman={rho:+.3f} "
              f"· 教师std={G[:, j].std():.4f} · 预测std={P[:, j].std():.4f}")
    # 常数预测基线 (教师均值) —— 模型若不如"总输出均值", 则它没学到东西
    const = np.repeat(G.mean(0)[None], len(G), 0)
    print(f"   对照: 常数基线(教师均值) xyz MAE={np.abs(const[:, :3]-G[:, :3]).mean():.4f}"
          f" · 模型 xyz MAE={np.abs(P[:, :3]-G[:, :3]).mean():.4f}")
    # 方向一致性 (符号): 夹爪开合 & xy 方向
    for j, nm in enumerate(names):
        agree = float(((np.sign(P[:, j]) == np.sign(G[:, j])) | (np.abs(G[:, j]) < 0.05)).mean())
        print(f"   方向一致率 {nm:<5}: {agree:.2f}")

    out = a.out or os.path.join(ROOT, "reports",
                                f"intact_replay_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"meta": {"h5": a.h5, "n": len(P), "stride": a.stride, "slot": a.slot,
                        "policy": os.environ.get("INTACT_POLICY", ""),
                        "runtime": os.environ.get("INTACT_RUNTIME", ""),
                        "obs": "数据集真帧 (与训练同源)", "ts": time.strftime("%F %T")},
               "per_axis": {nm: {"mae": float(np.abs(P[:, j] - G[:, j]).mean()),
                                 "pearson": float(pearsonr(P[:, j], G[:, j])[0]),
                                 "spearman": float(spearmanr(P[:, j], G[:, j])[0]),
                                 "teacher_std": float(G[:, j].std()),
                                 "pred_std": float(P[:, j].std())}
                            for j, nm in enumerate(names)},
               "model_xyz_mae": float(np.abs(P[:, :3] - G[:, :3]).mean()),
               "const_xyz_mae": float(np.abs(const[:, :3] - G[:, :3]).mean())},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"   → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
