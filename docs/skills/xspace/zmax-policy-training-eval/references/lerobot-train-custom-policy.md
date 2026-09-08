# lerobot_train 自定义 policy 接入完整配方 (2026-08-10 left_right 实测)

目标: 让 `src/lerobot/policies/<name>/` 的自定义 policy 能通过标准
`python -m lerobot.scripts.lerobot_train --config_path config_<name>.yaml` 训练。
失败模式全是 TypeError/ValueError/AttributeError 链, 按下面顺序排查即通。

## 1. 配置 yaml (config_left_right.yaml 骨架)

```yaml
output_dir: outputs/train/left_right_std
job_name: left_right_std

policy:
  type: left_right          # 必须 = PreTrainedConfig.register_subclass 名
  push_to_hub: false
  repo_id: MikeBMW/zmax-left-right
  n_obs_steps: 1
  n_action_steps: 1
  chunk_size: 1
  left_hidden: 512
  right_hidden: 256

dataset:
  repo_id: lerobot/pusht    # 占位, root 用本地
  root: data/metaworld_peg_long   # ⚠️ state 维度必须匹配 policy 输入 (39D!)
  episodes: [0]
  use_imagenet_stats: false

batch_size: 8
steps: 3000
num_workers: 0
persistent_workers: false
log_freq: 5
eval_freq: 0
save_freq: 1000
save_checkpoint: true
seed: 42

optimizer:
  type: adam
  lr: 0.0001                # ⚠️ 不要写 1e-4 (yaml 1.1 解析成字符串)
  weight_decay: 0.0

wandb:
  enable: false
```

坑: `training:` 顶层字段 → `draccus DecodingError: fields training not valid`。

## 2. src 适配清单 (每项对应一个真实报错)

| 组件 | 要求 | 报错 (缺了/错了) |
|---|---|---|
| policy `__init__` | `(self, config=None, dataset_stats=None, dataset_meta=None)` | `unexpected keyword argument 'dataset_meta'/'dataset_stats'` |
| `forward(batch)` | 返回 `(loss, output_dict)` 元组 | `ValueError: not enough values to unpack (expected 2, got 1)` |
| `compute_loss` | `loss, _ = self.forward(batch)` | 同上 |
| `get_optimizer_preset` | 返回 `AdamWConfig` 类 (from lerobot.optim.optimizers) | `'dict' object has no attribute 'build'` |
| `get_optim_params` | 返回 `[{"params": [...]}, ...]` 列表 | `optimizer can only optimize Tensors, but one of the params is str` |
| `normalization_mapping` | 键 = `"STATE"/"ACTION"` (FeatureType) | `ValueError: 'observation.state' is not a valid FeatureType` |
| `input_features/output_features` | `PolicyFeature(type=FeatureType.STATE, shape=(39,))` 对象 | 同上 (`'observation.state' is not a valid FeatureType`) |
| processor | PolicyProcessorPipeline + Rename/AddBatch/Device/Normalizer 标准步骤 | `'DataProcessorPipeline' object is not callable` |

### forward 返回元组示例
```python
out = pred_act.unsqueeze(1) if pred_act.ndim == 2 else pred_act
act_t = batch["action"].float()
if act_t.ndim == 3: act_t = act_t[:, -1]
loss = nn.functional.mse_loss(out.squeeze(1), act_t)
return loss, {"action": out}
```

### processor 骨架 (参考 act/processor_act.py)
```python
from lerobot.processor import (AddBatchDimensionProcessorStep, DeviceProcessorStep,
    NormalizerProcessorStep, PolicyProcessorPipeline, RenameObservationsProcessorStep,
    UnnormalizerProcessorStep)
from lerobot.configs.types import FeatureType, PolicyFeature

def make_<name>_pre_post_processors(config, dataset_stats=None):
    input_features = {"observation.state": PolicyFeature(type=FeatureType.STATE, shape=(39,))}
    output_features = {"action": PolicyFeature(type=FeatureType.ACTION, shape=(4,))}
    pre = PolicyProcessorPipeline(steps=[
        RenameObservationsProcessorStep(rename_map={}),
        AddBatchDimensionProcessorStep(),
        DeviceProcessorStep(device=config.device),
        NormalizerProcessorStep(features={**input_features, **output_features},
            norm_map=config.normalization_mapping, stats=dataset_stats, device=config.device),
    ], name="<name>_preprocessor")
    post = PolicyProcessorPipeline(steps=[
        UnnormalizerProcessorStep(features=output_features,
            norm_map=config.normalization_mapping, stats=dataset_stats),
        DeviceProcessorStep(device="cpu"),
    ], name="<name>_postprocessor")
    return pre, post
```

### factory.py 三处
1. 顶部 import config: `from .left_right.configuration_left_right import LeftRightConfig`
   (触发 register_subclass — 否则 `Unknown policy name`)
2. `_get_policy_cls_from_policy_name` 的 elif 分支 (或 make_policy)
3. make_pre_post_processors 的 `elif isinstance(policy_cfg, LeftRightConfig)` 分支

## 3. 兜底补丁 (可选, config 侧解析成 dict 时的保险)

`src/lerobot/optim/factory.py` make_optimizer_and_scheduler:
```python
optimizer_cfg = cfg.optimizer
if isinstance(optimizer_cfg, dict):
    from lerobot.optim.optimizers import AdamWConfig
    optimizer_cfg = AdamWConfig(lr=optimizer_cfg.get("lr", 1e-4),
        weight_decay=optimizer_cfg.get("weight_decay", 0.0),
        grad_clip_norm=optimizer_cfg.get("grad_clip_norm", 10.0))
optimizer = optimizer_cfg.build(params)
# scheduler 同理会是 dict → 跳过 (None)
```

## 4. 验证与信号

- 快速: `make_<name>_pre_post_processors(config, {})` → pre/post 均 `callable(pre) == True`
- 训练打通信号: `Training: 33% |███| 1000/3000 [00:31]` + `loss: 0.219→0.073` + checkpoint 001000
- left_right 实测: 30 step/s, mem 0.03GB (轻量 policy 秒级迭代)

## 5. 遗留: PolicyFeature JSON 序列化 (2026-08-10 未修)

checkpoint 保存报 `TypeError: Object of type PolicyFeature is not JSON serializable`。
save_pretrained/checkpoint 序列化 input_features 时转 dict:
`{"type": ft.type.value, "shape": list(ft.shape)}`。修完即可完整跑满 steps。
