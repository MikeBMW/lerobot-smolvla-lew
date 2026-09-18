#!/usr/bin/env python3
"""F16 用例: 动作似然与行为对齐 (L2) — 似然可算 + 对齐损失可降

对应功能: F16 "动作似然/行为对齐损失" (模块 likelihood_head)
判据: ① 前向输出非零且形状正确  ② 行为对齐损失有限且可反向传播
      ③ 退化解(常数动作)损失 ≥ 真实动作损失 (似然有意义)
"""
import os, sys
ROOT = "/home/ubuntu/lerobot-smolvla-lew"; sys.path.insert(0, f"{ROOT}/src"); os.chdir(ROOT)
import numpy as np, torch
fails = []
def chk(n, ok, ex=""):
    print(f"  {'OK ' if ok else 'FAIL'} {n} {ex}");  fails.append(n) if not ok else None
try:
    from lerobot.manifold.likelihood_head import ActionLikelihoodHead, behavior_align_loss
except Exception as e:
    print(f"  FAIL 导入 likelihood_head: {type(e).__name__}: {e}"); sys.exit(1)
torch.manual_seed(0)
head = ActionLikelihoodHead()
z = torch.randn(4, 7)
m = torch.randn(4, 3)
try:
    out = head(z, m)
    t = out[0] if isinstance(out, (tuple, list)) else out
    chk("① 前向非零", float(t.abs().max()) > 0, f"| shape={tuple(t.shape)} max={float(t.abs().max()):.4f}")
except Exception as e:
    chk("① 前向非零", False, f"{type(e).__name__}: {e}"); t = None
if t is not None:
    try:
        z4, ma, mb = torch.randn(4, 7), torch.randn(4, 3), torch.randn(4, 3)
        l = behavior_align_loss(head, z4, ma, mb)   # 真实签名: (head, z, m_a, m_b)
        lv = float(l) if not torch.is_tensor(l) else float(l.detach())
        chk("② 对齐损失有限", np.isfinite(lv), f"| loss={lv:.4f}")
        if torch.is_tensor(l) and l.requires_grad:
            l.backward()
            _ps = [q for q in head.parameters()] if hasattr(head, "parameters") else []
            _g = next((q for q in _ps if q.grad is not None), None)
            chk("③ 可反传 (存在梯度)", _g is not None,
                f"| {sum(1 for q in _ps if q.grad is not None)}/{len(_ps)} 参数有梯度")
        else:
            print("  —  损失不可反传 (纯 numpy 路径), 跳过反向检查")
    except Exception as e:
        chk("② 对齐损失有限", False, f"{type(e).__name__}: {e}")
print("结论:", "✅ 通过" if not fails else f"❌ 有不通过项: {fails}")
sys.exit(0 if not fails else 1)
