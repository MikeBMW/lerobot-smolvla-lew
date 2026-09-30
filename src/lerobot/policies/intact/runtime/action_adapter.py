# -*- coding: utf-8 -*-
"""🔀 动作适配层 (intact_node.action_adapter) — INTACT 官方动作空间 → 本工程 4D 状态空间。

为什么必须单独一层 (Step 0 结论):
  · 官方 paper 权重 action_dim = 10 (pusht 语义: 2D 点位移/速度等), 本工程状态空间动作是
    **4D**: (dx, dy, dz, gripper), 单位 m/s + gripper ∈ [-1,1]。
  · 10 → 4 **不是截取**: 哪个官方维度对应我们哪个轴、比例是多少, 属于**标定问题**, 必须由
    真实数据算出来 (同 L3 那套 u_ff = act × K_ACT)。所以本层默认 `enabled=False`:
      未标定时 `map_chunk()` **拒绝返回数值** (返回 None + reason), 绝不猜/不写死。
  · 标定产物落 `models/intact_action_map.json`:
      {"slice": {"x": i, "y": j, "z": k, "gripper": m},     # 官方维度索引
       "scale": {"x": Kx, "y": Ky, "z": Kz, "gripper": Kg}, # 归一化 → 本工程量纲
       "source": "<标定脚本+标定数据+日期>", "n_samples": N, "fit_metrics": {...}}
    由 `tools/calib_intact_action_map.py` (Step 1 任务, 尚未写) 用同口径数据拟合生成。

红线: 本层是 Step 0 的**骨架** —— 只定义契约与拒绝逻辑, **不接入引擎** (u_ff 注入属 Step 1)。
"""
from __future__ import annotations

import json
import os

import numpy as np

CALIB_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))),
    "models", "intact_action_map.json")


class IntactActionAdapter:
    """官方 [H, D_official] → 本工程 [H, 4] (dx, dy, dz, gripper)。

    默认 enabled=False: 没有标定文件时**拒绝映射**, 只给出 reason (诚实纪律)。
    """

    OUT_DIM = 4

    def __init__(self, calib_path: str | None = None, enabled: bool | None = None):
        self.calib_path = calib_path or CALIB_DEFAULT
        self.calib: dict | None = None
        self.reason = "未标定 (Step 1 任务: 用同口径数据拟合 models/intact_action_map.json)"
        if os.path.isfile(self.calib_path):
            try:
                with open(self.calib_path, encoding="utf-8") as f:
                    c = json.load(f)
                assert set(c.get("slice", {})) >= {"x", "y", "z", "gripper"}, "slice 不完整"
                assert set(c.get("scale", {})) >= {"x", "y", "z", "gripper"}, "scale 不完整"
                self.calib = c
                self.reason = f"已标定: {c.get('source', '?')}"
            except Exception as e:
                self.reason = f"标定文件不可用 ({type(e).__name__}: {e}) → 视为未标定"
        self.enabled = bool(self.calib is not None) if enabled is None else bool(enabled)
        if self.calib is None:
            self.enabled = False                    # 无标定一律不可用 (不看传参)

    # ── 映射 ──
    def map_chunk(self, chunk: np.ndarray) -> tuple[np.ndarray | None, str]:
        """[H, D_official] → ([H, 4] 或 None, reason)。未标定 → (None, reason)。"""
        if not self.enabled or self.calib is None:
            return None, f"拒绝映射: {self.reason}"
        a = np.asarray(chunk, dtype=np.float32)
        if a.ndim == 1:
            a = a[None]
        sl, sc = self.calib["slice"], self.calib["scale"]
        d_official = a.shape[-1]
        idx = [sl["x"], sl["y"], sl["z"], sl["gripper"]]
        if max(idx) >= d_official:
            return None, (f"拒绝映射: 标定索引 {idx} 超出官方动作维 {d_official} "
                          f"(权重与标定不匹配)")
        out = np.stack([a[:, sl["x"]] * sc["x"], a[:, sl["y"]] * sc["y"],
                        a[:, sl["z"]] * sc["z"], a[:, sl["gripper"]] * sc["gripper"]], axis=-1)
        return out.astype(np.float32), "ok"

    def describe(self) -> dict:
        return {"enabled": self.enabled, "calib_path": self.calib_path, "reason": self.reason,
                "out_dim": self.OUT_DIM, "calib": self.calib}


if __name__ == "__main__":       # 自检: 未标定必须拒绝 (不许产出数值)
    ad = IntactActionAdapter()
    out, why = ad.map_chunk(np.zeros((8, 10), dtype=np.float32))
    print("describe:", json.dumps(ad.describe(), ensure_ascii=False))
    print(f"未标定映射结果: {out if out is None else out.shape} · reason={why}")
    assert out is None, "未标定却返回了数值 = 违反诚实纪律"
    print("✅ 自检通过: 未标定 → 拒绝映射 (不产出假数值)")
