"""
SmolVLA 训练逐步调试脚本
每到一个阶段自动暂停，你可以用 pdb 命令查看当前状态
"""

import os
import sys

# 让 HuggingFace 用本地缓存，不要联网下载
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

print("=" * 60)
print("阶段0：导入库")
print("=" * 60)

import torch
import numpy as np

print(f"  PyTorch: {torch.__version__}")
print(f"  CUDA: {torch.cuda.is_available()}")
print(f"  GPU: {torch.cuda.get_device_name(0)}")
print()

# ============================================================
breakpoint()  # 停！输入 c 继续
# ============================================================

print("=" * 60)
print("阶段1：创建配置对象 SmolVLAConfig")
print("=" * 60)

from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig

config = SmolVLAConfig()
config.device = "cuda"
config.batch_size = 1

print(f"  type: {config.type}")
print(f"  vlm_model: {config.vlm_model_name}")
print(f"  chunk_size: {config.chunk_size}")
print(f"  num_steps: {config.num_steps}")
print(f"  train_expert_only: {config.train_expert_only}")
print(f"  freeze_vision_encoder: {config.freeze_vision_encoder}")
print(f"  max_state_dim: {config.max_state_dim}")
print(f"  max_action_dim: {config.max_action_dim}")
print(f"  load_vlm_weights: {config.load_vlm_weights}")
print()

# ============================================================
breakpoint()  # 停！输入 c 继续
# ============================================================

print("=" * 60)
print("阶段2：加载数据集")
print("=" * 60)

from lerobot.datasets.factory import make_dataset
from lerobot.configs.train import TrainPipelineConfig
from lerobot.configs.default import DatasetConfig

# 构建最小训练配置
cfg = TrainPipelineConfig(dataset=DatasetConfig(repo_id="lerobot/pusht"))
cfg.policy = config
cfg.batch_size = 1

print("  调用 make_dataset(cfg) ...")
dataset = make_dataset(cfg)

print(f"  数据集帧数: {dataset.num_frames}")
print(f"  episode数: {dataset.num_episodes}")
print(f"  特征: {list(dataset.features.keys())}")
print(f"  动作维度: {dataset.meta.shapes['action']}")
print(f"  状态维度: {dataset.meta.shapes['observation.state']}")
print(f"  图像尺寸(原始): {dataset.meta.shapes[dataset.meta.camera_keys[0]]}")
print()

# 取一个样本看看
sample = dataset[0]
print(f"  第0帧:")
print(f"    action shape: {sample['action'].shape}")
print(f"    action[:3]: {sample['action'][:3]}")  # 前3步动作
print(f"    state shape: {sample['observation.state'].shape}")
print(f"    state: {sample['observation.state']}")
print(f"    task: {sample.get('task', 'N/A')}")
print()

# ============================================================
breakpoint()  # 停！输入 c 继续
# ============================================================

print("=" * 60)
print("阶段3：创建 SmolVLA 模型")
print("=" * 60)

from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.configs import PolicyFeature, FeatureType
from lerobot.utils.constants import OBS_IMAGES, ACTION

# 设置输入输出特征（从数据集自动推断）
image_keys = [k.replace("observation.", "") for k in dataset.meta.camera_keys]
state_dim = dataset.meta.shapes["observation.state"][0]
action_dim = dataset.meta.shapes["action"][0]

config.input_features = {}
for k in dataset.meta.camera_keys:
    config.input_features[k] = PolicyFeature(
        type=FeatureType.VISUAL, shape=(3, 480, 640)
    )
config.output_features = {
    ACTION: PolicyFeature(type=FeatureType.ACTION, shape=(action_dim,))
}
config.max_action_dim = max(32, action_dim)
config.max_state_dim = max(32, state_dim)

print(f"  camera keys: {list(dataset.meta.camera_keys)}")
print(f"  action_dim: {action_dim}, max_action_dim: {config.max_action_dim}")
print(f"  state_dim: {state_dim}, max_state_dim: {config.max_state_dim}")
print(f"  image shape (dataset原始): {dataset.meta.shapes[dataset.meta.camera_keys[0]]}")
print()
print("  创建模型（加载VLM + 构建Expert）...")
print()

policy = SmolVLAPolicy(config)
policy = policy.cuda()

total = sum(p.numel() for p in policy.parameters())
trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
print(f"  总参数: {total:,}")
print(f"  可训练: {trainable:,}")

# 显示哪些模块可训练
for name, p in policy.named_parameters():
    if p.requires_grad:
        print(f"    可训练: {name} [{list(p.shape)}]")
        break  # 只打印第一个
print()

# ============================================================
breakpoint()  # 停！输入 c 继续
# ============================================================

print("=" * 60)
print("阶段4：创建优化器")
print("=" * 60)

optimizer = torch.optim.AdamW(
    policy.parameters(),
    lr=config.optimizer_lr,
    betas=config.optimizer_betas,
    eps=config.optimizer_eps,
    weight_decay=config.optimizer_weight_decay,
)

print(f"  优化器: AdamW")
print(f"  lr: {config.optimizer_lr}")
print(f"  betas: {config.optimizer_betas}")
print(f"  参数组数: {len(optimizer.param_groups)}")
print(f"  参数数量(可训练): {sum(p.numel() for pg in optimizer.param_groups for p in pg['params'] if p.requires_grad):,}")
print(f"  (优化器存储了全部{sum(p.numel() for pg in optimizer.param_groups for p in pg['params']):,}个参数的引用，但只更新requires_grad=True的)")
print()

# ============================================================
breakpoint()  # 停！输入 c 继续
# ============================================================

print("=" * 60)
print("阶段5：准备一个训练batch")
print("=" * 60)

from lerobot.utils.constants import OBS_STATE, OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
# 构建模型需要的batch字典
device = "cuda"
raw_batch = dataset[0]  # 取第0帧（数据集已自动返回chunk）

batch = {
    OBS_STATE: raw_batch["observation.state"].to(device).squeeze(0).unsqueeze(0),  # (1, 2)
    ACTION: raw_batch["action"].to(device).unsqueeze(0),  # (1, 50, 2)
}

# 图片
for k in dataset.meta.camera_keys:
    img = raw_batch[k].to(device)  # (3, 96, 96), uint8
    img = img.float() / 255.0  # 转float, [0,255]→[0,1]
    if img.ndim == 3:
        img = img.unsqueeze(0)  # (1, 3, 96, 96)
    batch[k] = img

# 语言指令
if "task" in raw_batch:
    task = raw_batch["task"]
    print(f"  任务指令: {task}")
    # 用VLM的tokenizer编码
    tokenizer = policy.model.vlm_with_expert.processor.tokenizer
    tokens = tokenizer([task], return_tensors="pt", padding="max_length", max_length=48, truncation=True)
    batch[OBS_LANGUAGE_TOKENS] = tokens["input_ids"].to(device)
    batch[OBS_LANGUAGE_ATTENTION_MASK] = tokens["attention_mask"].bool().to(device)
else:
    # 如果没有task字段，造一个
    batch[OBS_LANGUAGE_TOKENS] = torch.zeros(1, 48, dtype=torch.long, device=device)
    batch[OBS_LANGUAGE_ATTENTION_MASK] = torch.ones(1, 48, dtype=torch.bool, device=device)

print(f"  batch keys: {list(batch.keys())}")
for k, v in batch.items():
    print(f"    {k}: shape={list(v.shape)}, dtype={v.dtype}")
print()

# ============================================================
breakpoint()  # 停！输入 c 继续
# ============================================================

print("=" * 60)
print("阶段6：前向传播（计算loss）")
print("=" * 60)

policy.train()  # 训练模式

print("  调用 policy.forward(batch) ...")
print("  内部流程：")
print("    1. prepare_images  → 图片缩放+填充+归一化")
print("    2. prepare_state   → 状态填充到max_state_dim")
print("    3. prepare_action  → 动作填充到max_action_dim")
print("    4. embed_prefix    → 图像+语言+状态 → VLM → KV Cache")
print("    5. embed_suffix    → 加噪声+时间编码 → Expert输入")
print("    6. vlm_with_expert → Expert读取KV Cache，预测去噪方向")
print("    7. action_out_proj → 投影回动作空间")
print("    8. MSE loss        → 对比预测和真实值")
print()

# ============================================================
breakpoint()  # 停！输入 c 继续，然后实际执行 forward
# ============================================================

loss, loss_dict = policy.forward(batch)

print(f"  loss: {loss:.6f}")
print(f"  loss_dict: {loss_dict}")
print()

# ============================================================
breakpoint()  # 停！输入 c 继续
# ============================================================

print("=" * 60)
print("阶段7：反向传播（计算梯度）")
print("=" * 60)

print(f"  反向传播前 - state_proj.weight.grad = {policy.model.state_proj.weight.grad}")
print("  执行 loss.backward() ...")

if isinstance(loss, torch.Tensor):
    loss.backward()
else:
    # reduction='none' 时返回的是per-sample loss
    loss.mean().backward()

print(f"  反向传播后 - state_proj.weight.grad 范数 = {policy.model.state_proj.weight.grad.norm().item():.4f}")
print()

# ============================================================
breakpoint()  # 停！输入 c 继续
# ============================================================

print("=" * 60)
print("阶段8：优化器更新参数")
print("=" * 60)

# 保存更新前的参数
before = policy.model.state_proj.weight.clone().detach()

print("  执行 optimizer.step() ...")
optimizer.step()
optimizer.zero_grad()

after = policy.model.state_proj.weight.detach()
diff = (after - before).norm().item()
print(f"  state_proj.weight 变化量: {diff:.6f}")
print(f"  梯度已清零: state_proj.weight.grad = {policy.model.state_proj.weight.grad}")
print()

# ============================================================
breakpoint()  # 停！最后一站
# ============================================================

print("=" * 60)
print("训练一步完成！")
print("=" * 60)
print()
print("总结这一轮发生了什么：")
print(f"  1. 加载了 PushT 数据集（{dataset.num_frames}帧，{dataset.num_episodes}个episode）")
print(f"  2. 创建了 SmolVLA 模型（{total:,}参数，{trainable:,}可训练）")
print(f"  3. 取了一个batch：1帧图片+状态+语言指令+对应动作")
print(f"  4. 前向传播：loss = {loss:.4f}")
print(f"  5. 反向传播：计算了所有可训练参数的梯度")
print(f"  6. 优化器更新：参数朝减小loss的方向移动了一步")
print()
print("这6步循环20万次，就是完整的训练过程。")
print("现在你可以用 pdb 命令检查任何变量，比如：")
print("  p policy.model.state_proj.weight.shape")
print("  p list(policy.named_parameters())")
print("  输入 q 退出")
