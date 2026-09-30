"""Diffusion Pusht — 10步推理 × 20集"""
import torch, numpy as np, time, sys
import gymnasium as gym; import gym_pusht
from lerobot.policies.diffusion.modeling_diffusion import DiffusionPolicy
from collections import deque

N_EP = 20
N_STEPS = 10  # 扩散推断步数

p = DiffusionPolicy.from_pretrained('lerobot/diffusion_pusht').cuda().eval()
p.config.num_inference_steps = N_STEPS
p.diffusion.num_inference_steps = N_STEPS

env = gym.make('gym_pusht/PushT-v0', max_episode_steps=300, render_mode='rgb_array')
succ = 0
rewards = []

for ep in range(N_EP):
    obs, _ = env.reset()
    r = 0.0
    t0 = time.time()
    ib, sb = deque(maxlen=2), deque(maxlen=2)
    
    for step in range(300):
        img = torch.from_numpy(env.render()).float().permute(2, 0, 1) / 255.0
        st = torch.tensor(obs[:2]).float()
        ib.append(img); sb.append(st)
        if step == 0:
            ib.appendleft(img); sb.appendleft(st)
        oi = torch.stack(list(ib), dim=0)
        os_ = torch.stack(list(sb), dim=0)
        b = {'observation.image': oi.unsqueeze(0).cuda(),
             'observation.state': os_.unsqueeze(0).cuda()}
        with torch.no_grad():
            a = p.predict_action_chunk(b)
        obs, rew, term, trunc, info = env.step(a[0, 0, :2].cpu().numpy())
        r += rew
        if term or trunc:
            break
    
    s = info.get('success', False)
    succ += s
    rewards.append(r)
    tag = '✅' if s else ('⚡' if r > 50 else ('➡️' if r > 10 else '❌'))
    print(f'ep{ep+1:2d}: {tag}  steps={step+1:3d}  reward={r:6.1f}  '
          f'time={time.time()-t0:.0f}s  [{succ}/{ep+1}]')

env.close()
del p
torch.cuda.empty_cache()
print(f'\n=== {succ}/{N_EP} 成功 | 最高reward={max(rewards):.1f} | 平均={np.mean(rewards):.1f} ===')
