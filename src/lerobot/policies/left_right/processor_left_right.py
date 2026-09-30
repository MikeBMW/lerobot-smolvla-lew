"""Z-MAX LeftRight processor: 标准归一化 pre/post (2026-08-10)
参考 act/processor_act.py 结构 (PolicyProcessorPipeline)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from lerobot.processor import (
    AddBatchDimensionProcessorStep,
    DeviceProcessorStep,
    NormalizerProcessorStep,
    PolicyProcessorPipeline,
    RenameObservationsProcessorStep,
    UnnormalizerProcessorStep,
)
from lerobot.utils.constants import POLICY_POSTPROCESSOR_DEFAULT_NAME, POLICY_PREPROCESSOR_DEFAULT_NAME

if TYPE_CHECKING:
    from .configuration_left_right import LeftRightConfig

POLICY_PREPROCESSOR_DEFAULT_NAME = "left_right_preprocessor"
POLICY_POSTPROCESSOR_DEFAULT_NAME = "left_right_postprocessor"


def make_left_right_pre_post_processors(
    config: "LeftRightConfig",
    dataset_stats: dict[str, dict[str, Any]] | None = None,
):
    """创建 pre/post processor (lerobot 标准, 同 act 结构)"""
    if dataset_stats is None:
        dataset_stats = {}
    # 特征: 从 config 读, 默认 39D obs / 4D act (2026-08-10: 标准 PolicyFeature)
    from lerobot.configs.types import FeatureType, PolicyFeature
    def _feat(shape, ftype):
        return PolicyFeature(type=ftype, shape=tuple(shape))
    input_features = config.input_features if config.input_features else {"observation.state": _feat((39,), FeatureType.STATE)}
    output_features = config.output_features if config.output_features else {"action": _feat((4,), FeatureType.ACTION)}
    # 若传入的是 dict, 转 PolicyFeature
    for feat in (input_features, output_features):
        for k, v in feat.items():
            if isinstance(v, dict):
                ftype = FeatureType.STATE if "state" in k else FeatureType.ACTION
                feat[k] = PolicyFeature(type=ftype, shape=tuple(v.get("shape", (39,) if "state" in k else (4,))))

    input_steps = [
        RenameObservationsProcessorStep(rename_map={}),
        AddBatchDimensionProcessorStep(),
        DeviceProcessorStep(device=config.device),
        NormalizerProcessorStep(
            features={**input_features, **output_features},
            norm_map=config.normalization_mapping,
            stats=dataset_stats,
            device=config.device,
        ),
    ]
    output_steps = [
        UnnormalizerProcessorStep(
            features=output_features,
            norm_map=config.normalization_mapping,
            stats=dataset_stats,
        ),
        DeviceProcessorStep(device="cpu"),
    ]
    return (
        PolicyProcessorPipeline(steps=input_steps, name=POLICY_PREPROCESSOR_DEFAULT_NAME),
        PolicyProcessorPipeline(steps=output_steps, name=POLICY_POSTPROCESSOR_DEFAULT_NAME),
    )
