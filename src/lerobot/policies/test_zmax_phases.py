#!/usr/bin/env python3
"""
Z-MAX 全阶段策略测试脚本 (Standalone)
不依赖 lerobot 框架，只验证模型组件的构建和前向传播。

用法:
    cd src/lerobot/policies
    python test_zmax_phases.py
"""
import sys, os
import torch

# 将 policies 目录加入路径
POLICIES_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, POLICIES_DIR)


def test_phase1():
    """Phase 1: System 1 VTLA 基础功能"""
    print("=" * 60)
    print("Phase 1: zmax_sys1 — System 1 基础功能 (M+A)")
    print("=" * 60)

    from zmax_sys1.configuration_zmax_sys1 import ZmaxSys1Config
    from zmax_sys1.modeling_zmax_sys1 import ZmaxSys1Policy

    config = ZmaxSys1Config()
    policy = ZmaxSys1Policy(config)
    num_params = sum(p.numel() for p in policy.parameters())
    print(f"  ✓ 模型创建成功  |  参数量: {num_params:,}")

    batch = {
        "observation.state": torch.randn(2, 6),
        "observation.tactile": torch.randn(2, 6),
        "action": torch.randn(2, 7, 7),
    }
    out = policy(batch)
    print(f"  ✓ 前向传播成功  |  Loss: {out['loss'].item():.4f}  |  Action: {out['action'].shape}")
    print(f"  ✓ 配置: 触觉={config.enable_tactile}, 插入力={config.max_insertion_force}N, 容差={config.alignment_tolerance}mm")
    print()
    return True


def test_phase2():
    """Phase 2: Sys-11 泛化调优"""
    print("=" * 60)
    print("Phase 2: zmax_sys11 — Sys-11 泛化调优 (Z潜空间)")
    print("=" * 60)

    from zmax_sys11.configuration_zmax_sys11 import ZmaxSys11Config
    from zmax_sys11.modeling_zmax_sys11 import ZmaxSys11Policy

    config = ZmaxSys11Config()
    policy = ZmaxSys11Policy(config)
    num_params = sum(p.numel() for p in policy.parameters())
    print(f"  ✓ 模型创建成功  |  参数量: {num_params:,}")

    batch = {
        "observation.state": torch.randn(2, 6),
        "observation.tactile": torch.randn(2, 6),
        "action": torch.randn(2, 7, 7),
    }
    out = policy(batch)
    print(f"  ✓ 前向传播成功  |  Loss: {out['loss'].item():.4f}  |  KL: {out['kl_loss'].item():.4f}")
    print(f"  ✓ Z潜空间: dim={config.latent_dim}  |  模块型号: {config.num_module_types}  |  目标延迟: {config.target_inference_ms}ms")
    print()
    return True


def test_phase3():
    """Phase 3: Sys-12 空间感知"""
    print("=" * 60)
    print("Phase 3: zmax_sys12 — Sys-12 空间感知 (X+Z)")
    print("=" * 60)

    from zmax_sys12.configuration_zmax_sys12 import ZmaxSys12Config
    from zmax_sys12.modeling_zmax_sys12 import ZmaxSys12Policy

    config = ZmaxSys12Config()
    policy = ZmaxSys12Policy(config)
    num_params = sum(p.numel() for p in policy.parameters())
    print(f"  ✓ 模型创建成功  |  参数量: {num_params:,}")

    batch = {
        "observation.state": torch.randn(2, 6),
        "observation.tactile": torch.randn(2, 6),
        "action": torch.randn(2, 7, 7),
    }
    out = policy(batch)
    print(f"  ✓ 前向传播成功  |  Loss: {out['loss'].item():.4f}  |  KL: {out['kl_loss'].item():.4f}")
    print(f"  ✓ LeWorldModel: {config.lew_hidden_dim}d x {config.lew_num_layers}层  |  Target Pose: {out['target_pose'].shape}")
    print(f"  ✓ 空间: {config.spatial_resolution}x{config.spatial_resolution}  |  深度={config.enable_depth}  |  引导强度={config.guidance_strength}")
    print()
    return True


def test_phase4():
    """Phase 4: System 2 全系统"""
    print("=" * 60)
    print("Phase 4: zmax_system2 — System 2 全系统 (Z·M·A·X)")
    print("=" * 60)

    from zmax_system2.configuration_zmax_system2 import ZmaxSystem2Config
    from zmax_system2.modeling_zmax_system2 import ZmaxSystem2Policy

    config = ZmaxSystem2Config()
    policy = ZmaxSystem2Policy(config)
    num_params = sum(p.numel() for p in policy.parameters())
    print(f"  ✓ 模型创建成功  |  参数量: {num_params:,}")

    batch = {
        "observation.state": torch.randn(2, 6),
        "action": torch.randn(2, 7, 7),
    }
    out = policy(batch)
    print(f"  ✓ 前向传播成功  |  Loss: {out['loss'].item():.4f}")
    print(f"  ✓ 任务规划: {config.planner_hidden_dim}d x {config.planner_num_layers}层  |  Steps: {out['task_steps'].shape}")
    routing = out['routing_decision']
    print(f"  ✓ 子系统路由: sys1={routing['sys1']:.2f}  sys11={routing['sys11']:.2f}  sys12={routing['sys12']:.2f}")
    print(f"  ✓ 产线: max={config.max_concurrent_lines}  |  5G={config.enable_5g_comm}  |  阈值={config.success_threshold}")
    print()
    return True


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Z-MAX 产品迭代策略 · 全阶段 Standalone 测试          ║")
    print("║  Phase 1(系统1)→ Phase 2(Sys-11)→ Phase 3(Sys-12)→ Phase 4(全) ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    results = {}
    for name, func in [("Phase 1", test_phase1), ("Phase 2", test_phase2), ("Phase 3", test_phase3), ("Phase 4", test_phase4)]:
        try:
            results[name] = func()
        except Exception as e:
            results[name] = False
            print(f"  ✗ {name} 失败: {e}")
            import traceback; traceback.print_exc()
            print()

    print("=" * 60)
    print("测试汇总")
    print("=" * 60)
    for name, passed in results.items():
        print(f"  {'✅ PASS' if passed else '❌ FAIL'}  {name}")

    print()
    if all(results.values()):
        print("🎉 全部通过! Z-MAX 四个迭代阶段均可正常运行。")
    else:
        print("⚠️ 部分测试失败")
    sys.exit(0 if all(results.values()) else 1)
