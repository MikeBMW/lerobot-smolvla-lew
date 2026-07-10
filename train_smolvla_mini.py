#!/usr/bin/env python3
"""最小化SmolVLA-LEW训练 — pusht数据集, MPS加速, 小模型"""
import os, sys, torch, time, json
os.environ["WANDB_MODE"] = "disabled"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla_lew import SmolVLALewConfig, SmolVLALewPolicy

# ═══ 配置 ═══
DATASET = "lerobot/pusht"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs/train/smolvla_lew_mini")
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
EPOCHS = 5
BATCH_SIZE = 1  # MPS 内存有限
LR = 1e-4

print(f"🚀 训练 SmolVLA-LEW on {DATASET}")
print(f"   设备: {DEVICE}")
print(f"   输出: {OUTPUT_DIR}")

# ═══ 加载数据集 ═══
print("\n📊 加载数据集...")
dataset = LeRobotDataset(DATASET, split="train")
print(f"   样本数: {len(dataset)}")
print(f"   特征: {dataset.features}")
sample = dataset[0]
print(f"   样本键: {list(sample.keys())}")
print(f"   action shape: {sample.get('action', sample.get('action.action', '?'))}")

# 获取 actions 维度
if 'action' in sample:
    action = sample['action']
elif 'action.action' in sample:
    action = sample['action.action']
else:
    # 尝试找action相关字段
    import pdb; pdb.set_trace()

if hasattr(action, 'shape'):
    action_dim = action.shape[-1] if len(action.shape) > 0 else 1
else:
    action_dim = len(action) if isinstance(action, (list, tuple)) else 1
print(f"   action_dim: {action_dim}")

# ═══ 创建模型 ═══
print("\n🧠 创建模型...")
config = SmolVLALewConfig(
    input_shapes={"observation.image": [3, 64, 64], "observation.state": [2], "action": [action_dim]},
    output_shapes={"action": [action_dim]},
    smolvlm_name="HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    freeze_smolvlm=True,
    action_model_type="DiT-B",
    action_hidden_size=256,  # 更小
    action_num_layers=1,     # 最小
    num_inference_timesteps=2,
)
policy = SmolVLALewPolicy(config)
policy.to(DEVICE)

# 只训练 action head
trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
total = sum(p.numel() for p in policy.parameters())
print(f"   总参数: {total:,}  可训练: {trainable:,} ({100*trainable/total:.1f}%)")

# ═══ 训练 ═══
optimizer = torch.optim.AdamW(policy.parameters(), lr=LR)
policy.train()

print(f"\n🏋️ 开始训练 ({EPOCHS} epochs)...")
start = time.time()
for epoch in range(EPOCHS):
    epoch_loss = 0.0
    n_batches = 0
    for i in range(0, min(len(dataset), 200), BATCH_SIZE):  # 最多200样本
        batch = dataset[i:i+BATCH_SIZE]
        
        # 提取数据
        images = torch.tensor(batch['observation.image'], dtype=torch.float32).to(DEVICE)
        state = torch.tensor(batch['observation.state'], dtype=torch.float32).to(DEVICE)
        if 'action' in batch:
            actions = torch.tensor(batch['action'], dtype=torch.float32).to(DEVICE)
        else:
            actions = torch.tensor(batch['action.action'], dtype=torch.float32).to(DEVICE)
        
        # 添加batch维度
        if images.dim() == 3: images = images.unsqueeze(0)
        if state.dim() == 1: state = state.unsqueeze(0)
        if actions.dim() == 1: actions = actions.unsqueeze(0)
        
        optimizer.zero_grad()
        try:
            loss = policy.compute_loss(images, state, actions)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            n_batches += 1
        except Exception as e:
            print(f"   ⚠️ Batch {i} error: {e}")
            continue
    
    avg_loss = epoch_loss / max(n_batches, 1)
    elapsed = time.time() - start
    print(f"   Epoch {epoch+1}/{EPOCHS}  loss={avg_loss:.4f}  time={elapsed:.0f}s  batches={n_batches}")

# ═══ 保存 ═══
os.makedirs(OUTPUT_DIR, exist_ok=True)
policy.save_pretrained(OUTPUT_DIR)
torch.save({"config": config.to_dict(), "epoch": EPOCHS, "loss": avg_loss}, 
           os.path.join(OUTPUT_DIR, "training_state.pt"))
print(f"\n✅ 模型已保存到 {OUTPUT_DIR}")
print(f"   总耗时: {time.time()-start:.0f}s")
