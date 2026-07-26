"""采集仿真数据 + 简单专家策略"""
import torch, numpy as np, os
from PIL import Image
import gymnasium as gym, gym_pusht
import torch.nn.functional as F

os.makedirs('outputs/sim_data',exist_ok=True)

env=gym.make('gym_pusht/PushT-v0',max_episode_steps=300,render_mode='rgb_array')

all_states,all_actions,all_images=[],[],[]
n_episodes=10

for ep in range(n_episodes):
    obs,info=env.reset()
    states,actions,images=[],[],[]
    
    for step in range(200):
        # 简易专家: agent朝着T块移动
        agent_pos=obs[:2]          # agent位置
        block_pos=obs[2:4]         # T块位置
        goal_pos=np.array([0,0])   # 目标
        
        # 如果agent靠近T块，推它
        dist_to_block=np.linalg.norm(agent_pos-block_pos)
        if dist_to_block<50:
            # 推T块朝向目标
            target=block_pos+(block_pos-goal_pos)*0.5
            action=target.astype(np.float32)
        else:
            # 移向T块
            action=block_pos.astype(np.float32)
        
        # 加噪声避免过拟合
        action+=np.random.randn(2)*10
        action=np.clip(action,0,512)
        
        # 录制
        rdr=env.render()  # 680×680
        img=torch.tensor(rdr).float().permute(2,0,1)/255.0
        img=F.interpolate(img.unsqueeze(0),size=(96,96),mode='bilinear').squeeze(0)
        
        states.append(obs[:2].copy())
        actions.append(action.copy())
        images.append(img.numpy())
        
        obs,reward,term,trunc,info=env.step(action)
        if term or trunc: break
    
    if len(states)>10:
        all_states.append(np.stack(states))
        all_actions.append(np.stack(actions))
        all_images.append(np.stack(images))
        print(f'ep{ep+1}: {len(states)} frames')

# 保存
np.savez('outputs/sim_data/train_data.npz',
    states=np.concatenate(all_states),
    actions=np.concatenate(all_actions),
    images=np.concatenate(all_images))
env.close()
print(f'\n保存: {sum(len(s) for s in all_states)} 帧')
