#!/usr/bin/env python3
"""SmolVLA 从头训练 · PushT → 4060 CUDA"""
import os, sys, torch, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla_lew import SmolVLALewConfig, SmolVLALewPolicy

DEVICE = "cuda"
OUT = os.path.join(os.path.dirname(__file__), "outputs/smolvla_from_scratch")
os.makedirs(OUT, exist_ok=True)
EPOCHS, BATCH, LR = 50, 2, 1e-4

print(f"🚀 SmolVLA 从头训练 · PushT · {DEVICE}")
print(f"   GPU: {torch.cuda.get_device_name(0)} · {torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB")

# 数据
ds = LeRobotDataset("lerobot/pusht", split="train")
sample = ds[0]
action = sample.get('action', sample.get('action.action', None))
A_DIM = action.shape[-1]
print(f"   样本: {len(ds)} · action_dim={A_DIM}")

# 模型 (从头训练: freeze_smolvlm=False)
cfg = SmolVLALewConfig(
    input_shapes={"observation.image": [3,64,64], "observation.state": [2], "action": [A_DIM]},
    output_shapes={"action": [A_DIM]},
    smolvlm_name="HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    freeze_smolvlm=False,  # 从头训练!
    action_model_type="DiT-B",
    action_hidden_size=384,
    action_num_layers=4,
    num_inference_timesteps=4,
)
policy = SmolVLALewPolicy(cfg).to(DEVICE)
print(f"   参数: {sum(p.numel() for p in policy.parameters())/1e6:.0f}M")

opt = torch.optim.AdamW(policy.parameters(), lr=LR)
t0 = time.time()

for ep in range(EPOCHS):
    policy.train()
    loss_sum, n = 0, 0
    for i in range(0, min(len(ds), 500), BATCH):
        batch = ds[i:i+BATCH]
        imgs = torch.tensor(batch['observation.image'], dtype=torch.float32).to(DEVICE)
        st = torch.tensor(batch['observation.state'], dtype=torch.float32).to(DEVICE)
        act = torch.tensor(action, dtype=torch.float32).to(DEVICE) if i == 0 else torch.tensor(batch.get('action', batch['action.action']), dtype=torch.float32).to(DEVICE)
        if imgs.dim()==3: imgs=imgs.unsqueeze(0)
        if st.dim()==1: st=st.unsqueeze(0)
        if act.dim()==1: act=act.unsqueeze(0)
        try:
            loss = policy.compute_loss(imgs, st, act)
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
            opt.step()
            loss_sum += loss.item(); n += 1
        except Exception as e:
            if i < 10: print(f"   ⚠️ b{i}: {e}")
    avg = loss_sum/max(n,1)
    elapsed = time.time()-t0
    print(f"E{ep+1:02d}/{EPOCHS} loss={avg:.4f} | {elapsed:.0f}s")

policy.save_pretrained(OUT)
torch.save({"epoch":EPOCHS,"loss":avg}, f"{OUT}/training_state.pt")
print(f"✅ 模型保存: {OUT} · {time.time()-t0:.0f}s")
