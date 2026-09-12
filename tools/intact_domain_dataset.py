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
    ap.add_argument("--part-frames", type=int, default=20000,
                    help="内存闸: 累计帧数到阈值就先落一个 part npz (300 回合≈15万帧 "
                         "= 22GB 内存, 一次性 concat 会被 OOM 杀 — 实测踩坑)")
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
    parts: list[str] = []          # 已落盘的 part npz (内存闸分块, 防 OOM)
    _done_buf: list = []           # 本 part 内各回合 done (用于 part meta 的 done_rate)
    t0 = time.time()

    def _flush_part(_final=False):
        """把已攒的回合落成一个 part npz 并清空内存 (每 part 自包含 ep_len/ep_offset)。"""
        if not ep_len:
            return
        L_ = np.asarray(ep_len, dtype=np.int64)
        off_ = np.concatenate([[0], np.cumsum(L_)[:-1]]).astype(np.int64)
        px_ = np.concatenate(ep_pix, axis=0)
        ep_std_ = []
        for i, n in enumerate(L_):
            s = int(off_[i])
            ep_std_.append(float(np.mean([px_[s + j].std()
                                          for j in np.linspace(0, n - 1, 8).astype(int)])))
        bad_ = [i for i, v in enumerate(ep_std_) if v <= 5.0]
        if bad_:
            print(f"❌ part{len(parts):02d} 有 {len(bad_)} 个黑帧回合 (idx {bad_[:6]}) → 不落盘")
            return
        p = os.path.join(ROOT, "reports", f"{a.out_name}_part{len(parts):02d}.npz")
        np.savez_compressed(
            p, pixels=px_, action=np.concatenate(ep_act, axis=0).astype(np.float32),
            observation=np.concatenate(ep_obs, axis=0).astype(np.float32),
            ep_len=L_, ep_offset=off_,
            ep_idx=np.concatenate([np.full(n, i, dtype=np.int32) for i, n in enumerate(L_)]),
            step_idx=np.concatenate([np.arange(n, dtype=np.int64) for n in L_]),
            meta=np.array([{
                "source": "Z-MAX 六层引擎 RealStateSpaceSim 真链路 (metaworld insert)",
                "pixels": f"env.render() 真实渲染 → {a.img}² RGB (与 INTACT 原生分辨率一致)",
                "action": "sink 实收 env 级动作 act = [dx,dy,dz,gripper] (±1, 因果: 它造成该转移)",
                "observation": "env 原生 o[:39] (与引擎/L3 同源口径)",
                "mode": a.mode, "max_steps": a.max_steps,
                "episodes": len(L_), "frames": int(L_.sum()),
                "done_rate": (round(float(np.mean(_done_buf)), 4) if _done_buf else None),
                "ep_frame_std": [round(v, 2) for v in ep_std_],
                "ts": time.strftime("%F %T")}], dtype=object))
        parts.append(p)
        print(f"   💾 part{len(parts)-1:02d}: 回合 {len(L_)} · 帧 {int(L_.sum())} · "
              f"{os.path.getsize(p)/1e6:.0f}MB → {os.path.basename(p)}", flush=True)
        ep_pix.clear(); ep_act.clear(); ep_obs.clear(); ep_len.clear(); _done_buf.clear()

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
        ep_len.append(len(px)); done_flags.append(done); _done_buf.append(bool(done))
        print(f"  seed{seed}: {len(px)} 帧 · done={done} · 帧std={_std:.1f} · "
              f"(累计 {sum(ep_len) + sum(int(np.load(p, allow_pickle=True)['ep_len'].sum()) for p in parts)} 帧, "
              f"{time.time()-t0:.0f}s)", flush=True)
        if sum(ep_len) >= a.part_frames:            # 💾 内存闸: 攒够就落盘清空
            _flush_part()

    _flush_part(_final=True)
    if not parts:
        print("❌ 没有任何有效 part → 中止")
        return 2
    tot = 0
    for p in parts:
        tot += int(np.load(p, allow_pickle=True)["ep_len"].sum())
    dr = float(np.mean(done_flags)) if done_flags else float("nan")
    print(f"\n✅ 分块落盘 {len(parts)} 个 part (内存闸 {a.part_frames} 帧/块, 防 22GB OOM)")
    for p in parts:
        print(f"   {p}")
    print(f"   合计 回合 {len(done_flags)} · 帧 {tot} · done_rate={dr:.2f} · "
          f"用时 {time.time()-t0:.0f}s")
    print(f"   下一步: 合并转 h5 → "
          f"/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py "
          f"--parts 'reports/{a.out_name}_part*.npz' --out-name {a.out_name} "
          f"--dest {a.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
