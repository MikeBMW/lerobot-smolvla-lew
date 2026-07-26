"""SmolVLA base 仿真 + 录视频"""
import torch, numpy as np
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from transformers import AutoTokenizer
import gymnasium as gym, gym_pusht
from PIL import Image

m=SmolVLAPolicy.from_pretrained('lerobot/smolvla_base').cuda().eval()
tok=AutoTokenizer.from_pretrained(m.config.vlm_model_name)
enc=tok('push the T block to the target',return_tensors='pt',padding='max_length',max_length=48,truncation=True)

env=gym.make('gym_pusht/PushT-v0',max_episode_steps=300,render_mode='rgb_array')

successes=0
for ep in range(10):
    obs,info=env.reset()
    frames=[]; total_reward=0
    for step in range(300):
        img_rgb=env.render()
        frames.append(Image.fromarray(img_rgb).resize((240,180)))
        img=torch.tensor(img_rgb).cuda().float().permute(2,0,1)/255.0
        state=torch.tensor(obs[:2]).cuda().float()
        ib={'observation.images.camera1':img.unsqueeze(0),
            'observation.images.camera2':img.unsqueeze(0),
            'observation.images.camera3':img.unsqueeze(0),
            'observation.state':state.unsqueeze(0),
            OBS_LANGUAGE_TOKENS:enc['input_ids'].cuda(),
            OBS_LANGUAGE_ATTENTION_MASK:enc['attention_mask'].to(torch.bool).cuda()}
        with torch.no_grad(): action=m.predict_action_chunk(ib)
        obs,reward,term,trunc,info=env.step(action.squeeze(0)[0].cpu().numpy()[:2])
        total_reward+=reward
        if term or trunc: break
    succ=info.get('success',False)
    if succ: successes+=1
    print(f'ep{ep+1}: reward={total_reward:.1f} succ={succ} steps={step+1}')
    if succ:
        frames[0].save(f'/tmp/pusht_succ_{ep}.gif',save_all=True,append_images=frames[1:],duration=50,loop=0)

env.close();del m;torch.cuda.empty_cache()
print(f'\n成功率: {successes}/10')
