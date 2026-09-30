#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 生成 INTACT 直驱用的"目标帧" (goal)：成功回合的末帧 → 224² CHW float32 → .npy

为什么: INTACT 的意图/动作以 goal 潜变量为条件 (z_goal 来自目标观测帧)。直驱脚本原先用
"解析链跑完的末帧"当 goal (要先跑一遍解析链), 控制台 L4 档不方便 → 这里从**域内数据集里
挑一个 done=True 回合的末帧**固化成工件 (可复现, 带 provenance), 控制台直接读。

命令: python tools/make_intact_goal_frame.py [--ep 3] [--out reports/intact_goal_frame.npy]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="analytic", choices=["analytic", "dataset"],
                    help="analytic(默认)=解析链跑成功回合取末帧 (语义正确: 任务完成态); "
                         "dataset=从 h5 挑回合末帧 (无 done 元数据时只能估算, 不推荐)")
    ap.add_argument("--seed", type=int, default=0, help="analytic 模式用的种子 (0 在本机解析链成功)")
    ap.add_argument("--h5", default=os.path.join(CACHE, "datasets", "zmax_insert_v2.h5"))
    ap.add_argument("--ep", type=int, default=-1, help="dataset 模式指定回合; -1=自动")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "intact_goal_frame.npy"))
    ap.add_argument("--img", type=int, default=224)
    a = ap.parse_args()

    if a.mode == "analytic":
        # 解析链真跑一遍成功回合 → 取末帧当目标 (与 tools/intact_direct_rollout.py 同口径)
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        sys.path.insert(0, os.path.join(ROOT, "src"))
        import intact_direct_rollout as idr                  # noqa: PLC0415
        out, goal = idr.analytic_rollout(seed=a.seed, mode="insert", max_steps=600)
        if goal is None:
            print("❌ 解析链没产出帧 → 无法生成目标帧")
            return 3
        frame_std = float(goal.std())
        np.save(a.out, goal.astype(np.float32))
        prov = {"mode": "analytic", "seed": a.seed, "done": out["done"], "steps": out["steps"],
                "insert_mm": out.get("insert_mm"), "frame_std": round(frame_std, 1),
                "shape": list(goal.shape), "out": a.out,
                "why": "解析链跑到任务完成态的末帧 (语义=目标观测), 与直驱脚本同口径"}
        with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as fh:
            json.dump(prov, fh, ensure_ascii=False, indent=1)
        print(f"✅ 目标帧(analytic) → {a.out} {goal.shape} · 回合 done={out['done']} "
              f"steps={out['steps']} 插入={out.get('insert_mm')}mm · 帧std {frame_std:.1f}")
        return 0 if out["done"] else 4

    import h5py
    try:
        import hdf5plugin                                    # noqa: F401
    except Exception:
        pass
    import cv2

    with h5py.File(a.h5, "r") as f:
        off = np.asarray(f["ep_offset"][:], dtype=np.int64)
        ln = np.asarray(f["ep_len"][:], dtype=np.int64)
        n_ep = len(ln)
        # 选回合: 优先用 meta 里的 done 列表; 没有就挑帧数最多的回合 (长回合=跑完的回合)
        done = None
        try:
            meta = f.attrs.get("meta")
            if meta is not None:
                m = json.loads(meta) if isinstance(meta, str) else dict(meta)
                done = m.get("done_flags") or m.get("ep_done")
        except Exception:
            done = None
        if a.ep >= 0:
            ep = min(a.ep, n_ep - 1)
            why = "指定"
        elif isinstance(done, list) and any(done):
            ep = int(np.argmax([bool(x) for x in done]))
            why = "meta.done_flags 里第一个成功回合"
        else:
            ep = int(np.argmax(ln))
            why = "帧数最多的回合 (无 done 元数据时的兜底, 属估算)"
        e, s = int(off[ep]), int(off[ep]) + int(ln[ep])
        last = s - 1
        px = np.asarray(f["pixels"][last])                    # (H,W,3) uint8, 引擎真实渲染
        act = np.asarray(f["action"][last], np.float32)
        std = float(px.std())
        if std <= 5.0:
            print(f"❌ 该帧像黑帧 (std={std:.2f}) → 拒绝出工件")
            return 3
        img = cv2.resize(px, (a.img, a.img), interpolation=cv2.INTER_AREA) \
            .transpose(2, 0, 1).astype(np.float32)
        np.save(a.out, img)
        prov = {"source_h5": a.h5, "episode": ep, "frame": last, "ep_frames": int(ln[ep]),
                "why": why, "frame_std": round(std, 2), "mean_px": [round(float(x), 1) for x in px.reshape(-1, 3).mean(0)],
                "last_action": [round(float(x), 4) for x in act], "out": a.out,
                "shape": list(img.shape), "dtype": str(img.dtype)}
        with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as fh:
            json.dump(prov, fh, ensure_ascii=False, indent=1)
    print(f"✅ 目标帧 → {a.out} {img.shape} {img.dtype} (回合 {ep} 末帧 · 帧std {std:.1f} · {why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
