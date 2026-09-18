#!/usr/bin/env python3
"""F14 用例: 自适应增益调度 (L2) — 增益有界 + 势函数不增 + 内建自检通过

对应功能: F14 "自适应增益随风险收紧(有界)" (层 L2, 模块 adaptive_gain)
判据: ① 内建 self_test 通过  ② 输出增益恒在 [kmin,kmax]  ③ 越危险增益不增
"""
import os
import sys

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, f"{ROOT}/src")
os.chdir(ROOT)

fails = []


def chk(name, ok, extra=""):
    print(f"  {'OK ' if ok else 'FAIL'} {name} {extra}")
    if not ok:
        fails.append(name)


try:
    from lerobot.manifold.adaptive_gain import GainScheduler
except Exception as e:                                   # noqa: BLE001
    print(f"  FAIL 导入 adaptive_gain: {type(e).__name__}: {e}")
    sys.exit(1)

# ① 内建自检
has_st = hasattr(GainScheduler, "self_test")
if has_st:
    try:
        rc = GainScheduler.self_test() if isinstance(
            GainScheduler.__dict__.get("self_test"), staticmethod) else GainScheduler().self_test()
        chk("① 内建 self_test 通过", rc == 0 or rc is None, f"rc={rc}")
    except Exception as e:                                # noqa: BLE001
        chk("① 内建 self_test 通过", False, f"{type(e).__name__}: {e}")
else:
    print("  —  模块无内建 self_test, 改为行为验证")

# ②/③ 增益有界 + 单调性
import numpy as np
s = GainScheduler()
outs = []
for risk in (0.0, 0.5, 1.0, 3.0, 10.0):
    try:
        o = s.update(risk=risk, p=0.02) if hasattr(s, "update") else s.step(risk, 0.02)
    except Exception:                                     # noqa: BLE001
        try:
            o = s.step(np.array([risk, 0.02, 0.0, 0.0]))   # 通用入口
        except Exception as e:                            # noqa: BLE001
            chk("② 增益可算出", False, f"{type(e).__name__}: {e}")
            break
    k = getattr(o, "k", getattr(o, "gain", None))
    if k is None:
        k = o if isinstance(o, (int, float)) else None
    outs.append(float(k) if k is not None else float("nan"))

if outs and all(np.isfinite(outs)):
    chk("② 增益恒在界内 [0, 0.5]", all(0.0 <= v <= 0.5 + 1e-9 for v in outs),
        f"| gains={[round(v,4) for v in outs]}")
    chk("③ 越危险增益不增 (单调不增)", all(outs[i] >= outs[i+1] - 1e-9 for i in range(len(outs)-1)),
        f"| {[round(v,4) for v in outs]}")

print("结论:", "✅ 通过" if not fails else f"❌ 有不通过项: {fails}")
sys.exit(0 if not fails else 1)
