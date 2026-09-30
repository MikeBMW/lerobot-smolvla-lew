"""🧠 LEW 闭环控制器插件 — 引擎插入遇阻时用 LEW 世界模型前视修正
加载: models/lew_{tag}.pt (ar + proj + decode)
用法: SS_LEW=transformer|mamba 环境变量 (引擎侧注入, None=不启用)
核心: 遇阻时预测下一帧 z7' → 反解位移 → 修正 u (代替盲目回退)
"""
import os
import numpy as np
import torch
import torch.nn as nn

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LEW = None
_TAG = None


def _load(tag):
    global _LEW, _TAG
    if _LEW is not None and _TAG == tag:
        return _LEW
    import sys
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from lerobot.policies.smolvla_lew.world_model_le import ARPredictor
    ck = torch.load(os.path.join(ROOT, "models", f"lew_{tag}.pt"), map_location="cpu")
    mm = ck.get("mamba_mode")
    ar = ARPredictor(num_frames=2, depth=6, heads=8, mlp_dim=768,
                     input_dim=192, hidden_dim=192, output_dim=192,
                     dim_head=64, mamba_mode=mm)
    ar.load_state_dict(ck["ar"])
    ar.eval()
    proj = nn.Linear(7, 192)
    proj.load_state_dict(ck["proj"])
    proj.eval()
    decode = nn.Linear(192, 7)
    decode.load_state_dict(ck["decode"])
    decode.eval()
    _LEW = {"ar": ar, "proj": proj, "decode": decode}
    _TAG = tag
    return _LEW


def predict_next_z(z_hist, tag=None):
    """z_hist: list of 7D z vectors (需 ≥2) → 预测下一帧 z7'
    返回 np 7D 预测"""
    tag = tag or os.environ.get("SS_LEW", "transformer")
    lew = _load(tag)
    with torch.no_grad():
        zs = torch.from_numpy(np.stack(z_hist[-2:]).astype(np.float32)).unsqueeze(0)  # (1,2,7)
        xe = lew["proj"](zs)
        pred = lew["ar"](xe, xe)[:, -1]
        znext = lew["decode"](pred).squeeze(0).numpy()
    return znext
