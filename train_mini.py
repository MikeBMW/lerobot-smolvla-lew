#!/usr/bin/env python3
"""SmolVLA-LEW最小训练 — pusht, MPS, action-head only"""
import os, sys, torch, time, json
os.environ["WANDB_MODE"] = "disabled"
sys.path.insert(0, "src")

from lerobot.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
from lerobot.policies.smolvla_lew import SmolVLALewConfig, SmolVLALewPolicy

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
OUT = "outputs/train/smolvla_lew_pusht"
DATASET = "lerobot/pusht"
EPOCHS = 5
BS = 1
LR = 1e-4

print(f"🚀 SmolVLA-LEW 训练  |  {DATASET}  |  {DEVICE}")

# ── 数据集 ──
ds = LeRobotDataset(DATASET)
print(f"📊 {len(ds)} 样本, 动作维度: {ds.action_dim()}")

# ── 模型 ──
cfg = SmolVLALewConfig()
cfg.input_shapes = {"observation.image": [3, 64, 64], "observation.state": [ds.state_dim()], "action": [ds.action_dim()]}
cfg.output_shapes = {"action": [ds.action_dim()]}
cfg.smolvlm_name = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
cfg.freeze_smolvlm = True
cfg.action_hidden_size = 256
cfg.action_num_layers = 1
cfg.num_inference_timesteps = 2

model = SmolVLALewPolicy(cfg).to(DEVICE)
t = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f"🧠 总参数 {sum(p.numel() for p in model.parameters()):,} | 可训练 {t:,}")

opt = torch.optim.AdamW(model.parameters(), lr=LR)
model.train()

# ── 训练 ──
print(f"🏋️ {EPOCHS} epochs...")
t0 = time.time()
for ep in range(EPOCHS):
    total_loss, n = 0.0, 0
    for i in range(0, min(len(ds), 200), BS):
        batch = ds[i:i+BS]
        # 转为tensor
        b = {}
        for k, v in batch.items():
            if isinstance(v, torch.Tensor):
                b[k] = v.to(DEVICE)
            elif isinstance(v, (list, tuple)):
                b[k] = torch.tensor(v).to(DEVICE)
            else:
                b[k] = v
        try:
            loss, _ = model.forward(b)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total_loss += loss.item()
            n += 1
        except Exception as e:
            if i == 0:
                print(f"⚠️ Error: {e}")
    print(f"  Epoch {ep+1}: loss={total_loss/max(n,1):.4f}  ({n} batches)")

# ── 保存 ──
os.makedirs(OUT, exist_ok=True)
model.save_pretrained(OUT)
torch.save(cfg, f"{OUT}/config.pt")
print(f"\n✅ 训练完成! {time.time()-t0:.0f}s → {OUT}")
