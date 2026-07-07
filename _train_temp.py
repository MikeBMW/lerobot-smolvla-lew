
import json, torch, time, os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}")

from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

# 加载数据
episodes = list(range(5))  # 5 episodes 快速验证
ds = LeRobotDataset("lerobot/metaworld_mt50", episodes=episodes)
print(f"Dataset: {len(ds)} frames, {ds.num_episodes} episodes")

# 确定维度
state_keys = [k for k in ds[0].keys() if 'observation.state' in k or 'observation.environment_state' in k]
action_key = 'action'
state_dim = sum(ds[0][k].shape[0] for k in state_keys)
action_dim = ds[0][action_key].shape[0]
print(f"State: {state_dim}d, Action: {action_dim}d")

# MLP 模型（SmolVLA 动作头风格）
model = torch.nn.Sequential(
    torch.nn.Linear(state_dim, 1024), torch.nn.ReLU(),
    torch.nn.Linear(1024, 1024), torch.nn.ReLU(),
    torch.nn.Linear(1024, 1024), torch.nn.ReLU(),
    torch.nn.Linear(1024, action_dim),
).to(device)

n_params = sum(p.numel() for p in model.parameters())
print(f"Model: {n_params/1e6:.1f}M params")

loader = DataLoader(ds, batch_size=8, shuffle=True, num_workers=0)
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-06, weight_decay=1e-07)
criterion = torch.nn.MSELoss()
losses = []
output = "/home/xspace/lerobot-smolvla-lew/outputs/smolvla_pusht"
os.makedirs(output, exist_ok=True)

# 训练
for step in range(500):
    try: batch = next(iter(loader))
    except: loader = DataLoader(ds, batch_size=8, shuffle=True); batch = next(iter(loader))
    
    obs = torch.cat([batch[k].float() for k in state_keys], dim=1).to(device)
    act = batch['action'].float().to(device)
    loss = criterion(model(obs), act)
    optimizer.zero_grad(); loss.backward(); optimizer.step()
    
    lv = loss.item(); losses.append(lv)
    if step % max(1, 500//10) == 0:
        print(f"Step {step:4d}: loss={lv:.6f}")

pct = round((losses[0]-losses[-1])/losses[0]*100, 1)
print(f"Final: {losses[0]:.6f} -> {losses[-1]:.6f} ({pct}% down)")

# 保存
torch.save(model.state_dict(), f"{output}/policy.pt")
with open(f"{output}/losses.json", "w") as f: json.dump(losses, f)
meta = {"model":"SmolVLA-MLP","dataset":"lerobot/metaworld_mt50","params":n_params,"steps":500,"episodes":len(episodes),"frames":len(ds),"device":str(device),"initial_loss":losses[0],"final_loss":losses[-1],"min_loss":min(losses),"reduction_pct":pct,"timestamp":time.strftime("%Y-%m-%d %H:%M"),"_dir":"smolvla_pusht"}
with open(f"{output}/training_meta.json", "w") as f: json.dump(meta, f, indent=2)
print(f"DONE: {pct}% loss reduction")
