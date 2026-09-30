#!/usr/bin/env python3
"""
LeWorldModel 独立验证脚本 (Standalone Validator)

这个脚本只验证 world_model_le.py 的核心组件，不依赖 lerobot 框架。
可以在任何有 torch + einops 的环境中直接运行。

用法:
    python validate_world_model.py

预期输出:
    - 所有 Embedder / Transformer / ConditionalBlock / ARPredictor 组件通过
    - 完整 LeWorldModel forward + backward 测试通过
    - 梯度正常流动
"""

import sys
import torch
import torch.nn.functional as F

# 将当前目录加入路径
sys.path.insert(0, ".")

# ============================================================================
# 测试 1: 基础组件
# ============================================================================

def test_basic_components():
    """测试基础组件: modulate, FeedForward, Attention, ConditionalBlock"""
    print("\n" + "=" * 60)
    print("测试 1: 基础组件")
    print("=" * 60)
    
    from world_model_le import modulate, FeedForward, Attention, ConditionalBlock
    
    # 测试 modulate
    print("\n  1.1 modulate (AdaLN-zero)...")
    x = torch.randn(2, 10, 64)
    shift = torch.randn(2, 1, 64)
    scale = torch.randn(2, 1, 64)
    out = modulate(x, shift, scale)
    assert out.shape == x.shape, f"Shape mismatch: {out.shape} vs {x.shape}"
    print(f"      ✓ x={list(x.shape)}, shift={list(shift.shape)} -> {list(out.shape)}")
    
    # 测试 FeedForward
    print("\n  1.2 FeedForward...")
    ff = FeedForward(dim=64, hidden_dim=256)
    x = torch.randn(2, 10, 64)
    out = ff(x)
    assert out.shape == x.shape
    print(f"      ✓ x={list(x.shape)} -> {list(out.shape)}")
    
    # 测试 Attention
    print("\n  1.3 Attention (causal)...")
    attn = Attention(dim=64, heads=8, dim_head=8)
    x = torch.randn(2, 10, 64)
    out = attn(x, causal=True)
    assert out.shape == x.shape
    print(f"      ✓ x={list(x.shape)} -> {list(out.shape)}")
    
    # 测试 ConditionalBlock
    print("\n  1.4 ConditionalBlock (AdaLN-zero)...")
    block = ConditionalBlock(dim=64, heads=8, dim_head=8, mlp_dim=256)
    x = torch.randn(2, 10, 64)
    c = torch.randn(2, 1, 64)  # condition
    out = block(x, c)
    assert out.shape == x.shape
    print(f"      ✓ x={list(x.shape)}, c={list(c.shape)} -> {list(out.shape)}")
    
    print("\n  ✓ 所有基础组件通过")
    return True


# ============================================================================
# 测试 2: Transformer + ARPredictor
# ============================================================================

def test_transformer_and_predictor():
    """测试 Transformer 和 ARPredictor"""
    print("\n" + "=" * 60)
    print("测试 2: Transformer + ARPredictor")
    print("=" * 60)
    
    from world_model_le import Transformer, ARPredictor
    
    # 测试 Transformer
    print("\n  2.1 Transformer (AdaLN-zero conditioned)...")
    transformer = Transformer(
        input_dim=32,
        hidden_dim=64,
        output_dim=32,
        depth=2,
        heads=4,
        dim_head=16,
        mlp_dim=128,
    )
    x = torch.randn(2, 10, 32)
    c = torch.randn(2, 1, 32)  # condition
    out = transformer(x, c)
    assert out.shape == x.shape
    print(f"      ✓ x={list(x.shape)}, c={list(c.shape)} -> {list(out.shape)}")
    
    # 测试 ARPredictor
    print("\n  2.2 ARPredictor (position embedding + Transformer)...")
    predictor = ARPredictor(
        num_frames=10,
        depth=2,
        heads=4,
        mlp_dim=128,
        input_dim=32,
        hidden_dim=64,
        output_dim=32,
        dim_head=16,
    )
    x = torch.randn(2, 10, 32)
    c = torch.randn(2, 10, 32)  # condition per timestep
    out = predictor(x, c)
    assert out.shape == x.shape
    print(f"      ✓ x={list(x.shape)}, c={list(c.shape)} -> {list(out.shape)}")
    
    # 参数量
    params = sum(p.numel() for p in predictor.parameters())
    print(f"      ARPredictor 参数量: {params:,}")
    
    print("\n  ✓ Transformer + ARPredictor 通过")
    return True


# ============================================================================
# 测试 3: Embedder (Action Encoder)
# ============================================================================

def test_embedder():
    """测试 Embedder"""
    print("\n" + "=" * 60)
    print("测试 3: Embedder (Action Encoder)")
    print("=" * 60)
    
    from world_model_le import Embedder
    
    print("\n  3.1 Embedder (action -> embedding)...")
    embedder = Embedder(
        input_dim=4,   # action_dim
        smoothed_dim=8,
        emb_dim=64,
        mlp_scale=4,
    )
    actions = torch.randn(2, 10, 4)  # [B, T, action_dim]
    out = embedder(actions)
    assert out.shape == (2, 10, 64), f"Shape mismatch: {out.shape}"
    print(f"      ✓ actions={list(actions.shape)} -> embeddings={list(out.shape)}")
    
    params = sum(p.numel() for p in embedder.parameters())
    print(f"      Embedder 参数量: {params:,}")
    
    print("\n  ✓ Embedder 通过")
    return True


# ============================================================================
# 测试 4: 完整 LeWorldModel (模拟 SigLIP + Predictor)
# ============================================================================

def test_le_world_model():
    """测试完整 LeWorldModel (使用 mock vision encoder)"""
    print("\n" + "=" * 60)
    print("测试 4: LeWorldModel (完整 forward + backward)")
    print("=" * 60)
    
    from world_model_le import LeWorldModel
    from types import SimpleNamespace
    
    # 创建 mock vision encoder (模拟 SigLIP)
    class MockVisionEncoder(torch.nn.Module):
        def __init__(self, hidden_size=768):
            super().__init__()
            self.config = SimpleNamespace(
                vision_config=SimpleNamespace(hidden_size=hidden_size)
            )
            # 简单的 CNN 替代 SigLIP
            self.conv = torch.nn.Conv2d(3, hidden_size, kernel_size=32, stride=32)
            self.projection = torch.nn.Linear(hidden_size, hidden_size)
        
        def __call__(self, pixel_values):
            B, C, H, W = pixel_values.shape
            x = self.conv(pixel_values)  # [B, hidden, 1, 1]
            x = x.squeeze(-1).squeeze(-1)  # [B, hidden]
            x = self.projection(x)
            # 返回类似 transformers 的输出格式
            return SimpleNamespace(
                last_hidden_state=x.unsqueeze(1)  # [B, 1, hidden]
            )
    
    # 配置
    action_dim = 4
    obs_embed_dim = 64
    hidden_dim = 64
    num_layers = 2
    num_frames = 2  # 最小帧数 (t, t+1)
    
    vision_encoder = MockVisionEncoder(hidden_size=768)
    
    print("\n  4.1 初始化 LeWorldModel...")
    model = LeWorldModel(
        vision_encoder=vision_encoder,
        action_dim=action_dim,
        obs_embed_dim=obs_embed_dim,
        hidden_dim=hidden_dim,
        num_layers=num_layers,
        num_heads=4,
        dim_head=16,
        mlp_dim=256,
        num_frames=num_frames,
        dropout=0.1,
    )
    print(f"      ✓ 初始化成功")
    
    # 统计参数
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"      总参数: {total_params:,}")
    print(f"      可训练: {trainable_params:,}")
    
    # 创建假数据
    print("\n  4.2 创建假数据...")
    batch_size = 2
    num_views = 1
    T = num_frames
    H, W = 32, 32
    C = 3
    
    videos = torch.randn(batch_size, num_views, T, C, H, W)
    actions = torch.randn(batch_size, T, action_dim)
    
    print(f"      videos: {list(videos.shape)}")
    print(f"      actions: {list(actions.shape)}")
    
    # Forward
    print("\n  4.3 Forward (L1 loss)...")
    loss = model(videos, actions)
    print(f"      ✓ loss = {loss.item():.6f}")
    assert loss.item() > 0, "Loss should be positive"
    
    # Backward
    print("\n  4.4 Backward (梯度流动)...")
    loss.backward()
    
    # 检查梯度
    grad_count = 0
    for name, param in model.named_parameters():
        if param.grad is not None and param.grad.abs().sum() > 0:
            grad_count += 1
    
    total_params_with_grad = sum(1 for p in model.parameters() if p.requires_grad)
    print(f"      ✓ {grad_count}/{total_params_with_grad} 参数有梯度")
    
    if grad_count == 0:
        print("      ✗ 警告: 没有任何参数收到梯度!")
        return False
    
    print("\n  ✓ LeWorldModel 完整测试通过")
    return True


# ============================================================================
# 测试 5: Rollout (推理)
# ============================================================================

def test_rollout():
    """测试 rollout 推理"""
    print("\n" + "=" * 60)
    print("测试 5: Rollout (推理模式)")
    print("=" * 60)
    
    from world_model_le import LeWorldModel, Embedder, ARPredictor
    from types import SimpleNamespace
    
    # Mock vision encoder
    class MockVisionEncoder(torch.nn.Module):
        def __init__(self, hidden_size=768):
            super().__init__()
            self.config = SimpleNamespace(
                vision_config=SimpleNamespace(hidden_size=hidden_size)
            )
            self.conv = torch.nn.Conv2d(3, hidden_size, kernel_size=32, stride=32)
            self.projection = torch.nn.Linear(hidden_size, hidden_size)
        
        def __call__(self, pixel_values):
            B, C, H, W = pixel_values.shape
            x = self.conv(pixel_values)
            x = x.squeeze(-1).squeeze(-1)
            x = self.projection(x) if hasattr(self, 'projection') else x
            return SimpleNamespace(last_hidden_state=x.unsqueeze(1))
    
    action_dim = 4
    obs_embed_dim = 64
    
    vision_encoder = MockVisionEncoder(hidden_size=768)
    model = LeWorldModel(
        vision_encoder=vision_encoder,
        action_dim=action_dim,
        obs_embed_dim=obs_embed_dim,
        hidden_dim=64,
        num_layers=2,
        num_heads=4,
        dim_head=16,
        mlp_dim=256,
        num_frames=2,
        dropout=0.0,
    )
    model.eval()
    
    print("\n  5.1 自回归 Rollout...")
    # 初始帧
    init_frame = torch.randn(2, 1, 3, 32, 32)  # [B, V, C, H, W]
    
    # 未来动作序列
    rollout_steps = 5
    action_sequence = torch.randn(2, rollout_steps, action_dim)
    
    with torch.no_grad():
        rollout_emb = model.rollout(init_frame, action_sequence)
    
    print(f"      ✓ rollout_emb shape: {list(rollout_emb.shape)}")
    assert rollout_emb.shape[0] == 2  # batch
    assert rollout_emb.shape[1] == rollout_steps + 1  # initial + rollout
    
    print("\n  ✓ Rollout 推理通过")
    return True


# ============================================================================
# 主函数
# ============================================================================

def main():
    print("\n" + "=" * 60)
    print(" LeWorldModel 独立验证脚本")
    print("=" * 60)
    print(f"\n环境: PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}")
    
    results = []
    
    try:
        results.append(("基础组件", test_basic_components()))
    except Exception as e:
        print(f"\n  ✗ 基础组件失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("基础组件", False))
    
    try:
        results.append(("Transformer+ARPredictor", test_transformer_and_predictor()))
    except Exception as e:
        print(f"\n  ✗ Transformer+ARPredictor 失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Transformer+ARPredictor", False))
    
    try:
        results.append(("Embedder", test_embedder()))
    except Exception as e:
        print(f"\n  ✗ Embedder 失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Embedder", False))
    
    try:
        results.append(("LeWorldModel完整", test_le_world_model()))
    except Exception as e:
        print(f"\n  ✗ LeWorldModel 失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("LeWorldModel完整", False))
    
    try:
        results.append(("Rollout推理", test_rollout()))
    except Exception as e:
        print(f"\n  ✗ Rollout 失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Rollout推理", False))
    
    # 汇总
    print("\n" + "=" * 60)
    print(" 验证结果汇总")
    print("=" * 60)
    for name, passed in results:
        status = "✓" if passed else "✗"
        print(f"  {status} {name}")
    
    all_passed = all(r[1] for r in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print(" 🎉 所有测试通过! LeWorldModel 代码正确。")
        print("=" * 60)
        print("\n下一步: ")
        print("  1. 在 lerobot 训练环境中运行完整验证:")
        print("     python examples/smolvla_lew_demo.py")
        print("  2. 开始训练:")
        print("     lerobot-train --policy.type smolvla_lew ...")
        return 0
    else:
        print(" ✗ 部分测试失败，请检查上面的错误。")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
