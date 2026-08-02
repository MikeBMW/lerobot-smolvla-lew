#!/usr/bin/env python3
"""7电机模型单独评估: 用同数据(metaworld_joint_v2) 测试集验证泛化"""
import json, sys, time
from pathlib import Path
import numpy as np
import torch

proj = Path.home() / "lerobot-smolvla-lew"
sys.path.insert(0, str(proj / "src"))

def main():
    ckpt = sys.argv[1] if len(sys.argv) > 1 else str(proj / "outputs/train/act_7motor/checkpoints/002000/pretrained_model")
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies import make_pre_post_processors
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    print("⏳ 加载模型...")
    policy = ACTPolicy.from_pretrained(ckpt).cuda().eval()
    _, post = make_pre_post_processors(policy_cfg=policy.config, pretrained_path=str(ckpt))
    print(f"✅ 模型: state{list(policy.config.input_features['observation.state'].shape)} "
          f"action{list(policy.config.output_features['action'].shape)}")

    ds = LeRobotDataset("lerobot/pusht", root=str(proj / "data/metaworld_joint_v2"))
    n = len(ds)
    # 测试集: 后 30% 帧 (训练未见)
    test_idx = list(range(int(n * 0.7), n))
    mses, lats = [], []
    hits = 0
    t0 = time.time()
    for i in test_idx:
        item = ds[i]
        batch = {
            "observation.state": item["observation.state"].float().cuda().unsqueeze(0),
            "observation.image": item["observation.image"].float().cuda().unsqueeze(0),
        }
        gt = item["action"].numpy()
        ts = time.time()
        out = post(policy.select_action(batch))
        lat = (time.time() - ts) * 1000
        pred = np.asarray(out[0].cpu().numpy()).flatten()
        n = min(len(pred), len(gt))
        mse = float(np.mean((pred[:n] - gt[:n]) ** 2))
        mses.append(mse)
        lats.append(lat)
        if mse < 0.05:
            hits += 1
    mse = float(np.mean(mses))
    print(f"\n📊 7电机模型评估 (测试集 {len(test_idx)} 帧):")
    print(f"  MSE = {mse:.4f}")
    print(f"  成功率(<0.05) = {hits/len(test_idx)*100:.1f}%")
    print(f"  推理延迟 = {np.mean(lats):.1f}ms")
    print(f"  推理速度 = {1/(np.mean(lats)/1000):.0f} Hz")
    result = {"model": "act_7motor", "frames": len(test_idx),
              "action_mse": round(mse, 4), "success_rate": round(hits/len(test_idx), 3),
              "latency_ms": round(float(np.mean(lats)), 2)}
    out = proj / "docs" / "EVAL_7MOTOR.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"💾 保存: {out}")

if __name__ == "__main__":
    main()
