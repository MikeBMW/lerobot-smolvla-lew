"""Hybrid 单步调试 — 每行打印"""
import torch, sys, time, os

ckpt="outputs/zmax_hybrid_pusht/checkpoints/000100/pretrained_model"

print("1/12 导入torch"); import torch; print("  torch",torch.__version__)
print("2/12 导入Policy"); from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy; print("  done")
print("3/12 创建模型实例(不加载权重)"); cfg=None
print("4/12 用from_pretrained加载..."); t0=time.time()
m=ZmaxHybridPolicy.from_pretrained(ckpt, local_files_only=True); print(f"  {time.time()-t0:.1f}s")
print("5/12 移到GPU"); m=m.cuda(); print(f"  GPU: {torch.cuda.memory_allocated()/1e9:.2f}GB")
print("6/12 eval模式"); m.eval(); print("  done")
print("7/12 参数统计"); p=sum(p.numel() for p in m.parameters())/1e6; print(f"  {p:.0f}M")
print("8/12 构造state输入"); s=torch.rand(1,2).cuda(); print(f"  {s.shape}")
print("9/12 构造image输入"); img=torch.rand(1,3,64,64).cuda(); print(f"  {img.shape} min={img.min():.2f} max={img.max():.2f}")
print("10/12 调用predict_action_chunk..."); t0=time.time()
with torch.no_grad():
    a=m.predict_action_chunk({'observation.state':s,'observation.image':img})
print(f"  结果: {a.shape} 耗时: {time.time()-t0:.3f}s")
print(f"  动作范围: [{a.min().item():.3f}, {a.max().item():.3f}]")
print("11/12 构造action输入"); act=torch.randn(1,7,2).cuda(); print(f"  {act.shape}")
print("12/12 前向传播..."); loss,info=m.forward({'observation.state':s,'observation.image':img,'action':act})
print(f"  loss={loss.item():.4f}  info={info}")

print("\n✅ ALL 12 STEPS PASSED")
