# -*- coding: utf-8 -*-
"""🔬 L4 档 (mode=full + cap=l4, 4000 步预算) 为何跑满不成功 — 单手木桩诊断

复现 GUI「🧭 档位=L4」(「🤖 L4 用 INTACT 节点执行」默认勾选) 的真实链路:
  · 档位 L4 → mode=full → 引擎预算 = MAX_STEPS×2 = 4000 步
  · cap=l4 → 注入来料干扰 (移位/转向/dz) + 自主恢复
  · arm=direct  → install_direct_act (INTACT 模型动作直接 env.step, 每帧真推理)
     arm=analytic→ 解析链 (同 seed 同 cap 对照, 回答\"这个布局+干扰到底可不可解\")

用法 (必须 gui-venv311):
  gui-venv311/bin/python tools/diag_l4_stall.py --arm analytic --steps 4000 --seed 104
  INTACT_RUNTIME=root INTACT_POLICY=intact_l4_current \
    gui-venv311/bin/python tools/diag_l4_stall.py --arm direct --steps 600 --seed 104
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="analytic", choices=["analytic", "direct"])
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--mode", default="full", choices=["insert", "full"])
    ap.add_argument("--cap", default="l4")
    ap.add_argument("--infer-every", type=int, default=1)
    ap.add_argument("--video", default="", help="非空则录 480² mp4 (逐帧标注阶段/插入/动作来源)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    tag = time.strftime("%Y%m%d_%H%M%S")
    out = a.out or os.path.join(ROOT, "reports", f"diag_l4_{a.arm}_seed{a.seed}_{tag}.jsonl")
    fh = open(out, "w", encoding="utf-8")
    t0 = time.time()

    # ── 视频 (逐帧标注, 需要 CJK 字体) ──
    _wr = None
    _font = None
    if a.video:
        import cv2                                            # noqa: PLC0415
        from PIL import Image, ImageDraw, ImageFont           # noqa: PLC0415
        for _f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                   "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"):
            if os.path.isfile(_f):
                _font = ImageFont.truetype(_f, 17)
                break
        _wr = cv2.VideoWriter(a.video, cv2.VideoWriter_fourcc(*"mp4v"), 20, (480, 480))
        print(f"🎬 录像: {a.video} (font={'CJK' if _font else 'ASCII'})", flush=True)

    def _overlay(img, lines):
        import cv2                                            # noqa: PLC0415
        from PIL import Image, ImageDraw                       # noqa: PLC0415
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im)
        y = 6
        for ln in lines:
            dr.rectangle([4, y - 2, 476, y + 22], fill=(0, 0, 0))
            dr.text((8, y), ln, font=_font, fill=(0, 255, 200) if _font else (0, 255, 200))
            y += 24
        return np.asarray(im)

    def slog(*xs):
        line = " ".join(str(x) for x in xs)
        print(f"[{time.time()-t0:7.1f}s] {line}", flush=True)

    from state_space_sim_real import RealStateSpaceSim  # noqa: PLC0415

    meta = {"arm": a.arm, "seed": a.seed, "mode": a.mode, "cap": a.cap,
            "steps": a.steps, "infer_every": a.infer_every,
            "ts": time.strftime("%F %T"), "env": {}}

    rec = {"step": [], "stage": [], "grasped": [], "act": [], "x": [], "peg": []}
    state = {"n": 0, "calls": 0, "err": None}
    acts_all = []

    def sink(s, act, o):
        acts_all.append([float(v) for v in np.asarray(act, float).ravel()[:4]])
        if _wr is not None:
            try:
                _fr = np.asarray(s.env.render())
                if _fr.shape[0] != 480:
                    import cv2                                # noqa: PLC0415
                    _fr = cv2.resize(_fr, (480, 480))
                _g = state.get("gate") or {}
                _src = ("模型+闸(否决%d/融合%d)" % (_g.get("veto_dir", 0) + _g.get("veto_mag", 0),
                                                   _g.get("blend", 0))) if _g else "模型直驱"
                _ins = float(np.linalg.norm(np.asarray(o, float).ravel()[:3]
                                            - np.asarray(s.x, float).ravel()[:3]))
                _wr.write(_overlay(np.ascontiguousarray(_fr), [
                    f"[L4 {'模型直驱' if a.arm == 'direct' else '解析链'}] 步 {state['n']} · 阶段 {s.sched.stage()}",
                    f"插入/距离 {_ins*1000:.1f}mm · grasped={bool(getattr(s, 'grasped', False))}",
                    f"下发 action {np.round(np.asarray(act, float).ravel()[:4], 3).tolist()}",
                    f"来源 {_src} · 真推理 {state['calls']} 次 · err {state.get('err') or '无'}"[:70]]))
            except Exception:                                 # noqa: BLE001
                pass
        dd = {"i": state["n"], "st": str(s.sched.stage()),
              "gr": bool(getattr(s, "grasped", False)),
              "act": [round(float(v), 4) for v in np.asarray(act, float).ravel()[:4]],
              "x": [round(float(v), 4) for v in np.asarray(s.x, float).ravel()[:3]],
              "peg": [round(float(v), 4) for v in np.asarray(o, float).ravel()[4:7]],
              # 🔬 直驱取证: 模型真调用次数 / 异常 / 缓存动作 (异常时会被写成全 0 → 手冻结)
              "calls": state.get("calls"), "err": state.get("err"),
              "dact": None if getattr(s, "_direct_act", None) is None
                      else [round(float(v), 4) for v in np.asarray(s._direct_act, float).ravel()[:4]],
              "cache": None if getattr(s, "_dact_cache", None) is None
                       else [round(float(v), 4) for v in np.asarray(s._dact_cache, float).ravel()[:4]]}
        fh.write(json.dumps(dd, ensure_ascii=False) + "\n")
        if state["n"] % 25 == 0:
            fh.flush()
        state["n"] += 1

    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode=a.mode, log=slog)
    sim._frame_sink = sink

    if a.arm == "direct":
        os.environ.setdefault("INTACT_RUNTIME", "root")
        os.environ.setdefault("INTACT_POLICY", "intact_l4_current")
        import intact_direct_rollout as idr  # noqa: PLC0415
        from lerobot.manifold.intact_node import IntactNode, IntactRuntime  # noqa: PLC0415
        rt = IntactRuntime(task="pusht", device=os.environ.get("INTACT_DEVICE", "cpu"))
        node = IntactNode(horizon=8, runtime=rt)
        meta["env"] = {"trained": bool(rt.trained),
                       "reason": str(getattr(rt, "reason", "")),
                       "policy": str(getattr(rt, "policy_name", "") or os.environ.get("INTACT_POLICY")),
                       "runtime": os.environ.get("INTACT_RUNTIME"),
                       "device": os.environ.get("INTACT_DEVICE", "cpu")}
        slag = os.path.join(ROOT, "reports", "intact_goal_frame.npy")
        sstf = os.path.join(ROOT, "reports", "zmax_action_stats.json")
        if not (os.path.isfile(slag) and os.path.isfile(sstf)):
            print(f"❌ 缺目标帧/统计: {slag} / {sstf}")
            return 3
        node.set_goal(np.load(slag))
        am, asd, smeta = idr.load_stats(sstf)
        meta["env"]["stats"] = smeta
        # ⚠️ rec 必须交给 install_direct_act 自己建 (它按 `rec["raw"]` 直接索引;
        #   外部传残缺 dict → 每步 KeyError → 它会把 _dact_cache 写成全 0 = 假"手不动")
        idr.install_direct_act(sim, node, am, asd, infer_every=a.infer_every,
                               rec=None, state=state)

    t1 = time.time()
    tr = sim.run(max_steps=a.steps, cap=a.cap)
    dt = time.time() - t1

    done = bool(tr["done"][-1]) if tr.get("done") else False
    aoi = ((tr.get("_meta") or {}).get("aoi_report") or {})
    stages = {}
    for s in tr.get("stage", []):
        stages[str(s)] = stages.get(str(s), 0) + 1
    gr_any = bool(any(tr.get("grasped", []))) if tr.get("grasped") else False
    first_gr = None
    for i, g in enumerate(tr.get("grasped", []) or []):
        if g:
            first_gr = i
            break
    acts = np.asarray(acts_all, float) if acts_all else np.zeros((0, 4))
    summ = {"arm": a.arm, "seed": a.seed, "mode": a.mode, "cap": a.cap,
            "steps_run": len(tr.get("t", [])), "budget": a.steps,
            "done": done, "aoi_ok": aoi.get("ok"),
            "insert_mm": round(float(tr["dist"][-1]) * 1000, 2) if tr.get("dist") else None,
            "grasped_ever": gr_any, "first_grasp_step": first_gr,
            "stages": stages, "model_calls": state["calls"], "err": state["err"],
            "seconds": round(dt, 1), "sec_per_step": round(dt / max(1, len(tr.get("t", []))), 3),
            "act_mean": acts.mean(0).round(4).tolist() if len(acts) else None,
            "act_std": acts.std(0).round(4).tolist() if len(acts) else None,
            "act_absmax": np.abs(acts).max(0).round(3).tolist() if len(acts) else None,
            "residual_last": round(float(tr["residual"][-1]), 4) if tr.get("residual") else None,
            "residual_min": round(float(np.min(tr["residual"])), 4) if tr.get("residual") else None,
            "gate": state.get("gate"), "err_steps": state.get("err_steps"),
            "meta": meta, "out": out}
    fh.close()
    try:
        if _wr is not None:
            _wr.release()
            print(f"🎬 视频已写出: {a.video}", flush=True)
    except Exception:                                          # noqa: BLE001
        pass
    print("\n═══ 汇总 ═══", flush=True)
    print(json.dumps(summ, ensure_ascii=False, indent=1), flush=True)
    sp = os.path.join(ROOT, "reports", f"diag_l4_{a.arm}_seed{a.seed}_{tag}.json")
    json.dump(summ, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {sp}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
