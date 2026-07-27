#!/usr/bin/env python3
"""SmolVLA 原版训练 · PushT · 4060 CUDA"""
import os, sys, torch, time
from lerobot.configs.types import FeatureType, PolicyFeature
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
os.environ["WANDB_MODE"] = "disabled"

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla import SmolVLAConfig, SmolVLAPolicy

DEVICE = "cuda"
OUT = os.path.join(os.path.dirname(__file__), "outputs/smolvla_scratch")
os.makedirs(OUT, exist_ok=True)
EPOCHS, BATCH, LR = 30, 2, 1e-4

print(f"🚀 SmolVLA 原版训练 · PushT · {DEVICE}")
print(f"   GPU: {torch.cuda.get_device_name(0)}")

ds = LeRobotDataset("lerobot/pusht", episodes=range(200))
sample = ds[0]
A_DIM = sample['action'].shape[-1] if 'action' in sample else 2
print(f"   样本: {len(ds)} · action_dim={A_DIM}")

cfg = SmolVLAConfig(
    input_features={"observation.images": PolicyFeature(type=FeatureType.VISUAL, shape=(3,512,512)),
                    "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(2,))},
    output_features={"action": PolicyFeature(type=FeatureType.ACTION, shape=(2,))},
    freeze_vision_encoder=False,
)
policy = SmolVLAPolicy(cfg).to(DEVICE)
print(f"   参数: {sum(p.numel() for p in policy.parameters())/1e6:.1f}M")

opt = torch.optim.AdamW(policy.parameters(), lr=LR)
t0 = time.time()

for ep in range(EPOCHS):
    policy.train()
    loss_sum, n = 0, 0
    for i in range(0, min(len(ds), 200), BATCH):
        batch = [ds[j] for j in range(i, min(i+BATCH, len(ds)))]
        imgs = torch.stack([torch.nn.functional.interpolate(
            torch.tensor(b['observation.image'], dtype=torch.float32).unsqueeze(0),
            size=(512,512), mode='bilinear').squeeze(0) for b in batch])
        imgs = imgs.unsqueeze(1).to(DEVICE)  # [B,1,C,H,W] - single view
        st = torch.stack([torch.tensor(b['observation.state'], dtype=torch.float32) for b in batch]).to(DEVICE)
        act = torch.stack([torch.tensor(b['action'], dtype=torch.float32) for b in batch]).to(DEVICE)
        try:
            # SmolVLA需要语言tokens (PushT没有, 补dummy)
            batch_dict = {
                "observation.images": imgs,
                "observation.state": st,
                "action": act,
                "observation.language.tokens": torch.zeros(BATCH, 1, dtype=torch.long, device=DEVICE),
                "observation.language.attention_mask": torch.ones(BATCH, 1, dtype=torch.long, device=DEVICE),
            }
            loss_dict = policy.forward(batch_dict)
            loss = loss_dict.get("loss", torch.tensor(0.0))
            if loss.requires_grad:
                opt.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
                opt.step()
                loss_sum += loss.item(); n += 1
        except Exception as e:
            if i < 5: print(f"   ⚠️ {e}")
    avg = loss_sum/max(n,1)
    print(f"E{ep+1:02d} loss={avg:.4f} | {time.time()-t0:.0f}s")

policy.save_pretrained(OUT)
print(f"✅ {OUT}")
