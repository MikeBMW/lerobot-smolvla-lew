"""录像仿真评估"""
import torch, numpy as np
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
import gymnasium as gym
import gym_pusht
from PIL import Image

ckpt='outputs/zmax_hybrid_final/checkpoints/020000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
pre,post=make_pre_post_processors(m.config,ckpt,
    preprocessor_overrides={'device_processor':{'device':'cuda'}})

env=gym.make('gym_pusht/PushT-v0',max_episode_steps=200,render_mode='rgb_array')
obs,info=env.reset()

frames=[]
total_reward=0
for step in range(200):
    img_rgb=env.render()
    frames.append(Image.fromarray(img_rgb).resize((240,180)))
    
    img=torch.tensor(img_rgb).cuda().float().permute(2,0,1)/255.0
    state=torch.tensor(obs[:2]).cuda().float()
    batch={'observation.image':img.unsqueeze(0),'observation.state':state.unsqueeze(0),'task':'push the block'}
    pp=pre(batch)
    with torch.no_grad(): action=m.predict_action_chunk(pp)
    action=post(action).cpu().numpy().squeeze(0)[0]
    obs,reward,term,trunc,info=env.step(action)
    total_reward+=reward
    if term or trunc: break

env.close();del m;torch.cuda.empty_cache()

# 保存GIF
frames[0].save('/tmp/pusht_rollout.gif',save_all=True,append_images=frames[1:],
               duration=50,loop=0)
print(f'录制完成: {len(frames)}帧, reward={total_reward:.2f}, 成功={info.get("success",False)}')
print(f'文件: /tmp/pusht_rollout.gif')
