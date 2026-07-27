"""Z-MAX Hybrid 仿真 — 手动处理图像"""
import torch, numpy as np
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
import gymnasium as gym, gym_pusht
import torch.nn.functional as F

ckpt='outputs/zmax_hybrid_final/checkpoints/020000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
pre,post=make_pre_post_processors(m.config,ckpt,
    preprocessor_overrides={'device_processor':{'device':'cuda'}})

env=gym.make('gym_pusht/PushT-v0',max_episode_steps=300,render_mode='rgb_array')

for ep in range(5):
    obs,info=env.reset()
    total_reward=0
    for step in range(300):
        rdr=env.render()  # 640×480×3
        # 手动resize到96×96匹配训练数据
        img=torch.tensor(rdr).float().permute(2,0,1)/255.0
        img=F.interpolate(img.unsqueeze(0),size=(96,96),mode='bilinear').squeeze(0)
        state=torch.tensor(obs[:2]).float()
        
        batch={'observation.image':img.unsqueeze(0).cuda(),
               'observation.state':state.unsqueeze(0).cuda(),
               'task':'push the T block to the target'}
        pp=pre(batch)
        with torch.no_grad(): action=m.predict_action_chunk(pp)
        action=post(action).cpu().numpy().squeeze(0)[0]
        # Skalierung an gym [0,512]
        action=np.clip(action*2.0,0,512)
        
        obs,reward,term,trunc,info=env.step(action)
        total_reward+=reward
        if term or trunc: break
    
    succ=info.get('success',False)
    print(f'ep{ep+1}: reward={total_reward:.1f} succ={succ} steps={step+1}')

env.close();del m;torch.cuda.empty_cache()
