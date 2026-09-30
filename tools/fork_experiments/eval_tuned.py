"""仿真测试微调后的Hybrid"""
import torch, numpy as np
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
import gymnasium as gym, gym_pusht
import torch.nn.functional as F

ckpt='outputs/zmax_hybrid_final/checkpoints/020000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
m.load_state_dict(torch.load('outputs/sim_data/hybrid_simtuned.pt'),strict=False)

pre,post=make_pre_post_processors(m.config,ckpt,
    preprocessor_overrides={'device_processor':{'device':'cuda'}})
env=gym.make('gym_pusht/PushT-v0',max_episode_steps=300,render_mode='rgb_array')

succ=0
for ep in range(10):
    obs,_=env.reset(); r=0
    for step in range(300):
        rdr=env.render()
        img=torch.tensor(rdr).float().permute(2,0,1)/255.0
        img=F.interpolate(img.unsqueeze(0),size=(96,96),mode='bilinear').squeeze(0)
        st=torch.tensor(obs[:2]).float()
        b={'observation.image':img.unsqueeze(0).cuda(),'observation.state':st.unsqueeze(0).cuda(),'task':'push the block'}
        pp=pre(b)
        with torch.no_grad(): a=m.predict_action_chunk(pp)
        act=post(a).cpu().numpy().squeeze(0)[0]
        act=np.clip(act*2,0,512)
        obs,reward,term,trunc,info=env.step(act); r+=reward
        if term or trunc: break
    s=info.get('success',False)
    if s: succ+=1
    print(f'ep{ep+1}: r={r:.1f} succ={s}')

env.close();print(f'\n{succ}/10');del m;torch.cuda.empty_cache()
