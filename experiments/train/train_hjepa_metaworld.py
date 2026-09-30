#!/usr/bin/env python3
"""Z-MAX H-JEPA Hybrid v3.1 · MetaWorld全量训练 · 从头开始"""
import torch, torch.nn as nn, numpy as np, time, os, sys
from torch.utils.data import DataLoader
from datasets import load_dataset

# ═══ 配置 ═══
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH_SIZE = 8
EPOCHS = 100
LR = 3e-4
IMG_SIZE = 64
STATE_DIM = 39
ACTION_DIM = 4
Z_DIM = 256
HIDDEN_DIM = 512
OUT_DIR = "/home/xspace/lerobot-smolvla-lew/outputs/hjepa_hybrid_metaworld"
os.makedirs(OUT_DIR, exist_ok=True)

print(f"╔═══════════════════════════════════╗")
print(f"║  Z-MAX H-JEPA Hybrid v3.1        ║")
print(f"║  MetaWorld MT50 全量训练         ║")
print(f"║  Device: {DEVICE}                    ║")
print(f"╚═══════════════════════════════════╝")

# ═══ H-JEPA Hybrid 模型 ═══
class HJEPA_Hybrid(nn.Module):
    """H-JEPA v3.1: Vision Encoder + State Encoder + Latent Predictor + Action Decoder"""
    def __init__(self):
        super().__init__()
        # 视觉编码器: 64x64x3 → Z_DIM
        self.v_enc = nn.Sequential(
            nn.Conv2d(3, 32, 4, 2), nn.ReLU(),
            nn.Conv2d(32, 64, 4, 2), nn.ReLU(),
            nn.Conv2d(64, 128, 4, 2), nn.ReLU(),
            nn.Conv2d(128, 256, 3, 2), nn.ReLU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(),
            nn.Linear(256, Z_DIM)
        )
        # 状态编码器: STATE_DIM → Z_DIM
        self.s_proj = nn.Linear(STATE_DIM, Z_DIM)
        # Latent融合: 2*Z_DIM → HIDDEN_DIM
        self.fusion = nn.Sequential(
            nn.Linear(Z_DIM*2, HIDDEN_DIM), nn.ReLU(),
            nn.Linear(HIDDEN_DIM, HIDDEN_DIM//2), nn.ReLU(),
            nn.Linear(HIDDEN_DIM//2, Z_DIM)
        )
        # JEPA预测头: Z_DIM → Z_DIM (预测未来表征)
        self.predictor = nn.Sequential(
            nn.Linear(Z_DIM, HIDDEN_DIM//2), nn.ReLU(),
            nn.Linear(HIDDEN_DIM//2, Z_DIM)
        )
        # Action解码: Z_DIM → ACTION_DIM
        self.a_dec = nn.Sequential(
            nn.Linear(Z_DIM, HIDDEN_DIM//2), nn.ReLU(),
            nn.Linear(HIDDEN_DIM//2, ACTION_DIM)
        )

    def forward(self, img, state):
        vz = self.v_enc(img)           # [B, Z_DIM]
        sz = self.s_proj(state)        # [B, Z_DIM]
        z = self.fusion(torch.cat([vz, sz], -1))  # [B, Z_DIM]
        z_pred = self.predictor(z)     # 未来表征预测
        action = self.a_dec(z)         # 动作输出
        return action, z, z_pred, vz, sz

# ═══ 加载数据 ═══
print("\n📥 加载MetaWorld MT50数据集...")
ds = load_dataset("lerobot/metaworld_mt50", split="train")
print(f"   episodes: {len(ds)} | features: {list(ds.features.keys())}")

# 自动检测维度
sample = ds[0]
STATE_DIM = len(sample['observation.state'])
ACTION_DIM = len(sample['action'])
IMG_SIZE = 64
Z_DIM = 256
HIDDEN_DIM = 512
OUT_DIR = "/home/xspace/lerobot-smolvla-lew/outputs/hjepa_hybrid_metaworld"
os.makedirs(OUT_DIR, exist_ok=True)
print(f"   STATE_DIM={STATE_DIM} | ACTION_DIM={ACTION_DIM}")

def collate(batch):
    imgs, states, actions = [], [], []
    for b in batch:
        img = torch.tensor(np.array(b['observation.image'])).permute(2,0,1).float()/255.0
        img = torch.nn.functional.interpolate(img.unsqueeze(0), (IMG_SIZE,IMG_SIZE), mode='bilinear').squeeze(0)
        state = torch.tensor(b['observation.state'], dtype=torch.float32)
        action = torch.tensor(b['action'], dtype=torch.float32)
        imgs.append(img); states.append(state); actions.append(action)
    return torch.stack(imgs), torch.stack(states), torch.stack(actions)

loader = DataLoader(ds, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate, num_workers=2, prefetch_factor=2)
print(f"   batch_size: {BATCH_SIZE} | batches: {len(loader)}")

# ═══ 训练 ═══
model = HJEPA_Hybrid().to(DEVICE)
optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, EPOCHS)
mse = nn.MSELoss()

print(f"\n🚀 训练开始 · {EPOCHS} epochs · {sum(p.numel() for p in model.parameters())/1e6:.1f}M参数\n")
log_file = open(f"{OUT_DIR}/training_log.txt", "w")
log_file.write("epoch,loss,latent_loss,action_loss,lr\n")
best_loss = float('inf')
t0 = time.time()

for epoch in range(EPOCHS):
    model.train()
    total_loss, total_latent, total_action = 0, 0, 0
    
    for img, state, action in loader:
        img, state, action = img.to(DEVICE), state.to(DEVICE), action.to(DEVICE)
        
        # 直接监督学习: image+state → action
        action_pred, z, z_pred, vz, sz = model(img, state)
        
        action_loss = mse(action_pred, action)
        latent_loss = mse(z_pred, z.detach())  # 自监督一致性
        loss = action_loss + 0.1 * latent_loss
        
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        
        total_loss += loss.item()
        total_latent += latent_loss.item()
        total_action += action_loss.item()
    
    scheduler.step()
    n_batches = len(loader)
    avg_loss = total_loss / n_batches
    avg_latent = total_latent / n_batches
    avg_action = total_action / n_batches
    
    log_file.write(f"{epoch},{avg_loss:.6f},{avg_latent:.6f},{avg_action:.6f},{scheduler.get_last_lr()[0]:.6f}\n")
    
    # 每个epoch报告
    elapsed = time.time() - t0
    print(f"  E{epoch:03d} | loss={avg_loss:.4f} latent={avg_latent:.4f} action={avg_action:.4f} | LR={scheduler.get_last_lr()[0]:.2e} | {elapsed:.0f}s")
    
    # 保存最佳模型
    if avg_loss < best_loss:
        best_loss = avg_loss
        torch.save(model.state_dict(), f"{OUT_DIR}/best_model.pt")
    
    # 每10 epoch checkpoint
    if (epoch+1) % 10 == 0:
        torch.save({"epoch": epoch, "model": model.state_dict(), "optimizer": optimizer.state_dict()}, f"{OUT_DIR}/checkpoint_e{epoch+1}.pt")

log_file.close()
torch.save(model.state_dict(), f"{OUT_DIR}/final_model.pt")
elapsed = time.time() - t0

# ═══ 报告 ═══
print(f"\n╔═══════════════════════════════════╗")
print(f"║  ✅ 训练完成                      ║")
print(f"║  Epochs: {EPOCHS}                     ║")
print(f"║  Time: {elapsed/60:.1f}min              ║")
print(f"║  Best Loss: {best_loss:.4f}             ║")
print(f"║  Model: {OUT_DIR}/best_model.pt ║")
print(f"╚═══════════════════════════════════╝")
