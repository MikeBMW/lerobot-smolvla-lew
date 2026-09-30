#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""event_head.py — 🧠 事件级认知头 (运行时) —— 把离线训出的真权重接进引擎闭环

背景 (2026-09-26 定档): 值预测靶子判死(一步输持久 5.19×; 多步 K=1/5/10 全输持久/匀速);
  事件级靶子成立(6/6 赢平凡基线, v6→v5 跨域不退化; 变体 5 折 CV 6/6)。
本模块 = 该结论的**运行时落地**: 引擎每帧真调这个头 → 出 6 个事件概率 (3 事件 × 视界 5/10)。

契约:
    from lerobot.cognition.event_head import get_event_head
    h = get_event_head()                 # 单例 (进程内只加载一次)
    h.available() -> bool                # 权重在不在 (不在则引擎如实标 -1, 不用假值顶替)
    h.predict(obs)  -> (dict, ms)        # obs: 39 维 (只用 obs[0:7]) 或 7 维
    h.KEYS = ("gc_5","gc_10","rz_5","rz_10","mh_5","mh_10")
字段:  gc_*=夹爪闭合  rz_*=到位(reach_z)  mh_*=手在动(move_hand); 后缀 = 未来帧视界 H
口径:  与训练完全一致 —— 输入 obs[0:7] (手位3+夹爪1+速度3); 若 ckpt 训练时开过 --aug, 这里按同一公式增强
纪律:  拿不到权重 → available()=False, 引擎写 -1 (不冒充 0); 不 import GUI; 不阻塞 (单帧 <1ms, CPU/GPU 均可)
"""
from __future__ import annotations

import os

import numpy as np

CKPT_DIR = os.environ.get("ZMAX_COG_EVENT_DIR", "/home/ubuntu/stable-wm-cache/checkpoints/cog_event_head")
# ★ 2026-09-26 默认用**引擎同源**权重: 造数据管线训的 v6_long 进闭环 AUC 仅 0.238(低于随机),
#   换同源(引擎 tr)训的 engine_v2 → 闭环 AUC 0.997~1.000 (取证 verify_cog_event_loop 7/7)
PREFERRED = os.environ.get("ZMAX_COG_EVENT_TAG", "engine_v3")   # 300 段同源 (CV 6/6, 最低折 reach_z 0.929)
KEYS = ("gc_5", "gc_10", "rz_5", "rz_10", "mh_5", "mh_10")
_EV_ORDER = ("gripper_close", "reach_z", "move_hand")


def _augment(x):
    """与训练 --aug 完全同式 (只用当前帧, 不含未来)"""
    hand, grip, vel = x[:, 0:3], x[:, 3:4], x[:, 4:7]
    vn = np.linalg.norm(vel, axis=1, keepdims=True)
    extra = np.concatenate([vn, vn * grip, hand * grip, vel * grip, np.abs(vel), hand[:, 2:3]], axis=1)
    return np.concatenate([x, extra.astype(np.float32)], axis=1)


class EventHead:
    """事件级认知头 (每帧真前向; 权重来自 stable-wm-cache/checkpoints/cog_event_head)"""

    def __init__(self, ckpt_dir=None, tag=None):
        self.dir = ckpt_dir or CKPT_DIR
        self.tag = tag or PREFERRED
        self.nets = {}
        self.meta = {}
        self.calls = 0
        self.source = "未加载"
        self.trained = False
        self._torch = None
        self._dev = "cpu"
        self._load()

    # ---------- 加载 ----------
    def _load(self):
        try:
            import torch                                    # noqa: PLC0415
        except Exception:                                   # noqa: BLE001
            self.source = "torch 不可用"
            return
        self._torch = torch
        self._dev = "cuda" if torch.cuda.is_available() else "cpu"
        want = [("H5", os.path.join(self.dir, "head_H5_%s.pt" % self.tag)),
                ("H10", os.path.join(self.dir, "head_H10_%s.pt" % self.tag))]
        if not all(os.path.isfile(p) for _, p in want):     # tag 不存在 → 目录里任意一对可用 ckpt 兜底
            cand = {}
            for f in sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []:
                if f.startswith("head_H") and f.endswith(".pt"):
                    h = "H5" if f.startswith("head_H5_") else "H10"
                    cand.setdefault(h, os.path.join(self.dir, f))
            if len(cand) == 2:
                want = [(h, cand[h]) for h, _ in want if h in cand]
        try:
            for hkey, p in want:
                d = torch.load(p, map_location="cpu", weights_only=False)
                sd = d["state_dict"]
                hidden = int(d.get("hidden") or list(sd.values())[0].shape[0])
                aug = bool(d.get("aug", False))
                in_dim = int(sd["0.weight"].shape[1])
                net = torch.nn.Sequential(torch.nn.Linear(in_dim, hidden), torch.nn.ReLU(),
                                          torch.nn.Linear(hidden, hidden), torch.nn.ReLU(),
                                          torch.nn.Linear(hidden, len(_EV_ORDER))).to(self._dev)
                net.load_state_dict(sd)
                net.eval()
                self.nets[hkey] = net
                self.meta[hkey] = {"ckpt": os.path.basename(p), "hidden": hidden, "aug": aug,
                                   "in_dim": in_dim, "H": int(d.get("H", 5 if hkey == "H5" else 10)),
                                   "trained": True, "holdout_mean_auc": d.get("holdout_mean_auc"),
                                   "steps": d.get("steps")}
            if len(self.nets) == 2:
                self.source = "%s (H5:%s / H10:%s)" % (self.tag, self.meta["H5"]["ckpt"], self.meta["H10"]["ckpt"])
                self.trained = True
        except Exception as e:                              # noqa: BLE001
            self.nets, self.source, self.trained = {}, "加载失败: %s: %s" % (type(e).__name__, str(e)[:60]), False

    def available(self) -> bool:
        return bool(self.nets) and self.trained

    # ---------- 前向 ----------
    def predict(self, obs):
        """obs: (39,) 或 (7,) → ({"gc_5":p,...}, ms) ; 不可用 → ({}, -1.0)"""
        if not self.available():
            return {}, -1.0
        torch = self._torch
        import time as _t
        x = np.asarray(obs, dtype=np.float32).ravel()[:7]
        if x.shape[0] < 7:
            x = np.pad(x, (0, 7 - x.shape[0]))
        x = x[None, :]
        out, t0 = {}, _t.perf_counter()
        with torch.no_grad():
            for hkey, net in self.nets.items():
                xx = _augment(x) if self.meta[hkey]["aug"] else x
                p = torch.sigmoid(net(torch.tensor(xx, device=self._dev))).cpu().numpy().ravel()
                for i, ev in enumerate(_EV_ORDER):
                    out["%s_%d" % ({"gripper_close": "gc", "reach_z": "rz", "move_hand": "mh"}[ev],
                                   self.meta[hkey]["H"])] = float(p[i])
        self.calls += 1
        return out, (_t.perf_counter() - t0) * 1000.0

    def info(self) -> dict:
        return {"source": self.source, "trained": self.trained, "calls": self.calls,
                "meta": self.meta, "keys": list(KEYS), "device": self._dev}


_INSTANCE = None


def get_event_head():
    """进程内单例 (引擎逐帧调用; 只加载一次)"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = EventHead()
    return _INSTANCE
