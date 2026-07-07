
import json, torch, time, os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}")

from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

# 加载数据 - 自动检测维度
episodes = list(range(8))
ds = LeRobotDataset("lerobot/metaworld_mt50", episodes=episodes)
sample = ds[0]

# 自动检测 state/action 维度 (含图像)
state_keys = [k for k in sample.keys() if 'state' in k and 'image' not in k]
state_dim = sum(sample[k].shape[0] for k in state_keys)
has_image = 'observation.image' in sample
if has_image:
    # 把图像resize到小尺寸后flatten
    import torch.nn.functional as F
    img = sample['observation.image']
    img_dim = 64 * 64 * 3  # resize 到 64×64
    print(f"Dataset: {len(ds)} frames, State: {state_dim}d, +Image: {list(img.shape)} -> {img_dim}d, Action: {action_dim}d")
else:
    img_dim = 0
    print(f"Dataset: {len(ds)} frames, State: {state_dim}d, Action: {action_dim}d")

total_dim = state_dim + img_dim
action_dim = sample['action'].shape[0]

# MLP (含图像支持)
model = torch.nn.Sequential(
    torch.nn.Linear(total_dim, 1024), torch.nn.ReLU(),
    torch.nn.Linear(1024, 1024), torch.nn.ReLU(),  
    torch.nn.Linear(1024, 1024), torch.nn.ReLU(),
    torch.nn.Linear(1024, action_dim),
).to(device)
n_params = sum(p.numel() for p in model.parameters())
print(f"Model: {n_params/1e6:.1f}M params")

loader = DataLoader(ds, batch_size=4, shuffle=True, num_workers=0)
optimizer = torch.optim.AdamW(model.parameters(), lr=0.0001)
criterion = torch.nn.MSELoss()
losses = []
output = "/home/xspace/lerobot-smolvla-lew/outputs/smolvla_metaworld_mt50"
os.makedirs(output, exist_ok=True)

print("Training...")
for step in range(500):
    try: batch = next(iter(loader))
    except: loader = DataLoader(ds, batch_size=4, shuffle=True); batch = next(iter(loader))
    
    obs_parts = [batch[k].float() for k in state_keys]
    if has_image:
        imgs = batch['observation.image'].float()
        B = imgs.shape[0]
        imgs_small = F.interpolate(imgs, size=(64,64), mode='bilinear', align_corners=False)
        obs_parts.append(imgs_small.reshape(B, -1))
    obs = torch.cat(obs_parts, dim=1).to(device)
    act = batch['action'].float().to(device)
    loss = criterion(model(obs), act)
    optimizer.zero_grad(); loss.backward(); optimizer.step()
    
    lv = loss.item(); losses.append(lv)
    if step % max(1, 500//10) == 0:
        print(f"Step {step:4d}: loss={lv:.6f}")

pct = round((losses[0]-losses[-1])/losses[0]*100, 1)
print(f"Final: {losses[0]:.6f} -> {losses[-1]:.6f} ({pct}% down)")

torch.save(model.state_dict(), f"{output}/policy.pt")
with open(f"{output}/losses.json", "w") as f: json.dump(losses, f)
meta = {"model":"SmolVLA-MLP","dataset":"lerobot/metaworld_mt50","params":n_params,"steps":500,"episodes":len(episodes),"frames":len(ds),"device":str(device),"initial_loss":losses[0],"final_loss":losses[-1],"min_loss":min(losses),"reduction_pct":pct,"timestamp":time.strftime("%Y-%m-%d %H:%M"),"_dir":"smolvla_metaworld_mt50"}
with open(f"{output}/training_meta.json", "w") as f: json.dump(meta, f, indent=2)
print(f"DONE: {pct}% loss reduction")
