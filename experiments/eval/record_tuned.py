"""录一集视频"""
import torch, numpy as np
from lerobot.policies.zmax_hybrid import ZmaxHybridPolicy
from lerobot.policies.factory import make_pre_post_processors
import gymnasium as gym, gym_pusht
import torch.nn.functional as F
from PIL import Image

ckpt='outputs/zmax_hybrid_final/checkpoints/020000/pretrained_model'
m=ZmaxHybridPolicy.from_pretrained(ckpt,local_files_only=True).cuda().eval()
m.load_state_dict(torch.load('outputs/sim_data/hybrid_simtuned.pt'),strict=False)

pre,post=make_pre_post_processors(m.config,ckpt,
    preprocessor_overrides={'device_processor':{'device':'cuda'}})
env=gym.make('gym_pusht/PushT-v0',max_episode_steps=300,render_mode='rgb_array')

obs,_=env.reset(); frames=[]; r=0
for step in range(300):
    rdr=env.render()
    frames.append(Image.fromarray(rdr).resize((340,340)))
    img=torch.tensor(rdr).float().permute(2,0,1)/255.0
    img=F.interpolate(img.unsqueeze(0),size=(96,96),mode='bilinear').squeeze(0)
    st=torch.tensor(obs[:2]).float()
    b={'observation.image':img.unsqueeze(0).cuda(),'observation.state':st.unsqueeze(0).cuda(),'task':'push the block'}
    pp=pre(b)
    with torch.no_grad(): a=m.predict_action_chunk(pp)
    act=post(a).cpu().numpy().squeeze(0)[0]; act=np.clip(act*2,0,512)
    obs,reward,term,trunc,info=env.step(act); r+=reward
    if term or trunc: break

env.close()
frames[0].save('/tmp/hybrid_tuned.gif',save_all=True,append_images=frames[1:],duration=50,loop=0)
print(f'{len(frames)}帧 reward={r:.1f} 成功={info.get("success",False)}')
