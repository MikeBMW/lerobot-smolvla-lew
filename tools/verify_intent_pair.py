#!/usr/bin/env python3
"""F15 用例: 共享空间意图编码 (L2/L4 桥) — 两态同算子 + 前向都产动作

对应功能: F15 "共享意图编码(结构共享, 非对称梯度)" (模块 intent_pair)
真实接口: SharedIntentEncoder(z_t, m, kind="local"|"goal") → 4D 动作
判据: ① local 前向非零  ② goal 前向也非零(不为目标置零)  ③ goal 路径标 stop_grad
      ④ 同一算子处理两态(结构共享, 非两套网络)
"""
import os, sys
ROOT = "/home/ubuntu/lerobot-smolvla-lew"; sys.path.insert(0, f"{ROOT}/src"); os.chdir(ROOT)
import numpy as np
fails = []
def chk(n, ok, ex=""):
    print(f"  {'OK ' if ok else 'FAIL'} {n} {ex}")
    if not ok: fails.append(n)
try:
    from lerobot.manifold.intent_pair import SharedIntentEncoder, ManifoldIntentPair
except Exception as e:
    print(f"  FAIL 导入 intent_pair: {type(e).__name__}: {e}"); sys.exit(1)
enc = SharedIntentEncoder()
z_t = np.zeros(6, np.float32)
m = np.array([0.10, 0.20, 0.30], np.float32)      # 意图向量 R³
try:
    u_loc = np.asarray(enc(z_t, m, kind="local"), np.float32).ravel()
    chk("① local 前向非零", u_loc.size == 4 and float(np.abs(u_loc[:3]).max()) > 0,
        f"| u={np.round(u_loc,4)}")
    u_goal = np.asarray(enc(z_t, m, kind="goal"), np.float32).ravel()
    chk("② goal 前向也非零 (不置零)", float(np.abs(u_goal[:3]).max()) > 0,
        f"| u={np.round(u_goal,4)}")
    chk("③ goal 路径标记 stop_grad", bool(getattr(enc, "last_stop_grad", False)) is True,
        f"| last_stop_grad={getattr(enc,'last_stop_grad',None)} last_kind={getattr(enc,'last_kind',None)}")
    chk("④ 同一算子两态 (结构共享)", float(np.abs(u_loc - u_goal).max()) < 1e-9,
        f"| Δ(local,goal)={float(np.abs(u_loc-u_goal).max()):.2e} (同算子 → 应相同)")
except Exception as e:
    chk("意图编码可执行", False, f"{type(e).__name__}: {e}")
try:
    pair = ManifoldIntentPair()
    chk("⑤ 流形意图对可实例化", pair is not None, f"| eps={getattr(pair,'eps','?')}")
except Exception as e:
    chk("⑤ 流形意图对可实例化", False, f"{type(e).__name__}: {e}")
print("结论:", "✅ 通过" if not fails else f"❌ 有不通过项: {fails}")
sys.exit(0 if not fails else 1)
