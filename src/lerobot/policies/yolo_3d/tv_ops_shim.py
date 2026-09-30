#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tv_ops_shim.py — torchvision C++ ops 备用实现 (纯 torch NMS / IoU)

为什么需要 (2026-09-17, Orin 实测):
  Orin 上是 NVIDIA Jetson 的 torch 2.5.0a0+nv24.08, 但 torchvision 是 0.20.0 (通用轮子),
  两者的 C++ 扩展 ABI 不匹配 → `torchvision/extension.py::_assert_has_ops()` 抛
  "Couldn't load custom C++ ops", 于是 **ultralytics 的 NMS 直接崩** (YOLO 在 Orin 上跑不起来)。
  Orin 生产网无外网 → 装不了匹配的 NVIDIA torchvision 轮子。

  本模块给出数值等价的纯 torch 实现 (xyxy 坐标), 让检测链路在 Orin 上能跑:
    nms / batched_nms / box_iou
  代价: NMS 从 C++ 换成向量化 torch, 单帧多几毫秒 (实测 Orin CPU 推理 ~100ms/帧, NMS 占比小)。
  一旦 Orin 能装上匹配的 NVIDIA torchvision, 本 shim 自动失效 (只在 ops 真崩时才打补丁)。

  ⚠️ 不静默: 打补丁时会打印一行说明。
"""
from __future__ import annotations

import torch


def torch_nms(boxes: torch.Tensor, scores: torch.Tensor, iou_threshold: float) -> torch.Tensor:
    """标准 NMS (boxes: (N,4) xyxy, scores: (N,)) → 保留索引 (与 torchvision.ops.nms 同语义)"""
    if boxes.numel() == 0:
        return torch.zeros(0, dtype=torch.long, device=boxes.device)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
    order = scores.argsort(descending=True)
    keep = []
    while order.numel() > 0:
        i = order[0]
        keep.append(i)
        if order.numel() == 1:
            break
        rest = order[1:]
        xx1 = torch.maximum(x1[i], x1[rest])
        yy1 = torch.maximum(y1[i], y1[rest])
        xx2 = torch.minimum(x2[i], x2[rest])
        yy2 = torch.minimum(y2[i], y2[rest])
        inter = (xx2 - xx1).clamp(min=0) * (yy2 - yy1).clamp(min=0)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-7)
        order = rest[iou <= iou_threshold]
    return torch.stack(keep).to(torch.long) if keep else torch.zeros(0, dtype=torch.long, device=boxes.device)


def torch_batched_nms(boxes: torch.Tensor, scores: torch.Tensor, idxs: torch.Tensor,
                      iou_threshold: float) -> torch.Tensor:
    """按类别的 NMS: 把不同类的框平移到互不重叠区域再做全局 NMS (与 torchvision 同技巧)"""
    if boxes.numel() == 0:
        return torch.zeros(0, dtype=torch.long, device=boxes.device)
    max_coord = boxes.max()
    offsets = idxs.to(boxes.dtype) * (max_coord + 1.0)
    return torch_nms(boxes + offsets[:, None], scores, iou_threshold)


def torch_box_iou(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """成对 IoU (a: (N,4), b: (M,4) xyxy) → (N,M)"""
    area_a = (a[:, 2] - a[:, 0]).clamp(min=0) * (a[:, 3] - a[:, 1]).clamp(min=0)
    area_b = (b[:, 2] - b[:, 0]).clamp(min=0) * (b[:, 3] - b[:, 1]).clamp(min=0)
    lt = torch.max(a[:, None, :2], b[None, :, :2])
    rb = torch.min(a[:, None, 2:], b[None, :, 2:])
    wh = (rb - lt).clamp(min=0)
    inter = wh[:, :, 0] * wh[:, :, 1]
    return inter / (area_a[:, None] + area_b[None, :] - inter + 1e-7)


def install(verbose: bool = True) -> bool:
    """ops 真崩时才打补丁 → True 表示已打补丁"""
    try:
        import torchvision.ops as ops
    except Exception:                                                      # noqa: BLE001
        return False
    try:                                        # 快速探针: 直接跑一次真 NMS
        ops.nms(torch.tensor([[0.0, 0.0, 1.0, 1.0], [0.1, 0.1, 1.1, 1.1]]),
                torch.tensor([0.9, 0.8]), 0.5)
        return False                            # C++ ops 正常 → 不动
    except Exception as e:                                                 # noqa: BLE001
        reason = f"{type(e).__name__}: {str(e)[:60]}"
    ops.nms = torch_nms
    try:
        ops.batched_nms = torch_batched_nms
    except Exception:                                                      # noqa: BLE001
        pass
    try:
        ops.box_iou = torch_box_iou
    except Exception:                                                      # noqa: BLE001
        pass
    if hasattr(ops, "_assert_has_ops"):
        ops._assert_has_ops = lambda *a, **k: None
    if verbose:
        print(f"[tv_ops_shim] torchvision C++ ops 不可用 ({reason}) → 已切纯 torch NMS/IoU 备用实现 "
              f"(数值等价; 根治办法=装与 torch 匹配的 NVIDIA torchvision)", flush=True)
    return True


if __name__ == "__main__":
    print("shim installed:", install())
