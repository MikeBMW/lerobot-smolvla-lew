"""train_h_jepa_zflow.py — H-JEPA z流真实训练 · MetaWorld MT50"""
import torch, torch.nn as nn, numpy as np, os, time
from h_jepa_zflow import ZFlow_VLA
from z_config import ZFlowConfig
from datasets import load_dataset

cfg = ZFlowConfig()
cfg.epochs = 200
cfg.lr = 1e-4
cfg.batch_size = 4
model = ZFlow_VLA(cfg).cuda()
print(f"ZFlow_VLA: {sum(p.numel() for p in model.parameters())/1e6:.1f}M params")

# MetaWorld数据
print("📥 加载MetaWorld...")
ds = load_dataset("lerobot/metaworld_mt50", split="train[:5000]")
print(f"   样本: {len(ds)}")

opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr)
sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, cfg.epochs)
OUT = "/home/xspace/lerobot-smolvla-lew/outputs/hjepa_zflow"
os.makedirs(OUT, exist_ok=True)
best_loss = float('inf')
t0 = time.time()

for epoch in range(cfg.epochs):
    # 随机采样
    idx = np.random.randint(0, len(ds)-cfg.batch_size, cfg.batch_size)
    imgs, states, actions = [], [], []
    for i in idx:
        s = ds[i]
        img = torch.tensor(np.array(s['observation.image'])).permute(2,0,1).float()/255.0
        img = nn.functional.interpolate(img.unsqueeze(0),(128,128),mode='bilinear').squeeze(0)
        st = torch.tensor(s['observation.state'],dtype=torch.float32)[:7]
        if st.shape[0] < 7: st = nn.functional.pad(st, (0,7-st.shape[0]))
        act = torch.tensor(s['action'],dtype=torch.float32)
        imgs.append(img); states.append(st); actions.append(act)

    rgb = torch.stack(imgs).cuda()
    state = torch.stack(states).cuda()
    target = torch.stack(actions).cuda()

    # 扩展target到14×chunk
    if target.shape[1] != 14:
        target = target.repeat(1, 14//max(1,target.shape[1]) + 1)[:,:14]
    target = torch.nn.functional.pad(target.unsqueeze(-1),(0,6)).squeeze(-1) if target.dim()==2 else target
    target = target[:,:14]

    model.set_train()
    pred, energy = model(rgb, state)
    if pred.shape != target.shape:
        target = target.unsqueeze(-1).expand(-1,-1,pred.shape[-1]//14) if target.dim()==2 else target
        target = target.reshape(pred.shape)

    loss_act = nn.functional.mse_loss(pred, target)
    loss = loss_act + 0.01 * energy.mean()
    opt.zero_grad(); loss.backward()
    nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step(); sch.step()

    if epoch % 10 == 0:
        elapsed = time.time()-t0
        print(f"E{epoch:03d} | act={loss_act.item():.4f} e={energy.mean().item():.4f} | {elapsed:.0f}s")

    if loss.item() < best_loss:
        best_loss = loss.item()
        torch.save(model.state_dict(), f"{OUT}/best_model.pt")

torch.save(model.state_dict(), f"{OUT}/final_model.pt")
elapsed = time.time()-t0
print(f"\n✅ 完成 | {elapsed/60:.1f}min | Best={best_loss:.4f} | {OUT}/best_model.pt")
