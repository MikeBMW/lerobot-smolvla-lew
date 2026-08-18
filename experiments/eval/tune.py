"""仿真数据微调Hybrid"""
import torch, numpy as np
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from torch.utils.data import DataLoader, TensorDataset

# 加载数据
d=np.load('outputs/sim_data/train_data.npz')
states=torch.tensor(d['states']).float()
actions=torch.tensor(d['actions']).float()
images=torch.tensor(d['images']).float()
print(f'数据: {len(states)}帧 state{states.shape} act{actions.shape} img{images.shape}')

# 加载预训练Hybrid
ckpt='outputs/zmax_hybrid_final/checkpoints/020000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().train()

# 冻结VLM, 只训练Expert+WM
for n,p in m.named_parameters():
    if 'vlm' in n: p.requires_grad=False

optim=torch.optim.AdamW([p for p in m.parameters() if p.requires_grad],lr=1e-5)
ds=TensorDataset(images,states,actions)
loader=DataLoader(ds,batch_size=1,shuffle=True)

losses=[]
for epoch in range(20):
    total_loss=0
    for img,st,act in loader:
        img,st,act=img.cuda(),st.cuda(),act.cuda()
        loss,_=m.forward({'observation.image':img,'observation.state':st,'action':act.unsqueeze(1)})
        optim.zero_grad(); loss.backward(); optim.step()
        total_loss+=loss.item()
    avg=total_loss/len(loader)
    losses.append(avg)
    if epoch%5==0: print(f'epoch{epoch}: loss={avg:.4f}')

# 保存微调模型
torch.save(m.state_dict(),'outputs/sim_data/hybrid_simtuned.pt')
print(f'保存完成 loss: {losses[0]:.4f}→{losses[-1]:.4f}')
del m;torch.cuda.empty_cache()
