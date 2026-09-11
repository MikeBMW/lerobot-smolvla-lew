# -*- coding: utf-8 -*-
"""🧪 INTACT 节点自检 (S2 阶段): obs → 零搜索 chunk → RobotIO 全链打通。

判据 (全部真断言, 缺一即 FAIL):
  1. 数据源能出输入 (如为合成观测, 打印明确标注)
  2. chunk 形状 = [horizon, action_dim] 且全部有限
  3. RobotIO 收到 = chunk 展开后的步数 (逐步下发语义)
  4. 诊断键齐全 (intent_norm / forward_calls / candidate_sequences)
  5. trained=False 时 **必须**给出 reason (不许静默返回假动作)
用法: gui-venv311/bin/python -m lerobot.manifold.intact_node.selftest [--real]
      --real = 走真 worker (INTACT venv 桥; 依赖未装好时会诚实报 trained=False)
"""
from __future__ import annotations

import sys
import time

import numpy as np

from .model_adapter import IntactRuntime
from .node import NODE_NAME, IntactNode
from .robot_io import SimRobotIO

OK, FAIL = "✅", "❌"


def main(use_real: bool = False, steps: int = 5) -> int:
    print(f"=== {NODE_NAME} 自检 ({'真 worker' if use_real else '本地 stub'}) ===")
    rt = IntactRuntime(autostart=use_real)
    if not use_real:
        rt.reason = "selftest stub 模式 (未启动 worker)"
    node = IntactNode(horizon=4, action_dim=4, runtime=rt)
    node.set_data_source("l4_episode")                     # 我们的 L4 episode
    print("   数据源:", node.source.info())
    assert node.source.obs_mode in ("frames", "synthetic_from_trace")
    if node.source.obs_mode == "synthetic_from_trace":
        print("   ⚠️ 诚实标注: 观测为**合成图** (该 npz 无渲染帧), 仅供链路自检, 不作为视觉证据")

    applied = []
    io = SimRobotIO(apply_fn=lambda a: applied.append(np.asarray(a, copy=True)))
    node.attach_robot(io)

    t0 = time.perf_counter()
    outs = [node.step() for _ in range(steps)]
    dt = (time.perf_counter() - t0) * 1000.0 / max(1, steps)
    ok = True

    for i, o in enumerate(outs):
        shape_ok = o.chunk.shape == (node.horizon, node.action_dim)
        fin_ok = bool(np.isfinite(o.chunk).all())
        print(f"   step{i + 1}: chunk{o.chunk.shape} 有限={fin_ok} trained={o.trained} "
              f"源={o.source}")
        ok &= shape_ok and fin_ok
    print(f"   {OK if ok else FAIL} 1-2) chunk 形状/有限性")
    ok &= (len(applied) == steps * node.horizon)
    print(f"   {OK if len(applied) == steps * node.horizon else FAIL} 3) RobotIO 逐步下发: "
          f"{len(applied)} 步 (期望 {steps * node.horizon})")
    d = node.diagnostics()
    need = ("intent_norm", "forward_calls", "candidate_sequences", "latency_ms", "trained")
    ok &= all(k in d for k in need)
    print(f"   {OK if all(k in d for k in need) else FAIL} 4) 诊断键齐全: {d}")
    if not node.runtime.trained:
        ok &= bool(node.runtime.reason)
        print(f"   {OK if node.runtime.reason else FAIL} 5) trained=False 时给出 reason: "
              f"{node.runtime.reason}")
    else:
        print(f"   {OK} 5) trained=True (真权重): dims={node.runtime.dims}")
    print(f"\n   平均端到端 {dt:.1f} ms/步 (含 IO)")
    print(f"   describe(): {node.describe()}")
    node.close()
    print(f"\n{'✅ 自检通过' if ok else '❌ 自检失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(use_real="--real" in sys.argv))
