#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""target-decoder 推理模块 — S3' decoder v1

架构位置 (L2 三件套一行不动):
    意图(阶段 + 现场几何) ──▶ [TargetDecoder] ──▶ target ──▶ ⚡前馈加速器 u=Kp(target−pos)
                                                          ──▶ 🧭动作调制 ──▶ 🛡限幅 ──▶ 执行

两个头 (同一网络):
    head_t : 复现引擎规则意图 _stage_target()  (链路回归基线)
    head_n : 成功轨迹的真实运动 x_{t+1}        (策略版, 有增益潜力)

引擎侧: SS_TDEC=1 开启 (默认关), SS_TDEC_HEAD=next|target 选头。
规则版 _stage_target() 始终保留作兜底 + 影子对比。
"""
import os

import numpy as np
import torch
import torch.nn as nn

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


class Net(nn.Module):
    """与 tools/train_target_decoder.py 完全同构 (state_dict 按名匹配)。"""

    def __init__(self, din, h=256):
        super().__init__()
        self.body = nn.Sequential(nn.Linear(din, h), nn.SiLU(), nn.Linear(h, h), nn.SiLU())
        self.head_t = nn.Linear(h, 3)
        self.head_n = nn.Linear(h, 3)

    def forward(self, x):
        f = self.body(x)
        return self.head_t(f), self.head_n(f)


class TargetDecoder:
    def __init__(self, ckpt=None, head="next", device=None):
        ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/lerobot-smolvla-lew")
        self.ckpt = ckpt or os.path.join(ROOT, "outputs", "target_decoder", "model.pt")
        self.head = head if head in ("next", "target") else "next"
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        d = torch.load(self.ckpt, map_location="cpu", weights_only=False)   # 本地自产 ckpt (含 numpy 统计量)
        self.mu = np.asarray(d["mu"], np.float32)
        self.sd = np.asarray(d["sd"], np.float32)
        self.nmu = np.asarray(d["nmu"], np.float32)
        self.nsd = np.asarray(d["nsd"], np.float32)
        self.tmu = np.asarray(d["tmu"], np.float32)
        self.tsd = np.asarray(d["tsd"], np.float32)
        self.stages = list(d.get("stages", STAGES))
        self.net = Net(len(self.mu.ravel())).to(self.device)
        self.net.load_state_dict(d["state"])
        self.net.eval()
        self.hits = 0

    def _oh(self, stage):
        oh = np.zeros(len(self.stages), np.float32)
        s = str(stage).replace("阶段 ", "").split("·")[0].strip()
        if s in self.stages:
            oh[self.stages.index(s)] = 1.0
        return oh

    @torch.no_grad()
    def predict(self, stage, x, peg, hole):
        feat = np.concatenate([self._oh(stage),
                               np.asarray(x, np.float32).ravel()[:3],
                               np.asarray(peg, np.float32).ravel()[:3],
                               np.asarray(hole, np.float32).ravel()[:3]])[None, :]
        z = torch.from_numpy((feat - self.mu) / self.sd).float().to(self.device)
        ot, on = self.net(z)
        if self.head == "target":
            t = ot[0].cpu().numpy() * self.tsd + self.tmu
        else:
            t = on[0].cpu().numpy() * self.nsd + self.nmu
        self.hits += 1
        return np.asarray(t, np.float32).ravel()[:3]
