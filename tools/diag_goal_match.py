# -*- coding: utf-8 -*-
"""🎯 diag_goal_match.py — 查"提案被否决 98%"的真因: 目标帧口径 (2026-09-15)

已取证的**结构性事实**:
  · 训练 (INTACT-JEPA jepa.py:190 `_encode_goal`): goal = `info["goal"]` 的**像素帧**,
    即该回合的**末帧图** (train.py:87 `goal = embeddings[:, -1:]`) — 每个窗口自己的终态图
  · 运行时 (node.py:104 ensure_goal): 引擎**从不调 set_goal** → 用固定文件
    reports/intact_goal_frame_optical.npy (09-14 13:06 生成, 所有 seed 共用一张) ⇒ 与当前场景不一致
本脚本: 同 seed 对比三条臂的 L4 提案与执行结果
  A 默认固定目标帧 (现状)
  B 本 run 活目标帧 (解析链跑完后的终态帧, 与训练同构)
  C B 的对照组: 只换目标帧看提案是否变化 (若提案逐位相同 → 目标帧根本没被消费, 另一个 bug)
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_goal_match.py --seed 0 --steps 400
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

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


def _mk(seed):
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *x: None)
    node = IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu"))
    sim.attach_intact(node)
    return sim, node


def _proposals(tr):
    v = [u for u in tr.get("l4_u_ff_vec") or [] if u is not None]
    return np.asarray(v, float) if v else np.zeros((0, 4))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=400)
    a = ap.parse_args()
    os.environ["SS_L4_INTACT"] = "1"
    os.environ["SS_L4_INTACT_GATE"] = "0"          # 先关闸: 要看**原始提案**, 不被闸掩盖
    os.environ.pop("SS_L4_INTENT_LINE", None)

    # ① 解析链跑完 → 取本 run 的终态帧 (与训练同构的 goal)
    os.environ.pop("SS_L4_INTACT", None)
    sim_a, _ = _mk(a.seed)
    tr_a = sim_a.run(max_steps=a.steps)
    frame = np.asarray(sim_a._render_frame())
    # 统一成 HWC 再缩放 (cv2 只吃 2D/HWC; CHW 会报 "m->dims <= 2")
    if frame.ndim == 3 and frame.shape[0] in (1, 3, 4) and frame.shape[-1] not in (3, 4):
        frame = frame.transpose(1, 2, 0)
    import cv2
    goal_live = cv2.resize(np.ascontiguousarray(np.asarray(frame).astype(np.float32)), (224, 224),
                           interpolation=cv2.INTER_AREA).transpose(2, 0, 1)
    stg_a = [str(s).replace("阶段 ", "") for s in (tr_a.get("stage") or [])]
    print(f"① 解析链 seed{a.seed}: 阶段={sorted(set(stg_a))} done={tr_a.get('done',[False])[-1]} "
          f"→ 活目标帧 shape={goal_live.shape} std={goal_live.std():.1f}")

    # ② 默认固定目标帧的原始信息
    gdef = np.load(os.path.join(ROOT, "reports/intact_goal_frame_optical.npy"))
    print(f"② 默认固定目标帧: shape={gdef.shape} std={float(gdef.std()):.1f} · "
          f"与活目标帧逐像素 L1={float(np.abs(gdef-goal_live).mean()):.2f} (0=完全相同)")

    os.environ["SS_L4_INTACT"] = "1"
    res = {}
    for tag, use_live in (("A_默认固定goal", False), ("B_活目标帧", True)):
        sim, node = _mk(a.seed)
        if use_live:
            node.set_goal(goal_live)
        tr = sim.run(max_steps=a.steps)
        p = _proposals(tr)
        stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
        l4s = sim.l4_intact_summary()
        res[tag] = {"proposals": p, "stage": dict(Counter(stg)),
                    "veto": l4s.get("l2_veto"), "pass": l4s.get("gate_pass"),
                    "done": bool(tr.get("done", [False])[-1]),
                    "goal_src": getattr(node, "goal_src", "?"),
                    "dist_min": round(float(np.min(tr.get("dist") or [9])) * 1000, 1)}
        print(f"\n【{tag}】goal_src={res[tag]['goal_src']} · 阶段={res[tag]['stage']} · "
              f"done={res[tag]['done']} · 最小插入={res[tag]['dist_min']}mm · 提案帧数={len(p)}")
    pa, pb = res["A_默认固定goal"]["proposals"], res["B_活目标帧"]["proposals"]
    n = min(len(pa), len(pb))
    if n:
        same = int(np.sum(np.all(np.isclose(pa[:n], pb[:n], atol=1e-6), axis=1)))
        print(f"\n③ 两臂提案对照: 共同帧 {n} · **逐位相同** {same} 帧 "
              f"({same/n*100:.0f}%) · 平均 |Δ提案|={float(np.abs(pa[:n]-pb[:n]).mean()):.5f}")
        if same == n:
            print("   ⇒ 提案完全不受目标帧影响 → 目标帧**根本没被策略消费** (另一处 bug, 与 goal 无关)")
        else:
            print("   ⇒ 目标帧确实影响提案 → 固定 goal 是提案跑偏的一个真因")
    return 0


if __name__ == "__main__":
    sys.exit(main())
