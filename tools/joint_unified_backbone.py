#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧬 统一 backbone 联合训练 —— 共享预训练视觉主干 (SmolVLM2 SigLIP 768d) + 四头

老倪 2026-09-23: "能进行统一 backbone 改造么?"

与之前"投影拼接"的本质区别:
  之前: L4 的 from-scratch ViT-tiny(192) 当主干, 各层套投影头 → 主干弱、无预训练
        → 留出集必然过拟合 (已实测 2.5×~34× 劣化)
  现在: **一个预训练 SigLIP 主干 (768维)** 同时喂四个任务头
        L2 检测反馈 / L3 状态调度 / L4 认知预测 / L5 场景token
        → 共享视觉表征 → 真端到端联合

用法:
  python tools/joint_unified_backbone.py --steps 3000 --holdout <h5> --files a.h5,b.h5
"""
import argparse
import json
import os
import sys
import time

import h5py
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
SWM = "/home/ubuntu/stable-wm-cache"
MODEL = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
IMGSZ = 224


class RealH5(torch.utils.data.Dataset):
    """真数据: pixels/observation/action。返回 (obs, act, pix224)"""

    _PIX_CACHE = None       # 类级: fork 前加载 → 所有 worker 共享 (COW)

    def __init__(self, files, chunk=7):
        self.f = [h5py.File(p, "r") for p in files]
        self.off = np.cumsum([0] + [int(x["observation"].shape[0]) for x in self.f])
        self.chunk = chunk

    @classmethod
    def build_pixel_cache(cls, files, cap_bytes=14 * 1024**3):
        """把所有像素读进内存 (uint8)。h5 分块 512 帧 → 随机取 1 帧要解压 75MB, 这是真瓶颈。"""
        tot = sum(int(h5py.File(p, "r")["pixels"].shape[0]) for p in files)
        per = int(h5py.File(files[0], "r")["pixels"][0].nbytes) if tot else 0
        need = tot * per
        if need > cap_bytes:
            print(f"  ⚠️ 像素缓存需 {need/1024**3:.1f}GB > 上限 {cap_bytes/1024**3:.0f}GB → 跳过缓存")
            return None
        print(f"  载入像素缓存: {tot:,} 帧 × {per/1024:.0f}KB = {need/1024**3:.1f}GB ...", flush=True)
        arr = np.empty((tot,) + tuple(h5py.File(files[0], "r")["pixels"].shape[1:]), dtype=np.uint8)
        o = 0
        for p in files:
            fh = h5py.File(p, "r")
            n = int(fh["pixels"].shape[0])
            for s in range(0, n, 8192):
                e = min(n, s + 8192)
                arr[o + s:o + e] = fh["pixels"][s:e]      # 顺序读, 块利用率 100%
            o += n
            fh.close()
        cls._PIX_CACHE = arr
        print(f"  ✅ 像素缓存就绪 ({arr.nbytes/1024**3:.1f}GB, 供所有 worker 共享)")
        return arr

    def __len__(self):
        return int(self.off[-1])

    def __getitem__(self, i):
        gi = i
        for k in range(len(self.f)):
            if gi < self.off[k + 1]:
                f, j = self.f[k], gi - self.off[k]
                break
        else:
            f, j = self.f[-1], int(self.off[-1] - self.off[-2]) - 1
        N = int(f["observation"].shape[0])
        obs = np.asarray(f["observation"][j], dtype=np.float32)
        px = (RealH5._PIX_CACHE[gi] if RealH5._PIX_CACHE is not None
              else np.asarray(f["pixels"][j], dtype=np.uint8))
        # ★ 真未来目标: 下一帧观测 + 未来 chunk 步动作 (跳过样本末尾越界)
        jn = min(j + 1, N - 1)
        obs_next = np.asarray(f["observation"][jn], dtype=np.float32)
        jc = [min(j + k, N - 1) for k in range(self.chunk)]
        act_chunk = np.stack([np.asarray(f["action"][q], dtype=np.float32) for q in jc])  # (chunk, 4)
        return obs, act_chunk, px, obs_next


def to_img(px):
    """(B,H,W,3) uint8 [0,255]（ndarray 或 Tensor）→ 归一化 (B,3,IMGSZ,IMGSZ) float"""
    x = px if torch.is_tensor(px) else torch.from_numpy(np.asarray(px))
    x = x.float() / 255.0
    if x.shape[-1] == 3:
        x = x.permute(0, 3, 1, 2)
    if x.shape[-1] != IMGSZ or x.shape[-2] != IMGSZ:
        x = F.interpolate(x, size=(IMGSZ, IMGSZ), mode="bilinear", align_corners=False)
    mean = torch.tensor([0.5, 0.5, 0.5], device=x.device).view(1, 3, 1, 1)
    std = torch.tensor([0.5, 0.5, 0.5], device=x.device).view(1, 3, 1, 1)
    return (x - mean) / std


class Unified(nn.Module):
    """共享 SigLIP 主干 + 四头"""

    def __init__(self, trunk, d=768, obs_dim=39, act_dim=4, chunk=7, mem_dim=13, freeze=1):
        super().__init__()
        self.trunk = trunk
        for p in self.trunk.parameters():
            p.requires_grad_(not freeze)

        # L4 认知预测: 视觉特征 + obs → 世界模型 (预测下一观测)
        self.l4_fuse = nn.Sequential(nn.Linear(d + obs_dim, 512), nn.SiLU(), nn.Linear(512, 256))
        self.l4_pred_obs = nn.Linear(256, obs_dim)          # 认知预测: 下一帧观测
        self.l4_z = nn.Linear(256, 192)                     # 世界模型潜变量

        # L3 状态调度: 潜变量 + 记忆 → 动作块
        self.l3_mem = nn.Sequential(nn.Linear(mem_dim, 64), nn.SiLU(), nn.Linear(64, 192))
        self.l3 = nn.Sequential(nn.Linear(192 + 64, 256), nn.SiLU(), nn.Linear(256, chunk * act_dim))

        # L2 检测反馈: 视觉特征 → 目标 token + 反馈一致性
        self.l2_det = nn.Sequential(nn.Linear(d, 256), nn.SiLU(), nn.Linear(256, 64))
        self.l2_cons = nn.Linear(64, 192)

        # L5 场景 token: 视觉特征 → 场景摘要 (供上层)
        self.l5_scene = nn.Sequential(nn.Linear(d, 256), nn.SiLU(), nn.Linear(256, 64))

        self.chunk, self.act_dim = chunk, act_dim
        self.obs_dim = obs_dim

    def forward(self, img, obs, act, mem):
        # 共享主干 (预训练 SigLIP)
        f = self.trunk(pixel_values=img).last_hidden_state          # (B, N, 768)
        g = f[:, 0, :]                                              # CLS
        gp = f.mean(1)                                              # mean-pool (更稳)

        # L4 认知预测
        h = self.l4_fuse(torch.cat([gp, obs], -1))
        obs_hat = self.l4_pred_obs(h)                               # 预测下一观测
        z = self.l4_z(h)

        # L2 检测反馈
        det = self.l2_det(gp)
        z_l2 = self.l2_cons(det)

        # L5 场景 token
        scene = self.l5_scene(gp)

        # L3 状态调度 (记忆注入)
        zt = z + self.l3_mem(mem)
        u = self.l3(torch.cat([zt, scene], -1)).view(-1, self.chunk, self.act_dim)
        u = torch.tanh(u)                                           # 结构限幅

        return {"obs_hat": obs_hat, "z": z, "z_l2": z_l2, "u": u, "scene": scene}


def make_loader(files, bs, workers, chunk=7):
    ds = RealH5(files, chunk)
    return torch.utils.data.DataLoader(ds, batch_size=bs, shuffle=True, num_workers=workers,
                                       pin_memory=True, drop_last=True, persistent_workers=workers > 0)


def eval_holdout(model, files, dev, limit=768, chunk=7):
    """留出集: 返 L4认知预测 MAE / L3动作 MAE / 场景一致性"""
    model.eval()
    fh = h5py.File(files[0], "r")
    Nt = int(fh["observation"].shape[0])
    n = min(Nt - 1, limit)
    idx = np.sort(np.random.default_rng(11).choice(Nt - 1, n, replace=False))
    # ★ 整块读 (h5py 有序索引一次到位, 比逐样本快几十倍)
    o = np.asarray(fh["observation"][idx], dtype=np.float32)
    px = np.asarray(fh["pixels"][idx], dtype=np.uint8)
    nxt = np.asarray(fh["observation"][idx + 1], dtype=np.float32)
    jc = np.stack([np.minimum(idx + k, Nt - 1) for k in range(chunk)], 1)   # (n, chunk)
    Nc = int(fh["action"].shape[0])
    jc = np.minimum(jc, Nc - 1)
    lo, hi = int(jc.min()), int(jc.max())
    _blk = np.asarray(fh["action"][lo:hi + 1], dtype=np.float32)            # 连续块读
    a = _blk[jc - lo]                                                       # (n, chunk, 4)
    fh.close()
    mem = torch.zeros(n, 13)
    e_obs = e_act = 0.0
    cnt = 0
    with torch.no_grad():
        for s in range(0, n, 96):
            ob = torch.from_numpy(o[s:s + 96]).to(dev)
            ac = torch.from_numpy(a[s:s + 96]).to(dev)   # (b, chunk, 4)
            img = to_img(px[s:s + 96]).to(dev)
            m = mem[s:s + 96].to(dev)
            out = model(img, ob, ac, m)
            # L4 认知预测: 预测"下一帧观测"(用相邻帧近似目标)
            tgt = torch.from_numpy(nxt[s:s + 96]).to(dev)                       # 真未来观测
            e_obs += F.l1_loss(out["obs_hat"], tgt).item() * tgt.shape[0]
            u_tgt = ac[:, :out["u"].shape[1], :]                                 # 真未来动作块
            e_act += F.l1_loss(out["u"], u_tgt).item() * tgt.shape[0]
            cnt += tgt.shape[0]
    model.train()
    return e_obs / max(cnt, 1), e_act / max(cnt, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--wd", type=float, default=0.01)
    ap.add_argument("--chunk", type=int, default=7)
    ap.add_argument("--freeze-trunk", type=int, default=1, help="1=冻结预训练主干(默认,保护特征)")
    ap.add_argument("--files", default=f"{SWM}/datasets/optical_insert_v6_disturb.h5")
    ap.add_argument("--holdout", default="")
    ap.add_argument("--stats", type=int, default=250)
    ap.add_argument("--save", default="")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pixel-cache", type=int, default=1, help="1=像素进内存(消除h5随机读瓶颈)")
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    np.random.seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cuda":
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True

    files = [x for x in a.files.split(",") if x]
    print(f"🧬 统一 backbone 联合训练 (共享 SigLIP 768d + 四头)")
    print(f"   数据: {len(files)} 个 h5 · {sum(int(h5py.File(x,'r')['observation'].shape[0]) for x in files):,} 帧")
    print(f"   留出: {a.holdout or '(无)'} · device {dev} · 冻结主干={bool(a.freeze_trunk)}")

    from transformers import AutoModel
    full = AutoModel.from_pretrained(MODEL, dtype=torch.float32)
    trunk = full.vision_model
    del full
    model = Unified(trunk, freeze=a.freeze_trunk).to(dev)
    n_tr = sum(p.numel() for p in model.trunk.parameters())
    n_hd = sum(p.numel() for p in model.parameters()) - n_tr
    print(f"   主干 {n_tr/1e6:.1f}M ({'冻结' if a.freeze_trunk else '可训'}) · 四头 {n_hd/1e6:.2f}M")

    if a.pixel_cache:
        RealH5.build_pixel_cache(files)          # ★ 必须在建 DataLoader(fork) 之前
    dl = make_loader(files, a.batch, a.workers, a.chunk)
    it = iter(dl)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=a.wd)
    HO = ([a.holdout] if a.holdout and os.path.isfile(a.holdout) else None)
    best = [float("inf"), -1]
    t0 = time.time()
    model.train()
    for s in range(1, a.steps + 1):
        try:
            obs, actc, px, obs_next = next(it)
        except StopIteration:
            it = iter(dl)
            obs, actc, px, obs_next = next(it)
        obs = obs.to(dev, non_blocking=True)
        img = to_img(px).to(dev, non_blocking=True)
        mem = torch.zeros(obs.shape[0], 13, device=dev)
        out = model(img, obs, actc, mem)

        # 联合损失 (目标 = 真未来, 不是 roll)
        L_obs = F.mse_loss(out["obs_hat"], obs_next.to(dev, non_blocking=True))   # L4 认知预测
        u_tgt = actc.to(dev, non_blocking=True)[:, :out["u"].shape[1], :]         # (B,chunk,4)
        L_act = F.mse_loss(out["u"], u_tgt)                                       # L3 状态调度
        L_l2 = F.mse_loss(out["z_l2"], out["z"].detach())            # L2 反馈一致性
        L = L_obs + L_act + 0.1 * L_l2

        opt.zero_grad(set_to_none=True)
        L.backward()
        gn = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
        opt.step()

        if s % a.stats == 0 or s == 1:
            sps = s / max(1e-6, time.time() - t0)
            ho = ""
            if HO:
                mo, ma = eval_holdout(model, HO, dev, chunk=a.chunk)
                if mo < best[0]:
                    best[:] = [mo, s]
                    if a.save:
                        os.makedirs(a.save, exist_ok=True)
                        torch.save(model.state_dict(), os.path.join(a.save, "unified.pt"))
                ho = f" | 留出 L4预测 {mo:.3f} 动作 {ma:.3f} (best {best[0]:.3f}@{best[1]})"
            gpu = torch.cuda.max_memory_allocated() / 1048576 if dev == "cuda" else 0
            print(f"  step {s:6d}/{a.steps} | loss {L.item():.4f} L4 {L_obs.item():.4f} "
                  f"L3 {L_act.item():.4f} | ∇ {float(gn):.2e} | {sps:.1f}步/s | {gpu:.0f}MB{ho}", flush=True)

    print(f"✅ 完成 {a.steps} 步 / {time.time()-t0:.0f}s")
    if a.save:
        print(f"产物 → {a.save}/unified.pt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
