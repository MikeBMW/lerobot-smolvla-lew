"""train_compare_video.py — 三架构训练 + 视频对比"""
import torch, torch.nn as nn, numpy as np, os, argparse, time
from pathlib import Path
os.environ['MUJOCO_GL'] = 'osmesa'

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# ============ 共享模块 ============
class VLAEncoder(nn.Module):
    def __init__(self, vla_dim=256):
        super().__init__()
        self.v_enc = nn.Sequential(
            nn.Conv2d(3, 64, 8, 4), nn.ReLU(),
            nn.Conv2d(64, 128, 4, 2), nn.ReLU(),
            nn.Conv2d(128, vla_dim, 4, 2), nn.AdaptiveAvgPool2d(1))
        self.s_proj = nn.Linear(7, vla_dim)
    def forward(self, rgb, state):
        return self.v_enc(rgb).flatten(1) + self.s_proj(state)

class DiTActionHead(nn.Module):
    def __init__(self, in_dim=256, h_dim=512, chunk=14, act_dim=4):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, h_dim), nn.GELU(),
            nn.Linear(h_dim, h_dim*2), nn.GELU(),
            nn.Linear(h_dim*2, chunk*act_dim))
        self.chunk, self.act_dim = chunk, act_dim
    def forward(self, x):
        return self.net(x).view(x.shape[0], self.chunk, self.act_dim)

class LeWorldModel(nn.Module):
    def __init__(self, vla_dim=256, hidden=192, layers=4):
        super().__init__()
        self.tf = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(d_model=vla_dim, nhead=8, dim_feedforward=hidden*4, batch_first=True),
            num_layers=layers)
        self.head = nn.Linear(vla_dim, vla_dim)
    def forward(self, z_present, z_future):
        z = torch.stack([z_present, z_future], dim=1)
        return self.head(self.tf(z)[:, -1])

class ZFlowLayer(nn.Module):
    def __init__(self, in_dim, z_dim):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(in_dim, z_dim*2), nn.GELU(), nn.Linear(z_dim*2, z_dim), nn.LayerNorm(z_dim))
        self.pred = nn.Sequential(nn.Linear(z_dim, z_dim*2), nn.GELU(), nn.Linear(z_dim*2, z_dim), nn.LayerNorm(z_dim))
    def forward(self, x, prior=None):
        if prior is not None: x = x + prior
        z = self.enc(x)
        return z, self.pred(z)

# ============ 三种模型 ============
class ModelA(nn.Module):
    def __init__(self): super().__init__(); self.encoder=VLAEncoder(); self.head=DiTActionHead(256,512,14,4)
    def forward(self,r,s): return self.head(self.encoder(r,s))

class ModelB(nn.Module):
    def __init__(self): super().__init__(); self.encoder=VLAEncoder(); self.head=DiTActionHead(256,512,14,4); self.lew=LeWorldModel(256,192,4)
    def forward(self,r,s): return self.head(self.encoder(r,s)), None

class ModelC(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder=VLAEncoder(); self.head=DiTActionHead(512,256,14,4); self.lew=LeWorldModel(256,192,4)
        self.z_layer=nn.ModuleList([ZFlowLayer(256,256),ZFlowLayer(256,256),ZFlowLayer(256,128)])
        self.td32=nn.Linear(128,256); self.td21=nn.Linear(256,256)
        self.gate=nn.ParameterList([nn.Parameter(torch.tensor(-3.0)) for _ in range(3)])
        self.fuse=nn.Sequential(nn.Linear(640,512),nn.GELU(),nn.LayerNorm(512))
    def forward(self,r,s):
        v=self.encoder(r,s)
        z1,_=self.z_layer[0](v); z2,_=self.z_layer[1](z1); z3,z3p=self.z_layer[2](z2)
        _,z2p=self.z_layer[1](z1,self.td32(z3p)); _,z1p=self.z_layer[0](v,self.td21(z2p))
        gated=[torch.sigmoid(self.gate[i])*z for i,z in enumerate([z1,z2,z3])]
        return self.head(self.fuse(torch.cat(gated,-1)))

# ============ MetaWorld 数据采集 ============
def collect_metaworld_data(task_name='reach-v3', episodes=5, ep_len=50):
    import metaworld
    ml10 = metaworld.ML10()
    env = ml10.train_classes[task_name](render_mode='rgb_array')
    tasks = [t for t in ml10.train_tasks if t.env_name == task_name]
    
    all_obs, all_actions = [], []
    for ep in range(episodes):
        env.set_task(tasks[ep % len(tasks)])
        obs, _ = env.reset()
        for _ in range(ep_len):
            act = env.action_space.sample()
            img = env.render()
            nxt, _, _, _, _ = env.step(act)
            all_obs.append(img)
            all_actions.append(act)
    env.close()
    return np.array(all_obs, dtype=np.float32)/255.0, np.array(all_actions, dtype=np.float32)

# ============ 训练 ============
def train_model(model, obs, actions, epochs=150, lr=1e-4, bs=4):
    model.cpu()
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    obs_t = torch.tensor(np.transpose(obs, (0,3,1,2)), dtype=torch.float32)
    act_t = torch.tensor(actions, dtype=torch.float32)
    N = obs_t.shape[0]
    
    for ep in range(epochs):
        idx = np.random.choice(max(1, N-bs), bs, replace=True)
        rgb, act = obs_t[idx].cpu(), act_t[idx].cpu()
        state = torch.zeros(bs, 7).cpu()
        
        out = model(rgb, state)
        pred_act = out[0] if isinstance(out, tuple) else out
        loss = nn.functional.mse_loss(pred_act[:, 0, :], act)
        opt.zero_grad(); loss.backward(); opt.step()
        if ep % 30 == 0: print(f'  {ep:3d}: loss={loss.item():.6f}')
    return model

# ============ 视频生成 ============
def make_rollout_video(model, task_name, filename, steps=80):
    import metaworld
    ml10 = metaworld.ML10()
    env = ml10.train_classes[task_name](render_mode='rgb_array')
    tasks = [t for t in ml10.train_tasks if t.env_name == task_name]
    env.set_task(tasks[0])
    obs, _ = env.reset()
    
    model.cpu().eval()
    frames = []
    
    for _ in range(steps):
        frames.append(obs)
        img = torch.tensor(obs, dtype=torch.float32).permute(2,0,1).unsqueeze(0).cpu()/255.0
        state = torch.zeros(1,7).cpu()
        with torch.no_grad():
            out = model(img, state)
            act = (out[0] if isinstance(out, tuple) else out)[0,0,:4].cpu().numpy()
        act = np.clip(act, -1, 1)
        obs, _, _, _, _ = env.step(act)
    env.close()
    
    fig, ax = plt.subplots(figsize=(4,4))
    ax.axis('off')
    ims = [[ax.imshow(f, animated=True)] for f in frames]
    ani = animation.ArtistAnimation(fig, ims, interval=80, blit=True)
    ani.save(filename, writer='ffmpeg', dpi=100, fps=12)
    plt.close()
    print(f'  Video: {filename}')

# ============ Main ============
if __name__ == '__main__':
    print('📦 采集 MetaWorld 数据...')
    obs, actions = collect_metaworld_data('reach-v3', episodes=8, ep_len=50)
    print(f'  共 {len(obs)} 帧, action={actions.shape}')
    
    models = [
        (ModelA(), 'A_SmolVLA'),
        (ModelB(), 'B_SmolVLA+LeWM'),
        (ModelC(), 'C_SmolVLA+LeWM+ZFlow'),
    ]
    
    for model, name in models:
        print(f'\n🧬 训练 {name}...')
        train_model(model, obs, actions, epochs=150)
        torch.save(model.state_dict(), f'/root/models/compare/{name}.pt')
        print(f'🎬 生成视频 {name}...')
        make_rollout_video(model, 'reach-v3', f'/tmp/{name}.mp4')
    
    print('\n✅ 三个视频已生成:')
    for _, name in models:
        print(f'  /tmp/{name}.mp4')
