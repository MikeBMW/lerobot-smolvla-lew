"""Hybrid Eval — 用完整pipeline评估"""
import torch, time
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

ckpt='outputs/zmax_hybrid_train/checkpoints/005000/pretrained_model'
print(f'加载: {ckpt}')
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
pre,post=make_pre_post_processors(m.config, ckpt,
    preprocessor_overrides={'device_processor':{'device':'cuda'}})

ds=LeRobotDataset('lerobot/pusht', episodes=[0,1,2])
loader=DataLoader(ds, batch_size=1, shuffle=True)

losses,mses=[],[]
for i,raw in enumerate(loader):
    if i>=10: break
    raw={k:v.cuda() if isinstance(v,torch.Tensor) else v for k,v in raw.items()}
    gt=raw['action'][:7].clone()
    if gt.ndim==2 and gt.shape[0]==1: gt=gt.squeeze(0)
    
    pp=pre(raw)
    with torch.no_grad():
        pred=m.predict_action_chunk(pp)
    pred=post(pred).cuda()
    p7=pred.squeeze(0)[:7]
    
    mse=torch.nn.functional.mse_loss(p7, gt).item()
    mses.append(mse)
    loss,_=m.forward(raw)
    losses.append(loss.item())

print(f'avg loss: {sum(losses)/len(losses):.1f}')
print(f'avg MSE:  {sum(mses)/len(mses):.0f}')
print(f'动作范围: [{min(pred.min().item() for _ in range(10)):.0f},{max(pred.max().item() for _ in range(10)):.0f}]')

del m;torch.cuda.empty_cache();print('Done')
