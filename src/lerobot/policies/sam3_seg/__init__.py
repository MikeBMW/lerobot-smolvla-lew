# -*- coding: utf-8 -*-
"""开放词汇分割 (SAM3 分割 anything) —— L2 感知原语

与 `policies/yolo_3d/` **同级**放在 policies/ 下 (老倪 2026-09-29 纠正): 感知前端与各策略
同层级统一管理 —— 策略(动作) 与 感知(状态输入) 都在这里; `tools/` 只留**调用方**
(CLI / 常驻服务 / 叠加规格 / 画布节点胶水)。

分层口径 (别越层):
  · **L2 能力**: 一帧图 + 概念提示词(文本/框/点) → 该概念的**所有实例掩膜**(像素级) + 框 + 分数。
    与 L2-A01「YOLO 目标检测」同类, 差别是 ①掩膜不是框 ②开放词汇(概念来自提示词, 不靠固定类别)。
  · **L5 意图**: 概念短语/负框/点由 L5(VLM/人/工单)给 —— 本包不自己编概念。
  · **不进 L3/L4**: 不产动作、不编排技能序列、不预测不规划, 不是世界模型。

模块:
- segmenter.py   模型加载 + 前向 + 掩膜/多边形 (Sam3Segmenter)
- geometry3d.py  掩膜 → base 系 3D (深度/手眼/TCP 缺一环就如实拒答)
- frame_source.py 帧来源 (推流服务原始帧 / 本地图)

用法:
    from lerobot.policies.sam3_seg import segment, mask_to_polys, mask_3d, grab_frame
    seg = segment(img_bgr, ["光模块"])
    for it in seg["instances"]:
        print(it["label"], it["area_px"], mask_3d(it["mask"], "arm"))

权重: 官方 facebook/sam3 在 HF 是 gated(需审批) ⇒ 本机用逐文件镜像落盘, 一律 local_files_only 加载。
许可: SAM License (允许商用; 禁军事/ITAR; 再分发须附 LICENSE)。
"""
from .frame_source import SNAPSHOT_HOST, SNAPSHOT_PORT, grab_frame, read_image
from .geometry3d import DEPTH_DEAD_S, depth_status, mask_3d
from .segmenter import (
    DEFAULT,
    MIN_AREA_PX,
    POLY_EPS_PX,
    SAM3_DIR,
    SAM3_DTYPE,
    SAM3_SIZE,
    Sam3Segmenter,
    load_model,
    mask_to_polys,
    segment,
    state,
    unload_model,
)

__all__ = [
    "Sam3Segmenter", "DEFAULT", "load_model", "unload_model", "state",
    "segment", "mask_to_polys", "mask_3d", "depth_status",
    "grab_frame", "read_image",
    "SAM3_DIR", "SAM3_DTYPE", "SAM3_SIZE", "MIN_AREA_PX", "POLY_EPS_PX",
    "DEPTH_DEAD_S", "SNAPSHOT_HOST", "SNAPSHOT_PORT",
]
