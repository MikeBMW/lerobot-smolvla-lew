# -*- coding: utf-8 -*-
"""📦 v3 光模块插拔数据集 (短回合窗口) → INTACT 官方格式

为什么要有 v3 (相对 09-12 的 zmax_insert/v2):
  v2 = 整段长回合 (500-600 步) 直接喂训练 → 离线判闸 MAE 0.0968 vs 常数基线 0.0993,
  预测 std 小 16 倍 = **塌到均值**。根因之一 = 回合太长 + 动作被"小接近动作"主导,
  与论文契约 (50 步短回合, goal_displacement 取 +25 步) 不同构。
v3 做法 (只动数据, 不动 INTACT 任何代码/接口):
  · 仍用既有六层引擎真链路 (RealStateSpaceSim) 采真轨迹 (含真成功)
  · **切窗**: 每回合切出若干 50 步短窗口, 窗口**结束于插入完成帧附近** →
    goal (+25 步) 落在"对位→插入"动作富集相位 = 与论文同构, 且动作分布不再被小动作主导
  · 同时记录引擎阶段名 (sim.sched.stage()) 供溯源/统计 (只进 meta, 不进训练列)

用法 (gui-venv311, 引擎环境):
  ./gui-venv311/bin/python tools/intact_insert_dataset_v3.py \
      --seeds 0-299 --mode full --window 50 --n-per-ep 4 \
      --out-name optical_insert_v3 --dest /home/ubuntu/stable-wm-cache/datasets
  然后 (INTACT venv, 有 h5py) 转官方 h5:
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py \
      --parts 'reports/optical_insert_v3_part*.npz' --out-name optical_insert_v3 \
      --dest /home/ubuntu/stable-wm-cache/datasets
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
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)


def _parse_seeds(spec: str):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0-299")
    ap.add_argument("--mode", default="full", choices=["insert", "full"])
    ap.add_argument("--max-steps", type=int, default=1600, help="full 模式要留够 (插+拔+AOI)")
    ap.add_argument("--img", type=int, default=224)
    ap.add_argument("--window", type=int, default=50, help="短回合窗口长度 (与论文 50 步同量级)")
    ap.add_argument("--n-per-ep", type=int, default=4, help="每个长回合切几个窗口")
    ap.add_argument("--stride-back", type=int, default=15, help="窗口结束点相对完成帧的倒退步长")
    ap.add_argument("--out-name", default="optical_insert_v3")
    ap.add_argument("--dest", default=os.path.join(_CACHE, "datasets"))
    ap.add_argument("--part-frames", type=int, default=20000)
    ap.add_argument("--max-sec", type=float, default=0, help=">0 = 到点自动收尾 (后台跑用)")
    ap.add_argument("--cap", default="l4",
                    help="引擎能力档: l4 = 自主恢复 (失败回退/重抓不放弃, 预算×2) → 成功率显著更高; "
                         "none = 原始逻辑。⚠️ 实测不带 l4 时 900 seed 的 done_rate 只有 0.36, "
                         "失败回合窗口停在「接近/对位」= 对学插入没价值")
    ap.add_argument("--success-only", type=int, default=1,
                    help="1 = 只留成功回合窗口 (与官方 *_single_expert 数据集语义一致: 专家数据); "
                         "0 = 失败回合也切窗 (留真失败动力学)")
    ap.add_argument("--action-key", default="env", choices=["env", "u"],
                    help="动作列口径: env = env.step 收到的 4D 动作 (v3 用, 实测插入段近常量: "
                         "dy std 0.001 / grip std 0.000); u = sim._u_vec (引擎实际控制向量, "
                         "实测逐帧std [0.082,0.072,0.057,0.474] 有信息量)。⚠️ 闭环侧口径必须一致")
    ap.add_argument("--coverage", default="insert", choices=["insert", "all"],
                    help="窗口覆盖: insert = 只取结束于插入完成附近的窗口 (v3 用); "
                         "all = 按 stride 均匀铺满整个回合 (接近/对位/抓取/抬起/转移/插入全相位) "
                         "→ 治 v3『模型没见过怎么走到插入前』的病")
    ap.add_argument("--stride", type=int, default=50, help="coverage=all 时的窗口起点间隔")
    a = ap.parse_args()

    import cv2
    from state_space_sim_real import RealStateSpaceSim

    seeds = _parse_seeds(a.seeds)
    os.makedirs(a.dest, exist_ok=True)
    ep_pix, ep_act, ep_obs, ep_len, meta_eps = [], [], [], [], []
    parts, t0 = [], time.time()

    def _flush(final=False):
        if not ep_len:
            return
        L = np.asarray(ep_len, dtype=np.int64)
        off = np.concatenate([[0], np.cumsum(L)[:-1]]).astype(np.int64)
        px = np.concatenate(ep_pix, axis=0)
        stds = [float(np.mean([px[int(off[i]) + j].std()
                               for j in np.linspace(0, L[i] - 1, 8).astype(int)])) for i in range(len(L))]
        bad = [i for i, v in enumerate(stds) if v <= 5.0]
        if bad:
            print(f"❌ 有 {len(bad)} 个黑帧回合 → 不落盘 (idx {bad[:6]})", flush=True)
        else:
            p = os.path.join(ROOT, "reports", f"{a.out_name}_part{len(parts):02d}.npz")
            np.savez_compressed(
                p, pixels=px, action=np.concatenate(ep_act, axis=0).astype(np.float32),
                observation=np.concatenate(ep_obs, axis=0).astype(np.float32),
                ep_len=L, ep_offset=off,
                ep_idx=np.concatenate([np.full(n, i, dtype=np.int32) for i, n in enumerate(L)]),
                step_idx=np.concatenate([np.arange(n, dtype=np.int64) for n in L]),
                meta=np.array([{
                    "source": "Z-MAX 六层引擎 RealStateSpaceSim 真链路 (光模块插拔, metaworld 40×16mm 模块)",
                    "pixels": f"env.render() 真渲染 → {a.img}² RGB",
                    "action": "sink 实收 env 级动作 act=[dx,dy,dz,gripper] (±1)",
                    "observation": "env 原生 o[:39]",
                    "mode": a.mode, "window": a.window, "n_per_ep": a.n_per_ep,
                    "episodes": len(L), "frames": int(L.sum()),
                    "done_rate": round(float(np.mean([m["done"] for m in meta_eps[-len(L):]])), 4),
                    "ep_frame_std": [round(v, 2) for v in stds],
                    "ep_stage_end": [m["stage_end"] for m in meta_eps[-len(L):]],
                    "ts": time.strftime("%F %T")}], dtype=object))
            parts.append(p)
            print(f"   💾 part{len(parts)-1:02d}: 窗口回合 {len(L)} · 帧 {int(L.sum())} · "
                  f"{os.path.getsize(p)/1e6:.0f}MB · done_rate "
                  f"{np.mean([m['done'] for m in meta_eps[-len(L):]]):.2f}", flush=True)
        ep_pix.clear(); ep_act.clear(); ep_obs.clear(); ep_len.clear()

    n_ok = n_fail = n_win = n_skip = 0
    for si, seed in enumerate(seeds):
        if a.max_sec > 0 and time.time() - t0 > a.max_sec:
            print(f"⏱ 到点收尾 (已 {si} 个 seed)", flush=True)
            break
        px, ac, ob, st = [], [], [], []

        _u_key = str(a.action_key).lower() == "u"

        def _sink(sim, act, o, _px=px, _ac=ac, _ob=ob, _st=st, _uk=_u_key):
            _px.append(cv2.resize(np.asarray(sim.env.render()), (a.img, a.img),
                                  interpolation=cv2.INTER_AREA))
            if _uk:
                # u 口径: 引擎实际控制向量 (sim._u_vec, 与 tr['u_sat_vec'/'u_exec_vec'] 同源)
                _a = getattr(sim, "_u_vec", None)
                _ac.append(np.asarray(_a if _a is not None else act, dtype=np.float32).ravel()[:4])
            else:
                # env 口径: env.step 收到的动作 (v3 用; 插入段近常量)
                _ac.append(np.asarray(act, dtype=np.float32).ravel()[:4])
            _ob.append(np.asarray(o, dtype=np.float32).ravel()[:39])
            try:
                _st.append(str(sim.sched.stage()))
            except Exception:
                _st.append("?")

        sim = RealStateSpaceSim(seed=seed, vision=False, mode=a.mode, log=lambda *x: None)
        sim._frame_sink = _sink
        _cap = None if str(a.cap).lower() in ("none", "0", "") else a.cap
        tr = sim.run(max_steps=a.max_steps, cap=_cap)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        n = len(px)
        if done:
            n_ok += 1
        else:
            n_fail += 1
        if not done and int(a.success_only):
            n_skip += 1                     # 专家数据口径: 失败回合不切窗
            if (si + 1) % 20 == 0 or si == 0:
                print(f"[{si+1}/{len(seeds)}] seed {seed}: ⚠️未完成 (跳过切窗) {n} 步 · "
                      f"阶段末={st[-1] if st else '?'} · 窗口累计 {n_win} · 跳过 {n_skip} · "
                      f"用时 {time.time()-t0:.0f}s", flush=True)
            continue
        # 完成帧 = 首次 done=True; 没有就从末尾倒退
        idx_done = next((i for i, d in enumerate(tr.get("done") or []) if d), None)
        if idx_done is None:
            idx_done = n - 1
        W = int(a.window)
        if str(a.coverage).lower() == "all":
            # 🎯 v4: 均匀铺满整个回合 → 接近/对位/抓取/抬起/转移/插入 全相位都有样本
            ends = list(range(W - 1, n, max(1, int(a.stride))))
            if not ends or ends[-1] != n - 1:
                ends.append(n - 1)
        else:
            ends = [idx_done - k * int(a.stride_back) for k in range(int(a.n_per_ep))]
        for k, end in enumerate(ends):
            start = end - W + 1
            if start < 0 or end >= n:
                continue
            ep_pix.append(np.asarray(px[start:end + 1]))
            ep_act.append(np.asarray(ac[start:end + 1]))
            ep_obs.append(np.asarray(ob[start:end + 1]))
            ep_len.append(W)
            meta_eps.append({"seed": seed, "done": done, "stage_end": st[end], "end": int(end)})
            n_win += 1
        if (si + 1) % 20 == 0 or si == 0:
            print(f"[{si+1}/{len(seeds)}] seed {seed}: {'✅' if done else '⚠️未完成'} "
                  f"{n} 步 · 阶段末={st[-1] if st else '?'} · 窗口累计 {n_win} · "
                  f"用时 {time.time()-t0:.0f}s", flush=True)
        if len(ep_len) >= a.part_frames // W:
            _flush()
    _flush(final=True)
    print(f"\n✅ 完成: seed {len(seeds)} 个 (成功 {n_ok} / 未完成 {n_fail} · 失败跳过 {n_skip}) · 短回合窗口 {n_win} 条 "
          f"· 总帧 {sum(ep_len)+0} (落盘 parts {len(parts)}) · 用时 {time.time()-t0:.0f}s", flush=True)
    print("下一步 (INTACT venv 转官方 h5):")
    print(f"  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py "
          f"--parts 'reports/{a.out_name}_part*.npz' --out-name {a.out_name} --dest {a.dest}")


if __name__ == "__main__":
    main()
