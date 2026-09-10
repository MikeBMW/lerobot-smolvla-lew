#!/usr/bin/env python3
"""
ACT 策略推理验证 — Z-MAX 控制台
用法:
  python3 act_infer.py [模型路径或HF ID] [--image 图片路径] [--device cuda|cpu]

模型来源:
  - HF预训练: lerobot/aloha_static_act (官方ACT演示模型)
  - 本地训练产物: outputs/xxx/checkpoints/000300/pretrained_model
"""
import os
import sys
import time
import argparse
import numpy as np

os.environ.setdefault("WANDB_MODE", "disabled")
# 国内镜像（可选）
if os.environ.get("HF_ENDPOINT") is None:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)


def build_dummy_obs(policy, device, batch_size=1):
    """按策略输入特征构造合成观测"""
    import torch
    obs = {}
    for name, feat in policy.config.input_features.items():
        shape = [batch_size] + list(feat.shape)
        obs[name] = torch.randn(*shape, device=device)
    return obs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="?", default="lerobot/aloha_static_act",
                    help="模型路径或HF ID")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--steps", type=int, default=3, help="推理轮数")
    ap.add_argument("--image", default=None, help="真实图片路径(可选)")
    ap.add_argument("--random", action="store_true", help="用随机权重验证推理链路(跳过模型下载)")
    args = ap.parse_args()

    import torch
    from lerobot.policies.act import ACTConfig, ACTPolicy

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"🚀 ACT 推理验证 | 模型: {args.model} | 设备: {device}")

    t0 = time.time()
    if args.random:
        # 随机权重 — 验证推理链路 (Z-MAX 光模块插拔: 6轴+夹爪 = 7维动作)
        from lerobot.configs.types import FeatureType, PolicyFeature
        cfg = ACTConfig(
            n_obs_steps=1,
            chunk_size=50,
            n_action_steps=50,
            input_features={
                "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(6,)),
                "observation.images.cam_high": PolicyFeature(type=FeatureType.VISUAL, shape=(3, 480, 640)),
            },
            output_features={"action": PolicyFeature(type=FeatureType.ACTION, shape=(7,))},
        )
        policy = ACTPolicy(cfg)
        print("   ✅ 随机权重模型构建完成 (跳过下载)")
    else:
        policy = ACTPolicy.from_pretrained(args.model, local_files_only=os.path.exists(args.model))
    policy = policy.to(device)
    policy.eval()
    t1 = time.time()
    print(f"   ✅ 模型加载: {t1-t0:.1f}s")

    total = sum(p.numel() for p in policy.parameters())
    print(f"   🧠 参数: {total/1e6:.1f}M")
    cfg = policy.config
    print(f"   📋 cfg: n_obs={cfg.n_obs_steps} chunk={cfg.chunk_size} "
          f"n_action={cfg.n_action_steps} backbone={cfg.vision_backbone}")

    # 合成观测推理
    obs = build_dummy_obs(policy, device)
    with torch.no_grad():
        for i in range(args.steps):
            t2 = time.time()
            out = policy.select_action(obs)
            dt = time.time() - t2
            arr = np.asarray(out.detach().cpu() if torch.is_tensor(out) else out)
            print(f"   🔮 推理[{i+1}/{args.steps}]: {dt*1000:.0f}ms | shape={arr.shape} "
                  f"| 前5值={arr.flatten()[:5].round(3).tolist()}")

    print("\n✅ ACT 推理验证通过")
    print(f"   输出动作维度: {arr.shape}")


if __name__ == "__main__":
    main()
