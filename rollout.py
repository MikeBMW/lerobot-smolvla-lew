"""Hybrid PushT 仿真评估 — render获取图像"""
import torch, numpy as np
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
import gymnasium as gym
import gym_pusht

ckpt='outputs/zmax_hybrid_final/checkpoints/020000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
pre,post=make_pre_post_processors(m.config,ckpt,
    preprocessor_overrides={'device_processor':{'device':'cuda'}})

env=gym.make('gym_pusht/PushT-v0',max_episode_steps=200,render_mode='rgb_array')

for ep in range(5):
    obs,info=env.reset()
    total_reward=0
    for step in range(200):
        # 从render获取图像
        img_rgb=env.render()  # (480,640,3) uint8
        img=torch.tensor(img_rgb).cuda().float().permute(2,0,1)/255.0
        state=torch.tensor(obs[:2]).cuda().float()  # 只取agent坐标 [x,y]
        
        batch={'observation.image':img.unsqueeze(0),'observation.state':state.unsqueeze(0),'task':'push the block'}
        pp=pre(batch)
        with torch.no_grad(): action=m.predict_action_chunk(pp)
        action=post(action).cpu().numpy().squeeze(0)[0]
        
        obs,reward,term,trunc,info=env.step(action)
        total_reward+=reward
        if term or trunc: break
    
    success=info.get('success',False)
    print(f'ep{ep+1}: reward={total_reward:.2f} succ={success} steps={step+1}')

env.close();del m;torch.cuda.empty_cache()
