# -*- coding: utf-8 -*-
"""🔁 v4 光模块插拔 离线判闸 · **训练同源自监督回放** (v3 的口径修正版)

为什么要有 v4 (2026-09-14 夜, 老倪授权"补判闸口径"):
  v3 判闸 (intact_replay_check_v3.py, cron v6_judge_watch.py 在用) 有四处**与训练不同源**,
  导致它给出的 ❌ / "ΔMAE 7/7 全负" 不足以作为"记忆条无效"的证据:

  ① 观测窗口: v3 按 stride=120 抽样后**逐帧顺序喂**, 模型的 3 帧 obs 窗口 = 三帧相隔 360 帧的
     散帧; 训练里 obs 窗口 = 同一段轨迹上**相隔 2 帧**的连续帧 (frameskip=2)。
  ② 动作历史: v3 让 node 用**自己预测的 chunk** 滚动 action_hist (闭环); 训练里 previous_action
     = 该帧前 2 帧的**真动作** (PreviousActionDataset, raw 零初始化, 边界 raw 补零)。
  ③ goal: v3 把所有帧的 goal 都设成**第 0 回合末帧** (外来目标); 训练里 goal = 本窗口**自己末帧**
     (train.py::construct_intents → goal = embeddings[:, -1:]), 即"窗口内前视 2*(num_steps-1)=14 帧"
     的位移意图。⇒ 判闸喂的意图幅度与训练量级完全不同。
  ④ 覆盖/统计: v3 只抽 120 帧 (占 149,100 帧的 9.6%, 全在数据集前段), 只看 slot 0, 无重复、无波动。
     slot≥2 在 v3 里其实取到**空切片** (chunk 是 [horizon=8, 8], chunk[0, slot*4:] 只有 row0 的 8 维)。

本脚本按**训练口径**做 teacher-forced 回放, 并给出可判定记忆条件是否有效的最小充分设计:
  · 每个样本 = 一段**真轨迹上的连续窗口**:
      窗口 = 帧 [i-4, i-2, i] (stride=2, 与训练 frameskip 一致; 末帧 i = 要预测动作的那帧)
      action_history = 真值 raw 动作块 [i-4,i-3] 与 [i-2,i-1] (2 块 × 8 维 = [2,8])
      goal = 帧 i+10   (训练口径: 全长窗口 (8 obs, stride2) 的末帧相对该帧 = +2*(8-1)-2*(3-1) = +10)
      目标 = 帧 [i ... i+15] 的 raw 动作, 即模型 8 块 × (2 帧×4 维) 打平后的 16 个 4 维槽
  · 采样覆盖**全部 2,982 个回合** (回合均匀 + 回合内均匀), 默认 R=3 次独立重复 ⇒ 出均值±std
  · skill 三态 (on/zero) 同帧同权重消融 (记忆条件是否有增益的唯一硬口径)
  · 每槽都给常数基线 (教师均值), 便于"赢常数"判定按槽对照

用法:
  INTACT_POLICY=intact_goal_optical_insert_v6r5_s3072/weights_epoch_1.pt \
  ./gui-venv311/bin/python tools/intact_replay_check_v4.py --skill on --clips 240 --repeats 3 \
    --out reports/intact_v4_<fam>_on.json
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
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("STABLEWM_HOME", _CACHE)
os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

FRAMESKIP = 2          # 训练 zmax_v5.yaml: frameskip: 2
NUM_STEPS = 8          # 训练 num_frames: 8
HIST = 3               # 运行时契约 contracts.HISTORY_SIZE / 训练 history_size
BLOCK = 4              # 原始动作维 (dx,dy,dz,grip)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", default=os.path.join(_CACHE, "datasets", "optical_insert_v5_disturb.h5"))
    ap.add_argument("--stats", default=os.path.join(ROOT, "reports", "optical_insert_v5_action_stats.json"))
    ap.add_argument("--skill", default="on", choices=["on", "zero", "off"])
    ap.add_argument("--clips", type=int, default=240, help="每次重复抽多少段轨迹窗口")
    ap.add_argument("--repeats", type=int, default=3, help="独立重复次数 (出均值±std)")
    ap.add_argument("--seed", type=int, default=3072)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--task", default="pusht")
    ap.add_argument("--horizon", type=int, default=8)
    ap.add_argument("--goal-mode", default="train", choices=["train", "terminal"],
                    help="train = 训练口径 goal (窗口末帧 = 该帧 +%d) / terminal = 部署口径 (回合末帧, "
                         "= reports/intact_goal_frame_optical.npy 的同类目标)" % (FRAMESKIP * (NUM_STEPS - 1) - FRAMESKIP * (HIST - 1)))
    ap.add_argument("--lens", type=int, nargs="*", default=[0, 4, 8, 15],
                    help="要统计的动作槽 (帧偏移 k: 预测块槽 k ↔ 真值帧 i+k)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    import h5py
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime   # noqa: PLC0415

    stats = json.load(open(a.stats, encoding="utf-8"))
    a_mean = np.asarray(stats["mean"], np.float32)
    a_std = np.asarray(stats["std"], np.float32)

    f = h5py.File(a.h5, "r")
    px, act, ep_len, ep_off = f["pixels"], f["action"], f["ep_len"][:], f["ep_offset"][:]
    N = int(px.shape[0])
    n_ep = len(ep_len)
    has_sk = "skill_ctx" in f
    sk_dim = int(f["skill_ctx"].shape[1]) if has_sk else 0
    _SK = a.skill if (has_sk or a.skill == "off") else "off"

    # 训练口径常量 (显式打印, 不许含糊)
    goal_ahead = FRAMESKIP * (NUM_STEPS - 1) - FRAMESKIP * (HIST - 1)   # = +10 帧
    span_need = goal_ahead + FRAMESKIP * a.horizon                       # 目标窗口末端

    print(f"═══ v4 判闸 (训练同源自监督回放) · {os.path.basename(a.h5)} ═══")
    print(f"   数据: {N} 帧 / {n_ep} 回合 · 采样 {a.clips} 段 × {a.repeats} 次重复 (回合均匀)")
    print(f"   口径: frameskip={FRAMESKIP} num_steps={NUM_STEPS} obs窗口={HIST} 帧(stride {FRAMESKIP}) "
          f"· goal=+{goal_ahead} 帧(训练口径) · action_history=真值前 2 块 · skill={_SK}(dim={sk_dim})")

    rt = IntactRuntime(task=a.task, device=a.device)
    node = IntactNode(horizon=a.horizon, runtime=rt)
    if not node.runtime.trained and a.device != "cpu":
        # 🩹 2026-09-22: 官方加载路径 swm.wm.utils.load_pretrained() **硬要 CUDA**,
        #   没 GPU/CUDA_VISIBLE_DEVICES 空 时报 "No CUDA GPUs are available" → 判闸整条失败。
        #   判闸是**离线回放**, CPU 完全够 (实测 60 clips 约 2 分钟) ⇒ 自动回退 CPU 再试一次,
        #   并把原因说清楚(老倪红线: 失败要报根因, 不能静默降级成"判闸不可用")。
        _why = str(node.runtime.reason)
        if "CUDA" in _why or "GPU" in _why:
            print(f"⚠️ 官方加载路径要 CUDA ({_why[:80]}) → 自动回退 --device cpu 重试")
            rt = IntactRuntime(task=a.task, device="cpu")
            node = IntactNode(horizon=a.horizon, runtime=rt)
            a.device = "cpu"
    if not node.runtime.trained:
        print(f"❌ INTACT 未就绪: {node.runtime.reason}")
        return 3
    ad = int(node.action_dim)
    n_blocks = ad // BLOCK
    print(f"   模型: policy={os.environ.get('INTACT_POLICY','?')} · action_dim={ad} "
          f"({n_blocks} 块 × {BLOCK}) · runtime={os.environ.get('INTACT_RUNTIME','auto')}")

    def draw(rng, n):
        """回合均匀 + 回合内均匀抽 n 段 (不与边界冲突)。"""
        out = []
        tries, need = 0, n
        while len(out) < need and tries < need * 200:
            tries += 1
            e = int(rng.integers(0, n_ep))
            L = int(ep_len[e])
            if L < span_need + FRAMESKIP * (HIST - 1) + 4:
                continue
            lo = FRAMESKIP * (HIST - 1) + 2
            hi = L - span_need - 2
            if hi <= lo:
                continue
            i = int(rng.integers(lo, hi)) + int(ep_off[e])
            out.append((e, i))
        return out

    rows = []
    t0 = time.time()
    for rep in range(a.repeats):
        rng = np.random.default_rng(a.seed + rep)
        clips = draw(rng, a.clips)
        P = np.full((len(clips), a.horizon * n_blocks, BLOCK), np.nan, np.float32)
        G = np.full_like(P, np.nan)
        GMAG = np.full((len(clips),), np.nan, np.float32)     # 预测动作幅度 (|xyz|均值) 供 goal 口径对照
        for c, (e, i) in enumerate(clips):
            # 训练口径观测窗口: 帧 [i-4, i-2, i] (stride 2, 末帧=要预测的帧)
            win = [i - FRAMESKIP * (HIST - 1) + FRAMESKIP * j for j in range(HIST)]
            # 训练口径动作历史: 真值 raw 动作块 (每块 = 2 帧 × 4 维)
            hist = np.zeros((HIST, ad), np.float32)
            for j in range(HIST):
                b = i - FRAMESKIP * (HIST - 1) + FRAMESKIP * (j - 1)
                if b < 0:
                    continue
                seg = np.asarray(act[b:b + FRAMESKIP], np.float32).reshape(-1)
                hist[j, :seg.size] = seg[:ad]
            _gi = i + goal_ahead if a.goal_mode == "train" else int(ep_off[e] + ep_len[e] - 2)
            g = np.transpose(np.asarray(px[_gi], np.float32), (2, 0, 1))
            node.set_goal(g)
            node.obs_buf = [np.transpose(np.asarray(px[w], np.float32), (2, 0, 1)) for w in win[:-1]]
            node.action_hist = hist.copy()
            _sk_v = None
            if _SK == "on":
                _sk_v = np.asarray(f["skill_ctx"][win[-1]], np.float32)
            elif _SK == "zero":
                _sk_v = np.zeros(sk_dim, np.float32)
            out = node.step(np.transpose(np.asarray(px[win[-1]], np.float32), (2, 0, 1)),
                            obs_source="dataset_true_frame", skill_ctx=_sk_v)
            chunk = np.asarray(out.chunk, np.float32).reshape(-1)      # 打平成 4 维槽序列
            nslot = min(len(chunk) // BLOCK, a.horizon * n_blocks)
            for k in range(nslot):
                P[c, k] = np.clip(chunk[k * BLOCK:(k + 1) * BLOCK] * a_std + a_mean, -1, 1)
                G[c, k] = np.asarray(act[i + k], np.float32)
            if (c + 1) % 40 == 0:
                print(f"   [rep{rep} {c+1}/{len(clips)}] {time.time()-t0:.0f}s", flush=True)
            GMAG[c] = float(np.nanmean(np.abs(P[c, :, :3])))
        rows.append((P, G, GMAG))
    node.close()

    from scipy.stats import pearsonr
    kmax = min(rows[0][0].shape[1], min(len(rows[0][0][0]), 64))
    per_slot: dict[str, dict] = {}
    for k in range(kmax):
        maes, consts, srs = [], [], []
        prs: list[list[float]] = [[] for _ in range(BLOCK)]      # 🎯 逐轴 pearson (dx,dy,dz,grip)
        for P, G, _gm in rows:
            p, gt = P[:, k], G[:, k]
            ok = np.isfinite(p).all(1) & np.isfinite(gt).all(1)
            p, gt = p[ok], gt[ok]
            if len(p) < 20:
                continue
            maes.append(float(np.abs(p - gt).mean()))
            consts.append(float(np.abs(np.repeat(gt.mean(0)[None], len(gt), 0) - gt).mean()))
            # 🎯 KPI-1 要的是**逐轴** corr (L2 收口闸按逐轴 |corr|<0.5 否决), 不能只看 dx
            for _j in range(min(BLOCK, p.shape[1], gt.shape[1])):
                if p[:, _j].std() > 1e-9 and gt[:, _j].std() > 1e-9:
                    prs[_j].append(float(pearsonr(p[:, _j], gt[:, _j])[0]))
            srs.append(float(p[:, :3].std() / max(float(gt[:, :3].std()), 1e-9)))
        if not maes:
            continue
        _pm = [float(np.mean(v)) if v else float("nan") for v in prs]
        per_slot[str(k)] = {"mae": float(np.mean(maes)), "mae_std": float(np.std(maes, ddof=1)) if len(maes) > 1 else 0.0,
                            "const": float(np.mean(consts)), "pearson_dx": _pm[0],
                            "pearson_dy": _pm[1], "pearson_dz": _pm[2], "pearson_grip": _pm[3],
                            "pearson_xyz_min": float(np.nanmin(_pm[:3])),
                            "std_ratio_xyz": float(np.mean(srs)), "reps": len(maes)}
    if not per_slot:
        # 🩹 2026-09-22 (自检时抓到): clips 太少时每槽有效配对 <20 → 逐槽循环全 `continue`,
        #   后面均值变成 nan 并打印"❌ 输常数" —— 那是**假判决**(看着像模型失败, 其实是样本不够)。
        #   哨兵若用小 clips 跑会误报。这里显式拒绝判决并给可执行的修法。
        print(f"\n⚠️ 样本不足 → **本次不作判决**: 采了 {a.clips} 段, 每槽需要 ≥20 个有效配对才出结论。"
              f"\n   这不是模型失败(别据此报 ❌)。请把 --clips 提到 ≥30 再跑。")
        return 4
    ks = [int(k) for k in per_slot]
    print(f"\n═══ 逐槽 (n≈{a.clips}/重复 × {a.repeats} 重复) ═══")
    print(f"{'帧偏移k':>7}{'MAE':>10}{'±std':>8}{'常数基线':>10}{'赢常数':>7}"
          f"{'p_dx':>8}{'p_dy':>8}{'p_dz':>8}{'p_grip':>8}{'min|xyz|':>9}{'std比xyz':>9}")
    for k in ks:
        d = per_slot[str(k)]
        print(f"{k:>7}{d['mae']:>10.4f}{d['mae_std']:>8.4f}{d['const']:>10.4f}"
              f"{str(d['mae'] < d['const']):>7}{d['pearson_dx']:>8.3f}{d['pearson_dy']:>8.3f}"
              f"{d['pearson_dz']:>8.3f}{d['pearson_grip']:>8.3f}{d['pearson_xyz_min']:>9.3f}{d['std_ratio_xyz']:>9.3f}")

    sel = [k for k in a.lens if str(k) in per_slot] or ks
    mae_sel = float(np.mean([per_slot[str(k)]["mae"] for k in sel]))
    const_sel = float(np.mean([per_slot[str(k)]["const"] for k in sel]))
    out = a.out or os.path.join(ROOT, "reports", f"intact_v4_{_SK}_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"meta": {"h5": a.h5, "policy": os.environ.get("INTACT_POLICY", ""), "skill_mode": _SK,
                        "skill_dim": sk_dim, "clips": a.clips, "repeats": a.repeats, "seed": a.seed,
                        "horizon": a.horizon, "frameskip": FRAMESKIP, "num_steps": NUM_STEPS,
                        "device": a.device,
                        "obs_window": HIST, "goal_ahead_frames": goal_ahead, "goal_mode": a.goal_mode,
                        "action_history": "真值 raw 前 2 块 (训练口径)",
                        "obs": "数据集真帧 · 连续窗口 (stride 2) · teacher-forced",
                        "lens": sel, "ts": time.strftime("%F %T")},
               "per_slot": per_slot,
               "pred_abs_xyz_mean": float(np.mean([float(np.nanmean(g)) for _p, _g, g in rows])),
               "lens_mean_mae": mae_sel, "lens_mean_const": const_sel,
               "win_const": bool(mae_sel < const_sel)},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n   选用槽 {sel} 均值: 模型 MAE {mae_sel:.4f} vs 常数 {const_sel:.4f} → "
          f"{'✅ 赢常数' if mae_sel < const_sel else '❌ 输常数'}")
    print(f"   → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
