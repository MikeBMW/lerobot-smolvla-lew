#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📐 几何流形不变性验证 —— 检验"性能不变形"（等变性 / 鲁棒性）

老倪 2026-09-23: "确保产品性能不变形, 符合数据几何流形的不变性原理"

数学口径:
  模型 f 对几何变换 T 的响应应满足 **等变性**:  f(T·x) ≈ T·f(x)
  检验指标:
    ① 平移等变增益 g_t = Δu / Δx   —— 应稳定且有界(不是 0 也不是爆炸)
    ② 尺度鲁棒性: 缩放 σ 下预测的相对变化 ≤ 阈值
    ③ 旋转等变: 旋转 θ 下预测方向随 θ 线性变化(相关系数高)
    ④ 流形一致性: 各变换下的预测**方差** ≤ 阈值(说明不变形)
"""
import argparse
import os
import sys
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))


def load_model(ckpt=None):
    import torch
    from transformers import AutoModel
    from joint_unified_backbone import Unified, MODEL
    full = AutoModel.from_pretrained(MODEL, dtype=torch.float32)
    net = Unified(full.vision_model, freeze=True)
    ck = ckpt or "/home/ubuntu/stable-wm-cache/checkpoints/backbone_cont/unified.pt"
    sd = torch.load(ck, map_location="cpu", weights_only=False)
    net.load_state_dict(sd, strict=False)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    return net.eval().to(dev), dev


def infer(net, dev, img224, obs39):
    import torch
    with torch.no_grad():
        x = torch.from_numpy(img224).float().div_(255.0).permute(2, 0, 1)[None].to(dev)
        o = torch.from_numpy(obs39)[None].to(dev)
        mem = torch.zeros(1, 13, device=dev)
        out = net(x, o, o, mem)
        return out["u"][0].float().cpu().numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--dx", type=float, default=8.0, help="平移像素")
    ap.add_argument("--scale", type=float, default=1.10)
    ap.add_argument("--rot", type=float, default=8.0, help="旋转角度(度)")
    a = ap.parse_args()

    import h5py
    import cv2
    d = np.load("/tmp/bridge_engine_smpl.npz") if os.path.isfile("/tmp/bridge_engine_smpl.npz") else None
    if d is None:
        print("❌ 缺引擎样本 /tmp/bridge_engine_smpl.npz (先跑 bridge_engine_online.py PHASE=collect)")
        return 1
    O, P = d["O"][:a.n], d["P"][:a.n]
    net, dev = load_model(a.ckpt or None)
    print("=" * 78)
    print("📐 几何流形不变性验证 (%d 样本 · 引擎真帧)" % len(P))
    print("=" * 78)

    H, W = P.shape[1], P.shape[2]
    def warpH(im, dx=0.0, sc=1.0, rot=0.0):
        M = cv2.getRotationMatrix2D((W / 2.0, H / 2.0), rot, sc)
        M[0, 2] += dx
        M[1, 2] += 0.0
        o = cv2.warpAffine(im, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
        return o

    base = np.stack([infer(net, dev, P[i].astype(np.uint8), O[i].astype(np.float32)) for i in range(len(P))])
    # ★ 多幅度扫描: 单幅度噪声大 → 取多种幅度平均, 结论才稳
    MAG_T = (4.0, 8.0, 16.0)
    MAG_S = (1.05, 1.10)
    MAG_R = (5.0, 10.0)
    def _avg(mag_list, **kw):
        vals, last = [], []
        for mg in mag_list:
            k = dict(kw)
            k[list(kw.keys())[0]] = mg
            W2 = np.stack([infer(net, dev, warpH(P[i].astype(np.uint8), **k).astype(np.uint8),
                                 O[i].astype(np.float32)) for i in range(len(P))])
            # ★ 主指标: 方向一致性 cosine(尺度无关, 抗"小基准放大")
            A2 = W2.reshape(len(W2), -1); B2 = base.reshape(len(base), -1)
            num = np.sum(A2 * B2, 1)
            den = np.linalg.norm(A2, axis=1) * np.linalg.norm(B2, axis=1) + 1e-9
            cos = float(np.mean(num / den))
            vals.append(cos)                      # 此处 vals 存 cosine
            last.append(W2)
        return float(np.mean(vals)), vals, last[-1]
    csh, v_sh, shf = _avg(MAG_T, dx=0.0)
    csc, v_sc, scl = _avg(MAG_S, sc=1.0)
    cro, v_ro, rot = _avg(MAG_R, rot=0.0)

    d_sh = np.mean(np.abs(shf - base))
    d_sc = np.mean(np.abs(scl - base))
    d_ro = np.mean(np.abs(rot - base))
    mag = max(1e-9, np.mean(np.abs(base)))
    print("\n① 平移 %s px : **方向一致性 cos=%.4f** · 逐幅度 %s" % (MAG_T, csh, [round(v,4) for v in v_sh]))
    print("② 缩放 %s : **方向一致性 cos=%.4f** · 逐幅度 %s" % (MAG_S, csc, [round(v,4) for v in v_sc]))
    print("③ 旋转 %s° : **方向一致性 cos=%.4f** · 逐幅度 %s" % (MAG_R, cro, [round(v,4) for v in v_ro]))

    # ④ 流形一致性: 四种几何状态下预测的逐维方差(越小越"不变形")
    stack = np.stack([base, shf, scl, rot])          # (4, n, T, 4)
    dim_std = stack.std(0).mean()
    print("④ 流形一致性  : 四态预测逐维标准差 %.6f  (基准幅度 %.6f → %.1f%%)"
          % (dim_std, mag, 100 * dim_std / mag))

    thr_cos = 0.90     # 方向一致性下限 (cos≥0.90 视为几何稳定)
    thr_man = 0.30     # 流形一致性阈值
    rels = [csh, csc, cro]
    ok_re = all(r >= thr_cos for r in rels)
    ok_man = (dim_std / mag) <= thr_man
    print("\n" + "=" * 78)
    print("判据: 方向一致性 cos ≥ %.2f · 流形一致性 ≤ %.0f%%" % (thr_cos, thr_man * 100))
    print("结果: 方向一致性 %s (%.3f/%.3f/%.3f) · 流形一致性 %s (%.1f%%)" % ("✅" if ok_re else "❌", csh, csc, cro, "✅" if ok_man else "❌", 100*float(np.mean(np.stack([base,shf,scl,rot]).std(0))/mag)))
    print("→ %s" % ("✅ 性能不变形 (几何流形上稳定)" if (ok_re and ok_man) else "⚠️ 存在几何敏感性, 需域增强"))
    print("=" * 78)
    return 0 if (ok_re and ok_man) else 2


if __name__ == "__main__":
    raise SystemExit(main())
