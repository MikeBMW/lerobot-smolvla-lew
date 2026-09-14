# -*- coding: utf-8 -*-
"""🧠 collect_stop_data.py — 采集"交权/停"判据的训练数据 (2026-09-15, ⑤ m_stop)

动机: 实测 `mani_risk`(接触流形) **不区分成功/卡死** (成功 0.0114 vs 卡死 0.0097),
不能直接当停判据 → 用实测数据学一个: 每帧特征 → 这一局**最终会不会失败**。
口径: 每个 seed 独立进程冷记忆 (避免肌肉记忆/场景污染), 解析链真跑 900 步。
特征 (每帧): z7(7) + 专家6 (risk/progress/V/eta/rem/dperp) + 接触/执行 (contact_p, force,
            |u_sat|, depth, dh) + 阶段 one-hot(13) = 7+6+5+13 = 31 维
标签: 该局是否 done (局级) + 帧在插入/转移段 (只在这些段切片训练)
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/collect_stop_data.py --seeds 0..11
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
for k, v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
             ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
             ("INTACT_RUNTIME", "root"), ("INTACT_POLICY", "intact_l4_current"),
             ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(k, v)
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "插入 · 接触",
          "拔出", "AOI转移", "AOI检测", "回程", "放下", "完成"]
STAGE_IDX = {s: i for i, s in enumerate(STAGES)}
FOCUS = ("插入", "转移", "下降", "对位")     # 只在"决定成败"的段切片


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2,3,4,5,6,7,8,9,10,11")
    ap.add_argument("--steps", type=int, default=900)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "stop_signal_v1.npz"))
    a = ap.parse_args()
    Feat, Lab, Sid, Stg = [], [], [], []
    meta = []
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        os.environ["SS_MUSCLE_PATH"] = f"/tmp/stop_collect_{os.getpid()}_{sd}.json"
        from state_space_sim_real import RealStateSpaceSim
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *x: None)
        tr = sim.run(max_steps=a.steps)
        done = bool(tr.get("done", [False])[-1])
        stg = [str(x).replace("阶段 ", "") for x in (tr.get("stage") or [])]
        n = len(stg)

        def col(k, dim, default=0.0):
            v = [x for x in (tr.get(k) or []) if x is not None]
            arr = np.asarray(v, float).reshape(len(v), -1)[:, :dim] if v else np.zeros((0, dim))
            if arr.shape[0] < n:
                arr = np.vstack([arr, np.full((n - arr.shape[0], dim), default)])
            return arr[:n]

        z7 = col("z7_vec", 7); mp = col("mani_pred", 6)
        expert = np.column_stack([col("mani_risk", 1)[:, 0], col("mani_progress", 1)[:, 0],
                                  col("mani_V", 1)[:, 0], col("mani_eta", 1)[:, 0],
                                  col("mani_rem", 1)[:, 0], col("mani_dperp", 1)[:, 0]])
        cp = col("contact_p", 1); fo = col("force", 1); u = col("u_sat_vec", 4)
        dth = col("dist", 1); gr = col("grasped", 1)
        onehot = np.zeros((n, len(STAGES)), float)
        for i, s in enumerate(stg):
            onehot[i, STAGE_IDX.get(s, len(STAGES) - 1)] = 1.0
        F = np.hstack([z7, expert, cp, fo, np.linalg.norm(u[:, :3], axis=1, keepdims=True),
                       dth, gr, onehot])
        keep = np.array([str(s).split(" ·")[0] in FOCUS for s in stg])
        Feat.append(F[keep]); Lab.append(np.full(int(keep.sum()), 1.0 - float(done)))
        Sid.append(np.full(int(keep.sum()), sd)); Stg.append(np.array(stg)[keep])
        meta.append({"seed": sd, "done": done, "frames_total": n, "frames_kept": int(keep.sum()),
                     "stages": {s: stg.count(s) for s in sorted(set(stg))}})
        print(f"  seed{sd}: done={done} 帧 {n} → 保留 {int(keep.sum())} · 阶段={meta[-1]['stages']}",
              flush=True)
    F = np.vstack(Feat); L = np.concatenate(Lab); S = np.concatenate(Sid); G = np.concatenate(Stg)
    np.savez_compressed(a.out, X=F.astype(np.float32), y=L.astype(np.float32), seed=S, stage=G,
                        feat_dim=np.asarray([F.shape[1]]))
    print(f"\n✅ 落盘 {a.out}: {F.shape} · 失败帧占比 {L.mean():.3f} · seeds={len(meta)}")
    import json
    json.dump(meta, open(os.path.join(ROOT, "reports", "stop_signal_collect_20260915.json"), "w"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
