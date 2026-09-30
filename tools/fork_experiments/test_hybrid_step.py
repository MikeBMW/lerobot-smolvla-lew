"""Hybrid 逐步验证"""
import torch, time
print("=== Step 1: 导入模块 ===")
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
print("OK")

print("\n=== Step 2: 查checkpoint文件 ===")
import os; ckpt="outputs/zmax_hybrid_pusht/checkpoints/000100/pretrained_model"
for f in sorted(os.listdir(ckpt)):
    sz = os.path.getsize(os.path.join(ckpt,f))/1e6
    print(f"  {f}: {sz:.0f}MB")
print("OK")

print("\n=== Step 3: 加载模型(等VLM...) ===")
t0=time.time()
m=ZmaxHybridPolicy.from_pretrained(ckpt, local_files_only=True).cuda().eval()
print(f"  耗时: {time.time()-t0:.1f}s")
p=sum(p.numel() for p in m.parameters())/1e6
print(f"  参数: {p:.0f}M")
print("OK")

print("\n=== Step 4: 构造输入 ===")
# PushT state是2维
b={
    'observation.state': torch.rand(1,2).cuda(),
    'observation.image': torch.rand(1,3,64,64).cuda(),
}
print(f"  state: {b['observation.state'].shape}")
print(f"  image: {b['observation.image'].shape}")
print("OK")

print("\n=== Step 5: 推理 ===")
t0=time.time()
with torch.no_grad():
    a=m.predict_action_chunk(b)
t=time.time()-t0
print(f"  耗时: {t*1000:.0f}ms")
print(f"  动作: {a.shape}")
print(f"  GPU: {torch.cuda.memory_allocated()/1e9:.2f}GB")
print("OK")

print("\n=== Step 6: 前向(训练模式) ===")
b['action']=torch.randn(1,7,2).cuda()  # PushT action是2维
loss, info=m.forward(b)
print(f"  Loss: {loss.item():.4f}")
print(f"  Info: {info}")
print("OK")

print("\n✅ 全部通过!")
