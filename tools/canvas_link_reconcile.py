#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 画布逐连线对账 (代码 + 运行时双证) — 2026-09-24, 老倪点名的硬要求

做法:
  ① 跑一次**真实引擎** (RealStateSpaceSim, insert, 120 步, 记录每帧 io_trace);
  ② 取运行时真实发布的模块通道集合 (key = 画布节点名);
  ③ 画布每个节点分级:  R1 = 引擎每帧真发 io  ·  R2 = 真源存在但只在档位链/双击自检时执行
                        R3 = 语义容器/标注 (记忆/图谱/字典/档位等, 设计如此)  ·  R4 = 合法可视化终端
  ④ 每条连线分级: 双端 R1 / 单端 R1 / 双端非 R1  → 输出"运行时数据流"与"设计语义"两张清单
  ⑤ 全部落盘 reports/canvas_link_reconcile_<ts>.json (可复跑, 数字不手抄)

判据 (老倪红线): 画布上连的线要么是**运行时真数据流**, 要么明确是**设计语义**(容器/记忆/档位),
不允许"看起来连着但两边都不存在"。本脚本给的就是这条判定的**逐条清单**。
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
for _k, _v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
               ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
               ("INTACT_RUNTIME", "root"), ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(_k, _v)

# 语义容器/标注类节点 (设计上不产生运行时 io): 记忆 / 图谱 / 字典 / 档位 / 训练编排 / 待办研究节点
CONTAINER = {"n_eng_mem", "n_mem_links", "n_skill_dict", "n_intent_bundle", "n_intent_direct",
             "ssmode", "sscap", "ss_mem_share", "ss_mem_l2", "ss_mem_l3", "ss_mem_l4",
             "ss_mem_field", "ssllm", "ssskill", "ssreason", "ssllm_in", "n_dsvl", "n_vlm_llm",
             "n_board_frame", "ss_moe", "ss_lora_l4", "ss_lora_l3"}
TERMINAL = {"ssbypv", "ssff_hist", "ssvideo", "ss3d_view", "ssvideo2", "sstest", "ssfeat",
            "swvideo", "swds"}
SOURCE = {"ssdata", "ssz700"}


def main() -> int:
    from state_space_sim_real import RealStateSpaceSim                    # noqa: PLC0415
    t0 = time.time()
    sim = RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *x: None)
    tr = sim.run(max_steps=120)
    n = len(tr.get("t", []))
    io = tr.get("io_trace") or []
    keys = set()
    for _t, d in io:
        keys |= set(d.keys())
    print(f"引擎真跑: {n} 步 · io_trace {len(io)} 帧 · 运行时模块通道 {len(keys)} 个 ({time.time()-t0:.1f}s)")
    print("运行时通道: " + " · ".join(sorted(keys)))

    flow = json.load(open(os.path.join(ROOT, "flows", "state_space_obs.json"), encoding="utf-8"))
    nm = {x["id"]: str(x.get("name", "")) for x in flow["nodes"]
          if x.get("type") != "row_bg"}                      # 🐛 行带背景不是节点, 必须排除
    band_names = {str(x.get("name", "")) for x in flow["nodes"] if x.get("type") == "row_bg"}

    def runtime_match(name: str) -> str | None:
        best = None
        for k in keys:
            kk = k.replace("🛡 安全限幅", "安全执行边界").replace("🤖 执行器", "机器人执行器")
            if kk in name or name.split(" (")[0] in k:
                if best is None or len(k) > len(best):
                    best = k
        return best

    grade = {}
    for nid, name in nm.items():
        if nid in SOURCE:
            grade[nid] = "R1-源"
            continue
        if nid in ("ss_moe", "ss_lora_l4", "ss_lora_l3"):
            grade[nid] = "R5-待建"                      # 待办任务节点 (老倪: 待办也要做成功能节点)
            continue
        m = runtime_match(name)
        if m:
            grade[nid] = "R1"
        elif nid in TERMINAL:
            grade[nid] = "R4-终端"
        elif nid in CONTAINER:
            grade[nid] = "R3-语义"
        else:
            grade[nid] = "R2-档位链"                    # 真模型/真算子, 但引擎默认档不每帧调

    cnt = defaultdict(int)
    for v in grade.values():
        cnt[v] += 1
    print("\n节点分级: " + " · ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    r2 = [f"{nm[i]}" for i, g in grade.items() if g == "R2-档位链"]
    if r2:
        print(f"R2-档位链 ({len(r2)}): " + " | ".join(x[:24] for x in r2))

    both, one, none = [], [], []
    for L in flow["links"]:
        a, b = grade.get(L["f"], "?"), grade.get(L["t"], "?")
        rec = f"{nm.get(L['f'], L['f'])[:22]} → {nm.get(L['t'], L['t'])[:22]}"
        if a.startswith("R1") and b.startswith("R1"):
            both.append(rec)
        elif a.startswith("R1") or b.startswith("R1"):
            one.append(rec)
        else:
            none.append(rec)
    print(f"\n连线分级 ({len(flow['links'])} 条): 双端运行时 {len(both)} · "
          f"单端运行时 {len(one)} · 双端非运行时(设计语义/待接入) {len(none)}")
    if none:
        print("双端非运行时清单 (前 12):")
        for x in none[:12]:
            print("   " + x)

    out = {"ts": time.strftime("%Y%m%d_%H%M%S"), "steps": n, "runtime_channels": sorted(keys),
           "node_grade": {nm[i]: g for i, g in grade.items()},
           "links": {"both_runtime": len(both), "one_runtime": len(one), "none_runtime": len(none)},
           "none_runtime_list": none, "one_runtime_list": one}
    p = os.path.join(ROOT, "reports", f"canvas_link_reconcile_{out['ts']}.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
