# Copyright 2026 Z-MAX. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
"""🧠 INTACT 策略 (L4) — lerobot 策略外壳，真算法在 runtime/ (跨 venv 子进程桥)。

架构 (docs/design/zmax_l4_intact_policy.md):
    metaworld 数据源 (runtime/metaworld_source.py, 真渲染帧 + 39D)
      → IntactPolicy.select_action / predict_action_chunk   (零搜索 意图→动作, 真权重)
      → IntactIntentDecoder                                  (L4 → L3 条件: u_ff 先验 + 流形条件)
      → L3 (SmolVLA-Lew VLM+DiT)                             (条件注入, 默认关闭)

诚实边界:
  · forward()/训练 **不支持** —— INTACT 权重训练在外部运行时 (INTACT-JEPA paper_runtime)。
  · 未就绪 (trained=False) 时 **raise**, 绝不返回零动作冒充成功 (老倪红线)。
"""
from __future__ import annotations

import os

import numpy as np
import torch
import torch.nn as nn

from lerobot.policies.pretrained import PreTrainedPolicy

from .configuration_intact import IntactConfig
from .decoder import DecodedIntent, IntactIntentDecoder


class IntactPolicy(PreTrainedPolicy):
    """INTACT 意图-动作策略 (L4)。推理-only, 真权重经子进程桥。

    用法:
        pol = IntactPolicy(IntactConfig(ckpt="intact_goal_optical_insert_v5_s3072/weights_epoch_1.pt",
                                        runtime="root", intact_device="cpu"))
        pol.set_data_source("metaworld", seed=0)          # 数据源直接接入 metaworld
        chunk = pol.predict_action_chunk({})              # [1, H, 4] 真推理
        dec = pol.predict_intent({}, stage="接近")        # → u_ff 先验 + L3 条件 (未标定则拒绝)
    """

    config_class = IntactConfig
    name = "intact"

    def __init__(self, config: IntactConfig, dataset_stats=None, dataset_info=None) -> None:
        super().__init__(config)
        self.config = config
        self._node = None                       # 懒建 (首次推理才起子进程桥)
        self._decoder = IntactIntentDecoder(
            cond_dim=int(getattr(config, "l3_cond_dim", 6)),
            excluded_stages=tuple(getattr(config, "l3_exclude_stages", ()) or ()),
            action_dim=int(getattr(config, "action_dim", 4)))
        self._dummy = nn.Parameter(torch.zeros(1))     # 让 .to()/parameters() 可用 (无参策略)
        self.last_decoded: DecodedIntent | None = None

    # ── 节点 (真算法) ──
    @property
    def node(self):
        if self._node is None:
            from .runtime import IntactNode, IntactRuntime      # noqa: PLC0415
            rt = IntactRuntime(repo=None, policy=str(self.config.runtime),
                               ckpt=str(self.config.ckpt) or None,
                               device=str(getattr(self.config, "intact_device", "cpu")))
            self._node = IntactNode(horizon=int(self.config.horizon),
                                    action_dim=int(self.config.action_dim),
                                    intent_mode=str(self.config.intent_mode),
                                    feature_layout=str(self.config.feature_layout),
                                    runtime=rt, log=lambda *a: None)
        return self._node

    def set_data_source(self, src: str = "metaworld", **kw):
        """默认 metaworld (老倪: 数据源直接接入 metaworld)。"""
        return self.node.set_data_source(src, **kw)

    def set_goal(self, goal=None, waypoint=None, path: str | None = None) -> None:
        """设目标意图: 显式帧 / 目标点 / 或从 npy 读 (默认本域真实目标帧)。"""
        if goal is None and path:
            g = np.asarray(np.load(path), dtype=np.float32)
            goal = np.transpose(g, (2, 0, 1)) if (g.ndim == 3 and g.shape[0] not in (1, 3, 4)) else g
        self.node.set_goal(goal=goal, waypoint=waypoint)

    # ── lerobot 推理接口 ──
    @staticmethod
    def _frame_from_batch(batch: dict) -> np.ndarray | None:
        """从 lerobot batch 取一帧 → node 口径 CHW float32 0..255; 无则 None (走数据源)。"""
        for k in ("observation.images.top", "observation.image", "observation.images.camera",
                  "pixels"):
            v = (batch or {}).get(k)
            if v is None:
                continue
            t = v if torch.is_tensor(v) else torch.as_tensor(v)
            if t.ndim == 5:                     # [B,T,C,H,W]
                t = t[0, -1]
            elif t.ndim == 4:                   # [B,C,H,W]
                t = t[0]
            a = t.detach().cpu().float().numpy()
            if a.max() <= 1.5:
                a = a * 255.0
            return a
        return None

    @torch.no_grad()
    def predict_action_chunk(self, batch: dict, **kwargs) -> torch.Tensor:
        """真推理一次 → 动作块 [B, H, action_dim] (metaworld act 空间 ±1)。未就绪则 raise。"""
        fr = self._frame_from_batch(batch or {})
        out = self.node.step(fr, obs_source=("engine_render" if fr is not None else None))
        chunk = np.asarray(out.chunk, dtype=np.float32)
        if chunk.ndim == 1:
            chunk = chunk[None]
        return torch.from_numpy(chunk[None])                 # [1,H,D]

    @torch.no_grad()
    def select_action(self, batch: dict, **kwargs) -> torch.Tensor:
        """取动作块首帧 [B, action_dim] (lerobot 单步契约)。"""
        return self.predict_action_chunk(batch or {}, **kwargs)[:, 0]

    @torch.no_grad()
    def predict_intent(self, batch: dict, stage: str = "", **kwargs) -> DecodedIntent:
        """解码 L4 → L3: u_ff 先验 (量纲逆运算) + 流形条件 (未标定则拒绝, 不写死)。"""
        fr = self._frame_from_batch(batch or {})
        out = self.node.step(fr, obs_source=("engine_render" if fr is not None else None))
        self.last_decoded = self._decoder.decode(out, stage=stage, cfg=self.config)
        return self.last_decoded

    def forward(self, batch: dict):                        # type: ignore[override]
        raise NotImplementedError(
            "INTACT 权重训练在外部运行时 (INTACT-JEPA paper_runtime) 中进行；本策略仅提供推理 "
            "(select_action / predict_action_chunk / predict_intent)。若需微调本域数据，"
            "见 config/train/intact_goal_optical_insert_v5.yaml + l4_ab 接力守护。")

    def reset(self) -> None:
        if self._node is not None:
            self._node.reset()

    def get_optim_params(self) -> dict:
        return {}

    # ── 诊断 ──
    def describe(self) -> dict:
        d = {"policy": self.name, "config": {k: getattr(self.config, k) for k in
                                            ("horizon", "action_dim", "intent_mode", "runtime",
                                             "ckpt", "intact_device", "l3_prior_weight")},
             "decoder": self._decoder.describe(), "node_built": self._node is not None}
        if self._node is not None:
            d["source"] = self._node.source.info() if self._node.source else None
            d["runtime"] = self._node.runtime.info()
            d["diagnostics"] = self._node.diagnostics()
        return d

    def runtime_ready(self) -> tuple[bool, str]:
        """就绪度 (不触发大加载: 只问 runtime 的静态信息)。"""
        try:
            rt = self.node.runtime
            return bool(getattr(rt, "trained", False)), str(getattr(rt, "reason", "") or "")
        except Exception as e:                                          # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"
