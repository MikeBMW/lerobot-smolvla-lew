#!/usr/bin/env python3
"""Z-MAX H-JEPA Hybrid v3.1 · 三层潜空间预测 · z₀→z₁→z₂→Action"""
import torch, torch.nn as nn, numpy as np, time, os
from torch.utils.data import DataLoader
from datasets import load_dataset

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH, EPOCHS, LR = 8, 100, 3e-4
IMG_SIZE = 64

print(f"╔═══════════════════════════════════╗")
print(f"║  Z-MAX H-JEPA v3.1 · 三层z流转   ║")
print(f"╚═══════════════════════════════════╝")

# 自动检测维度
ds = load_dataset("lerobot/metaworld_mt50", split="train")
sample = ds[0]
S_DIM = len(sample['observation.state'])
A_DIM = len(sample['action'])
Z_DIM = 128
H_DIM = 256
print(f"S_DIM={S_DIM} A_DIM={A_DIM} | Z_DIM={Z_DIM}")

class ThreeLevelJEPA(nn.Module):
    """z₀→z₁→z₂ 三层潜空间预测 + Action解码"""
    def __init__(self):
        super().__init__()
        # z₀: 视觉+状态 → 第一层潜空间
        self.v_enc = nn.Sequential(
            nn.Conv2d(3,32,4,2),nn.ReLU(),nn.Conv2d(32,64,4,2),nn.ReLU(),
            nn.Conv2d(64,128,4,2),nn.ReLU(),nn.Conv2d(128,256,3,2),nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),nn.Flatten(),nn.Linear(256,Z_DIM)
        )
        self.s_proj = nn.Linear(S_DIM, Z_DIM)
        self.to_z0 = nn.Sequential(nn.Linear(Z_DIM*2,Z_DIM), nn.ReLU(), nn.Linear(Z_DIM,Z_DIM))

        # z₀ → z₁: 第一层预测第二层（短时预测 ~0.5s）
        self.jepa_01 = nn.Sequential(
            nn.Linear(Z_DIM, H_DIM), nn.ReLU(),
            nn.Linear(H_DIM, Z_DIM)
        )
        # z₁ → z₂: 第二层预测第三层（长时预测 ~5s）
        self.jepa_12 = nn.Sequential(
            nn.Linear(Z_DIM, H_DIM), nn.ReLU(),
            nn.Linear(H_DIM, Z_DIM)
        )
        # z₀→z₁→z₂ 级联
        self.cascade = nn.Sequential(
            nn.Linear(Z_DIM, H_DIM), nn.ReLU(),
            nn.Linear(H_DIM, H_DIM//2), nn.ReLU(),
        )
        # z₂ → Action
        self.a_dec = nn.Sequential(
            nn.Linear(H_DIM//2, H_DIM//4), nn.ReLU(),
            nn.Linear(H_DIM//4, A_DIM)
        )

    def forward(self, img, state):
        # z₀: 感知层 (当前时刻)
        vz = self.v_enc(img)
        sz = self.s_proj(state)
        z0 = self.to_z0(torch.cat([vz, sz], -1))

        # z₁: 预测层 (0.5s后)
        z1_pred = self.jepa_01(z0)

        # z₂: 规划层 (5s后)
        z2_pred = self.jepa_12(z1_pred)

        # Action: 从z₂级联解码
        z2 = self.cascade(z0)
        action = self.a_dec(z2)

        return action, z0, z1_pred, z2_pred, z2

model = ThreeLevelJEPA().to(DEVICE)
print(f"参数: {sum(p.numel() for p in model.parameters())/1e6:.2f}M")

# 数据加载
def collate(batch):
    imgs, states, actions = [], [], []
    for b in batch:
        img = torch.tensor(np.array(b['observation.image'])).permute(2,0,1).float()/255.0
        img = nn.functional.interpolate(img.unsqueeze(0),(IMG_SIZE,IMG_SIZE),mode='bilinear').squeeze(0)
        imgs.append(img); states.append(torch.tensor(b['observation.state'],dtype=torch.float32))
        actions.append(torch.tensor(b['action'],dtype=torch.float32))
    return torch.stack(imgs), torch.stack(states), torch.stack(actions)

loader = DataLoader(ds, batch_size=BATCH, shuffle=True, collate_fn=collate, num_workers=2)

optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, EPOCHS)
mse = nn.MSELoss()
OUT = "/home/xspace/lerobot-smolvla-lew/outputs/hjepa_3level"
os.makedirs(OUT, exist_ok=True)

print(f"🚀 训练 {EPOCHS} epochs · {len(loader)} batches/epoch\n")
best_loss = float('inf')
t0 = time.time()

for epoch in range(EPOCHS):
    model.train()
    total, a_loss, l01, l12, l2 = 0, 0, 0, 0, 0
    n = 0

    for img, state, action in loader:
        img, state, action = img.to(DEVICE), state.to(DEVICE), action.to(DEVICE)
        B = img.shape[0]
        if B < 3: continue

        # 取3帧窗口: 当前(t) → 10帧后(t+10) → 50帧后(t+50)
        stride = max(1, B // 3)
        img_t, img_t10, img_t50 = img[0:B:stride][:3], img[stride:B+stride:stride][:3], img[2*stride:B+2*stride:stride][:3]
        state_t = state[0:B:stride][:3]
        action_t = action[0:B:stride][:3]

        if len(img_t) < 3: img_t=img[:3]; img_t10=img[1:4]; img_t50=img[2:5]; state_t=state[:3]; action_t=action[:3]
        if len(img_t) < 3: continue

        # 三层前向
        _, z0_now, _, _, _ = model(img_t, state_t)
        _, _, z1_now, _, _ = model(img_t10, state_t)
        _, _, _, z2_now, _ = model(img_t50, state_t)

        # 训练: 用当前z0预测未来z1/z2
        _, z0, z1p, z2p, z2 = model(img[0:3], state[0:3])

        loss_01 = mse(z1p, z1_now.detach())   # z0→z1预测损失
        loss_12 = mse(z2p, z2_now.detach())   # z1→z2预测损失
        loss_2 = mse(z2, z2_now.detach())     # 级联z2一致性
        loss_a = mse(model.a_dec(z2), action[0:3]) # Action损失

        loss = loss_a + 0.3*loss_01 + 0.2*loss_12 + 0.1*loss_2
        optimizer.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        total += loss.item(); a_loss += loss_a.item()
        l01 += loss_01.item(); l12 += loss_12.item(); l2 += loss_2.item()
        n += 1

    scheduler.step()
    if n == 0: continue
    avg = total/n; aa = a_loss/n; a01 = l01/n; a12 = l12/n; a2 = l2/n

    elapsed = time.time() - t0
    print(f"E{epoch:03d} | Loss={avg:.4f} act={aa:.4f} J01={a01:.4f} J12={a12:.4f} J_2={a2:.4f} | {elapsed:.0f}s")

    if avg < best_loss:
        best_loss = avg
        torch.save(model.state_dict(), f"{OUT}/best_model.pt")
    if (epoch+1)%10 == 0:
        torch.save({"epoch":epoch,"model":model.state_dict(),"optimizer":optimizer.state_dict()}, f"{OUT}/ckpt_e{epoch+1}.pt")

torch.save(model.state_dict(), f"{OUT}/final_model.pt")
t = time.time()-t0
print(f"\n✅ 完成 | {t/60:.1f}min | Best={best_loss:.4f} | {OUT}/best_model.pt")
