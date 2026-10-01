#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_train.py — 用 gsplat 从「已知真值位姿」数据集训练 3DGS 环境资产 (Z-MAX)

为什么不用 COLMAP: 臂上相机随臂动 = 每个视角都有 50Hz TCP 真值 + 手眼(残差 0.06mm) ⇒
外参是**算出来的**不是 SfM 解出来的; 省掉整条最脆的链。

输入: tools/gs_dataset.py 产出的 cameras.json (convention=T_cam2world, OpenCV 光学系) + images/
输出: <out>/gs.ply (真尺度) · <out>/gs.splat (网页查看器用) · <out>/renders/*.png (留出视角)
      <out>/train_report.json (步数/高斯数/PSNR/耗时/归一化参数)

用法: ~/gs-venv/bin/python tools/gs_train.py --data <数据集目录> --out <输出目录> \
        [--steps 15000] [--sh-degree 2] [--eval-every 2000] [--smoke 200]
"""
from __future__ import annotations
import argparse, json, math, os, sys, time

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


# ── 极简 SSIM (3DGS 原版口径: 11x11 高斯窗, 0.8*L1 + 0.2*(1-SSIM)) ──
def _ssim(x, y, window_size=11, size_average=True):
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ch = x.shape[1]
    coords = torch.arange(window_size, dtype=x.dtype, device=x.device) - window_size // 2
    g = torch.exp(-(coords ** 2) / (2 * 1.5 ** 2))
    g = (g / g.sum()).unsqueeze(0)
    w = (g.t() @ g).unsqueeze(0).unsqueeze(0).repeat(ch, 1, 1, 1)
    pad = window_size // 2
    mu1 = F.conv2d(x, w, padding=pad, groups=ch)
    mu2 = F.conv2d(y, w, padding=pad, groups=ch)
    s11 = F.conv2d(x * x, w, padding=pad, groups=ch) - mu1 ** 2
    s22 = F.conv2d(y * y, w, padding=pad, groups=ch) - mu2 ** 2
    s12 = F.conv2d(x * y, w, padding=pad, groups=ch) - mu1 * mu2
    ssim = ((2 * mu1 * mu2 + c1) * (2 * s12 + c2)) / ((mu1 ** 2 + mu2 ** 2 + c1) * (s11 + s22 + c2))
    return ssim.mean()


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 99.0 if mse <= 1e-12 else -10.0 * math.log10(mse)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="数据集目录(含 cameras.json 与 images/)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=15000)
    ap.add_argument("--sh-degree", type=int, default=2)
    ap.add_argument("--eval-every", type=int, default=2000)
    ap.add_argument("--holdout", type=int, default=20, help="留出视角数(从数据里每隔 k 取一个)")
    ap.add_argument("--init-points", type=int, default=100000)
    ap.add_argument("--smoke", type=int, default=0, help=">0 时只跑这么多步(冒烟测试)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed); np.random.seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    import gsplat
    from gsplat.strategy import DefaultStrategy
    print("torch %s · cuda=%s (%s) · gsplat %s" % (torch.__version__, torch.cuda.is_available(),
          torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-", gsplat.__version__))

    cj = json.load(open(os.path.join(a.data, "cameras.json"), encoding="utf-8"))
    W, H = int(cj["width"]), int(cj["height"])
    K = torch.tensor(cj["K"], dtype=torch.float32, device=dev).unsqueeze(0)
    frames = cj["frames"]
    print("数据集: %d 帧 %dx%d · convention=%s" % (len(frames), W, H, cj["convention"]))

    # 位姿: viewmat = inv(T_cam2world) (world→cam); 场景归一化(3DGS 学习率按归一化尺度给)
    # ⚠️ 2026-10-01 真跑踩到: tr/te 原来直接拿 cameras.json 的原始 frame 字典, 里面**没有 R**(只有 T_cam2world),
    #    render() 里 c["R"] 直接 KeyError。⇒ 先把每个视角富化成统一结构(必须**在建 tr/te 之前**), 只用富化对象。
    cams = []
    for f in frames:
        T = np.array(f["T_cam2world"], dtype=np.float64)
        R, t = T[:3, :3], T[:3, 3]
        cams.append({"file": f["file"], "src": f.get("src"), "R": R, "t": t, "T": T})

    # 留出视角: 每 step 取一个, 不参与训练(评估泛化)
    step_h = max(2, len(frames) // max(1, a.holdout))
    hold = set(range(0, len(frames), step_h))
    tr = [c for i, c in enumerate(cams) if i not in hold]
    te = [c for i, c in enumerate(cams) if i in hold]
    print("训练 %d 视角 · 留出 %d 视角" % (len(tr), len(te)))
    centers = np.array([c["t"] for c in cams])
    center = centers.mean(0)
    spread = np.abs(centers - center).max()
    S = 1.0 / max(1e-6, spread)                      # world → 归一化系:  x' = S*(x - center)
    print("场景归一化: center=%s spread=%.4fm S=%.3f" % (np.round(center, 4), spread, S))

    def viewmat_of(c):
        Tn = np.eye(4)
        Tn[:3, :3] = c["R"]
        Tn[:3, 3] = S * (c["t"] - center)
        return torch.tensor(np.linalg.inv(Tn), dtype=torch.float32, device=dev)

    # 初值点云: 相机前向 0.28m 之外的中位视点周围, 尺寸按相机跨度(无 COLMAP 点云时的常规替代)
    fwd = np.array([c["R"] @ np.array([0, 0, 1.0]) for c in cams])   # OpenCV 光学系 z 前
    look = centers + 0.28 * fwd
    lc = look.mean(0) - center                                        # 归一化系里的场景中心
    sz = np.array([0.30, 0.30, 0.20]) * S
    N = a.init_points
    means = torch.tensor(np.random.uniform(-sz / 2, sz / 2, size=(N, 3)) + lc, dtype=torch.float32, device=dev)
    scales = torch.log(torch.full((N, 3), 0.01 * S, device=dev))
    quats = torch.zeros((N, 4), device=dev); quats[:, 0] = 1.0
    opac = torch.logit(torch.full((N,), 0.1, device=dev))
    sh_dim = (a.sh_degree + 1) ** 2
    colors = torch.zeros((N, sh_dim, 3), device=dev)
    C0 = 0.28209479177387814
    colors[:, 0, :] = (torch.tensor([0.5, 0.5, 0.5], device=dev) - 0.5) / C0
    print("初值: %d 个高斯 · SH 阶 %d (dim %d)" % (N, a.sh_degree, sh_dim))

    params = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(means), "scales": torch.nn.Parameter(scales),
        "quats": torch.nn.Parameter(quats), "opacities": torch.nn.Parameter(opac),
        "sh0": torch.nn.Parameter(colors[:, :1, :].contiguous()),
        "shN": torch.nn.Parameter(colors[:, 1:, :].contiguous()),
    }).to(dev)
    scene_scale = float(S * 0.5)
    lrs = {"means": 1.6e-4 * scene_scale, "scales": 5e-3, "quats": 1e-3,
           "opacities": 5e-2, "sh0": 2.5e-3, "shN": 2.5e-3 / 20}
    opts = {k: torch.optim.Adam([{"params": [params[k]], "lr": v}], betas=(0.9, 0.999)) for k, v in lrs.items()}
    strategy = DefaultStrategy(verbose=True)
    strat_state = strategy.initialize_state(scene_scale=scene_scale)

    # 图像: 常驻内存(uint8), 每步搬一张上卡
    def load(f):
        im = Image.open(os.path.join(a.data, "images", f["file"])).convert("RGB")
        return torch.tensor(np.asarray(im), dtype=torch.uint8, device=dev).float().div_(255.0)

    def render(camsub, sh_flag=True):
        vm = viewmat_of(camsub).unsqueeze(0)
        col = torch.cat([params["sh0"], params["shN"]], dim=1)
        img, alpha, info = gsplat.rasterization(
            params["means"], params["quats"], params["scales"], torch.sigmoid(params["opacities"]),
            col, viewmats=vm, Ks=K, width=W, height=H, sh_degree=(a.sh_degree if sh_flag else None),
            # 🔧 2026-10-01: 不传 backgrounds —— gsplat 要求 (B,H,W,C), 传错会
            #   "assert backgrounds.shape == image_dims + (channels,)"。不传=按 alpha 在黑底合成,
            #   是 3DGS 标准做法(训练用 L1+alpha 合成, 不受底色影响)。
            packed=True, near_plane=0.01)
        return img[0].permute(2, 0, 1).clamp(0, 1), info

    @torch.no_grad()
    def evaluate():
        ps = []
        for c in te[:min(8, len(te))]:
            im = load(c).permute(2, 0, 1)
            out, _ = render(c)
            ps.append(psnr(out, im))
        return float(np.mean(ps)) if ps else 0.0

    steps = a.smoke or a.steps
    os.makedirs(os.path.join(a.out, "renders"), exist_ok=True)
    t0 = time.time(); log = []
    for step in range(1, steps + 1):
        c = tr[np.random.randint(len(tr))]
        gt = load(c).permute(2, 0, 1)
        out, info = render(c)
        if strategy.absgrad:
            info["means2d"].retain_grad()
        l1 = (out - gt).abs().mean()
        loss = 0.8 * l1 + 0.2 * (1.0 - _ssim(out.unsqueeze(0), gt.unsqueeze(0)))
        strategy.step_pre_backward(params, opts, strat_state, step, info)
        loss.backward()
        strategy.step_post_backward(params, opts, strat_state, step, info, packed=True)
        for o in opts.values():
            o.step(); o.zero_grad(set_to_none=True)
        if step % 200 == 0 or step == steps:
            msg = "[%5d/%d] loss %.4f (L1 %.4f) · 高斯 %d · %.1fs" % (
                step, steps, float(loss), float(l1), params["means"].shape[0], time.time() - t0)
            print(msg, flush=True); log.append(msg)
        if a.eval_every and (step % a.eval_every == 0 or step == steps):
            print("   ↳ 留出视角 PSNR = %.2f dB" % evaluate(), flush=True)

    # 导出: 反归一化回真尺度(base_link, 米)
    with torch.no_grad():
        m = (params["means"] / S) + torch.tensor(center, dtype=torch.float32, device=dev)
        sc = params["scales"].exp() / S
        q = F.normalize(params["quats"], dim=-1)
        op = torch.sigmoid(params["opacities"])
        sh0 = params["sh0"].detach(); shN = params["shN"].detach()
    ply = os.path.join(a.out, "gs.ply"); splat = os.path.join(a.out, "gs.splat")
    gsplat.export_splats(means=m, scales=sc, quats=q, opacities=op, sh0=sh0, shN=shN, format="ply", save_to=ply)
    gsplat.export_splats(means=m, scales=sc, quats=q, opacities=op, sh0=sh0, shN=shN, format="splat", save_to=splat)
    # 留出视角渲图存档
    for i, c in enumerate(te[:6]):
        with torch.no_grad():
            out, _ = render(c)
        Image.fromarray((out.permute(1, 2, 0).cpu().numpy() * 255).astype(np.uint8)).save(
            os.path.join(a.out, "renders", "holdout_%02d.png" % i))
        Image.open(os.path.join(a.data, "images", c["file"])).save(
            os.path.join(a.out, "renders", "holdout_%02d_gt.png" % i))
    rep = {"data": a.data, "steps": steps, "sh_degree": a.sh_degree, "n_gaussians": int(params["means"].shape[0]),
           "psnr_holdout_db": evaluate(), "seconds": time.time() - t0, "normalize": {"center": list(center), "S": S},
           "ply": ply, "splat": splat, "log_tail": log[-6:], "device": dev}
    json.dump(rep, open(os.path.join(a.out, "train_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 训练完成 · 高斯 %d · 留出 PSNR %.2f dB · %.1fs" % (rep["n_gaussians"], rep["psnr_holdout_db"], rep["seconds"]))
    print("   ply=%s\n   splat=%s" % (ply, splat))
    return 0


if __name__ == "__main__":
    sys.exit(main())
