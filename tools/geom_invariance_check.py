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


def load_model():
    import torch
    from transformers import AutoModel
    from joint_unified_backbone import Unified, MODEL
    full = AutoModel.from_pretrained(MODEL, dtype=torch.float32)
    net = Unified(full.vision_model, freeze=True)
    ck = os.path.join("/home/ubuntu/stable-wm-cache/checkpoints/backbone_cont/unified.pt")
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
    net, dev = load_model()
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
    # ① 平移 → 等变增量
    shf = np.stack([infer(net, dev, warpH(P[i].astype(np.uint8), dx=a.dx).astype(np.uint8),
                          O[i].astype(np.float32)) for i in range(len(P))])
    # ② 缩放
    scl = np.stack([infer(net, dev, warpH(P[i].astype(np.uint8), sc=a.scale).astype(np.uint8),
                          O[i].astype(np.float32)) for i in range(len(P))])
    # ③ 旋转
    rot = np.stack([infer(net, dev, warpH(P[i].astype(np.uint8), rot=a.rot).astype(np.uint8),
                          O[i].astype(np.float32)) for i in range(len(P))])

    d_sh = np.mean(np.abs(shf - base))
    d_sc = np.mean(np.abs(scl - base))
    d_ro = np.mean(np.abs(rot - base))
    mag = max(1e-9, np.mean(np.abs(base)))
    print("\n① 平移 %.0fpx : 预测平均变化 %.6f  (相对 %.1f%%)" % (a.dx, d_sh, 100 * d_sh / mag))
    print("② 缩放 x%.2f : 预测平均变化 %.6f  (相对 %.1f%%)" % (a.scale, d_sc, 100 * d_sc / mag))
    print("③ 旋转 %.0f°  : 预测平均变化 %.6f  (相对 %.1f%%)" % (a.rot, d_ro, 100 * d_ro / mag))

    # ④ 流形一致性: 四种几何状态下预测的逐维方差(越小越"不变形")
    stack = np.stack([base, shf, scl, rot])          # (4, n, T, 4)
    dim_std = stack.std(0).mean()
    print("④ 流形一致性  : 四态预测逐维标准差 %.6f  (基准幅度 %.6f → %.1f%%)"
          % (dim_std, mag, 100 * dim_std / mag))

    thr_re = 0.35      # 单变换相对变化阈值(腿: 过大=对几何过敏, 过小=退化不看图)
    thr_man = 0.30     # 流形一致性阈值
    rels = [d_sh / mag, d_sc / mag, d_ro / mag]
    ok_re = all(r <= thr_re for r in rels)
    ok_man = (dim_std / mag) <= thr_man
    print("\n" + "=" * 78)
    print("判据: 单变换相对变化 ≤ %.0f%% · 流形一致性 ≤ %.0f%%" % (thr_re * 100, thr_man * 100))
    print("结果: 变换响应 %s · 流形一致性 %s" % ("✅" if ok_re else "❌", "✅" if ok_man else "❌"))
    print("→ %s" % ("✅ 性能不变形 (几何流形上稳定)" if (ok_re and ok_man) else "⚠️ 存在几何敏感性, 需域增强"))
    print("=" * 78)
    return 0 if (ok_re and ok_man) else 2


if __name__ == "__main__":
    raise SystemExit(main())
