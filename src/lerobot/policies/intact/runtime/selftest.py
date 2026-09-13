# -*- coding: utf-8 -*-
"""🧪 INTACT 节点自检 — 两条路径都要验, 且必须能识别"假成功"。

A) 无真权重 (stub): 节点**必须拒绝**返回零动作 (防"形状对+全零"被当成成功)
B) 有真权重 (--real): 每步 chunk 必须**非零且随观测变化** (真推理, 不是常量/零回退)

用法:
  PYTHONPATH=src python -m lerobot.manifold.intact_node.selftest          # A: 防假成功闸
  STABLEWM_HOME=... INTACT_RUNTIME=paper INTACT_DEVICE=cuda \
    PYTHONPATH=src python -m lerobot.manifold.intact_node.selftest --real  # B: 真权重单步
"""
from __future__ import annotations

import sys
import time

import numpy as np

from .model_adapter import IntactRuntime
from .node import NODE_NAME, IntactNode
from .robot_io import SimRobotIO

OK, FAIL = "✅", "❌"


class _UnavailableRuntime:
    """确定性"不可用"运行时 (自检 A 路径): 不启动真 worker, 只用于验证节点拒绝零动作。"""

    def __init__(self):
        self.trained = False
        self.dims: dict = {}
        self.reason = "selftest: 故意不可用 (验证防假成功闸)"

    def get_action(self, info, horizon=8):
        return (np.zeros((int(horizon), 4), dtype=np.float32),
                {"trained": 0.0, "reason_zero_action": 1.0})

    def start(self):
        return False

    def close(self):
        pass

    def info(self):
        return {"trained": False, "reason": self.reason, "dims": {}, "repo": "(stub)"}


def _mk_node(use_real: bool, steps_horizon: int = 4):
    rt = IntactRuntime(autostart=True) if use_real else _UnavailableRuntime()
    node = IntactNode(horizon=steps_horizon, runtime=rt)
    node.set_data_source("l4_episode")
    applied = []
    node.attach_robot(SimRobotIO(apply_fn=lambda a: applied.append(np.asarray(a, copy=True))))
    return node, rt, applied


def main(use_real: bool = False, steps: int = 3) -> int:
    print(f"=== {NODE_NAME} 自检 ({'真权重 (paper 运行时)' if use_real else '无权重 stub'}) ===")
    node, rt, applied = _mk_node(use_real)
    print("   数据源:", node.source.info())
    if getattr(node.source, "obs_mode", "") == "synthetic_from_trace":
        print("   ⚠️ 诚实标注: 观测为**合成运动序列** (该 npz 无渲染帧), 不是相机图")

    ok = True
    if not use_real:
        # A) stub: 必须被"防假成功"硬闸拦住
        try:
            node.step()
            print(f"   {FAIL} stub 下居然返回了动作 (防假成功闸失效!)")
            ok = False
        except RuntimeError as e:
            print(f"   {OK} 防假成功闸生效: stub 被拒 → {e}")
        node.close()
        print(f"\n{'✅ 自检通过' if ok else '❌ 自检失败'}")
        return 0 if ok else 1

    # B) 真权重: 真推理判据 = 非零 / 非常量 / 随观测变化
    print(f"   runtime: trained={rt.trained} dims={rt.dims}")
    chunks = []
    t0 = time.perf_counter()
    for i in range(steps):
        out = node.step()
        a = np.asarray(out.chunk)
        chunks.append(a)
        nz = int(np.count_nonzero(a))
        print(f"   step{i + 1}: chunk{a.shape} nonzero={nz} std={a.std():.5f} "
              f"trained={out.trained} diag={out.diagnostics}")
        if nz == 0 or a.std() == 0:
            print(f"   {FAIL} 平零/常量输出 → 非真推理")
            ok = False
    dt = (time.perf_counter() - t0) * 1000.0 / max(1, steps)
    if len(chunks) > 1:
        uniq = sum(1 for i in range(1, len(chunks)) if not np.allclose(chunks[i], chunks[i - 1]))
        print(f"   {OK if uniq else FAIL} 随观测变化: {uniq}/{len(chunks) - 1} 步与上一步不同")
        ok &= uniq > 0
    print(f"   {OK if len(applied) == steps * node.horizon else FAIL} RobotIO 逐步下发: "
          f"{len(applied)} = {steps}×{node.horizon}")
    ok &= (len(applied) == steps * node.horizon)
    print(f"\n   平均单步 {dt:.1f} ms (含 IPC + 模型前向) | 零搜索: "
          f"candidate_sequences={node.diagnostics().get('candidate_sequences')}")
    node.close()
    print(f"\n{'✅ 自检通过' if ok else '❌ 自检失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(use_real="--real" in sys.argv))
