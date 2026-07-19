"""train_h_jepa.py — H-JEPA z流训练 + MetaWorld 数据"""
import torch, torch.nn as nn, numpy as np, os, wandb, time
from pathlib import Path
from h_jepa_zflow import ZFlow_VLA
from z_config import ZFlowConfig

cfg = ZFlowConfig()
model = ZFlow_VLA(cfg).cuda()

# MetaWorld 数据加载
files = list(Path(cfg.data_dir).glob("*.npz"))
if files:
    data = []
    for f in files:
        d = np.load(f)
        obs = d['observations']
        # Fix shape: NHWC -> NCHW, resize to 128x128
        if len(obs.shape)==4 and obs.shape[-1]==3:
            obs = np.transpose(obs, (0,3,1,2))  # NHWC -> NCHW
        st = d['states']
        # Match frames count
        n = min(obs.shape[0], st.shape[0])
        obs, st = obs[:n], st[:n]
        # Resize to 128x128
        obs = torch.tensor(obs, dtype=torch.float32).permute(0,3,1,2)  # NCHW
        obs = torch.nn.functional.interpolate(obs, size=(128,128), mode='bilinear', align_corners=False)
        data.append({'obs': obs / 255.0,
                     'state': torch.tensor(st, dtype=torch.float32),
                     'task': str(d.get('task_name', f.stem))})
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
