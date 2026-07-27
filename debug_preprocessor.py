#!/usr/bin/env python3
"""调试：检查preprocessor输出"""
import torch

device = torch.device("cuda")
from lerobot.datasets import LeRobotDataset, LeRobotDatasetMetadata
from lerobot.configs import FeatureType
from lerobot.policies import make_pre_post_processors
from lerobot.policies.smolvla import SmolVLAConfig
from lerobot.utils.feature_utils import dataset_to_policy_features
from torch.utils.data import DataLoader
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK

repo = "lerobot/pusht"
ds = LeRobotDataset(repo, episodes=[0,1,2])
meta = LeRobotDatasetMetadata(repo)
features = dataset_to_policy_features(meta.features)
output_features = {k: v for k, v in features.items() if v.type is FeatureType.ACTION}
input_features = {k: v for k, v in features.items() if k not in output_features}

print(f"Input features: {list(input_features.keys())}")
print(f"Output features: {list(output_features.keys())}")

cfg = SmolVLAConfig(
    input_features=input_features,
    output_features=output_features,
    tokenizer_max_length=48,
    freeze_vision_encoder=True, train_expert_only=True,
)
preprocessor, _ = make_pre_post_processors(cfg, dataset_stats=meta.stats)

loader = DataLoader(ds, batch_size=1, shuffle=False, num_workers=0)
batch = next(iter(loader))
batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
print(f"\nBefore preprocessor keys: {list(batch.keys())}")

batch = preprocessor(batch)
print(f"\nAfter preprocessor keys: {list(batch.keys())}")
for k, v in batch.items():
    if isinstance(v, torch.Tensor):
        print(f"  {k}: shape={v.shape}, dtype={v.dtype}")
    else:
        print(f"  {k}: type={type(v).__name__}, val={v}")

# Check language tokens
if OBS_LANGUAGE_TOKENS in batch:
    lt = batch[OBS_LANGUAGE_TOKENS]
    lm = batch[OBS_LANGUAGE_ATTENTION_MASK]
    print(f"\nLanguage tokens: shape={lt.shape}, valid tokens={(lt > 0).sum().item()}/{lt.shape[1]}")
    print(f"Language mask: shape={lm.shape}, active={lm.sum().item()}")
