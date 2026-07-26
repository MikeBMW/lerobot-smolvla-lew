"""SmolVLA base PushT 标准评估 — 用 LeRobot 官方 pipeline"""
import torch, numpy as np, time
import gymnasium as gym
import gym_pusht
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from transformers import AutoTokenizer

N_EPISODES = 10
MAX_STEPS = 300

print(f"Loading SmolVLA base from HuggingFace...")
policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base")
policy.cuda().eval()

tokenizer = AutoTokenizer.from_pretrained(policy.config.vlm_model_name)
tokens = tokenizer("push the T block to the target", return_tensors="pt",
                   max_length=48, padding="max_length", truncation=True)

env = gym.make("gym_pusht/PushT-v0", max_episode_steps=MAX_STEPS, render_mode="rgb_array")

successes = []
total_rewards = []
total_steps = []
times = []

for ep in range(1, N_EPISODES + 1):
    obs, _ = env.reset()
    ep_reward = 0
    t0 = time.time()

    for step in range(MAX_STEPS):
        # 构建 batch (和 LeRobot eval pipeline 一致)
        img = torch.from_numpy(env.render()).float().permute(2, 0, 1) / 255.0
        state = torch.tensor(obs[:2]).float()

        batch = {
            "observation.images.camera1": img.unsqueeze(0).cuda(),
            "observation.images.camera2": img.unsqueeze(0).cuda(),
            "observation.images.camera3": img.unsqueeze(0).cuda(),
            "observation.state": state.unsqueeze(0).cuda(),
            OBS_LANGUAGE_TOKENS: tokens["input_ids"].cuda(),
            OBS_LANGUAGE_ATTENTION_MASK: tokens["attention_mask"].to(torch.bool).cuda(),
        }

        with torch.no_grad():
            actions = policy.predict_action_chunk(batch)  # [1, chunk, act_dim]
        action = actions[0, 0, :2].cpu().numpy()

        obs, reward, terminated, truncated, info = env.step(action)
        ep_reward += reward

        if terminated or truncated:
            break

    elapsed = time.time() - t0
    success = info.get("success", False)
    successes.append(success)
    total_rewards.append(ep_reward)
    total_steps.append(step + 1)
    times.append(elapsed)

    print(f"  ep {ep:2d}: {'✅' if success else '❌'}  steps={step+1:3d}  "
          f"reward={ep_reward:.1f}  time={elapsed:.1f}s")

env.close()
del policy
torch.cuda.empty_cache()

print(f"\n{'='*50}")
print(f"SmolVLA base PushT 评估结果 (N={N_EPISODES})")
print(f"{'='*50}")
print(f"  成功率:    {sum(successes)}/{N_EPISODES} ({100*sum(successes)/N_EPISODES:.0f}%)")
print(f"  平均步数:  {np.mean(total_steps):.0f}")
print(f"  平均奖励:  {np.mean(total_rewards):.1f}")
print(f"  平均时间:  {np.mean(times):.1f}s/ep")
print(f"{'='*50}")
