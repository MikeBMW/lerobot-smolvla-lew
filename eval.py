import torch
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

ckpt='outputs/zmax_hybrid_train/checkpoints/002000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
pre,post=make_pre_post_processors(m.config, ckpt, preprocessor_overrides={'device_processor':{'device':'cuda'}})

ds=LeRobotDataset('lerobot/pusht', episodes=[0])
b=next(iter(DataLoader(ds,batch_size=1)))
b={k:v.cuda() if isinstance(v,torch.Tensor) else v for k,v in b.items()}
gt=b['action'][:7].clone()
if gt.ndim==2 and gt.shape[0]==1: gt=gt.squeeze(0)

b_pp=pre(b)
with torch.no_grad(): a=m.predict_action_chunk(b_pp)
a=post(a).cuda()
a7=a.squeeze(0)[:7]

print(f'predict: min={a7.min().item():.0f} max={a7.max().item():.0f}')
print(f'gt:      min={gt.min().item():.0f} max={gt.max().item():.0f}')
mse=torch.nn.functional.mse_loss(a7, gt)
print(f'MSE: {mse.item():.0f}')
mae=torch.nn.functional.l1_loss(a7, gt)
print(f'MAE: {mae.item():.0f} pixels')
del m;torch.cuda.empty_cache()
