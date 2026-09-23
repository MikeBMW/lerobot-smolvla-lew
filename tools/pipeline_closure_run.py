#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""♻️ 数据闭环运行器 —— 按画布节点顺序真跑 pipeline, 逐节点落状态(画布高亮), 全绿=闭环完成

老倪 2026-09-23: "运行到执行节点要高亮显示, 所有pipeline节点跑完就是执行完成整个数据闭环"

双击机制:
  ① 画布 flow (flows/pipeline_closure.json) 的 node.params.status
     → pending/running/success/failed → 画布自动上色 (running=#00d4aa 高亮)
  ② CICD 控制台 (每 2s 轮询) 读 docs/PIPELINE_STATE.json 的 stages[*].status

2026-09-23 静静升级 (老倪: "仿真端保证完整 pipeline 运行"):
  · 输入不再是零图/零 obs —— 真帧 = 引擎渲染帧, 真 obs39 = 引擎真实观测
  · L2 = **在役光模块检测器** (models/yolo_peg_live.pt), 不再静默退到通用 yolov8s COCO
  · L5 = 真 TaskPlanner (planner.taskplanner), 依赖缺失自动回退 planner.rules 并标注
  · L4 = 真权重 (node.unified 真 ckpt; --vote 时并联 node.intact 仲裁)
  · exec 节点 = **真闭环**: 把整条 Pipeline 挂到引擎跑一轮 (done/步数/最小插入距)
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(REPO, "flows", "pipeline_closure.json")
STATE = os.path.join(REPO, "docs", "PIPELINE_STATE.json")
for _p in (REPO + "/tools", REPO + "/tools/gui", REPO + "/src"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 阶段定义: (key, 画布节点名, 说明)
STAGES = [
    ("l5", "L5 定方向·造数据", "任务分解 + 变体方向"),
    ("mem", "记忆层 五层联络", "跨层记忆检索与注入"),
    ("l2", "L2 检测反馈", "在役 YOLO 2D→3D + 反馈一致性"),
    ("l4", "L4 认知预测", "统一主干多模型仲裁"),
    ("l3", "L3 状态调度", "动作块 → u_ff (量纲逆运算)"),
    ("exec", "执行 · 数据闭环", "引擎闭环回放 + 回流 + 完成判定"),
]


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def set_flow_status(flow, key, status):
    """写画布节点状态 → 画布/控制台轮询即可高亮"""
    for n in flow.get("nodes", []):
        if n.get("params", {}).get("layer", "").lower() == key.upper().lower():
            n["params"]["status"] = status
            n["params"]["ts"] = _now()
    flow["sim"] = flow.get("sim", {})
    flow["sim"]["last_update"] = _now()
    json.dump(flow, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def set_state_status(key, status, note=""):
    """写 CICD 控制台状态 (每 2s 轮询)"""
    st = {}
    if os.path.isfile(STATE):
        try:
            st = json.load(open(STATE, encoding="utf-8"))
        except Exception:                                                # noqa: BLE001
            st = {}
    st.setdefault("stages", {})[key] = {"status": status, "ts": _now(), "note": note}
    st["stage"] = key
    st["state"] = status
    st["ts"] = _now()
    st["log"] = (st.get("log", "") + "\n[%s] %s: %s %s" % (_now(), key, status, note))[-4000:]
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--steps", type=int, default=450,
                    help="exec 节点引擎回放步数 (seed104 插入任务实测需 ~350 步)")
    ap.add_argument("--vote", action="store_true", help="L4 并联 node.intact 仲裁")
    ap.add_argument("--engine", type=int, default=1, help="1=exec 节点真跑引擎闭环")
    ap.add_argument("--l5", default="auto", choices=["auto", "taskplanner", "rules"])
    a = ap.parse_args()

    if not os.path.isfile(FLOW):
        print("❌ 缺画布 flow — 先跑: python tools/gen_pipeline_closure_flow.py")
        return 1
    flow = json.load(open(FLOW, encoding="utf-8"))
    for n in flow["nodes"]:
        n["params"]["status"] = "pending"
    json.dump(flow, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    import cv2
    import numpy as np
    from multi_layer_pipeline import Pipeline, build_default_spec, _default_live_weights
    from state_space_sim_real import RealStateSpaceSim

    print("=" * 78)
    # ★ 真输入: 引擎渲染帧 + 引擎真实 obs39 (不再是零图/零 obs)
    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode="insert", log=lambda *x: None)
    sim.run(max_steps=8)
    img = cv2.resize(np.asarray(sim._render_frame()), (224, 224),
                     interpolation=cv2.INTER_AREA).astype(np.uint8)
    obs39 = np.asarray(sim._last_obs39, float).ravel()[:39].astype(np.float32)
    print("真输入: 渲染帧 %s mean=%.1f std=%.1f | obs39[:3]=%s"
          % (img.shape, img.mean(), img.std(), np.round(obs39[:3], 3)))
    print("L2 在役检测器: %s" % _default_live_weights())

    l5 = a.l5
    if l5 == "auto":
        try:
            sys.path.insert(0, REPO + "/src")
            from lerobot.policies.left_right.state_space.planner import TaskPlanner  # noqa: PLC0415,F401
            l5 = "planner.taskplanner"
        except Exception:                                                # noqa: BLE001
            l5 = "planner.rules"
    else:
        l5 = "planner.taskplanner" if l5 == "taskplanner" else "planner.rules"

    spec = build_default_spec(L5=l5, L2="detect.yolo", L4="node.unified", L3="dispatch.engine")
    if a.vote:
        spec["L4"] = {"impl": "node.unified", "on": True, "combine": "vote",
                      "peers": ["node.intact"]}
    _PIPE = Pipeline(spec)                      # ★ 只装配一次 (避免逐节点重载模型)
    _K2N = {"l5": "L5", "mem": "MEM", "l2": "L2", "l4": "L4", "l3": "L3"}
    ctx = {"img": img, "obs39": obs39}
    print("♻️ 数据闭环启动 · 节点顺序: %s" % " → ".join(s[0] for s in STAGES))
    print("   pipeline 装配: %s | L5=%s | L4=%s | L2=在役YOLO"
          % (" → ".join(_PIPE.order), l5, "vote[unified,intact]" if a.vote else "node.unified"))
    print("=" * 78)
    t00 = time.time()
    results = {}
    exec_meta = {}
    for i, (key, name, desc) in enumerate(STAGES):
        set_flow_status(flow, key, "running")          # ← 画布高亮 #00d4aa
        set_state_status(key, "running", desc)
        print("\n● [%d/%d] %s ← **高亮 running**" % (i + 1, len(STAGES), name))
        t0 = time.time()
        ok, note = True, desc
        try:
            if key in _K2N:
                _so = _PIPE.stages[_K2N[key]]
                # 🐛 VoteCombiner 只有 .run(ctx), 普通 Layer 只有 .infer(ctx)
                st = _so.run(ctx) if hasattr(_so, "run") else _so.infer(ctx)
                ctx[_K2N[key]] = st
                ok = bool(st.ok)
                note = "%s%s  conf=%.3f  %.1fms" % (st.src, "" if ok else " ✗",
                                                    float(st.conf), float(st.latency_ms))
            else:  # exec: 真闭环 (整条 pipeline 挂引擎跑一轮)
                if not a.engine:
                    note = "已跳过引擎回放 (--engine 0)"
                else:
                    for k in ("SS_INTACT", "SS_L4_INTACT_SHADOW"):
                        os.environ.pop(k, None)
                    os.environ["SS_L4_INTACT"] = "1"
                    os.environ.setdefault("SS_INTACT_EVERY", "8")
                    from multi_layer_pipeline import PipelineNode        # noqa: PLC0415
                    sim2 = RealStateSpaceSim(seed=a.seed, vision=False, mode="insert",
                                             log=lambda *x: None)
                    sim2.attach_intact(PipelineNode(spec=spec, sim=sim2), None)
                    tr = sim2.run(max_steps=a.steps)
                    st4 = dict(getattr(sim2, "_l4_stats", {}) or {})
                    done = bool(tr["done"][-1]) if tr.get("done") else False
                    mind = round(float(np.min(tr["dist"])) * 1000, 1) if tr.get("dist") else None
                    exec_meta = {"done": done, "steps": len(tr["t"]), "min_dist_mm": mind,
                                 "l4_calls": st4.get("calls", 0), "blend": st4.get("blend", 0),
                                 "refused": st4.get("refused", 0),
                                 "l2_veto": {"total": st4.get("l2_veto", 0),
                                             "dir": st4.get("l2_veto_dir", 0),
                                             "mag": st4.get("l2_veto_mag", 0)}}
                    ok = bool(done)
                    note = ("引擎闭环: done=%s · %d 步 · 最小插入距 %.1fmm · L4真推理%d次 · "
                            "融合%d帧 · L2收口否决%d(方向%d)" %
                            (done, len(tr["t"]), mind or -1, st4.get("calls", 0),
                             st4.get("blend", 0), st4.get("l2_veto", 0),
                             st4.get("l2_veto_dir", 0)))
        except Exception as e:                                           # noqa: BLE001
            ok, note = False, "异常: %s" % str(e)[:150]
        dt = (time.time() - t0) * 1000
        results[key] = (ok, note, dt)
        set_flow_status(flow, key, "success" if ok else "failed")
        set_state_status(key, "success" if ok else "failed", note)
        print("   %s %s  %.1fms" % ("✓" if ok else "✗", note, dt))

    all_ok = all(v[0] for v in results.values())
    flow["sim"]["closure"] = "done" if all_ok else "failed"
    flow["sim"]["last_run"] = {"seed": a.seed, "stages": {k: v[1] for k, v in results.items()},
                               "exec": exec_meta, "ts": _now()}
    json.dump(flow, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    set_state_status("closure", "success" if all_ok else "failed",
                     "全部 pipeline 节点跑完" if all_ok else "存在失败节点")

    print("\n" + "=" * 78)
    if all_ok:
        print("✅ **整个数据闭环执行完成** — %d/%d 节点 success · 总耗时 %.1fs"
              % (len(STAGES), len(STAGES), time.time() - t00))
        print("   画布: 全部节点 ●→✓ (绿) · flow.sim.closure = 'done'")
    else:
        print("❌ 闭环未完成 — 失败节点: %s" % [k for k, v in results.items() if not v[0]])
    print("=" * 78)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
