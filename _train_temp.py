
import json, torch, time, os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}")

# SmolVLA: Flow Matching VLA model
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

print("Loading SmolVLA base model (Flow Matching)...")
policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base")
policy.to(device)

# Freeze VLM, only train action head
for name, param in policy.named_parameters():
    if "smolvlm" in name or "vlm" in name.lower():
        param.requires_grad = False
trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
total = sum(p.numel() for p in policy.parameters())
print(f"Model: {total/1e6:.0f}M total, {trainable/1e6:.0f}M trainable (VLM frozen)")

# Data
episodes = list(range(5))
ds = LeRobotDataset("lerobot/metaworld_mt50", episodes=episodes)
print(f"Dataset: {len(ds)} frames")

loader = DataLoader(ds, batch_size=4, shuffle=True, num_workers=0)
optimizer = torch.optim.AdamW(filter(lambda p: p.requires_grad, policy.parameters()), lr=0.0001)
losses = []
output = "/home/xspace/lerobot-smolvla-lew/outputs/smolvla_pusht"
os.makedirs(output, exist_ok=True)

print("Training (Flow Matching)...")
policy.train()
for step in range(500):
    try: batch = next(iter(loader))
    except: loader = DataLoader(ds, batch_size=4, shuffle=True); batch = next(iter(loader))
    
    batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
    loss = policy.forward(batch)
    optimizer.zero_grad(); loss.backward(); optimizer.step()
    
    lv = loss.item(); losses.append(lv)
    if step % max(1, 500//10) == 0:
        print(f"Step {step:4d}: loss={lv:.6f}")

pct = round((losses[0]-losses[-1])/losses[0]*100, 1)
print(f"Final: {losses[0]:.6f} -> {losses[-1]:.6f} ({pct}% down)")

torch.save(policy.state_dict(), f"{output}/policy.pt")
with open(f"{output}/losses.json", "w") as f: json.dump(losses, f)
meta = {"model":"SmolVLA-FlowMatching","dataset":"lerobot/metaworld_mt50","params":int(trainable),"total_params":int(total),"steps":500,"episodes":len(episodes),"frames":len(ds),"device":str(device),"initial_loss":losses[0],"final_loss":losses[-1],"min_loss":min(losses),"reduction_pct":pct,"timestamp":time.strftime("%Y-%m-%d %H:%M"),"_dir":"smolvla_pusht"}
with open(f"{output}/training_meta.json", "w") as f: json.dump(meta, f, indent=2)
print(f"DONE: {pct}% loss (SmolVLA Flow Matching)")
