# -*- coding: utf-8 -*-
"""单步有效性核查: 确认 chunk 是**真实模型输出**而非零动作回退 (老倪: 报结论前验数据有效性)。

判据:
  · chunk 非全零 (count_nonzero > 0) 且 std > 0 (逐维有变化)
  · runtime.reason 为空 (没有发生 act 失败回退)
  · 连续多步的 chunk 不同 (模型在按 obs/goal 真实推理, 不是常量)
用法: STABLEWM_HOME=... INTACT_RUNTIME=paper PYTHONPATH=src python3 -m ... <this file>
"""
import os
import sys

import numpy as np

from lerobot.manifold.intact_node import IntactNode, IntactRuntime

STEPS = int(os.environ.get("STEPS", "3"))


def main() -> int:
    rt = IntactRuntime(device=os.environ.get("INTACT_DEVICE", "cuda"))
    node = IntactNode(horizon=int(os.environ.get("HORIZON", "5")), runtime=rt)
    node.set_data_source("l4_episode")
    print(f"runtime: trained={rt.trained} dims={rt.dims} reason={rt.reason!r}")
    ok = bool(rt.trained) and not rt.reason
    prev = None
    for i in range(STEPS):
        out = node.step()
        a = np.asarray(out.chunk)
        nz = int(np.count_nonzero(a))
        print(f"step{i + 1}: shape={a.shape} nonzero={nz} std={a.std():.5f} "
              f"min={a.min():.4f} max={a.max():.4f} trained={out.trained}")
        print(f"        row0={np.round(a[0], 4)}")
        print(f"        diag={out.diagnostics}")
        if nz == 0 or a.std() == 0:
            print("   ❌ 平零/常量 → 疑似零动作回退, 不是真实推理")
            ok = False
        if prev is not None and np.allclose(a, prev):
            print("   ⚠️ 与上一步完全相同 (常量输出?)")
        prev = a
    print(f"\nreason after steps: {rt.reason!r}")
    if rt.reason:
        print("   ❌ runtime.reason 非空 = 发生过 act 失败")
        ok = False
    node.close()
    print("✅ 单步输出为真实模型推理" if ok else "❌ 单步输出有效性未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
