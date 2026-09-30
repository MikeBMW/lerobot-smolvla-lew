"""Hybrid Eval — 归一化空间直接对比 (绕过反归一化)"""
import torch
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

ckpt='outputs/zmax_hybrid_final/checkpoints/020000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
pre,_=make_pre_post_processors(m.config,ckpt,
    preprocessor_overrides={'device_processor':{'device':'cuda'}})

ds=LeRobotDataset('lerobot/pusht',episodes=[0,1,2])
loader=DataLoader(ds,batch_size=1)

total_mse=0; count=0
for raw in loader:
    if count>=10: break
    raw={k:v.cuda() if isinstance(v,torch.Tensor) else v for k,v in raw.items()}
    
    pp=pre(raw)
    gt_norm=pp['action'].squeeze(0)[:7]  # 归一化空间GT
    if gt_norm.ndim==2 and gt_norm.shape[0]==1: gt_norm=gt_norm.squeeze(0)
    
    with torch.no_grad(): pred=m.predict_action_chunk(pp)
    pred_norm=pred.squeeze(0)[:7]  # 归一化空间预测
    
    mse=torch.nn.functional.mse_loss(pred_norm, gt_norm).item()
    total_mse+=mse; count+=1

avg_mse=total_mse/count
print(f'归一化空间MSE: {avg_mse:.4f} (10样本平均)')
print(f'GT范围: [{gt_norm.min():.2f},{gt_norm.max():.2f}]')
print(f'预测范围: [{pred_norm.min():.2f},{pred_norm.max():.2f}]')

# 逐维对比
for d in range(2):
    print(f'dim{d}: GT={gt_norm[:,d].mean():.2f}±{gt_norm[:,d].std():.2f}  pred={pred_norm[:,d].mean():.2f}±{pred_norm[:,d].std():.2f}')

del m;torch.cuda.empty_cache()
