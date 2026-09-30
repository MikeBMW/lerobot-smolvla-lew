"""ZmaxHybrid 40K → PushT 仿真"""
import torch, numpy as np, time
import gymnasium as gym; import gym_pusht
from lerobot.policies.zmax_hybrid.modeling_zmax_hybrid import ZmaxHybridPolicy

CKPT = "outputs/zmax_hybrid_final/checkpoints/040000/pretrained_model"
N_EP = 10

print(f"Loading ZmaxHybrid from {CKPT}...")
policy = ZmaxHybridPolicy.from_pretrained(CKPT).cuda().eval()

env = gym.make("gym_pusht/PushT-v0", max_episode_steps=300, render_mode="rgb_array")
succ = 0; rewards = []

for ep in range(N_EP):
    obs, _ = env.reset(); r = 0.0; t0 = time.time()
    for step in range(300):
        img = torch.from_numpy(env.render()).float().permute(2, 0, 1) / 255.0
        st = torch.tensor(obs[:2]).float()
        b = {
            "observation.images.camera1": img.unsqueeze(0).cuda(),
            "observation.images.camera2": img.unsqueeze(0).cuda(),
            "observation.images.camera3": img.unsqueeze(0).cuda(),
            "observation.state": st.unsqueeze(0).cuda(),
        }
        with torch.no_grad():
            act = policy.predict_action_chunk(b)
        obs, rew, term, trunc, info = env.step(act[0, 0, :2].cpu().numpy())
        r += rew
        if term or trunc:
            break
    s = info.get("success", False); succ += s; rewards.append(r)
    tag = "✅" if s else ("⚡" if r > 50 else ("➡️" if r > 10 else "❌"))
    print(f"ep{ep+1:2d}: {tag}  steps={step+1:3d}  reward={r:6.1f}  time={time.time()-t0:.0f}s  [{succ}/{ep+1}]")

env.close(); del policy; torch.cuda.empty_cache()
print(f"\n=== ZmaxHybrid 40K: {succ}/{N_EP} 成功 | 最高={max(rewards):.1f} | 平均={np.mean(rewards):.1f} ===")
