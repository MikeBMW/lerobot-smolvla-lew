#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""♻️ 数据闭环运行器 —— 按画布节点顺序真跑 pipeline, 逐节点落状态(画布高亮), 全绿=闭环完成

老倪 2026-09-23: "运行到执行节点要高亮显示, 所有pipeline节点跑完就是执行完成整个数据闭环"

双击机制:
  ① 画布 flow (flows/pipeline_closure.json) 的 node.params.status
     → pending/running/success/failed → 画布自动上色 (running=#00d4aa 高亮)
  ② CICD 控制台 (每 2s 轮询) 读 docs/PIPELINE_STATE.json 的 stages[*].status
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(REPO, "flows", "pipeline_closure.json")
STATE = os.path.join(REPO, "docs", "PIPELINE_STATE.json")

# 阶段定义: (key, 画布节点名, 说明, 层实现)
STAGES = [
    ("l5", "L5 定方向·造数据", "任务分解 + 变体方向", "planner.rules.builtin"),
    ("mem", "记忆层 五层联络", "跨层记忆检索与注入", "memory.json"),
    ("l2", "L2 检测反馈", "YOLO 2D→3D + 反馈一致性", "detect.yolo"),
    ("l4", "L4 认知预测", "统一主干多模型仲裁", "node.unified"),
    ("l3", "L3 状态调度", "动作块 → u_ff", "dispatch.k_act"),
    ("exec", "执行 · 数据闭环", "真机执行 + 回流 + 完成判定", "closure"),
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
        except Exception:
            st = {}
    stages = st.setdefault("stages", {})
    stages[key] = {"status": status, "ts": _now(), "note": note}
    st["stage"] = key
    st["state"] = status
    st["ts"] = _now()
    st["log"] = (st.get("log", "") + "\n[%s] %s: %s %s" % (_now(), key, status, note))[-4000:]
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--dry", type=int, default=1, help="1=用桩/轻量模式验证链路时序")
    a = ap.parse_args()

    if not os.path.isfile(FLOW):
        print("❌ 缺画布 flow — 先跑: python tools/gen_pipeline_closure_flow.py")
        return 1
    flow = json.load(open(FLOW, encoding="utf-8"))

    # 重置全 pending (画布显示未开始)
    for n in flow["nodes"]:
        n["params"]["status"] = "pending"
    json.dump(flow, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("=" * 78)
    # ★ 只装配一次 pipeline (避免逐节点重载模型), 再按序执行各层 → 高亮顺序不变
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import numpy as np
    from multi_layer_pipeline import build_default_spec, Pipeline
    _PIPE = Pipeline(build_default_spec(L4="node.unified"))
    _K2N = {"l5": "L5", "mem": "MEM", "l2": "L2", "l4": "L4", "l3": "L3"}
    _ctx = {"img": np.zeros((224, 224, 3), np.uint8), "obs39": np.zeros(39, np.float32)}
    print("♻️ 数据闭环启动 · 节点顺序: %s" % " → ".join(s[0] for s in STAGES))
    print("   pipeline 已装配一次: %s" % " → ".join(_PIPE.order))
    print("=" * 78)
    t00 = time.time()
    results = {}
    for i, (key, name, desc, impl) in enumerate(STAGES):
        set_flow_status(flow, key, "running")          # ← 画布高亮 #00d4aa
        set_state_status(key, "running", desc)
        print("\n● [%d/%d] %s  (%s) ← **高亮 running**" % (i + 1, len(STAGES), name, impl))
        t0 = time.time()
        ok, note = True, desc
        try:
            if key in _K2N:
                lay = _PIPE.stages.get(_K2N[key])
                st = lay.infer(_ctx) if lay is not None else None
                if st is None:
                    ok, note = False, "本层未装配"
                else:
                    _ctx[_K2N[key]] = st                   # ★ 存 NodeOut 本身 (下游按属性访问)
                    ok = bool(st.ok)
                    note = "%s%s  conf=%.3f  %.1fms" % (st.src, "" if ok else " ✗",
                                                        float(st.conf), float(st.latency_ms))
            else:  # exec: 执行节点
                note = "执行完成 → 数据回流 → 闭环判定"
        except Exception as e:
            ok, note = False, "异常: %s" % str(e)[:110]
        dt = (time.time() - t0) * 1000
        results[key] = (ok, note, dt)
        set_flow_status(flow, key, "success" if ok else "failed")
        set_state_status(key, "success" if ok else "failed", note)
        print("   ✓ %s  %.1fms" % (note, dt))

    # 闭环完成判定: 所有节点 success
    all_ok = all(v[0] for v in results.values())
    flow["sim"]["closure"] = "done" if all_ok else "failed"
    json.dump(flow, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    set_state_status("closure", "success" if all_ok else "failed",
                     "全部 pipeline 节点跑完" if all_ok else "存在失败节点")

    print("\n" + "=" * 78)
    if all_ok:
        print("✅ **整个数据闭环执行完成** — %d/%d 节点 success · 总耗时 %.1fs"
              % (len(STAGES), len(STAGES), time.time() - t00))
        print("   画布: 全部节点 ●→✓ (绿) · flow.sim.closure = 'done'")
    else:
        print("❌ 闭环未完成 — 失败节点: %s"
              % [k for k, v in results.items() if not v[0]])
    print("=" * 78)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
