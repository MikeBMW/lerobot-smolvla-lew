#!/usr/bin/env python3
"""smolvla_lew 联合训练 — 10步性能基准"""
import os, sys, torch, time, json, gc
os.environ["WANDB_MODE"] = "disabled"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.smolvla_lew.configuration_smolvla_lew import SmolVLALewConfig
from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy

STEPS = 10
DEVICE = "cuda"
OUTPUT = os.path.join(os.path.dirname(__file__), "outputs/train/smolvla_lew_10step")

print("="*60)
print(f"  smolvla_lew 联合训练 · {STEPS}步基准")
print(f"  GPU: {torch.cuda.get_device_name(0)}")
print(f"  输出: {OUTPUT}")
print("="*60)

# ═══ 加载数据 ═══
print("\n[1/4] 加载数据集...")
ds = LeRobotDataset("lerobot/pusht")
print(f"  样本: {len(ds)} episodes, {len(ds)} frames")
print(f"  特征: {list(ds[0].keys())}")

# ═══ 构建模型 ═══
print("\n[2/4] 构建 smolvla_lew (Sys-11纯动作)...")
features = {
    'observation.images.top': PolicyFeature(FeatureType.VISUAL, (3, 96, 96)),
    'observation.state': PolicyFeature(FeatureType.STATE, (2,)),
}
out_f = {'action': PolicyFeature(FeatureType.ACTION, (2,))}

t0 = time.time()
cfg = SmolVLALewConfig(
    enable_lew_world_model=False,
    input_features=features,
    output_features=out_f,
    chunk_size=7, n_action_steps=7,
    freeze_smolvlm=True,
)
model = SmolVLALewPolicy(cfg)
model.to(DEVICE).train()
load_time = time.time() - t0

total_p = sum(p.numel() for p in model.parameters())/1e6
train_p = sum(p.numel() for p in model.parameters() if p.requires_grad)/1e6
mem = torch.cuda.memory_allocated()/1024**3
print(f"  总参数: {total_p:.0f}M | 可训: {train_p:.0f}M ({train_p/total_p*100:.0f}%)")
print(f"  加载时间: {load_time:.1f}s | 显存: {mem:.3f}GB")

# ═══ 优化器 ═══
opt = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=1e-5)

# ═══ 训练 ═══
print(f"\n[3/4] 开始训练 {STEPS}步...")
metrics = []
torch.cuda.reset_peak_memory_stats()

for step in range(STEPS):
    data = ds[step % len(ds)]
    
    # 准备batch
    img = data['observation.image']
    if img.ndim == 2: img = img.unsqueeze(0)
    elif img.ndim == 4 and img.shape[0] > 1: img = img[:1]
    if img.ndim == 3: img = img.unsqueeze(0)
    
    batch = {
        'observation.state': data['observation.state'].unsqueeze(0).to(DEVICE).float(),
        'observation.images.top': img.to(DEVICE).float(),
        'action': data['action'].unsqueeze(0).to(DEVICE).float(),
    }
    
    t1 = time.time()
    opt.zero_grad()
    loss, info = model.forward(batch)
    loss.backward()
    opt.step()
    
    step_time = time.time() - t1
    mem_now = torch.cuda.memory_allocated()/1024**3
    peak_now = torch.cuda.max_memory_allocated()/1024**3
    
    metrics.append({
        'step': step+1,
        'loss': float(loss.item()),
        'time_ms': round(step_time*1000, 1),
        'mem_gb': round(mem_now, 3),
        'peak_gb': round(peak_now, 3),
    })
    
    print(f"  步{step+1:2d}/{STEPS} | loss={loss.item():.4f} | "
          f"{step_time*1000:.0f}ms | 显存{mem_now:.2f}/{peak_now:.2f}GB")

# ═══ 报告 ═══
torch.cuda.synchronize()
peak = torch.cuda.max_memory_allocated()/1024**3
losses = [m['loss'] for m in metrics]
times = [m['time_ms'] for m in metrics]

print(f"\n[4/4] 训练完成")
print("="*60)
print(f"  步数: {STEPS}")
print(f"  loss: {losses[0]:.4f} → {losses[-1]:.4f} (降幅: {(1-losses[-1]/losses[0])*100:.1f}%)" if losses[0]>0 else f"  final loss: {losses[-1]:.4f}")
print(f"  平均/步: {np.mean(times):.0f}ms | 最快: {np.min(times):.0f}ms | 最慢: {np.max(times):.0f}ms")
print(f"  吞吐: {1000/np.mean(times):.1f} steps/s")
print(f"  峰值显存: {peak:.3f}GB | 加载: {mem:.3f}GB")
print(f"  总耗时: {sum(times)/1000:.1f}s")
print("="*60)

# 保存
os.makedirs(OUTPUT, exist_ok=True)
with open(f"{OUTPUT}/metrics.json", "w") as f:
    json.dump({
        'model': 'smolvla_lew',
        'steps': STEPS,
        'total_params_m': round(total_p, 1),
        'trainable_params_m': round(train_p, 1),
        'load_time_s': round(load_time, 1),
        'peak_memory_gb': round(peak, 3),
        'loss_start': losses[0],
        'loss_end': losses[-1],
        'avg_step_ms': round(np.mean(times), 0),
        'throughput_steps_s': round(1000/np.mean(times), 1),
        'details': metrics,
    }, f, indent=2, ensure_ascii=False)
print(f"\n✅ 指标已保存: {OUTPUT}/metrics.json")
