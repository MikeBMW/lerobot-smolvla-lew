"""逐步展示归一化问题"""
import torch
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

ckpt='outputs/zmax_hybrid_final/checkpoints/010000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
pre,post=make_pre_post_processors(m.config, ckpt,
    preprocessor_overrides={'device_processor':{'device':'cuda'}})

ds=LeRobotDataset('lerobot/pusht',episodes=[0])
b=next(iter(DataLoader(ds,batch_size=1)))
gt_raw=b['action'].clone()

print("1. 原始GT (训练管线没做预处理前):")
print(f"   shape={gt_raw.shape}  range=[{gt_raw.min():.0f},{gt_raw.max():.0f}]")

b2={k:v.cuda() if isinstance(v,torch.Tensor) else v for k,v in b.items()}
b_pp=pre(b2)
print(f"\n2. 预处理后 (模型实际训练用的):")
print(f"   state={b_pp['observation.state'].shape} range=[{b_pp['observation.state'].min():.2f},{b_pp['observation.state'].max():.2f}]")
if 'action' in b_pp:
    print(f"   action={b_pp['action'].shape} range=[{b_pp['action'].min():.2f},{b_pp['action'].max():.2f}]")

with torch.no_grad(): 
    pred_norm=m.predict_action_chunk(b_pp)
print(f"\n3. 模型预测 (归一化空间):")
print(f"   shape={pred_norm.shape} range=[{pred_norm.min():.2f},{pred_norm.max():.2f}]")

pred_raw=post(pred_norm)
print(f"\n4. 反归一化后:")
print(f"   shape={pred_raw.shape} range=[{pred_raw.min():.2f},{pred_raw.max():.2f}]")
print(f"   dim={pred_raw.shape[-1]}")

print(f"\n5. 问题: GT是{gt_raw.shape[-1]}维, 预测是{pred_raw.shape[-1]}维 → 对不齐!")

del m;torch.cuda.empty_cache()
