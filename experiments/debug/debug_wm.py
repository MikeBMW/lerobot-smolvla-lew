"""WM单步调试 — 每步打印shape"""
import torch, torch.nn as nn, torch.nn.functional as F

# 模拟参数
B,T = 2,5           # batch=2, 序列长度=5
obs_dim, ctx_dim = 4, 512
hidden = 256

# 模拟输入
obs_seq = torch.randn(B, T, obs_dim)
ctx = torch.randn(B, ctx_dim)

print("=== WM 单步张量流 ===")
print(f"obs_seq:  {obs_seq.shape}  ← [B,T,obs_dim] 连续帧的 state+action")
print(f"ctx_feat: {ctx.shape}     ← [B,ctx_dim] VLA特征\n")

# Step 1
obs_proj = nn.Linear(obs_dim, hidden)
obs_emb = obs_proj(obs_seq)
print(f"1. obs_proj: {obs_emb.shape} ← Linear({obs_dim}→{hidden})")

# Step 2
ctx_proj = nn.Linear(ctx_dim, hidden)
ctx_emb = ctx_proj(ctx)
print(f"2. ctx_proj: {ctx_emb.shape} ← Linear({ctx_dim}→{hidden})")

# Step 3
h0 = ctx_emb.unsqueeze(0).repeat(2, 1, 1)
print(f"3. h0:       {h0.shape} ← (层数=2) VLA注入GRU初始状态")

# Step 4
gru = nn.GRU(hidden, hidden, num_layers=2, batch_first=True)
gru_out, h_n = gru(obs_emb, h0)
print(f"4. gru_out:  {gru_out.shape}  ← [B,T,hidden]")
print(f"   h_n:      {h_n.shape}      ← [layers,B,hidden] 最终隐藏状态")

# Step 5
last = gru_out[:, -1, :]
print(f"5. last:     {last.shape}  ← 取最后一帧")

# Step 6
heads = [nn.Sequential(nn.Linear(hidden,hidden), nn.ReLU(), nn.Linear(hidden,z)) for z in [256,256,128]]
z_list = [h(last) for h in heads]
print(f"6. z₁:       {z_list[0].shape}  ← 空间潜空间")
print(f"   z₂:       {z_list[1].shape}  ← 物体潜空间")
print(f"   z₃:       {z_list[2].shape}  ← 语义潜空间")

# Step 7 
target = obs_proj(obs_seq[:, 1:, :])
pred   = gru_out[:, :-1, :]
energy = F.mse_loss(pred, target)
print(f"7. target:   {target.shape} ← 实际下一帧编码")
print(f"   pred:     {pred.shape}   ← 预测下一帧编码")
print(f"   energy:   {energy.item():.4f} ← H-JEPA损失")

print(f"\n✅ WM参数: {sum(p.numel() for p in [obs_proj,ctx_proj,gru]+[p for h in heads for p in h.parameters()]):,}")
