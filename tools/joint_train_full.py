#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔥 全负荷联合集训 V6 —— L2检测反馈 ⊗ 记忆 ⊗ L3状态调度 ⊗ L4认知预测 同图 · GPU 打满

老倪 2026-09-23: "L5层继续定方向造数据; L4认知预测; L3状态调度; L2检测反馈; 加大力度集训"
              "模型要一起训练 GPU必须全负荷工作"

与 V5 的区别 (V5 只验证机制, 7s/200步 → GPU 几乎没吃):
  · AMP 混合精度 (autocast+scaler) → 允许大 batch
  · **真实 DataLoader**: h5 内存映射 + num_workers 多进程预取 + pin_memory → 不饿 GPU
  · **大 batch** (自动搜索到显存上限的 ~85%)
  · **长跑** (默认 20000 步, 定期 ckpt), 目标 GPU 持续满载
  · 数据: v5_disturb(7.4G) + v6_disturb(4.3G) 全量

四层职责映射 (老倪定义):
  L2 检测反馈  — 像素 → 检测 token + 反馈一致性
  (记忆层)     — 五层记忆 → mem_cond 注入
  L3 状态调度  — z_pred → 状态/阶段调度 (官方同构动作头)
  L4 认知预测  — ViT 编码 → ARPredictor 预测 z_pred (世界模型)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
INTACT = "/home/ubuntu/INTACT-JEPA"
SWM = os.environ.get("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
CKPT = f"{SWM}/checkpoints/intact_l4_current"


# ────────────────────────── 真数据 (h5, 多进程预取) ──────────────────────────
class RealH5(torch.utils.data.Dataset):
    """多文件真正数据集 (不改内存布局, 只读)。"""

    def __init__(self, files, chunk=1):
        import h5py
        self.files, self.cols = [], []
        for f in files:
            if not os.path.isfile(f):
                print(f"  ⚠️ 跳过缺失: {f}")
                continue
            h = h5py.File(f, "r")
            n = int(h["observation"].shape[0])
            self.cols.append((f, n))
            h.close()
            self.files.append(f)
        self.total = sum(n for _, n in self.cols)
        if self.total == 0:
            raise SystemExit("❌ 无可用数据")
        self._h = {}
        self.chunk = chunk

    def _h5(self, f):
        if f not in self._h:
            import h5py
            self._h[f] = h5py.File(f, "r")
        return self._h[f]

    def __len__(self):
        return self.total

    def __getitem__(self, i):
        for f, n in self.cols:
            if i < n:
                break
            i -= n
        h = self._h5(f)
        obs = np.asarray(h["observation"][i], dtype=np.float32)
        act = np.asarray(h["action"][i], dtype=np.float32)
        try:
            px = np.asarray(h["pixels"][i])
        except Exception:
            px = np.zeros((224, 224, 3), dtype=np.uint8)
        # 目标: 取未来第 chunk 帧的观测 (L4 认知预测的目标)
        j = min(i + self.chunk, n - 1)
        goal = np.asarray(h["observation"][j], dtype=np.float32)
        return obs, act, px, goal


def to_img_batch(px: torch.Tensor, size=224):
    """(b,H,W,3) uint8 或 (b,3,H,W) → (b,3,size,size) float[0,1]"""
    if px.dtype != torch.float32:
        px = px.float()
    if px.shape[-1] == 3 and px.shape[1] != 3:      # HWC
        px = px.permute(0, 3, 1, 2)
    px = px / 255.0
    if px.shape[-1] != size:
        px = F.interpolate(px, size=(size, size), mode="bilinear", align_corners=False)
    return px.contiguous()


# ────────────────────────── 联合模型 (四层一张图) ──────────────────────────
class JointFull(nn.Module):
    def __init__(self, jepa, z=192, mem_dim=13, act_dim=4, chunk=7, act_enc_dim=8):
        super().__init__()
        self.jepa = jepa
        # L2 检测反馈: 像素 → 检测 token
        self.l2_proj = nn.Sequential(nn.Conv2d(3, 16, 7, 4, 3), nn.SiLU(),
                                     nn.Conv2d(16, 32, 5, 2, 2), nn.SiLU(),
                                     nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(32, z))
        self.l2_cons = nn.Linear(z, z)                      # L2 反馈一致性头
        # 记忆编码
        self.mem_enc = nn.Sequential(nn.Linear(mem_dim, 64), nn.SiLU(), nn.Linear(64, z))
        # L3 状态调度 (官方同构: Linear→SiLU→...→Linear)
        self.l3 = nn.Sequential(nn.Linear(z, 256), nn.SiLU(), nn.Linear(256, 256), nn.SiLU(),
                                nn.Linear(256, chunk * act_dim))
        self.chunk, self.act_dim = chunk, act_dim
        self.act_enc_dim = act_enc_dim
        self.goal_enc = nn.Sequential(nn.Linear(39, z), nn.SiLU(), nn.Linear(z, z))
        # L4 反馈: 预测潜 → 观测空间 (认知预测的监督)
        self.obs_head = nn.Sequential(nn.Linear(z, z), nn.SiLU(), nn.Linear(z, 39))

    def forward(self, px, obs, act, mem, goal):
        z_l2 = self.l2_proj(px)                                   # L2 检测
        # L4 的 action 语义: 8 维 (在役 ckpt); 真数据 4 维 → 补零 (引擎同做法)
        d_enc = self.act_enc_dim
        act_e = act if act.shape[-1] == d_enc else F.pad(act, (0, d_enc - act.shape[-1]))
        # L4 编码 (★ encode 内部也用 action, 必须喂补零后的)
        info = {"pixels": px.unsqueeze(1), "action": act_e.unsqueeze(1)}
        enc = self.jepa.encode(info)
        z_t = enc["emb"] if isinstance(enc, dict) else enc
        if z_t.dim() == 4:
            z_t = z_t[:, :, 0, :]
        if z_t.dim() == 3:
            z_t = z_t[:, 0, :]
        z_t = z_t[:, :z_l2.shape[-1]]
        z_in = z_t + z_l2 + self.mem_enc(mem)                     # 三路注入
        a_emb = self.jepa.action_encoder(act_e.unsqueeze(1))
        z_pred = self.jepa.predict(z_in.unsqueeze(1), a_emb)       # L4 认知预测
        z_pred = z_pred[:, 0, :]
        u = self.l3(z_pred).view(-1, self.chunk, self.act_dim)     # L3 状态调度
        # L2 反馈一致性: 从 z_pred 反推 "感知应看到什么"
        l2_fb = self.l2_cons(z_pred)
        # L4 到观测的预测 (认知预测的显式监督)
        obs_hat = self.obs_head(z_pred)
        return dict(z_pred=z_pred, u=u, l2_fb=l2_fb, z_l2=z_l2, obs_hat=obs_hat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=20000)
    ap.add_argument("--batch", type=int, default=0, help="0=自动搜索打满显存")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--chunk", type=int, default=7)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--save", default=f"{SWM}/checkpoints/joint_full_v6")
    ap.add_argument("--stats", type=int, default=200, help="每 N 步打印 GPU 状态")
    ap.add_argument("--amp", type=int, default=0, help="1=用混合精度 (与 L4 内部 fp32 有冲突, 默认关)")
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🔥 全负荷联合集训 V6 · 设备 {dev} · 目标 {a.steps} 步")

    # ── L4 真模型 ──
    sys.path.insert(0, INTACT)
    from hydra.utils import instantiate
    cfg = json.load(open(f"{CKPT}/config.json"))
    jepa = instantiate(cfg)
    sd = torch.load(f"{CKPT}/weights.pt", map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "state_dict" in sd:
        sd = sd["state_dict"]
    miss, unexp = jepa.load_state_dict(sd, strict=False)
    print(f"L4 JEPA 加载 | missing={len(miss)} unexpected={len(unexp)} | {sum(p.numel() for p in jepa.parameters()):,} 参数")
    jepa = jepa.to(dev)

    # 从 ckpt 配置读 action_encoder 的输入维 (在役=8)
    try:
        ae_cfg = cfg["action_encoder"]
        d_enc = int(getattr(ae_cfg, "input_dim", None) or ae_cfg.get("input_dim", 8))
    except Exception:
        d_enc = 8
    print(f"L4 action_encoder 输入维 = {d_enc} (真数据 action 4 维 → 补零对齐)")
    model = JointFull(jepa, chunk=a.chunk, act_enc_dim=d_enc).to(dev)
    n_l2 = sum(p.numel() for p in model.l2_proj.parameters()) + sum(p.numel() for p in model.l2_cons.parameters())
    n_mem = sum(p.numel() for p in model.mem_enc.parameters())
    n_l3 = sum(p.numel() for p in model.l3.parameters())
    print(f"L2 检测反馈 {n_l2:,} | 记忆 {n_mem:,} | L3 状态调度 {n_l3:,} | L4 认知预测 {sum(p.numel() for p in model.jepa.parameters()):,}")

    # ── 真数据 ──
    files = [f"{SWM}/datasets/optical_insert_v6_disturb.h5", f"{SWM}/datasets/optical_insert_v5_disturb.h5"]
    ds = RealH5(files, chunk=a.chunk)
    print(f"真数据 {ds.total:,} 帧 (v6+v5) · {len(ds.cols)} 个 h5")

    # ── 记忆向量 (五层聚合) ──
    mem = torch.zeros(13, device=dev)
    try:
        import glob
        mm = json.load(open(f"{ROOT}/data/muscle_memory.json"))
        sm = json.load(open(f"{ROOT}/data/shared_memory.json"))
        am = json.load(open(f"{ROOT}/data/assembly_memory.json"))
        vals = [len(mm), len(sm.get("l2", [])), len(sm.get("l3", [])), len(sm.get("l4", [])),
                len(sm.get("links", [])), len(am.get("runs", []))]
        mem[:6] = torch.tensor([float(v) for v in vals], device=dev)
        print(f"记忆已入图: muscle={len(mm)} shared_l2={len(sm.get('l2', []))} ...")
    except Exception as e:
        print(f"记忆读取跳过: {e}")

    # ── AMP ──
    use_amp = bool(a.amp) and dev == "cuda"
    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_tf32 = True
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=1e-4)

    def make_loader(bs):
        return torch.utils.data.DataLoader(ds, batch_size=bs, shuffle=True, num_workers=a.workers,
                                           pin_memory=True, drop_last=True, persistent_workers=a.workers > 0,
                                           prefetch_factor=4 if a.workers > 0 else None)

    def step_once(dl, bs):
        opt.zero_grad(set_to_none=True)
        obs, act, px, goal = next(iter(dl))
        obs, act, goal = obs.to(dev, non_blocking=True), act.to(dev, non_blocking=True), goal.to(dev, non_blocking=True)
        img = to_img_batch(px).to(dev, non_blocking=True)   # ★ 必须搬 GPU
        with torch.amp.autocast("cuda", enabled=use_amp):
            out = model(img, obs, act, mem.unsqueeze(0).repeat(bs, 1), goal)
            L_act = F.mse_loss(out["u"], act.unsqueeze(1).repeat(1, a.chunk, 1))
            L_obs = F.mse_loss(out["obs_hat"], goal)                        # L4 认知预测
            L_l2 = F.mse_loss(F.normalize(out["l2_fb"], dim=-1), F.normalize(out["z_l2"].detach(), dim=-1))
            loss = L_act + L_obs + 0.3 * L_l2
        scaler.scale(loss).backward()
        scaler.unscale_(opt)
        gn = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
        scaler.step(opt)
        scaler.update()
        return loss.item(), L_act.item(), L_obs.item(), L_l2.item(), float(gn)

    # ── batch 自动搜索: 打满显存 (~85%) ──
    if a.batch > 0:
        bs = a.batch
    else:
        bs = 8
        if dev == "cuda":
            for cand in [8, 16, 24, 32, 48, 64, 96, 128, 192, 256]:
                try:
                    torch.cuda.reset_peak_memory_stats()
                    dl = make_loader(cand)
                    step_once(dl, cand)
                    peak = torch.cuda.max_memory_allocated() / 1048576
                    if peak > 5200:
                        print(f"  batch {cand} 峰值 {peak:.0f}MB → 超过 5200MB 安全线, 退回上一档")
                        break
                    bs = cand
                    print(f"  batch {cand} 峰值 {peak:.0f}MB ✓")
                except (RuntimeError, torch.cuda.OutOfMemoryError) as e:
                    print(f"  batch {cand} OOM → 定为 {bs}")
                    torch.cuda.empty_cache()
                    break
        print(f"🎯 选定 batch={bs}")

    dl = make_loader(bs)
    it = iter(dl)
    hist = []
    t0 = time.time()
    for s in range(1, a.steps + 1):
        try:
            obs, act, px, goal = next(it)
        except StopIteration:
            it = iter(dl)
            obs, act, px, goal = next(it)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache(); bs = max(4, bs // 2)
            print(f"  ⚠️ OOM → batch 降到 {bs}, 重建 loader", flush=True)
            dl = make_loader(bs); it = iter(dl); continue
        obs, act, goal = obs.to(dev, non_blocking=True), act.to(dev, non_blocking=True), goal.to(dev, non_blocking=True)
        img = to_img_batch(px).to(dev, non_blocking=True)   # ★ 必须搬 GPU
        opt.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda", enabled=use_amp):
            out = model(img, obs, act, mem.unsqueeze(0).repeat(obs.shape[0], 1), goal)
            L_act = F.mse_loss(out["u"], act.unsqueeze(1).repeat(1, a.chunk, 1))
            L_obs = F.mse_loss(out["obs_hat"], goal)
            L_l2 = F.mse_loss(F.normalize(out["l2_fb"], dim=-1), F.normalize(out["z_l2"].detach(), dim=-1))
            loss = L_act + L_obs + 0.3 * L_l2
        scaler.scale(loss).backward()
        scaler.unscale_(opt)
        gn = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
        scaler.step(opt)
        scaler.update()
        hist.append(loss.item())
        if s % a.stats == 0 or s == 1:
            sps = s / max(1e-6, time.time() - t0)
            gpu_u = gpu_m = -1
            if dev == "cuda":
                gpu_m = torch.cuda.max_memory_allocated() / 1048576
                gpu_r = torch.cuda.memory_reserved() / 1048576
            print(f"  step {s:6d}/{a.steps} | loss {loss.item():.4f} L_act {L_act.item():.4f} "
                  f"L_obs {L_obs.item():.4f} L_l2 {L_l2.item():.4f} | ∇ {float(gn):.2e} | "
                  f"{sps:.1f} 步/s | 显存 {gpu_m:.0f}/{gpu_r:.0f}MB", flush=True)
    dt = time.time() - t0
    print(f"✅ 完成 {a.steps} 步 / {dt:.1f}s ({a.steps/dt:.1f} 步/s) | loss {hist[0]:.4f} → {hist[-1]:.4f}")

    if a.save:
        os.makedirs(a.save, exist_ok=True)
        torch.save(model.jepa.state_dict(), f"{a.save}/weights.pt")     # 扁平! 引擎可直接加载
        import shutil
        shutil.copy(f"{CKPT}/config.json", f"{a.save}/config.json")
        torch.save({k: v for k, v in model.state_dict().items()
                    if k.startswith(("l2_", "l3.", "mem_enc.", "goal_enc.", "obs_head."))},
                   f"{a.save}/joint_full.pt")
        print(f"产物 → {a.save} (weights.pt 扁平 + config.json + joint_full.pt)")
    Path(f"{ROOT}/reports").mkdir(exist_ok=True)
    json.dump({"steps": a.steps, "batch": bs, "sec": dt, "sps": a.steps / dt,
               "loss_first": hist[0], "loss_last": hist[-1], "n_l2": n_l2, "n_mem": n_mem, "n_l3": n_l3},
              open(f"{ROOT}/reports/joint_full_v6.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
