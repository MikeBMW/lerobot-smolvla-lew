# -*- coding: utf-8 -*-
"""🧪 配对数据采集 (Step 1 标定 + Step 2 解码性探针 共用) — 六层引擎真链路

一帧一条记录, 四路取自**同一帧** (口径必须一致, 否则标定就是拼凑):
  · frame    : 引擎真渲染 (corner2) → 224² CHW      (喂 INTACT)
  · z_t/chunk: INTACT 纸权重真前向 (z_t 192维 / 官方 10维动作 chunk)
  · u_ff     : 本引擎前馈加速器**真输出** 4D (tr['u_ff_vec'], 蒸馏 MLP 主路径)
  · mani6    : 本引擎流形真值 6 维 (tr mani_progress/risk/V + eta/rem/dperp)
  · obs39    : 引擎 39 维观测 (训练/推理同源)

产出: reports/intact_pair_<ts>.npz (含全部数组 + stage) —— 供
  · tools/intact_fit_maps.py --mode action   (10→4 标定, 写 models/intact_action_map.json)
  · tools/intact_fit_maps.py --mode decode   (192→流形6维 可解码性, R²/CCA)

诚实边界: 帧是 480²→224² 下采样 (相机原生 480²); INTACT 原生训练分辨率就是 224², 因此这是
**同分辨率**输入, 不是上采样凑数。INTACT 用 CPU 推理 (避让同机训练显存)。

用法: MUJOCO_GL=egl gui-venv311/bin/python tools/intact_pair_collect.py --seed 0 --stride 8 --max-steps 500
"""
import argparse
import json
import os
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

IMG = 224


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", default="insert", choices=["insert", "full"])
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--stride", type=int, default=8, help="每 N 帧取 1 帧做 INTACT 推理 (=chunk 语义)")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--task", default="pusht")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    import cv2                                            # noqa: PLC0415
    from state_space_sim_real import RealStateSpaceSim    # noqa: PLC0415
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime   # noqa: PLC0415

    frames = []           # 原生渲染帧 (HWC, 480²) — 只留采样到的, 省内存

    def _sink(sim, act, o):
        frames.append(np.asarray(sim.env.render()))

    print(f"═══ 配对采集: 引擎 mode={a.mode} seed={a.seed} max_steps={a.max_steps} ═══", flush=True)
    t0 = time.time()
    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode=a.mode, log=lambda *x: None)
    sim._frame_sink = _sink
    tr = sim.run(max_steps=a.max_steps)
    done = bool(tr["done"][-1]) if tr.get("done") else False
    n = len(frames)
    print(f"   引擎: done={done} 步数={len(tr['t'])} 渲染帧={n} · {time.time()-t0:.0f}s", flush=True)
    if n == 0:
        print("❌ 无渲染帧 → 中止 (不拿合成观测凑数)")
        return 2

    # 采样下标 (stride)
    idxs = list(range(0, n, a.stride))
    mani = None
    keys6 = ["mani_progress", "mani_risk", "mani_V", "mani_eta", "mani_rem", "mani_dperp"]
    if all(k in tr and len(tr[k]) == n for k in keys6):
        mani = np.stack([np.asarray(tr[k], dtype=np.float32) for k in keys6], axis=1)   # [n,6]
    else:
        print("⚠️ 引擎缺 mani_* 真值列 → 流形真值置 NaN (诚实记录, 不编数)")
    u_ff = np.asarray(tr.get("u_ff_vec") or [], dtype=np.float32)
    if u_ff.shape[0] != n:
        print(f"⚠️ u_ff_vec 长度 {u_ff.shape[0]} != 帧数 {n} → 前馈真值置 NaN")
        u_ff = np.full((n, 4), np.nan, dtype=np.float32)
    obs = np.asarray(tr.get("obs") or [], dtype=np.float32)

    # INTACT 真前向 (CPU), 每 stride 帧一次
    rt = IntactRuntime(task=a.task, device=a.device)
    node = IntactNode(horizon=8, runtime=rt)
    if not node.runtime.trained:
        print(f"❌ INTACT 未就绪: {node.runtime.reason}")
        return 3
    print(f"   INTACT 就绪: action_dim={node.action_dim} hist={node.hist_size} device={a.device}", flush=True)

    # goal 帧 = 本轮最后一帧 (任务完成态)
    _last = frames[-1]
    node.set_goal(cv2.resize(_last, (IMG, IMG), interpolation=cv2.INTER_AREA)
                  .transpose(2, 0, 1).astype(np.float32))

    rows = {"idx": [], "z_t": [], "z_goal": [], "delta": [], "chunk": [], "u_ff": [],
            "mani6": [], "obs39": [], "stage": []}
    for k, i in enumerate(idxs):
        fr = cv2.resize(frames[i], (IMG, IMG), interpolation=cv2.INTER_AREA) \
            .transpose(2, 0, 1).astype(np.float32)
        out = node.step(fr, obs_source="engine_render")
        lat = out.latent or {}
        rows["idx"].append(i)
        rows["z_t"].append(lat.get("z_t")[0] if lat.get("z_t") is not None else np.full(192, np.nan, np.float32))
        rows["z_goal"].append(lat.get("z_goal")[0] if lat.get("z_goal") is not None else np.full(192, np.nan, np.float32))
        rows["delta"].append(lat.get("delta")[0] if lat.get("delta") is not None else np.full(192, np.nan, np.float32))
        rows["chunk"].append(np.asarray(out.chunk, dtype=np.float32))
        rows["u_ff"].append(u_ff[i] if u_ff.shape[0] > i else np.full(4, np.nan, np.float32))
        rows["mani6"].append(mani[i] if mani is not None else np.full(6, np.nan, np.float32))
        rows["obs39"].append(obs[i] if obs.shape[0] > i else np.full(39, np.nan, np.float32))
        rows["stage"].append(str((tr.get("stage") or ["?"])[i]))
        if (k + 1) % 10 == 0:
            print(f"   [{k+1}/{len(idxs)}] i={i} {rows['stage'][-1][:14]} "
                  f"|z|={np.linalg.norm(rows['z_t'][-1]):.3f} |Δ|={np.linalg.norm(rows['delta'][-1]):.3f} "
                  f"u_ff={np.round(rows['u_ff'][-1], 4).tolist()}", flush=True)
    node.close()

    tag = time.strftime("%Y%m%d_%H%M%S")
    out = a.out or os.path.join(ROOT, "reports", f"intact_pair_seed{a.seed}_{tag}.npz")
    np.savez_compressed(
        out,
        idx=np.asarray(rows["idx"], dtype=np.int64),
        z_t=np.stack(rows["z_t"]), z_goal=np.stack(rows["z_goal"]), delta=np.stack(rows["delta"]),
        chunk=np.stack(rows["chunk"]), u_ff=np.stack(rows["u_ff"]),
        mani6=np.stack(rows["mani6"]), obs39=np.stack(rows["obs39"]),
        stage=np.asarray(rows["stage"], dtype=object),
        meta=np.array([{"seed": a.seed, "mode": a.mode, "steps": len(tr["t"]), "frames": n,
                        "stride": a.stride, "done": done, "device": a.device, "task": a.task,
                        "obs_source": "engine_render 480²→224²(CHW)",
                        "policy": os.environ.get("INTACT_POLICY",
                                                 f"recovery_delta_full_{a.task}_s3072"),
                        "runtime": os.environ.get("INTACT_RUNTIME", "paper"),
                        "mani_keys": keys6, "ts": time.strftime("%F %T")}], dtype=object))
    print(f"\n   → {out}")
    print(f"   样本 {len(idxs)} 条 · 引擎 done={done} · 阶段覆盖 "
          f"{len(set(rows['stage']))} 个阶段 · 用时 {time.time()-t0:.0f}s")
    print(json.dumps({"n": len(idxs), "steps": len(tr["t"]), "done": done}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
