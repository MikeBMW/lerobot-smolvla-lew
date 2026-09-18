#!/usr/bin/env python3
"""F18 用例: 潜空间预测器 (L4) — 前向 + 一致性度量可算

对应功能: F18 "潜空间一步预测 + readout" (模块 predictor_layer)
判据: ① LatentPredictor 前向输出形状正确且非零  ② readout 输出非零
      ③ 一致性度量(cy) 有限
"""
import os, sys
ROOT = "/home/ubuntu/lerobot-smolvla-lew"; sys.path.insert(0, f"{ROOT}/src"); os.chdir(ROOT)
import numpy as np, torch
fails = []
def chk(n, ok, ex=""):
    print(f"  {'OK ' if ok else 'FAIL'} {n} {ex}");  fails.append(n) if not ok else None
try:
    from lerobot.manifold.predictor_layer import LatentPredictor, ManifoldReadout, cy_consistency_loss
except Exception as e:
    print(f"  FAIL 导入 predictor_layer: {type(e).__name__}: {e}"); sys.exit(1)
torch.manual_seed(0)
z = torch.randn(2, 8, 960); a = torch.randn(2, 8, 4)
try:
    pr = LatentPredictor(z_dim=960, act_dim=4)
    out = pr(z, a)
    t = out[0] if isinstance(out, (tuple, list)) else out
    chk("① 预测器前向", t.shape[-1] == 960 and float(t.abs().max()) > 0,
        f"| shape={tuple(t.shape)} max={float(t.abs().max()):.4f}")
except Exception as e:
    chk("① 预测器前向", False, f"{type(e).__name__}: {e}")
try:
    ro = ManifoldReadout(z_dim=960, manifold_dim=6)
    o2 = ro(torch.randn(2, 960))
    t2 = o2[0] if isinstance(o2, (tuple, list)) else o2
    chk("② readout 输出非零", float(t2.abs().max()) > 0, f"| shape={tuple(t2.shape)}")
except Exception as e:
    chk("② readout 输出非零", False, f"{type(e).__name__}: {e}")
try:
    l = cy_consistency_loss(torch.randn(2,960), torch.randn(2,4), torch.randn(2,3),
                            torch.randn(2,960), torch.randn(2,3))
    lv = float(l) if not torch.is_tensor(l) else float(l.detach())
    chk("③ 一致性度量有限", np.isfinite(lv), f"| cy={lv:.4f}")
except Exception as e:
    chk("③ 一致性度量有限", False, f"{type(e).__name__}: {e}")
print("结论:", "✅ 通过" if not fails else f"❌ 有不通过项: {fails}")
sys.exit(0 if not fails else 1)
