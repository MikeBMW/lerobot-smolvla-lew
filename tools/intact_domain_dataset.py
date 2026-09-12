# -*- coding: utf-8 -*-
"""📦 Z-MAX 域内数据集 → INTACT 官方训练格式 (h5: per-column + ep_len/ep_offset)

为什么: 官方权重是 pusht/cube 任务训的, 与我们插拔任务**域不同** (Step 1 标定中位 R²=−0.147 是
直接证据)。要让 INTACT 在本任务可用, 必须用**本任务真实轨迹**微调。

数据来源: 六层引擎真链路 (RealStateSpaceSim) 逐帧采集 —— 每帧:
  · pixels      = env.render() 真实渲染 480² → 224² (RGB uint8, HWC)   [与 INTACT 原生 224 同分辨率]
  · action      = sink 拿到的**实际下发动作 act** (4D: dx,dy,dz,gripper; env 级 ±1) —— 因果正确 (它造成了该转移)
  · observation = env 原生观测 o[:39] (与引擎/L3 同源口径)
  · ep_len/ep_offset = 回合长度与偏移 (h5 格式硬要求)

口径: 不做任何筛选/插值/回填 —— 失败的回合也留下 (世界模型要见到真实的失败动力学),
在 meta 里如实标注 done_rate。

用法:
  gui-venv311/bin/python tools/intact_domain_dataset.py --seeds 0,1,2 --mode insert --max-steps 600 \
      --out-name zmax_insert --dest /home/ubuntu/stable-wm-cache/datasets
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2,3")
    ap.add_argument("--mode", default="insert", choices=["insert", "full"])
    ap.add_argument("--max-steps", type=int, default=600)
    ap.add_argument("--img", type=int, default=224)
    ap.add_argument("--out-name", default="zmax_insert")
    ap.add_argument("--dest", default=os.path.join(_CACHE, "datasets"))
    ap.add_argument("--vis-every", type=int, default=1)
    a = ap.parse_args()

    import cv2                                             # noqa: PLC0415
    from state_space_sim_real import RealStateSpaceSim     # noqa: PLC0415
    # 注意: gui-venv311 没有 h5py → 这里只落 .npz, 再由 tools/intact_domain_to_h5.py
    # (用 INTACT 自己的 venv, 有 h5py) 转成官方 h5 格式。分两步是刻意的: 采集靠引擎环境,
    # 写 h5 靠 INTACT 环境, 互不污染。

    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    os.makedirs(a.dest, exist_ok=True)
    out_path = os.path.join(a.dest, f"{a.out_name}.h5")

    ep_pix, ep_act, ep_obs, ep_len = [], [], [], []
    done_flags = []
    t0 = time.time()
    for si, seed in enumerate(seeds):
        px, ac, ob = [], [], []

        def _sink(sim, act, o, _px=px, _ac=ac, _ob=ob):
            _px.append(cv2.resize(np.asarray(sim.env.render()), (a.img, a.img),
                                  interpolation=cv2.INTER_AREA))
            _ac.append(np.asarray(act, dtype=np.float32).ravel()[:4])
            _ob.append(np.asarray(o, dtype=np.float32).ravel()[:39])

        sim = RealStateSpaceSim(seed=seed, vision=False, mode=a.mode, log=lambda *x: None)
        sim._frame_sink = _sink
        tr = sim.run(max_steps=a.max_steps)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        # ★ 绝不 close: 引擎 _make_env() 是**进程级单例**, close 后下一轮复用已关 env →
        #   渲染全黑 (实测: 36 回合里只有第 1 个是真图, 其余 std=0)。mujoco 资源随进程退出释放。
        if not px:
            print(f"  seed{seed}: 无帧 → 跳过")
            continue
        _std = float(np.mean([np.asarray(x).std() for x in px[:5]]))
        if _std <= 5.0:
            print(f"  seed{seed}: ❌ 黑帧 (帧std={_std:.1f} ≤ 5) → 丢弃该回合并中止 "
                  f"(不许拿黑图训世界模型 — 蒙眼=假结论)", flush=True)
            return 4
        ep_pix.append(np.stack(px)); ep_act.append(np.stack(ac)); ep_obs.append(np.stack(ob))
        ep_len.append(len(px)); done_flags.append(done)
        print(f"  seed{seed}: {len(px)} 帧 · done={done} · 帧std={_std:.1f} · "
              f"(累计 {sum(ep_len)} 帧, {time.time()-t0:.0f}s)", flush=True)

    if not ep_len:
        print("❌ 一帧都没采到 → 中止")
        return 2

    E = len(ep_len)
    L = np.asarray(ep_len, dtype=np.int64)
    off = np.concatenate([[0], np.cumsum(L)[:-1]]).astype(np.int64)
    pixels = np.concatenate(ep_pix, axis=0)          # [N,img,img,3] uint8
    action = np.concatenate(ep_act, axis=0).astype(np.float32)
    obs = np.concatenate(ep_obs, axis=0).astype(np.float32)
    ep_idx = np.concatenate([np.full(n, i, dtype=np.int32) for i, n in enumerate(L)])
    step_idx = np.concatenate([np.arange(n, dtype=np.int64) for n in L])
    # ★ 保存前最后一次"蒙眼"检查: 每个回合抽 8 帧看 std, 任何回合黑帧 → 不落盘
    ep_std = []
    for i, n in enumerate(L):
        s = int(off[i])
        ep_std.append(float(np.mean([pixels[s + j].std() for j in np.linspace(0, n - 1, 8).astype(int)])))
    bad = [i for i, v in enumerate(ep_std) if v <= 5.0]
    if bad:
        print(f"❌ 有 {len(bad)} 个回合是黑帧 (idx {bad[:8]}) → 不落盘 (数据无效)")
        return 4
    print(f"   帧有效性: 每回合帧std {min(ep_std):.1f}~{max(ep_std):.1f} (全部 > 5 ✓)")

    # 落 .npz (可由 INTACT venv 转 h5); pixels 单独存以控制内存
    out_path = os.path.join(ROOT, "reports", f"{a.out_name}_raw.npz")
    np.savez_compressed(
        out_path, pixels=pixels, action=action, observation=obs,
        ep_len=L, ep_offset=off, ep_idx=ep_idx, step_idx=step_idx,
        meta=np.array([{
            "source": "Z-MAX 六层引擎 RealStateSpaceSim 真链路 (metaworld insert)",
            "pixels": f"env.render() 真实渲染 → {a.img}² RGB (与 INTACT 原生分辨率一致)",
            "action": "sink 实收 env 级动作 act = [dx,dy,dz,gripper] (±1, 因果: 它造成该转移)",
            "observation": "env 原生 o[:39] (与引擎/L3 同源口径)",
            "mode": a.mode, "max_steps": a.max_steps, "seeds": seeds,
            "episodes": E, "frames": int(L.sum()), "done_rate": float(np.mean(done_flags)),
            "ts": time.strftime("%F %T")}], dtype=object))
    sz = os.path.getsize(out_path)
    print(f"\n✅ {out_path}\n   回合 {E} · 帧 {int(L.sum())} · 动作维 {action.shape[1]} · "
          f"观测维 {obs.shape[1]} · done_rate={np.mean(done_flags):.2f} · 文件 {sz/1e6:.1f}MB · "
          f"用时 {time.time()-t0:.0f}s")
    print(f"   下一步: /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_domain_to_h5.py "
          f"--npz {out_path} --out-name {a.out_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
