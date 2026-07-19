"""train_compare.py — 三种架构对比训练：SmolVLA | SmolVLA+LeWM | SmolVLA+LeWM+ZFlow"""
import torch, torch.nn as nn, numpy as np, os, wandb, time, argparse
from pathlib import Path

# ============ 共享基础模块 ============
class VLAEncoder(nn.Module):
    """VLA 视觉+状态编码器"""
    def __init__(self, vla_dim=256):
        super().__init__()
        self.v_enc = nn.Sequential(
            nn.Conv2d(3, 64, 8, 4), nn.ReLU(),
            nn.Conv2d(64, 128, 4, 2), nn.ReLU(),
            nn.Conv2d(128, vla_dim, 4, 2),
            nn.AdaptiveAvgPool2d(1))
        self.s_proj = nn.Linear(7, vla_dim)

    def forward(self, rgb, state):
        v = self.v_enc(rgb).flatten(1) + self.s_proj(state)
        return v

class DiTActionHead(nn.Module):
    """DiT 动作头: 256D → 14步×7维"""
    def __init__(self, in_dim=256, h_dim=512, chunk=14, act_dim=7):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, h_dim), nn.GELU(),
            nn.Linear(h_dim, h_dim*2), nn.GELU(),
            nn.Linear(h_dim*2, chunk*act_dim))
        self.chunk, self.act_dim = chunk, act_dim

    def forward(self, x):
        return self.net(x).view(x.shape[0], self.chunk, self.act_dim)

class LeWorldModel(nn.Module):
    """LeWorld 世界模型: 预测未来帧表征"""
    def __init__(self, vla_dim=256, hidden=192, layers=4):
        super().__init__()
        self.tf = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=vla_dim, nhead=8,
                dim_feedforward=hidden*4,
                batch_first=True),
            num_layers=layers)
        self.head = nn.Linear(vla_dim, vla_dim)
        self.energy = nn.Sequential(
            nn.Linear(vla_dim, hidden//4), nn.GELU(), nn.Linear(hidden//4, 1))

    def forward(self, z_present, z_future):
        """z_present: (b,d), z_future: (b,d) → predicted z', energy"""
        z = torch.stack([z_present, z_future], dim=1)
        z_out = self.tf(z)[:, -1]
        zp = self.head(z_out)
        e = self.energy(zp)
        return zp, e.mean()

class ZFlowLayer(nn.Module):
    """单层JEPA: 编码器 + 预测器 + 能量"""
    def __init__(self, in_dim, z_dim):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(in_dim, z_dim*2), nn.GELU(), nn.Linear(z_dim*2, z_dim), nn.LayerNorm(z_dim))
        self.pred = nn.Sequential(nn.Linear(z_dim, z_dim*2), nn.GELU(), nn.Linear(z_dim*2, z_dim), nn.LayerNorm(z_dim))
        self.energy = nn.Sequential(nn.Linear(z_dim, z_dim//4), nn.GELU(), nn.Linear(z_dim//4, 1))

    def forward(self, x, prior=None):
        if prior is not None: x = x + prior
        z = self.enc(x)
        zp = self.pred(z)
        e = self.energy(zp)
        return z, zp, e.mean()

# ============ 三种架构 ============
class Model_A_SmolVLA(nn.Module):
    """配置A: 纯 SmolVLA (baseline)"""
    def __init__(self):
        super().__init__()
        self.encoder = VLAEncoder(256)
        self.head = DiTActionHead(256, 512, 14, 7)

    def forward(self, rgb, state):
        v = self.encoder(rgb, state)
        act = self.head(v)
        return act, torch.tensor(0.0)

class Model_B_SmolVLA_LeWM(nn.Module):
    """配置B: SmolVLA + LeWorldModel 并列"""
    def __init__(self):
        super().__init__()
        self.encoder = VLAEncoder(256)
        self.head = DiTActionHead(256, 512, 14, 7)
        self.lew = LeWorldModel(256, 192, 4)

    def forward(self, rgb, state):
        v = self.encoder(rgb, state)
        act = self.head(v)
        # LeWM 用当前帧预测下一帧表征
        z_present = v
        rgb_next = rgb.roll(-1, dims=0)  # 模拟下一帧
        v_next = self.encoder(rgb_next, state)
        _, e = self.lew(z_present, v_next)
        return act, e

class Model_C_ZFlowVLA(nn.Module):
    """配置C: SmolVLA + LeWM + ZFlow 三层潜空间交叉反馈"""
    def __init__(self):
        super().__init__()
        self.encoder = VLAEncoder(256)
        self.lew = LeWorldModel(256, 192, 4)
        self.head = DiTActionHead(512, 256, 14, 7)
        # ZFlow 三层: z1(空间256), z2(物体256), z3(语义128)
        self.z_layer = nn.ModuleList([
            ZFlowLayer(256, 256), ZFlowLayer(256, 256), ZFlowLayer(256, 128)])
        self.td32 = nn.Linear(128, 256)  # z3→z2
        self.td21 = nn.Linear(256, 256)  # z2→z1
        self.gate = nn.ParameterList([nn.Parameter(torch.tensor(-3.0)) for _ in range(3)])
        self.fuse = nn.Sequential(nn.Linear(640, 512), nn.GELU(), nn.LayerNorm(512))
        self.train_mode = True

    def forward(self, rgb, state):
        v = self.encoder(rgb, state)
        # ZFlow 三层
        z1, z1p, e1 = self.z_layer[0](v)
        z2, z2p, e2 = self.z_layer[1](z1)
        z3, z3p, e3 = self.z_layer[2](z2)
        # 级联反馈
        _, z2p_c, e2c = self.z_layer[1](z1, self.td32(z3p))
        _, z1p_c, e1c = self.z_layer[0](v, self.td21(z2p_c))
        e_flow = (e1+e2+e3+e1c+e2c)/5
        # 门控
        gated = [torch.sigmoid(self.gate[i]) * z for i, z in enumerate([z1, z2, z3])]
        # LeWM
        rgb_next = rgb.roll(-1, dims=0)
        v_next = self.encoder(rgb_next, state)
        _, e_lew = self.lew(v, v_next)
        # 融合
        fused = self.fuse(torch.cat(gated, -1))
        act = self.head(fused)
        return act, (e_flow + e_lew) / 2

    def set_train(self): self.train_mode = True
    def set_infer(self): self.train_mode = False

# ============ 训练 ============
def train(model, name, data_dir, epochs=200, lr=1e-4, bs=8):
    model = model.cuda()
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    files = list(Path(data_dir).glob("*_real.npz"))
    
    # 加载数据
    data = []
    for f in files:
        d = np.load(f)
        obs = d['observations']
        if obs.shape[-1] == 3: obs = np.transpose(obs, (0, 3, 1, 2))
        n = min(obs.shape[0], d['states'].shape[0])
        data.append({
            'obs': torch.tensor(obs[:n], dtype=torch.float32)/255.0,
            'state': torch.tensor(d['states'][:n, :7] if d['states'].shape[1]>=7 else 
                np.pad(d['states'][:n], ((0,0),(0,7-d['states'].shape[1]))), dtype=torch.float32)})
    
    wandb.init(project='zmax-compare', name=name)
    best_loss = float('inf')
    
    for epoch in range(epochs):
        t = data[np.random.randint(0, len(data))]
        idx = np.random.choice(max(1, t['obs'].shape[0]-bs-1), bs, replace=True)
        rgb = t['obs'][idx].cuda()
        state = t['state'][idx].cuda()
        
        act, e = model(rgb, state)
        loss_act = nn.functional.mse_loss(act, torch.zeros_like(act))
        loss = loss_act + 0.01 * e
        
        opt.zero_grad()
        loss.backward()
        opt.step()
        
        if epoch % 20 == 0:
            wandb.log({'epoch': epoch, 'loss_act': loss_act.item(), 'energy': e.item(), 'total': loss.item()})
            print(f'{name} {epoch:3d}: act={loss_act.item():.5f} E={e.item():.4f}')
        
        if loss.item() < best_loss:
            best_loss = loss.item()
            os.makedirs(f'/root/models/compare', exist_ok=True)
            torch.save(model.state_dict(), f'/root/models/compare/{name}.pt')
    
    wandb.finish()
    return best_loss

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['A','B','C','all'], default='all')
    parser.add_argument('--data', default='/root/datasets/metaworld/tasks')
    parser.add_argument('--epochs', type=int, default=200)
    args = parser.parse_args()
    
    models = {
        'A': (Model_A_SmolVLA, 'A_SmolVLA'),
        'B': (Model_B_SmolVLA_LeWM, 'B_SmolVLA+LeWM'),
        'C': (Model_C_ZFlowVLA, 'C_SmolVLA+LeWM+ZFlow'),
    }
    
    results = {}
    for mode, (cls, name) in models.items():
        if args.mode != 'all' and args.mode != mode:
            continue
        print(f'\n{"="*50}\n🔬 训练 {name}\n{"="*50}')
        t0 = time.time()
        loss = train(cls(), name, args.data, args.epochs)
        elapsed = time.time() - t0
        results[name] = {'loss': loss, 'time': elapsed}
        print(f'✅ {name}: best_loss={loss:.5f} ({elapsed:.0f}s)')
    
    print('\n🏆 对比结果:')
    for name, r in sorted(results.items(), key=lambda x: x[1]['loss']):
        print(f'  {name}: loss={r["loss"]:.5f}  ({r["time"]:.0f}s)')
