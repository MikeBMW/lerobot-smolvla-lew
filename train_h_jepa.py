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
    valid_files = []
    for f in files:
        d = np.load(f)
        if d["states"].shape[1] >= 7: valid_files.append(f)
    files = valid_files
    all_obs, all_state = [], []
    for f in files:
        d = np.load(f)
        all_obs.append(torch.tensor(d['observations'],dtype=torch.float32).cuda())
        all_state.append(torch.tensor(d['states'],dtype=torch.float32).cuda())
    obs_data = torch.cat(all_obs,0)
    state_data = torch.cat(all_state,0)
    print(f'📦 加载 {len(files)} 个任务 ({obs_data.shape[0]}帧)')
else:
    obs_data = torch.randn(1000,3,128,128).cuda()
    state_data = torch.randn(1000,7).cuda()
    print('⚠️ 无数据, 随机生成')

opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr)
wandb.init(project='zmax-hjepa', entity='xspace', name='zflow-v1')

for epoch in range(cfg.epochs):
    i = np.random.randint(0, max(1, obs_data.shape[0]-cfg.batch_size), cfg.batch_size)
    rgb, state = obs_data[i], state_data[i]

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
