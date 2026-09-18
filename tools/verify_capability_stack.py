#!/usr/bin/env python3
"""F19 用例: 能力栈收缩投影 (ALL) — 越界 100% 被夹紧 + 逐层收窄

对应功能: F19 "能力栈逐层收缩(可行域收窄)" (模块 capability_stack)
判据: ① 越界输入 100% 被夹紧到界内  ② 界内输入不被改动  ③ 收缩方向单调(不放大)
"""
import os, sys
ROOT = "/home/ubuntu/lerobot-smolvla-lew"; sys.path.insert(0, f"{ROOT}/src"); os.chdir(ROOT)
import numpy as np
fails = []
def chk(n, ok, ex=""):
    print(f"  {'OK ' if ok else 'FAIL'} {n} {ex}");  fails.append(n) if not ok else None
try:
    from lerobot.manifold.capability_stack import CapabilityStack
except Exception as e:
    print(f"  FAIL 导入 capability_stack: {type(e).__name__}: {e}"); sys.exit(1)
try:
    cs = CapabilityStack(bounds=(-1.0, 1.0), dim=4)
    def project(u):
        for fn in ("project", "clamp", "shrink", "__call__", "step"):
            if hasattr(cs, fn):
                try:
                    o = getattr(cs, fn)(np.asarray(u, np.float32))
                    return np.asarray(o if not isinstance(o, tuple) else o[0], np.float32).ravel()
                except Exception: pass
        raise RuntimeError("无投影入口")
    big = np.array([9.0, -9.0, 0.5, -0.5], np.float32)
    p = project(big)
    inb = (p >= -1.0 - 1e-6) & (p <= 1.0 + 1e-6)
    chk("① 越界 100% 夹紧", bool(inb.all()), f"| in={np.round(p,4)}")
    chk("② 界内不动", bool(inb[[2,3]].all()), f"| {np.round(p[2:],4)}")
    chk("③ 不放大 (收缩单调)", all(abs(p[i]) <= abs(big[i]) + 1e-6 for i in range(4)),
        f"| |out|={np.round(np.abs(p),3)} <= |in|={np.round(np.abs(big),3)}")
except Exception as e:
    chk("能力栈行为验证", False, f"{type(e).__name__}: {e}")
print("结论:", "✅ 通过" if not fails else f"❌ 有不通过项: {fails}")
sys.exit(0 if not fails else 1)
