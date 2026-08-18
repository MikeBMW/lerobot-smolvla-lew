#!/usr/bin/env python3
"""
Z-MAX SmolVLA 全流程 v3 — 直接用推理验证训练可行性
先用最简单的流程: 加载模型 → 过一遍数据 → 看loss变化
"""
import torch, json, time, os

device = torch.device("cuda")
from lerobot.datasets import LeRobotDataset
from lerobot.policies.smolvla import SmolVLAPolicy
from torch.utils.data import DataLoader

ds = LeRobotDataset("lerobot/pusht", episodes=[0,1,2])
print(f"PushT: {len(ds)} frames")

policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base")
policy.to(device)
for n, p in policy.named_parameters():
    if n.startswith("model.vlm_with_expert.vlm") or n.startswith("model.lm_head"):
        p.requires_grad = False

total = sum(p.numel() for p in policy.parameters())
trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
print(f"SmolVLA: {total/1e6:.0f}M ({trainable/1e6:.0f}M trainable), prefix_length={policy.config.prefix_length}")

# 直接试一个batch的forward
loader = DataLoader(ds, batch_size=1, shuffle=True, num_workers=0)
batch = next(iter(loader))
batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
print(f"\n原始batch keys: {list(batch.keys())}")

# 手动构造SmolVLA需要的格式
from lerobot.policies.smolvla.modeling_smolvla import resize_with_pad
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from transformers import AutoTokenizer

img = batch["observation.image"]
img = resize_with_pad(img, 512, 512, pad_value=0) * 2.0 - 1.0
B = img.shape[0]

tokenizer = AutoTokenizer.from_pretrained(policy.config.vlm_model_name)
task_text = batch.get("task", ["push block"])[0]
encoded = tokenizer(task_text.strip(), return_tensors="pt", padding="max_length",
                    max_length=policy.config.tokenizer_max_length, truncation=True)

input_batch = {
    "observation.images.camera1": img,
    "observation.images.camera2": torch.ones(B, 3, 512, 512, device=device) * -1,
    "observation.images.camera3": torch.ones(B, 3, 512, 512, device=device) * -1,
    "observation.state": batch["observation.state"],
    OBS_LANGUAGE_TOKENS: encoded["input_ids"].to(device),
    OBS_LANGUAGE_ATTENTION_MASK: encoded["attention_mask"].to(torch.bool).to(device),
    "action": batch["action"],
}

print(f"\ninput_batch shapes:")
for k, v in input_batch.items():
    if isinstance(v, torch.Tensor):
        print(f"  {k}: {v.shape}")

print(f"\n试推理...")
with torch.no_grad():
    actions = policy.predict_action_chunk(input_batch)
    print(f"  ✅ predict_action_chunk OK: {actions.shape}")

print(f"\n试训练forward...")
policy.train()
try:
    loss, _ = policy.forward(input_batch)
    print(f"  ✅ forward OK: loss={loss.item():.6f}")
    
    # 完整训练循环
    print(f"\n开始300步训练...")
    optimizer = torch.optim.AdamW(filter(lambda p: p.requires_grad, policy.parameters()), lr=1e-4, weight_decay=1e-10)
    losses = []
    t0 = time.time()
    
    for step in range(300):
        try: raw = next(loader_iter)
        except: loader_iter = iter(loader); raw = next(loader_iter)
        
        raw = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in raw.items()}
        img = resize_with_pad(raw["observation.image"], 512, 512, pad_value=0) * 2.0 - 1.0
        B = img.shape[0]
        task_text = raw.get("task", ["push block"])[0]
        encoded = tokenizer(task_text.strip(), return_tensors="pt", padding="max_length",
                           max_length=policy.config.tokenizer_max_length, truncation=True)
        
        b = {
            "observation.images.camera1": img,
            "observation.images.camera2": torch.ones(B, 3, 512, 512, device=device) * -1,
            "observation.images.camera3": torch.ones(B, 3, 512, 512, device=device) * -1,
            "observation.state": raw["observation.state"],
            OBS_LANGUAGE_TOKENS: encoded["input_ids"].to(device),
            OBS_LANGUAGE_ATTENTION_MASK: encoded["attention_mask"].to(torch.bool).to(device),
            "action": raw["action"],
        }
        
        loss, _ = policy.forward(b)
        optimizer.zero_grad(); loss.backward(); optimizer.step()
        lv = loss.item(); losses.append(lv)
        if step % 30 == 0:
            print(f"  Step {step:4d}: loss={lv:.6f}  GPU={torch.cuda.memory_allocated()/1e9:.2f}GB")

    elapsed = time.time() - t0
    pct = round((losses[0]-losses[-1])/losses[0]*100, 1)
    print(f"\n✅ 训练完成 ({elapsed:.1f}s)  Loss: {losses[0]:.6f}→{losses[-1]:.6f} ({pct}%↓)")
    
    # 推理
    policy.eval()
    with torch.no_grad():
        test_loss, _ = policy.forward(b)
        print(f"   推理Loss: {test_loss.item():.6f}")
    
    # 保存
    out = "outputs/smolvla_pusht_full"
    os.makedirs(out, exist_ok=True)
    torch.save(policy.state_dict(), f"{out}/policy.pt")
    json.dump(losses, open(f"{out}/losses.json","w"))
    
    print(f"\n{'='*60}")
    print(f"Z-MAX SmolVLA 全流程: Loss {losses[0]:.4f}→{losses[-1]:.4f} ({pct}%↓)  推理={test_loss.item():.4f}")
    print(f"{'='*60}")

except Exception as e:
    print(f"\n❌ {e}")
    import traceback; traceback.print_exc()
