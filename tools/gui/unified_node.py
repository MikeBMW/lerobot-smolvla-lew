#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UnifiedNode — 把统一主干(SigLIP+四头)接进引擎闭环 (接口对齐 IntactNode)

引擎调用面 (见 state_space_sim_real.py:1365):
    out = node.step(fr, obs_source="engine_render")            # fr: (3,224,224) float32 0-255
    chunk = out.chunk        # (chunk,4) 动作块
    out.latent['z_t']        # 可选
    out.trained              # 自检标志
obs39 来源: 引擎每步写 self._last_obs39 (env 原生 o[:39]) — 与训练同口径
"""
import os
import sys

import numpy as np
import torch


class _Out:
    __slots__ = ("chunk", "latent", "trained", "intent_norm")

    def __init__(self, chunk, z_t, trained=True):
        self.chunk = chunk
        self.latent = {"z_t": z_t}
        self.trained = trained
        self.intent_norm = float(np.linalg.norm(chunk))


class UnifiedNode:
    """共享预训练主干(SigLIP 768d 冻结) + 四头 → 出动作块。接口同 IntactNode。"""

    def __init__(self, ckpt, sim=None, horizon=8, dev=None, repo="/home/ubuntu/lerobot-smolvla-lew"):
        self.ckpt = ckpt
        self.sim = sim
        self.horizon = horizon
        if repo not in sys.path:
            sys.path.insert(0, repo)
        if os.path.join(repo, "tools") not in sys.path:
            sys.path.insert(0, os.path.join(repo, "tools"))
        from transformers import AutoModel                       # noqa: E402
        from joint_unified_backbone import MODEL, Unified        # noqa: E402

        dev = dev or ("cuda" if torch.cuda.is_available() else "cpu")
        self.dev = dev
        full = AutoModel.from_pretrained(MODEL, dtype=torch.float32)
        self.net = Unified(full.vision_model, freeze=True)
        sd = torch.load(ckpt, map_location="cpu", weights_only=False)
        if isinstance(sd, dict) and "model" in sd and "trunk.embeddings.patch_embedding.weight" not in sd:
            sd = sd["model"]
        missing, unexpected = self.net.load_state_dict(sd, strict=False)
        self.net = self.net.eval().to(dev)
        self.selfcheck = (len([k for k in missing if "trunk" not in k]) == 0)
        print(f"🧬 UnifiedNode 已挂载: ckpt={os.path.basename(os.path.dirname(ckpt))} · "
              f"missing={len(missing)}(非trunk {len([k for k in missing if 'trunk' not in k])}) · "
              f"trained={self.selfcheck} · dev={dev}", flush=True)

    def _obs39(self):
        v = getattr(self.sim, "_last_obs39", None) if self.sim is not None else None
        if v is None:
            return np.zeros(39, dtype=np.float32)
        return np.asarray(v, dtype=np.float32).ravel()[:39]

    @torch.no_grad()
    def step(self, fr, obs_source=None, skill_ctx=None):
        """fr: (3,224,224) float32 0-255 (引擎已 resize) → 出 (horizon,4) tanh 限幅动作块"""
        x = np.asarray(fr, dtype=np.float32)
        if x.ndim == 3 and x.shape[0] == 3:
            img = torch.from_numpy(x / 255.0).unsqueeze(0)
        else:                                     # (224,224,3) 兜底
            img = torch.from_numpy(x / 255.0).permute(2, 0, 1).unsqueeze(0)
        img = img.to(self.dev)
        obs = torch.from_numpy(self._obs39()).unsqueeze(0).to(self.dev)
        mem = torch.zeros(1, 13, device=self.dev)
        out = self.net(img, obs, torch.zeros(1, 1, 4, device=self.dev), mem)
        chunk = out["u"][0].float().cpu().numpy().astype(np.float32)     # (T,4), 已 tanh
        return _Out(chunk, out["z"][0].float().cpu().numpy(), self.selfcheck)
