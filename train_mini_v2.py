#!/usr/bin/env python3
"""SmolVLA-LEW Mini训练 — 自建CNN视觉编码器(无外部下载) + DiT Action Head + MPS"""
import os, sys, torch, time, math
os.environ["WANDB_MODE"] = "disabled"
sys.path.insert(0, "src")

from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.smolvla_lew.configuration_smolvla_lew import SmolVLALewConfig
from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
OUT = "outputs/train/smolvla_lew_mini"
EPOCHS, BS, LR, N = 50, 4, 5e-4, 200

print(f"🚀 SmolVLA-LEW Mini | {DEVICE} | 纯本地(无下载)")

# ── 合成数据 ──
torch.manual_seed(42)
synth = [{"observation.image": torch.rand(3,64,64),
          "observation.state": torch.randn(2)*0.5,
          "action": -0.5*torch.randn(2)*0.5 + torch.randn(2)*0.1}
         for _ in range(N)]

# ── 小型视觉编码器 (替代SmolVLM) ──
class TinyVisionEncoder(torch.nn.Module):
    """极小CNN编码器: 3×64×64 → 256维特征"""
    def __init__(self, out_dim=256):
        super().__init__()
        self.net = torch.nn.Sequential(
            torch.nn.Conv2d(3, 16, 3, 2, 1), torch.nn.ReLU(),     # 32×32
            torch.nn.Conv2d(16, 32, 3, 2, 1), torch.nn.ReLU(),    # 16×16
            torch.nn.Conv2d(32, 64, 3, 2, 1), torch.nn.ReLU(),    # 8×8
            torch.nn.Conv2d(64, 128, 3, 2, 1), torch.nn.ReLU(),   # 4×4
            torch.nn.AdaptiveAvgPool2d(1), torch.nn.Flatten(),
            torch.nn.Linear(128, out_dim),
        )
    def forward(self, x):
        return self.net(x)

# ── DiT Action Head (Flow Matching) ──
class MiniDiTActionHead(torch.nn.Module):
    """极小DiT: state+vision → action via flow matching"""
    def __init__(self, vision_dim=256, state_dim=2, action_dim=2, hidden=256):
        super().__init__()
        self.action_dim = action_dim
        in_dim = vision_dim + state_dim + action_dim + 1  # +1 for timestep
        self.net = torch.nn.Sequential(
            torch.nn.Linear(in_dim, hidden), torch.nn.ReLU(),
            torch.nn.Linear(hidden, hidden), torch.nn.ReLU(),
            torch.nn.Linear(hidden, action_dim),
        )
        self.t_embed = torch.nn.Linear(1, action_dim)  # timestep embedding
    
    def forward(self, vision_feat, state, noisy_action, t):
        # t: [B] or scalar → 1维特征
        if isinstance(t, (int, float)):
            t = torch.full((vision_feat.shape[0], 1), t, device=vision_feat.device, dtype=torch.float32)
        elif t.dim() == 0:
            t = t.unsqueeze(0).unsqueeze(-1).expand(vision_feat.shape[0], 1)
        elif t.dim() == 1:
            t = t.unsqueeze(-1).float()
        x = torch.cat([vision_feat, state, noisy_action, t], dim=-1)
        return self.net(x)
    
    def predict(self, vision_feat, state, num_steps=4):
        """Flow matching 推理"""
        B = vision_feat.shape[0]
        action = torch.randn(B, self.action_dim, device=vision_feat.device)
        dt = 1.0 / num_steps
        for step in range(num_steps):
            t = step * dt
            v = self.forward(vision_feat, state, action, t)
            action = action + v * dt
        return action

# ── 组合模型 ──
class SmolVLAMini(torch.nn.Module):
    def __init__(self, vision_dim=256, state_dim=2, action_dim=2, hidden=256):
        super().__init__()
        self.vision = TinyVisionEncoder(vision_dim)
        self.action_head = MiniDiTActionHead(vision_dim, state_dim, action_dim, hidden)
    
    def forward(self, batch):
        img = batch["observation.image"]
        state = batch["observation.state"]
        action = batch["action"]
        B = img.shape[0]
        
        # 噪声动作 + 随机时间步
        noise = torch.randn_like(action)
        t = torch.rand(B, device=img.device)
        noisy_action = (1-t[:,None]) * action + t[:,None] * noise
        
        vision_feat = self.vision(img)
        pred_velocity = self.action_head(vision_feat, state, noisy_action, t)
        
        # Flow matching loss: |pred - (noise - action)|²
        target = noise - action
        loss = torch.nn.functional.mse_loss(pred_velocity, target)
        return loss, {"loss": loss.item()}
    
    def predict(self, batch):
        img = batch["observation.image"]
        state = batch["observation.state"]
        vision_feat = self.vision(img)
        return self.action_head.predict(vision_feat, state)

model = SmolVLAMini().to(DEVICE)
total = sum(p.numel() for p in model.parameters())
print(f"🧠 {total:,} params (all trainable)")

opt = torch.optim.AdamW(model.parameters(), lr=LR)
model.train()

# ── 训练 ──
print(f"\n🏋️ {EPOCHS} epochs × {N} samples...")
t0 = time.time(); losses = []
for ep in range(EPOCHS):
    el, nb = 0.0, 0
    for i in range(0, N, BS):
        bd = synth[i:i+BS]; b = {}
        for k in bd[0]: b[k] = torch.stack([d[k] for d in bd]).to(DEVICE)
        loss, _ = model.forward(b)
        opt.zero_grad(); loss.backward(); opt.step()
        el += loss.item(); nb += 1
    avg = el/nb; losses.append(avg)
    if (ep+1) % 5 == 0 or ep == 0:
        print(f"  Ep {ep+1:3d}: loss={avg:.6f} [{time.time()-t0:.0f}s]")

# ── 推理 ──
model.eval()
b = {k: synth[0][k].unsqueeze(0).to(DEVICE) for k in synth[0]}
with torch.no_grad():
    pred = model.predict(b)
true = synth[0]['action'].tolist()
print(f"\n🔮 推理测试:")
print(f"   state:  {[f'{x:.2f}' for x in synth[0]['observation.state'].tolist()]}")
print(f"   真实:  {[f'{x:.3f}' for x in true]}")
print(f"   预测:  {[f'{x:.3f}' for x in pred[0].cpu().tolist()]}")

# ── 保存 ──
os.makedirs(OUT, exist_ok=True)
torch.save(model.state_dict(), f"{OUT}/model.pt")
torch.save({"losses": losses, "epochs": EPOCHS, "final_loss": losses[-1]}, f"{OUT}/train_state.pt")
ttl = time.time()-t0
print(f"\n{'='*50}")
print(f"✅ 训练完成! {ttl:.0f}s ({ttl/60:.1f}min)")
print(f"   模型: {OUT}/model.pt")
print(f"   Loss: {losses[0]:.4f} → {losses[-1]:.4f} (↓{(losses[0]-losses[-1])/losses[0]*100:.1f}%)")
print(f"   参数: {total:,}")
print(f"{'='*50}")
