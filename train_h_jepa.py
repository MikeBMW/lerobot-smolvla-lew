"""train_h_jepa.py — H-JEPA z流训练 + MetaWorld 数据"""
import torch, torch.nn as nn, numpy as np, os, wandb, time
from pathlib import Path
from h_jepa_zflow import ZFlow_VLA
from z_config import ZFlowConfig

cfg = ZFlowConfig()
model = ZFlow_VLA(cfg).cuda()

# MetaWorld 数据加载
files = [f for f in Path(cfg.data_dir).glob("*_demo.npz")]
if files:
    data = []
    for f in files:
        d = np.load(f)
        obs_raw = d['observations']
        st_raw = d['states']
        # Standardize: NHWC -> NCHW
        if len(obs_raw.shape)==4 and obs_raw.shape[-1]==3:
            obs_raw = np.transpose(obs_raw, (0,3,1,2))
        n = min(obs_raw.shape[0], st_raw.shape[0])
        obs_t = torch.tensor(obs_raw[:n], dtype=torch.float32)
        st_t = torch.tensor(st_raw[:n], dtype=torch.float32)
        # Resize if needed
        if obs_t.shape[2]!=128 or obs_t.shape[3]!=128:
            obs_t = torch.nn.functional.interpolate(obs_t, size=(128,128), mode='bilinear', align_corners=False)
        if st_t.shape[-1] > 7:
            st_t = st_t[:, :7]  # MetaWorld: use first 7 dims
        elif st_t.shape[-1] == 6:
            st_t = torch.nn.functional.pad(st_t, (0, 1))
        data.append({'obs': obs_t/255.0, 'state': st_t, 'task': str(d.get('task_name', f.stem))})
    print(f'📦 加载 {len(files)} 个任务')
else:
    print('⚠️ 无MetaWorld数据, 使用随机数据验证')

opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr)
wandb.init(project='zmax-hjepa', entity='xspace', name='zflow-v1')

for epoch in range(cfg.epochs):
    if files:
        t = data[np.random.randint(0, len(data))]
        i = np.random.randint(0, max(1, t['obs'].shape[0]-cfg.batch_size), cfg.batch_size)
        rgb, state = t['obs'][i].cuda(), t['state'][i].cuda()
    else:
        rgb, state = torch.randn(cfg.batch_size,3,128,128).cuda(), torch.randn(cfg.batch_size,7).cuda()

    model.set_train()
    pred, energy = model(rgb, state)
    target_act = torch.zeros(cfg.batch_size,14,7).cuda()
    loss_act = nn.functional.mse_loss(pred, target_act)
    loss = loss_act + 0.01*energy.mean()
    opt.zero_grad(); loss.backward(); opt.step()

    if epoch % 50 == 0:
        wandb.log({'epoch': epoch, 'loss_act': loss_act.item(), 'loss_energy': energy.mean().item()})
        print(f'{epoch:3d}: act={loss_act.item():.4f} energy={energy.mean().item():.4f}')

# 保存
os.makedirs('/root/models/hjepa_zflow', exist_ok=True)
torch.save(model.state_dict(), '/root/models/hjepa_zflow/model.pt')
wandb.save('/root/models/hjepa_zflow/model.pt')
wandb.finish()
print(f'✅ 训练完成 → /root/models/hjepa_zflow/model.pt')
