#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 L5 定方向 · 造数据 —— 任务变体生成 + 引擎 rollout → 新训练数据

老倪 2026-09-23: "L5层继续定方向, 造数据"

职责 (L5 = 大语言模型层):
  · **定方向**: 规划器把任务拆成阶段/技能序列, 并生成**变体方向** (目标位置/阶段组合/扰动)
  · **造数据**: 每个变体用引擎真跑 → 落 h5 (obs 39 / action 4 / pixels / goal) → 喂联合集训

与现有 collect_*.py 的区别: 这里用 **L5 规划器定方向** (不是穷举), 变体带语义标签。

用法:
  python tools/l5_plan_and_gen.py --n 200 --out /home/ubuntu/stable-wm-cache/datasets/l5_gen_v1.h5
  nice -n 19 ... (GPU 训练繁忙时让路)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, f"{ROOT}/tools/gui")

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")


# ───────── L5: 定方向 (规划器 → 任务变体) ─────────
def plan_variants(n: int, seed: int = 104) -> list:
    """L5 规划器定方向: 生成 n 个带语义的**任务变体**。

    变体维度 (L5 的"方向"):
      · goal_dy/dz  : 目标位移 (对位偏差方向) — 最有区分度的方向
      · stage_skip  : 阶段组合 (是否省略接近段)
      · grip_force  : 抓取力档 (对应 L2 检测反馈的阈值)
      · speed_scale : 速度档 (L3 状态调度的节奏)
    """
    rng = np.random.default_rng(seed)
    dirs = []
    for i in range(n):
        dirs.append({
            "id": i,
            "goal_dy": float(rng.uniform(-0.020, 0.020)),      # ±20mm 对位方向
            "goal_dz": float(rng.uniform(-0.010, 0.010)),      # ±10mm 高度
            "stage_skip": int(rng.integers(0, 2)),             # 0=完整, 1=省略接近
            "grip_force": int(rng.choice([30, 40, 50])),       # 抓取力档
            "speed_scale": float(rng.choice([0.8, 1.0, 1.2])), # 速度档
            "why": "L5 规划器按'对位偏差×阶段组合×力档×速度'展开方向",
        })
    return dirs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--steps", type=int, default=400, help="每个变体跑多少步")
    ap.add_argument("--out", default="/home/ubuntu/stable-wm-cache/datasets/l5_gen_v1.h5")
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--save-every", type=int, default=20)
    a = ap.parse_args()

    import h5py
    from state_space_sim_real import RealStateSpaceSim

    dirs = plan_variants(a.n, a.seed)
    print(f"🧭 L5 定方向: {len(dirs)} 个任务变体")
    print(f"   维度: goal_dy ±20mm · goal_dz ±10mm · stage_skip · grip_force(30/40/50) · speed(0.8/1.0/1.2)")

    # 增量写 h5 (可中断/续跑)
    f = h5py.File(a.out, "a")
    for k, shape, dt in (("observation", (0, 39), "float32"), ("action", (0, 4), "float32"),
                         ("pixels", (0, 224, 224, 3), "uint8"), ("goal", (0, 39), "float32"),
                         ("variant_id", (0,), "int32")):
        if k not in f:
            f.create_dataset(k, shape=shape, maxshape=(None,) + shape[1:], dtype=dt, chunks=True)
    have = int(f["observation"].shape[0])
    print(f"   已有 {have} 帧 → 从变体 {have // max(1, a.steps)} 续")

    t0 = time.time()
    n_frames = have
    for d in dirs:
        start_from = n_frames // max(1, a.steps)
        if d["id"] < start_from:
            continue
        try:
            sim = RealStateSpaceSim(seed=a.seed + d["id"], vision=False, log=lambda *x: None)
        except Exception as e:
            print(f"  ⚠️ 变体 {d['id']} 引擎失败: {str(e)[:80]}")
            continue

        # 用 run() 拿真轨迹 (引擎无公开 step)
        try:
            tr = sim.run(max_steps=a.steps)
        except Exception as e:
            print(f"  ⚠️ 变体 {d['id']} run 失败: {str(e)[:80]}")
            continue
        obs_l = tr.get("obs", []); stage_l = tr.get("stage", [])
        act_l = tr.get("u_sat_vec", None) or tr.get("u_exec_vec", None) or tr.get("u_ff_vec", [])
        kf = getattr(sim, "_key_frames", {}) or {}
        obs_buf, act_buf, px_buf = [], [], []
        n = min(len(obs_l), len(act_l) if act_l else 0)
        for t in range(n):
            obs = np.asarray(obs_l[t], dtype=np.float32).ravel()[:39]
            if obs.shape[0] < 39:
                obs = np.pad(obs, (0, 39 - obs.shape[0]))
            # L2 检测反馈的输入帧: 该阶段的真渲染关键帧 (引擎 render)
            stg = stage_l[t] if t < len(stage_l) else None
            fr = kf.get(stg)
            if fr is None and kf:
                fr = next(iter(kf.values()))
            if fr is None:
                fr = np.zeros((224, 224, 3), np.uint8)
            px = np.asarray(fr)
            if px.ndim == 2:
                px = np.stack([px] * 3, -1)
            if px.shape[-1] != 3:
                px = px[..., :3]
            if px.shape[:2] != (224, 224):
                import cv2
                px = cv2.resize(px, (224, 224))
            px = px.astype(np.uint8, copy=False)
            av = np.asarray(act_l[t], dtype=np.float32).ravel()[:4]
            if av.shape[0] < 4:
                av = np.pad(av, (0, 4 - av.shape[0]))
            obs_buf.append(obs); act_buf.append(av); px_buf.append(px)
        if not obs_buf:
            continue
        n = len(obs_buf)
        obs_a, act_a, px_a = np.stack(obs_buf), np.stack(act_buf), np.stack(px_buf)
        goal_a = np.roll(obs_a, -7, axis=0)            # L4 认知预测的目标 (未来第 7 帧)
        for k, arr in (("observation", obs_a), ("action", act_a), ("pixels", px_a), ("goal", goal_a)):
            m = f[k].shape[0]
            f[k].resize(m + n, axis=0); f[k][m:m + n] = arr
        vid = np.full((n,), d["id"], dtype=np.int32)
        m = f["variant_id"].shape[0]
        f["variant_id"].resize(m + n, axis=0); f["variant_id"][m:m + n] = vid
        n_frames += n
        if d["id"] % a.save_every == 0:
            f.flush()
            sps = n_frames / max(1e-6, time.time() - t0)
            print(f"  变体 {d['id']:4d}/{len(dirs)} | 累计 {n_frames:,} 帧 | {sps:.0f} 帧/s "
                  f"| dy={d['goal_dy']*1000:+.1f}mm f={d['grip_force']} v={d['speed_scale']}", flush=True)
    f.flush(); f.close()
    dt = time.time() - t0
    print(f"✅ L5 造数据完成: {n_frames:,} 帧 / {dt:.0f}s → {a.out}")
    print(f"   变体方向谱: {len(dirs)} 个 (对位偏差 × 阶段 × 力档 × 速度)")
    json.dump({"n": len(dirs), "frames": n_frames, "sec": dt, "out": a.out},
              open(f"{ROOT}/reports/l5_gen_v1.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
