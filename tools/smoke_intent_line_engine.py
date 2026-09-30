# -*- coding: utf-8 -*-
"""🧬 smoke_intent_line_engine.py — 引擎内**真跑**直连线 (三档对照: 关 / 开不注入 / 开注入)

目的 (老倪: 写了要真接上, 不许表演):
  A 关   (SS_L4_INTENT_LINE 不设)          → 基准
  B 开但 w=0 (SS_L4_INTENT_LINE_W=0)       → 线路真跑(真推理真出流形), 但不注入 ⇒ 必须与 A **逐位相同**
  C 开且注入 (W=1, 预测器已过质量闸)        → 与 A 不同, 且给出流形/夹紧/来源证据

输出: /tmp/intent_line_smoke.json (三档的 u_ff 轨迹 hash + L4/直连线摘要)
用法: MUJOCO_GL=egl INTACT_POLICY=... ./gui-venv311/bin/python tools/smoke_intent_line_engine.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("INTACT_RUNTIME", "root")
os.environ.setdefault("INTACT_POLICY",
                      "intact_goal_optical_insert_v6r10_s3072/weights_epoch_1.pt")

STEPS = int(os.environ.get("SMOKE_STEPS", "220"))


def h(x) -> str:
    a = np.ascontiguousarray(np.asarray(x, np.float64))
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


def one(tag: str, *, line: bool, w: float) -> dict:
    os.environ["SS_L4_INTACT"] = "1"        # 进 L4 直驱档 (解码器→直连线在这条链上)
    if line:
        os.environ["SS_L4_INTENT_LINE"] = "1"
        os.environ["SS_L4_INTENT_LINE_W"] = str(w)
    else:
        os.environ.pop("SS_L4_INTENT_LINE", None)
        os.environ.pop("SS_L4_INTENT_LINE_W", None)
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    t0 = time.time()
    sim = RealStateSpaceSim(seed=0, vision=False, mode="insert", log=lambda *x: None)
    node = IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu"))
    sim.attach_intact(node)
    tr = sim.run(max_steps=STEPS)
    uff = np.asarray(tr.get("u_ff_vec") or [], float)
    out = {"tag": tag, "line_env": os.environ.get("SS_L4_INTENT_LINE"),
           "w_env": os.environ.get("SS_L4_INTENT_LINE_W"),
           "steps": int(len(tr.get("t", []))), "u_ff_hash": h(uff) if uff.size else "none",
           "u_ff_vec": uff,
           "u_ff_norm_mean": round(float(np.linalg.norm(uff[:, :3], axis=1).mean()), 6) if uff.size else None,
           "l4_summary": sim.l4_intact_summary(),
           "intent_line_summary": sim.l4_intent_line_summary(),
           "sec": round(time.time() - t0, 1)}
    if "il_u_ff_vec" in tr:                      # 直连线每帧的 u_int 证据
        il = [v for v in tr["il_u_ff_vec"] if v is not None]
        ilw = [float(v) for v in tr.get("il_w", [])]
        imm = [v for v in tr.get("il_manifold_vec", []) if v is not None]
        out["il_frames"] = len(il)
        out["il_w_mean"] = round(float(np.mean(ilw)), 4) if ilw else None
        out["il_norm_mean"] = round(float(np.mean([np.linalg.norm(v[:3]) for v in il])), 6) if il else None
        out["il_manifold_last"] = [round(float(x), 5) for x in (imm[-1] if imm else [])]
    return out


def main() -> int:
    A = one("A_关", line=False, w=0.0)
    B = one("B_开不注入(w=0)", line=True, w=0.0)
    C = one("C_开注入(w=1)", line=True, w=1.0)
    # 逐帧差异 (hash 太严: L4 档的 INTACT CPU 前向有 FP 非确定性 → 混沌放大, 必须给量级)
    def _diff(x, y):
        n = min(len(x), len(y))
        if n == 0:
            return {"n": 0}
        dx = np.abs(np.asarray(x, float)[:n] - np.asarray(y, float)[:n])
        per = dx.reshape(n, -1)
        first = int(np.argmax(per.max(1) > 1e-9)) if (per.max(1) > 1e-9).any() else -1
        return {"n": n, "max_abs_u_ff": float(dx.max()),
                "max_abs_first30": float(per[:30].max()), "first_divergent_frame": first}
    rep = {"A": A, "B": B, "C": C,
           "zero_regression_A_vs_B_hash": bool(A["u_ff_hash"] == B["u_ff_hash"]),
           "A_vs_B_diff": _diff(A["u_ff_vec"], B["u_ff_vec"]),
           "B_vs_C_diff": _diff(B["u_ff_vec"], C["u_ff_vec"]),
           "predictor_ready": bool(C["intent_line_summary"]["ready"]),
           "ready_src": C["intent_line_summary"]["ready_src"]}
    for _k in ("A", "B", "C"):                       # 轨迹数组不塞 JSON (太大且非标量)
        rep[_k].pop("u_ff_vec", None)
    json.dump(rep, open("/tmp/intent_line_smoke.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: rep[k] for k in ("zero_regression_A_vs_B_hash", "A_vs_B_diff",
                                          "B_vs_C_diff", "predictor_ready", "ready_src")},
                     ensure_ascii=False, indent=1))
    for k in ("A", "B", "C"):
        r = rep[k]
        s = r["intent_line_summary"]
        print(f"[{r['tag']}] steps={r['steps']} u_ff_hash={r['u_ff_hash']} "
              f"| 直连线 frames={s['frames']} ran={s['ran']} applied={s['applied']} w_zero={s['w_zero']} "
              f"refused={s['refused']} ready={s['ready']} w_last={s['w_last']} clip_max={s['clip_max']} "
              f"| il_frames={r.get('il_frames')} il_w_mean={r.get('il_w_mean')} "
              f"il_norm={r.get('il_norm_mean')} | err={s['err']}")
    print(f"\n→ /tmp/intent_line_smoke.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
