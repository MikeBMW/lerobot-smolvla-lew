# -*- coding: utf-8 -*-
"""🔁 skill_ctx 口径回归: 用**共享构造器**重算已落盘 part 的 skill_ctx, 与记录值逐位对比。

为什么必须有: 训练数据 (采集器) 和闭环推理 (桥) 若用两套代码构造 skill_ctx, 模型学到的
就是另一种分布 → 口径不一致 = 白训。本脚本是这条红线的证据 (老倪: "数据一致性最重要")。

判据: stage one-hot 逐位相同 / L2 w 逐位 (容差 1e-6) / d_perp 与 arc_frac 容差 1e-6 / grip 相同。
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True)
    ap.add_argument("--seed", type=int, default=104, help="L2 势场构造 seed (与采集器一致 = 104)")
    ap.add_argument("--n", type=int, default=400, help="抽查帧数")
    a = ap.parse_args()

    from lerobot.memory.potential_field import MemoryLayerBridge
    from lerobot.policies.intact.skill_ctx import SKILL_CTX_DIM, STAGE_ORDER, build_skill_ctx

    d = np.load(a.part, allow_pickle=True)
    sk = np.asarray(d["skill_ctx"], np.float32)
    obs = np.asarray(d["observation"], np.float32)
    act = np.asarray(d["action"], np.float32)
    bridge = MemoryLayerBridge.from_real_data(root=ROOT, seed=int(a.seed), use_engine_geom=True)
    print(f"part {os.path.basename(a.part)}: skill_ctx {sk.shape} · 定义 {SKILL_CTX_DIM} 维")
    assert sk.shape[1] == SKILL_CTX_DIM, "维度不符"

    idx = np.linspace(0, len(sk) - 1, min(int(a.n), len(sk))).astype(int)
    worst = {"stage": 0, "w": 0.0, "dperp": 0.0, "arc": 0.0, "grip": 0.0}
    for i in idx:
        stage = STAGE_ORDER[int(np.argmax(sk[i, :13]))]
        grip = float(sk[i, -1])
        ref = build_skill_ctx(bridge.process, obs[i, :3], stage, grip)
        worst["stage"] = max(worst["stage"], int(np.abs(ref[:13] - sk[i, :13]).max() > 0))
        worst["w"] = max(worst["w"], float(np.abs(ref[13:21] - sk[i, 13:21]).max()))
        worst["dperp"] = max(worst["dperp"], float(abs(ref[21] - sk[i, 21])))
        worst["arc"] = max(worst["arc"], float(abs(ref[22] - sk[i, 22])))
        worst["grip"] = max(worst["grip"], float(abs(ref[23] - sk[i, 23])))
    print(f"抽查 {len(idx)} 帧 → 最大偏差: stage⊕={worst['stage']} · w={worst['w']:.2e} · "
          f"d_perp={worst['dperp']:.2e} · arc={worst['arc']:.2e} · grip={worst['grip']:.2e}")
    tol = {"stage": 0, "w": 1e-6, "dperp": 1e-6, "arc": 1e-6, "grip": 1e-6}
    ok = all(worst[k] <= tol[k] for k in tol)
    # 信息量检查: 不能是常量 (那等于没给模型任何东西)
    nz = {k: (float(np.std(sk[:, j])) if k == "dperp" else float(np.mean(sk[:, j] > 0)))
          for k, j in (("dperp", 21), ("arc", 22), ("w", 13))}
    print(f"信息量: d_perp std={nz['dperp']:.4f} · arc_frac 非零占比={nz['arc']:.2f} · "
          f"w[0] 非零占比={nz['w']:.2f}")
    print(f"口径一致性: {'✅ 逐位一致 (采集器 = 共享构造器)' if ok else '❌ 有偏差 → 训练/推理口径不一致'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
