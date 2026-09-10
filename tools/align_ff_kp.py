#!/usr/bin/env python3
"""align_ff_kp.py — ⚡前馈加速器 vs 🧠左脑MLP(547K): Kp 等效值反推/校验 (2026-09-04)

对齐对象:
  A) 真模型: 状态空间场景 (ss_insert_lerobot 39D, [0:3]=hand [36:39]=hole) 训练的左脑 MLP
     产物: outputs/train/state_space_*/checkpoints/003000/pretrained_model/model.pt 的 "left"
     推理链路 (与 ss_verify_trained.py 一致, 该脚本已验证它能替换解析加速器跑通插拔仿真):
       norm 从 parquet 重算 (model.pt 未存): sm/ss = obs mean/std, am/astd = act mean/std
       u_true = left((obs − sm) / ss) · astd + am          # 4D 物理域建议动作
  B) 解析替身: parallel.py:21 FeedforwardAccelerator (Kp=1.2 写死, 0 参数)
       u_ff = clip(Kp·(hole−hand), ±0.5)  [+ 水平距<0.03 时叠加 0.03 最小趋近推力]

   ⚠️ 不适用的靶子: outputs/rl_peg/full_pipeline.pt — metaworld 抓取+转移+插入全流程场景,
      39D 布局 [36:39]≠hole site (实测 x 偏 0.066), 与解析版"末端直朝孔位"语义不同,
      逐帧 Kp 拟合无意义 (实测拟合 Kp≈14万 爆表)。

方法: 同一批真实 obs 帧 (parquet) 上, 以真模型物理域输出为基准,
      过原点最小二乘反推 Kp_hat = argmin Σ‖u_true − Kp·e‖², e = hole−hand,
      按水平距离分层 (远/中/近) 校验写死值 1.2 是否成立, 输出建议。

用法:
  ~/lerobot-venv/bin/python tools/align_ff_kp.py                        # 自动选最新 state_space 产物
  ~/lerobot-venv/bin/python tools/align_ff_kp.py --ckpt <model.pt>      # 手动指定
  ~/lerobot-venv/bin/python tools/align_ff_kp.py --list                 # 列出候选产物
"""
import os
import sys
import glob
import argparse

import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

KP_WRITTEN = 1.2          # parallel.py:35 写死的比例增益
CLIP = 0.5                # parallel.py:36/40 限幅
D_NEAR = 0.03             # parallel.py:38 近距阈值 (最小趋近推力 + 夹爪闭合判据)
THRUST = 0.03             # parallel.py:40 最小趋近推力
DATA_DEF = os.path.join(ROOT, "data", "ss_insert_lerobot", "data", "chunk-000", "file-000.parquet")
CKPT_GLOB = os.path.join(ROOT, "outputs", "train", "state_space_*", "checkpoints", "*",
                         "pretrained_model", "model.pt")
AMP_INSANE = 2.0          # 3D 动作幅值中位数超过此值 = norm/数据不匹配 (量纲爆表)


def find_candidates():
    cands = sorted(glob.glob(CKPT_GLOB), key=os.path.getmtime, reverse=True)
    return cands


def load_model(ckpt_path, parquet_path):
    """载入左脑 MLP (model.pt 'left') + 从 parquet 重算归一化 (同 ss_verify_trained.py)"""
    from lerobot.policies.left_right.modeling_left_right import LeftBrainMLP
    sd = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    obs_dim = int(sd.get("obs_dim", 39))
    act_dim = int(sd.get("act_dim", 4))
    net = LeftBrainMLP(obs_dim=obs_dim, act_dim=act_dim)
    net.load_state_dict(sd["left"])
    net.eval()
    import pandas as pd
    df = pd.read_parquet(parquet_path)
    S = np.stack(df["observation.state"].values).astype(np.float32)
    A = np.stack(df["action"].values).astype(np.float32)
    norm = {"sm": S.mean(0), "ss": S.std(0) + 1e-8,
            "am": A.mean(0), "astd": A.std(0) + 1e-8}
    return net, obs_dim, act_dim, norm


def parse_analytic(obs, kp):
    """parallel.py FeedforwardAccelerator.forward 的忠实复刻 (可换 Kp), 返回 4D u_ff
    parallel.py 细节: dist_h = 水平xy距离; dir_vec[:2] = 水平单位向量; 推力只加 u[:2];
    夹爪开关判据也是水平距离 <0.03; 先 clip 再加推力再 clip。"""
    pos = obs[:, 0:3]
    target = obs[:, 36:39]
    e = target - pos
    u = np.clip(kp * e, -CLIP, CLIP)
    d_xy = np.linalg.norm(e[:, :2], axis=1)          # dist_h: 水平距离
    near = (d_xy < D_NEAR) & (d_xy > 1e-6)
    if near.any():
        dir_v_xy = e[near, :2] / d_xy[near][:, None]   # 水平单位向量 (= dir_vec[:2])
        u[near, :2] = np.clip(u[near, :2] + THRUST * dir_v_xy, -CLIP, CLIP)
    gripper = np.where(d_xy < D_NEAR, 1.0, 0.0)
    return np.concatenate([u, gripper[:, None]], axis=1)


def ols_kp(e3, u3):
    """过原点最小二乘: Kp = Σ⟨e,u⟩ / Σ‖e‖²  (3D 合并, 单一增益假设)"""
    num = float(np.sum(e3 * u3))
    den = float(np.sum(e3 * e3))
    return (num / den) if den > 0 else float("nan")


def layer_report(name, e3, u3):
    """单层: 样本数 / 拟合 Kp / 相关 / MAE(写死 vs 拟合)"""
    n = len(e3)
    if n == 0:
        print(f"  {name:<8} n=0")
        return {}
    kp = ols_kp(e3, u3)
    e_xy = e3[:, :2].ravel(); u_xy = u3[:, :2].ravel()
    corr_xy = np.corrcoef(e_xy, u_xy)[0, 1]
    corr_z = np.corrcoef(e3[:, 2], u3[:, 2])[0, 1]
    kp_z = ols_kp(e3[:, 2:3], u3[:, 2:3])

    def mae(k):
        pred = np.clip(k * e3, -CLIP, CLIP)
        return float(np.mean(np.abs(pred - u3)))
    mae_w, mae_h = mae(KP_WRITTEN), mae(kp)
    u_amp = float(np.mean(np.abs(u3)))
    z_share = float(np.mean(np.abs(u3[:, 2])) / (u_amp + 1e-12))
    print(f"  {name:<8} n={n:<5} Kp_hat={kp:6.3f}  corr(xy)={corr_xy:6.3f} corr(z)={corr_z:6.3f} "
          f"|u|mean={u_amp:.4f}  MAE[Kp=1.2]={mae_w:.4f}  MAE[Kp_hat]={mae_h:.4f}  "
          f"(z 独立拟合 Kp={kp_z:.3f}, z 能量占比 {z_share:.0%})")
    return {"n": n, "kp": kp, "mae_w": mae_w, "mae_h": mae_h, "corr_xy": corr_xy, "corr_z": corr_z}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=None, help="model.pt (默认自动选最新 state_space 产物)")
    ap.add_argument("--data", default=DATA_DEF)
    ap.add_argument("--n", type=int, default=0, help="采样上限, 0=全部")
    ap.add_argument("--list", action="store_true", help="列出候选产物")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.list:
        for c in find_candidates():
            print(f"  {os.path.getmtime(c):.0f}  {c}")
        return

    ckpt = args.ckpt
    if not ckpt:
        cands = find_candidates()
        if not cands:
            print(f"❌ 未找到 state_space 候选产物: {CKPT_GLOB}")
            print("   请用 --ckpt 指定 (如 outputs/train/state_space_*/checkpoints/003000/pretrained_model/model.pt)")
            return 1
        ckpt = cands[0]
        print(f"📂 自动选择最新 state_space 产物: {ckpt}")

    net, obs_dim, act_dim, norm = load_model(ckpt, args.data)
    print(f"🧠 真模型: 左脑 MLP (obs {obs_dim}D → act {act_dim}D, 547K) ← {ckpt}")
    print(f"   归一化: 从 {os.path.basename(args.data)} 重算 (与 ss_verify_trained.py 同款)")
    print(f"           sm[:3]={norm['sm'][:3]}  ss[:3]={norm['ss'][:3]}")
    print(f"           am={norm['am']}  astd={norm['astd']}")

    import pandas as pd
    df = pd.read_parquet(args.data)
    S = np.stack(df["observation.state"].values).astype(np.float32)
    if args.n and len(S) > args.n:
        rng = np.random.default_rng(args.seed)
        S = S[rng.choice(len(S), args.n, replace=False)]
    print(f"📦 真实 obs 帧: {len(S)} 条 ← {args.data}")

    # ── 真模型推理 (与 ss_verify_trained 一致的物理域还原) ──
    with torch.no_grad():
        xin = torch.from_numpy((S - norm["sm"]) / norm["ss"])
        u_true = net(xin).numpy() * norm["astd"] + norm["am"]   # (N,4) 物理域
    amp_med = float(np.median(np.abs(u_true[:, :3])))
    if amp_med > AMP_INSANE:
        print(f"\n❌ 量纲自检失败: 3D 动作幅值中位数 {amp_med:.1f} > {AMP_INSANE}")
        print("   norm 与数据不匹配或靶子模型场景不对 (full_pipeline.pt 会这样)。中止。")
        return 2
    print(f"   ✅ 量纲自检通过: 3D 动作幅值中位数 {amp_med:.4f} (物理域正常)")

    e3 = S[:, 36:39] - S[:, 0:3]                      # hole − hand (解析版 e)
    d_xy = np.linalg.norm(e3[:, :2], axis=1)

    print(f"\n═══ 1) 全局拟合 (3D 合并, 过原点) ═══")
    kp_all = ols_kp(e3, u_true[:, :3])
    print(f"  Kp_hat(全样本) = {kp_all:.4f}   写死 Kp = {KP_WRITTEN}")
    print(f"  数据覆盖: d_xy min={d_xy.min():.4f} med={np.median(d_xy):.4f} p90={np.percentile(d_xy,90):.4f} max={d_xy.max():.4f}")

    print(f"\n═══ 2) 分层校验 (远/中/近, 近=解析版 0.03 推力段) ═══")
    far = d_xy >= 0.08
    mid = (d_xy >= D_NEAR) & (d_xy < 0.08)
    near = d_xy < D_NEAR
    r_far = layer_report("远≥8cm", e3[far], u_true[far, :3])
    r_mid = layer_report("中3-8cm", e3[mid], u_true[mid, :3])
    r_near = layer_report("近<3cm", e3[near], u_true[near, :3])

    print(f"\n═══ 3) 完整解析律复刻对比 (含 clip ±0.5 + 0.03 近距推力 + 夹爪开关) ═══")
    for kp_name, kp in [("Kp=1.2(写死)", KP_WRITTEN), (f"Kp={kp_all:.3f}(拟合)", kp_all)]:
        u_par = parse_analytic(S, kp)
        mae = float(np.mean(np.abs(u_par[:, :3] - u_true[:, :3])))
        print(f"  {kp_name:<18}: 解析律 vs 真模型 3D MAE = {mae:.4f}")

    print(f"\n═══ 4) 夹爪维 (act[3]) — 解析开关 0/1 vs 真模型连续输出 ═══")
    g = u_true[:, 3]
    print(f"  真模型 gripper: mean={g.mean():.3f} std={g.std():.3f} min={g.min():.3f} max={g.max():.3f}")
    for name, m in [("远≥8cm", far), ("中3-8cm", mid), ("近<3cm", near)]:
        gm = g[m]
        if len(gm):
            print(f"    {name:<8}: mean={gm.mean():.3f}  >0.5占比={100*(gm>0.5).mean():5.1f}%  (解析规则: 近距=1.0)")
    corr_g = np.corrcoef(d_xy, g)[0, 1]
    print(f"  corr(d_xy, gripper) = {corr_g:+.3f}   (负=越近越闭合, 解析规则假设成立)")

    print(f"\n═══ 5) 结论 ═══")
    kps = [v["kp"] for v in (r_far, r_mid, r_near) if v]
    if kps:
        kmin, kmax = min(kps), max(kps)
        inside = kmin <= KP_WRITTEN <= kmax
        verdict = "✅ 写死 Kp=1.2 落在分层拟合区间内 → 等效值校验通过, 可维持" if inside else \
                  f"⚠️ 写死 1.2 超出分层区间 [{kmin:.2f}, {kmax:.2f}] → 建议改 {np.mean(kps):.2f}"
        print(f"  分层 Kp_hat 范围: [{kmin:.2f}, {kmax:.2f}] (各层均值 {np.mean(kps):.2f})")
        print(f"  {verdict}")
        print(f"  注: Kp 拟合是线性近似, corr/MAE 反映解析替身与 547K 模型的真实差距;"
              f"\n      z 维独立拟合/夹爪维统计用于判断哪些段需要额外机制 (非比例项)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
