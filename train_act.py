#!/usr/bin/env python3
"""ACT 模型训练脚本 — 从 Orin 采集的 MetaWorld 格式数据"""
import torch, numpy as np, os, time, wandb, sys
from pathlib import Path

DATA_DIR = "/root/datasets/metaworld/tasks"
MODEL_DIR = "/root/models/act_policy"
os.makedirs(MODEL_DIR, exist_ok=True)

# ACT: CVAE Encoder-Decoder
class ACTPolicy(torch.nn.Module):
    def __init__(self, state_dim=7, action_dim=6, hidden=256, latent=32, chunk=50):
        super().__init__()
        self.encoder = torch.nn.Sequential(
            torch.nn.Conv2d(3,32,8,4), torch.nn.ReLU(),
            torch.nn.Conv2d(32,64,4,2), torch.nn.ReLU(),
            torch.nn.Conv2d(64,64,3,1), torch.nn.AdaptiveAvgPool2d(1))
        self.state_enc = torch.nn.Linear(state_dim, hidden)
        self.fuse = torch.nn.Linear(64+hidden, hidden)
        self.mu = torch.nn.Linear(hidden, latent)
        self.logvar = torch.nn.Linear(hidden, latent)
        self.decoder = torch.nn.Sequential(
            torch.nn.Linear(latent+state_dim, hidden), torch.nn.ReLU(),
            torch.nn.Linear(hidden, hidden), torch.nn.ReLU(),
            torch.nn.Linear(hidden, action_dim*chunk))

    def forward(self, img, state):
        b = img.shape[0]
        f = self.encoder(img).view(b, -1)
        s = self.state_enc(state)
        h = self.fuse(torch.cat([f,s],-1))
        mu, logvar = self.mu(h), self.logvar(h)
        z = mu + torch.randn_like(logvar)*torch.exp(0.5*logvar)
        a = self.decoder(torch.cat([z,state],-1))
        return a.view(b, 50, 6), mu, logvar

def train():
    # Find all .npz files
    files = list(Path(DATA_DIR).glob("*.npz"))
    if not files:
        print("❌ 无数据文件, 请先上传 .npz 到", DATA_DIR)
        return
    print(f"📦 找到 {len(files)} 个任务文件")

    # Load all data
    all_img, all_state, all_action = [], [], []
    for f in files:
        d = np.load(f)
        all_img.append(d['observations'])
        all_state.append(d['states'])
        all_action.append(d.get('actions', d['states'][1:]-d['states'][:-1]))
    img = torch.tensor(np.concatenate(all_img), dtype=torch.float32).cuda()
    state = torch.tensor(np.concatenate(all_state), dtype=torch.float32).cuda()
    action = torch.tensor(np.concatenate(all_action), dtype=torch.float32).cuda()
    print(f"📊 总样本: {img.shape[0]} 帧")

    model = ACTPolicy().cuda()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4)

    wandb.init(project='zmax-act', entity='xspace', name='act-orin-'+time.strftime('%m%d-%H%M'))
    EPOCHS = 300
    for epoch in range(EPOCHS):
        idx = np.random.randint(0, img.shape[0]-50, 8)
        imgs = torch.stack([img[i:i+1].squeeze(0) for i in idx]).cuda()
        states = state[idx].cuda()
        targets = torch.stack([action[i:i+50] for i in idx]).cuda()
        pred, mu, logvar = model(imgs, states)
        loss_recon = torch.nn.functional.mse_loss(pred, targets)
        loss_kl = -0.5 * (1 + logvar - mu.pow(2) - logvar.exp()).mean()
        loss = loss_recon + 0.001*loss_kl
        opt.zero_grad(); loss.backward(); opt.step()
        if epoch%30==0:
            wandb.log({'epoch':epoch,'loss':loss.item(),'recon':loss_recon.item(),'kl':loss_kl.item()})
            print(f'epoch {epoch:3d}: loss={loss.item():.4f}')

    torch.save(model.state_dict(), f'{MODEL_DIR}/act_policy.pt')
    wandb.save(f'{MODEL_DIR}/act_policy.pt')
    wandb.finish()
    print(f'✅ ACT训练完成 → {MODEL_DIR}/act_policy.pt')

if __name__ == '__main__':
    train()
