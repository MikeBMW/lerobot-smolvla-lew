"""
SmolVLA 训练流程逐步调试 — LeRobot 风格
用法:
  python debug_train.py --policy.type=smolvla --policy.push_to_hub=false \
    --dataset.repo_id=lerobot/pusht --batch_size=1 --steps=2 \
    --output_dir=outputs/debug --job_name=debug
"""
import os, time, logging
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import torch
from lerobot.configs import parser
from lerobot.configs.train import TrainPipelineConfig
from lerobot.datasets import make_dataset, EpisodeAwareSampler
from lerobot.policies import make_policy, make_pre_post_processors
from lerobot.optim.factory import make_optimizer_and_scheduler
from lerobot.utils.collate import lerobot_collate_fn
from lerobot.utils.random_utils import set_seed
from lerobot.utils.utils import cycle, init_logging
from accelerate import Accelerator
from accelerate.utils import DistributedDataParallelKwargs

logging.basicConfig(level=logging.INFO, format="%(message)s")


@parser.wrap()
def debug_train(cfg: TrainPipelineConfig):
    # ══════════════════════════════════════════════════════════════
    breakpoint()  # 阶段0: 配置已解析。输入 c 继续
    # ══════════════════════════════════════════════════════════════

    print("=" * 60)
    print("阶段0: 配置已解析")
    print("=" * 60)
    print(f"  策略: {cfg.policy.type}")
    print(f"  数据集: {cfg.dataset.repo_id}")
    print(f"  batch_size: {cfg.batch_size}")
    print(f"  steps: {cfg.steps}")
    print(f"  output_dir: {cfg.output_dir}")

    # 重要：validate 会从 policy 的 preset 填充 optimizer/scheduler 配置
    cfg.validate()

    # ── Accelerator ──
    ddp_kwargs = DistributedDataParallelKwargs(find_unused_parameters=True)
    accelerator = Accelerator(step_scheduler_with_optimizer=False, kwargs_handlers=[ddp_kwargs])
    device = accelerator.device
    init_logging(accelerator=accelerator)
    is_main = accelerator.is_main_process
    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_tf32 = True
    if cfg.seed is not None:
        set_seed(cfg.seed, accelerator=accelerator)
    print(f"  设备: {device}")

    # ══════════════════════════════════════════════════════════════
    breakpoint()  # 阶段1: Accelerator就绪。输入 c 创建数据集
    # ══════════════════════════════════════════════════════════════

    print("=" * 60)
    print("阶段1: 创建数据集")
    print("=" * 60)
    if is_main:
        logging.info("Creating dataset")
    dataset = make_dataset(cfg)
    accelerator.wait_for_everyone()
    if not is_main:
        dataset = make_dataset(cfg)
    print(f"  帧数: {dataset.num_frames}")
    print(f"  Episodes: {dataset.num_episodes}")
    print(f"  Camera: {dataset.meta.camera_keys}")
    print(f"  Action shape: {dataset.meta.shapes['action']}")

    # ══════════════════════════════════════════════════════════════
    breakpoint()  # 阶段2: 数据集就绪。输入 c 创建模型
    # ══════════════════════════════════════════════════════════════

    print("=" * 60)
    print("阶段2: 创建 SmolVLA 模型")
    print("=" * 60)
    if is_main:
        logging.info("Creating policy")
    policy = make_policy(cfg=cfg.policy, ds_meta=dataset.meta, rename_map=cfg.rename_map)
    total_p = sum(p.numel() for p in policy.parameters())
    trainable_p = sum(p.numel() for p in policy.parameters() if p.requires_grad)
    print(f"  总参数: {total_p:,}")
    print(f"  可训练: {trainable_p:,}")

    # ══════════════════════════════════════════════════════════════
    breakpoint()  # 阶段3: 模型就绪。输入 c 创建处理器+优化器
    # ══════════════════════════════════════════════════════════════

    print("=" * 60)
    print("阶段3: 创建处理器 + 优化器 + DataLoader")
    print("=" * 60)

    # 处理器
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=cfg.policy, dataset_stats=dataset.meta.stats
    )
    print(f"  Preprocessor: {len(preprocessor.steps)}步骤")
    for s in preprocessor.steps:
        print(f"    - {type(s).__name__}")

    # 优化器
    if is_main:
        logging.info("Creating optimizer and scheduler")
    optimizer, lr_scheduler = make_optimizer_and_scheduler(cfg, policy)
    print(f"  优化器: AdamW, lr={cfg.policy.optimizer_lr}")

    # DataLoader
    sampler = EpisodeAwareSampler(
        dataset.meta.episodes["dataset_from_index"],
        dataset.meta.episodes["dataset_to_index"],
        episode_indices_to_use=dataset.episodes,
        shuffle=True,
        seed=cfg.seed if cfg.seed is not None else 0,
    )
    collate_fn = lerobot_collate_fn if dataset.meta.has_language_columns else None
    dataloader = torch.utils.data.DataLoader(
        dataset, num_workers=cfg.num_workers, batch_size=cfg.batch_size,
        sampler=sampler, pin_memory=device.type == "cuda", collate_fn=collate_fn,
        prefetch_factor=cfg.prefetch_factor if cfg.num_workers > 0 else None,
        persistent_workers=cfg.persistent_workers and cfg.num_workers > 0,
    )
    print(f"  DataLoader: batch={cfg.batch_size}, workers={cfg.num_workers}")

    # ══════════════════════════════════════════════════════════════
    breakpoint()  # 阶段4: 一切就绪。输入 c 执行 accelerator.prepare
    # ══════════════════════════════════════════════════════════════

    print("=" * 60)
    print("阶段4: accelerator.prepare + 训练循环就绪")
    print("=" * 60)
    accelerator.wait_for_everyone()
    policy, optimizer, dataloader, lr_scheduler = accelerator.prepare(
        policy, optimizer, dataloader, lr_scheduler
    )
    dl_iter = cycle(dataloader)
    policy.train()
    print(f"  prepare 完成, 模型设备: {next(policy.parameters()).device}")
    print(f"  总步数: {cfg.steps}")

    # ══════════════════════════════════════════════════════════════
    # 训练循环
    # ══════════════════════════════════════════════════════════════

    for step in range(cfg.steps):
        print(f"\n{'─'*50}")
        print(f"Step {step+1}/{cfg.steps}")
        print(f"{'─'*50}")

        # ── 取batch ──
        start = time.perf_counter()
        batch = next(dl_iter)
        for cam_key in dataset.meta.camera_keys:
            if cam_key in batch and batch[cam_key].dtype == torch.uint8:
                batch[cam_key] = batch[cam_key].to(torch.float32) / 255.0

        # ══════════════════════════════════════════════════════════
        breakpoint()  # 停！batch已取。输入 c 执行 preprocessor + forward
        # ══════════════════════════════════════════════════════════

        print(f"  batch size: {cfg.batch_size}")
        for k in batch:
            if hasattr(batch[k], 'shape'):
                print(f"    {k}: {list(batch[k].shape)}")

        # 预处理
        batch = preprocessor(batch)
        data_s = time.perf_counter() - start
        print(f"  数据加载: {data_s:.3f}s")

        # 前向传播
        with accelerator.autocast():
            loss, output_dict = policy.forward(batch)
        print(f"  Loss: {loss.item():.4f}")

        # ══════════════════════════════════════════════════════════
        breakpoint()  # 停！forward完成。输入 c 执行 backward + optimizer.step
        # ══════════════════════════════════════════════════════════

        # 反向传播
        accelerator.backward(loss)

        # 梯度裁剪
        grad_norm = accelerator.clip_grad_norm_(policy.parameters(), cfg.optimizer.grad_clip_norm)
        print(f"  梯度范数: {grad_norm.item():.4f}")

        # 优化器更新
        optimizer.step()
        optimizer.zero_grad()

        # 学习率调度
        if lr_scheduler is not None:
            lr_scheduler.step()

        cur_lr = optimizer.param_groups[0]["lr"]
        print(f"  学习率: {cur_lr:.2e}")
        step_time = time.perf_counter() - start
        print(f"  Step耗时: {step_time:.3f}s")

        # ══════════════════════════════════════════════════════════
        if step < cfg.steps - 1:
            breakpoint()  # 停！这一步完成。输入 c 进入下一步
        # ══════════════════════════════════════════════════════════

    print(f"\n{'='*60}")
    print(f"训练完成！最终 loss: {loss.item():.4f}")
    print(f"{'='*60}")


if __name__ == "__main__":
    debug_train()
