#!/usr/bin/env python3
"""F02 用例: 按意图零搜索产出动作块 (L4) — 候选搜索数=0 且动作块非零

对应功能: F02 "按意图零搜索产出动作块" (层 L4, 开关 SS_L4_INTACT)
判据: 
  · 模型就绪 (trained=True) — 未就绪必须显式拒绝, 不许返回假动作
  · 动作块非零 (真推理)
  · 候选序列数 = 0 (零搜索: 不采样候选, 免 CEM)
  · 前向次数 == horizon (真跑了)
"""
import os
import sys

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, f"{ROOT}/src")
os.chdir(ROOT)
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")

import numpy as np  # noqa: E402

fails = []


def chk(name, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))
    if not ok:
        fails.append(name)


try:
    from lerobot.manifold.intact_node import IntactNode  # noqa: E402

    node = IntactNode(horizon=8)
    node.set_data_source("official", task="cube")
    out = node.step()
    d = node.diagnostics()

    chunk = np.asarray(out.chunk, dtype=np.float64)
    chk("模型就绪 (trained=True)", bool(out.trained), f"trained={out.trained}")
    chk("策略=direct (零搜索)", str(out.policy).startswith("direct"), f"policy={out.policy}")
    chk("动作块非零", chunk.size > 0 and float(np.abs(chunk).max()) > 1e-6,
        f"shape={chunk.shape} max|a|={float(np.abs(chunk).max()):.4f}")
    chk("候选搜索数 = 0", float(d.get("candidate_sequences", -1)) == 0.0,
        f"cand_seq={d.get('candidate_sequences')}")
    chk("前向次数 = horizon", float(d.get("forward_calls", -1)) == 8.0,
        f"fwd={d.get('forward_calls')}")
    chk("意图位移非零", float(d.get("intent_norm", 0)) > 1e-6,
        f"intent_norm={float(d.get('intent_norm', 0)):.4f}")
except Exception as e:
    chk("F02 用例执行", False, f"{type(e).__name__}: {str(e)[:80]}")

print("结论: " + ("✅ 通过" if not fails else f"❌ 有不通过项: {fails}"))
sys.exit(0 if not fails else 1)
