#!/usr/bin/env python3
"""SmolVLA-LEW训练 — HF镜像 + 合成数据 + MPS"""
import os, sys, torch, time
os.environ["WANDB_MODE"] = "disabled"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"  # 国内镜像
sys.path.insert(0, "src")

from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.smolvla_lew import SmolVLALewConfig, SmolVLALewPolicy

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
OUT = "outputs/train/smolvla_lew_synth"
EPOCHS, BS, LR, N = 10, 2, 1e-4, 100

print(f"🚀 SmolVLA-LEW | {DEVICE} | HF Mirror")

# ── 合成数据 ──
torch.manual_seed(42)
synth = [{"observation.image": torch.rand(3,64,64),
          "observation.state": torch.randn(2)*0.5,
          "action": -0.5*torch.randn(2)*0.5 + torch.randn(2)*0.1}
         for _ in range(N)]

# ── 模型 ──
cfg = SmolVLALewConfig(
    input_features={
        "observation.image": PolicyFeature(FeatureType.VISUAL, (3,64,64)),
        "observation.state": PolicyFeature(FeatureType.STATE, (2,)),
    },
    output_features={"action": PolicyFeature(FeatureType.ACTION, (2,))},
    smolvlm_name="HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    freeze_smolvlm=True,
    action_hidden_size=256, action_num_layers=1,
    num_inference_timesteps=2,
    chunk_size=1, n_action_steps=1,
)
cfg.validate_features()

print("🧠 创建模型(下载VLM权重约1GB, 请稍候)...")
model = SmolVLALewPolicy(cfg).to(DEVICE)
total = sum(p.numel() for p in model.parameters())
trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f"   参数: {total:,} total | {trainable:,} trainable ({100*trainable/total:.1f}%)")

opt = torch.optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=LR)
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
    print(f"  Ep {ep+1:2d}: loss={avg:.6f} [{time.time()-t0:.0f}s]")

# ── 推理 ──
model.eval(); b = {k: synth[0][k].unsqueeze(0).to(DEVICE) for k in synth[0]}
with torch.no_grad(): pred = model.predict(b)
print(f"\n🔮 推理: state={[f'{x:.2f}' for x in synth[0]['observation.state'].tolist()]} → {[f'{x:.3f}' for x in pred[0]] if hasattr(pred,'__iter__') else pred}")

# ── 保存 ──
os.makedirs(OUT, exist_ok=True)
model.save_pretrained(OUT)
torch.save(cfg, f"{OUT}/config.pt")
ttl = time.time()-t0
print(f"\n{'='*50}")
print(f"✅ 训练完成! {ttl:.0f}s")
print(f"   模型: {OUT}")
print(f"   Loss: {losses[0]:.4f} → {losses[-1]:.4f} (↓{(losses[0]-losses[-1])/losses[0]*100:.1f}%)")
print(f"{'='*50}")
