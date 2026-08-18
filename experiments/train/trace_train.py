"""
SmolVLA 训练 — 张量形状全追踪版本
跑200步，展示每一步的loss变化，在loss稳定下降后暂停
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

logging.basicConfig(level=logging.WARNING)  # 减少日志噪音

@parser.wrap()
def train_trace(cfg: TrainPipelineConfig):
    cfg.validate()

    ddp_kwargs = DistributedDataParallelKwargs(find_unused_parameters=True)
    accelerator = Accelerator(step_scheduler_with_optimizer=False, kwargs_handlers=[ddp_kwargs])
    device = accelerator.device
    init_logging(accelerator=accelerator)
    is_main = accelerator.is_main_process
    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_tf32 = True
    if cfg.seed is not None:
        set_seed(cfg.seed, accelerator=accelerator)

    # ── Dataset ──
    if is_main:
        logging.info("Creating dataset")
    dataset = make_dataset(cfg)
    accelerator.wait_for_everyone()
    if not is_main:
        dataset = make_dataset(cfg)

    # ── Policy ──
    if is_main:
        logging.info("Creating policy")
    policy = make_policy(cfg=cfg.policy, ds_meta=dataset.meta, rename_map=cfg.rename_map)

    # ── Processors ──
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=cfg.policy, dataset_stats=dataset.meta.stats
    )

    # ── Optimizer ──
    optimizer, lr_scheduler = make_optimizer_and_scheduler(cfg, policy)

    # ── DataLoader ──
    sampler = EpisodeAwareSampler(
        dataset.meta.episodes["dataset_from_index"],
        dataset.meta.episodes["dataset_to_index"],
        episode_indices_to_use=dataset.episodes,
        shuffle=True, seed=cfg.seed if cfg.seed is not None else 0,
    )
    collate_fn = lerobot_collate_fn if dataset.meta.has_language_columns else None
    dataloader = torch.utils.data.DataLoader(
        dataset, num_workers=cfg.num_workers, batch_size=cfg.batch_size,
        sampler=sampler, pin_memory=device.type=="cuda", collate_fn=collate_fn,
        prefetch_factor=cfg.prefetch_factor if cfg.num_workers>0 else None,
        persistent_workers=cfg.persistent_workers and cfg.num_workers>0,
    )

    # ── Prepare ──
    accelerator.wait_for_everyone()
    policy, optimizer, dataloader, lr_scheduler = accelerator.prepare(
        policy, optimizer, dataloader, lr_scheduler
    )
    dl_iter = cycle(dataloader)
    policy.train()

    print(f"\n{'='*70}")
    print(f"  SmolVLA 训练 — 张量形状全追踪")
    print(f"  数据集: {cfg.dataset.repo_id} | {dataset.num_frames}帧")
    print(f"  模型: {sum(p.numel() for p in policy.parameters()):,}参数 | {sum(p.numel() for p in policy.parameters() if p.requires_grad):,}可训练")
    print(f"  Batch: {cfg.batch_size} | Steps: {cfg.steps}")
    print(f"{'='*70}\n")

    # ── 第0步: 展示完整的张量形状流 ──
    print("─" * 70)
    print("【第0步: 张量形状追踪 — 首次forward，展示每个子模块】")
    print("─" * 70)
    
    batch = next(dl_iter)
    for cam_key in dataset.meta.camera_keys:
        if cam_key in batch and batch[cam_key].dtype == torch.uint8:
            batch[cam_key] = batch[cam_key].to(torch.float32) / 255.0

    print(f"\n① 原始batch (DataLoader输出):")
    for k in sorted(batch.keys()):
        if hasattr(batch[k], 'shape'):
            print(f"   {k:30s} {str(list(batch[k].shape)):20s} {str(batch[k].dtype)}")

    # preprocessor
    batch = preprocessor(batch)
    print(f"\n② 预处理后 (preprocessor 6步骤):")
    for k in sorted(batch.keys()):
        if hasattr(batch[k], 'shape'):
            print(f"   {k:30s} {str(list(batch[k].shape)):20s} {str(batch[k].dtype)}")

    # 检查模型内部结构
    from lerobot.utils.constants import OBS_STATE, ACTION, OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
    
    print(f"\n③ 模型内部 — 各子模块的输入/输出:")
    
    # prepare_images
    try:
        images, img_masks = policy.prepare_images(batch)
        print(f"   prepare_images:")
        for i, (img, m) in enumerate(zip(images, img_masks)):
            print(f"     image[{i}]: {list(img.shape)} (原始→resize+pad→[-1,1])")
    except Exception as e:
        print(f"   prepare_images: {e}")

    # prepare_state
    try:
        state = policy.prepare_state(batch)
        print(f"   prepare_state:  {list(state.shape)} (原始dim→pad至max_state_dim=32)")
    except Exception as e:
        print(f"   prepare_state: {e}")

    # prepare_action
    try:
        action = policy.prepare_action(batch)
        print(f"   prepare_action: {list(action.shape)} (原始dim→pad至max_action_dim=32)")
    except Exception as e:
        print(f"   prepare_action: {e}")

    # embed_prefix
    try:
        state_t = batch[OBS_STATE]
        if state_t.ndim == 2:
            state_t = state_t[:, None, :]
        images2, img_masks2 = policy.prepare_images(batch)
        prefix_embs, prefix_pad, prefix_att = policy.model.embed_prefix(
            images2, img_masks2,
            batch[OBS_LANGUAGE_TOKENS],
            batch[OBS_LANGUAGE_ATTENTION_MASK],
            state=state_t
        )
        print(f"   embed_prefix:   {list(prefix_embs.shape)} (图像+语言+状态拼成的prefix)")
        print(f"                   → {prefix_embs.shape[1]}个token, 每个{prefix_embs.shape[2]}维")
    except Exception as e:
        print(f"   embed_prefix: {e}")

    # forward
    with accelerator.autocast():
        loss, output_dict = policy.forward(batch)
    
    print(f"\n④ forward结果:")
    print(f"   loss: {loss.item():.4f}")
    if output_dict:
        for k, v in output_dict.items():
            print(f"   {k}: {v}")

    # backward
    accelerator.backward(loss)
    grad_norm = accelerator.clip_grad_norm_(policy.parameters(), cfg.optimizer.grad_clip_norm)
    optimizer.step()
    optimizer.zero_grad()
    if lr_scheduler is not None:
        lr_scheduler.step()
    
    print(f"\n⑤ 更新结果:")
    print(f"   grad_norm: {grad_norm.item():.4f} (裁剪前)")
    print(f"   lr: {optimizer.param_groups[0]['lr']:.2e}")
    print()

    # ══════════════════════════════════════════════════════════════
    breakpoint()  # 张量形状已展示完毕。输入 c 开始训练循环
    # ══════════════════════════════════════════════════════════════

    # ── 训练循环 ──
    losses = []
    grad_norms = []
    print(f"{'─'*70}")
    print(f"  开始训练循环 ({cfg.steps}步)")
    print(f"  格式: [step] loss=xxx grdn=xxx lr=x.xe-x | 注释")
    print(f"{'─'*70}\n")

    for step in range(cfg.steps):
        start = time.perf_counter()
        batch = next(dl_iter)
        for cam_key in dataset.meta.camera_keys:
            if cam_key in batch and batch[cam_key].dtype == torch.uint8:
                batch[cam_key] = batch[cam_key].to(torch.float32) / 255.0
        batch = preprocessor(batch)

        with accelerator.autocast():
            loss, _ = policy.forward(batch)

        accelerator.backward(loss)
        gn = accelerator.clip_grad_norm_(policy.parameters(), cfg.optimizer.grad_clip_norm)
        optimizer.step()
        optimizer.zero_grad()
        if lr_scheduler is not None:
            lr_scheduler.step()

        losses.append(loss.item())
        grad_norms.append(gn.item())
        cur_lr = optimizer.param_groups[0]["lr"]
        step_time = time.perf_counter() - start

        # 每10步打印一次
        if step % 10 == 0 or step < 5:
            # 判断趋势
            if step >= 10:
                avg_recent = sum(losses[-10:]) / 10
                avg_prev = sum(losses[-20:-10]) / 10 if len(losses) >= 20 else avg_recent
                if losses[-1] < avg_recent * 0.9:
                    trend = "↓ 快速下降"
                elif losses[-1] < avg_recent:
                    trend = "↘ 缓慢下降"
                elif losses[-1] > avg_recent * 1.1:
                    trend = "↑ 震荡"
                else:
                    trend = "→ 平稳"
            else:
                trend = ""

            print(f"  [{step:4d}] loss={losses[-1]:.4f} grdn={grad_norms[-1]:.1f} lr={cur_lr:.1e} | {step_time:.2f}s {trend}")

    # ══════════════════════════════════════════════════════════════
    breakpoint()  # 训练完成。输入 c 看总结
    # ══════════════════════════════════════════════════════════════

    print(f"\n{'='*70}")
    print(f"  训练完成！")
    print(f"{'='*70}")
    print(f"  总步数: {cfg.steps}")
    print(f"  初始loss: {losses[0]:.4f}")
    print(f"  最终loss: {losses[-1]:.4f}")
    if len(losses) >= 50:
        print(f"  最后50步平均: {sum(losses[-50:])/50:.4f}")
    if len(losses) >= 10:
        print(f"  最后10步平均: {sum(losses[-10:])/10:.4f}")
    print(f"  Loss范围: [{min(losses):.4f}, {max(losses):.4f}]")
    print(f"  (输入 q 退出)")


if __name__ == "__main__":
    train_trace()
