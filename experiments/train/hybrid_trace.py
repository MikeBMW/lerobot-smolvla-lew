"""ZmaxHybrid 训练追踪"""
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

logging.basicConfig(level=logging.WARNING)

@parser.wrap()
def run(cfg: TrainPipelineConfig):
    cfg.validate()
    acc = Accelerator(step_scheduler_with_optimizer=False,
                      kwargs_handlers=[DistributedDataParallelKwargs(find_unused_parameters=True)])
    device = acc.device
    init_logging()
    is_main = acc.is_main_process
    torch.backends.cudnn.benchmark = True
    if cfg.seed is not None: set_seed(cfg.seed, accelerator=acc)

    ds = make_dataset(cfg)
    acc.wait_for_everyone()
    if not is_main: ds = make_dataset(cfg)
    print(f"Dataset: {ds.num_frames} frames, {ds.num_episodes} episodes")

    policy = make_policy(cfg=cfg.policy, ds_meta=ds.meta, rename_map=cfg.rename_map)
    total = sum(p.numel() for p in policy.parameters())
    trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
    print(f"Model: {total:,} total, {trainable:,} trainable")

    opt, sch = make_optimizer_and_scheduler(cfg, policy)
    
    # 创建处理器
    pre, post = make_pre_post_processors(policy_cfg=cfg.policy, dataset_stats=ds.meta.stats)
    
    sampler = EpisodeAwareSampler(ds.meta.episodes["dataset_from_index"],
        ds.meta.episodes["dataset_to_index"], episode_indices_to_use=ds.episodes,
        shuffle=True, seed=cfg.seed if cfg.seed is not None else 0)
    dl = torch.utils.data.DataLoader(ds, num_workers=0, batch_size=cfg.batch_size,
        sampler=sampler, pin_memory=device.type=="cuda",
        collate_fn=lerobot_collate_fn if ds.meta.has_language_columns else None)
    
    acc.wait_for_everyone()
    policy, opt, dl, sch = acc.prepare(policy, opt, dl, sch)
    dl_iter = cycle(dl)
    policy.train()

    losses = []
    print(f"\n{'='*50}")
    print(f"Training {cfg.steps} steps...")
    print(f"{'='*50}\n")
    
    for step in range(cfg.steps):
        batch = next(dl_iter)
        for cam_key in ds.meta.camera_keys:
            if cam_key in batch and batch[cam_key].dtype == torch.uint8:
                batch[cam_key] = batch[cam_key].to(torch.float32) / 255.0
        batch = pre(batch)   # 归一化处理
        with acc.autocast():
            loss, _ = policy.forward(batch)
        acc.backward(loss)
        acc.clip_grad_norm_(policy.parameters(), cfg.optimizer.grad_clip_norm)
        opt.step()
        opt.zero_grad()
        if sch is not None: sch.step()
        losses.append(loss.item())
        
        if step % 10 == 0 or step < 5:
            if step >= 10:
                avg10 = sum(losses[-10:]) / 10
                avg20 = sum(losses[-20:-10]) / 10 if len(losses) >= 20 else avg10
                trend = "↓" if losses[-1] < avg10 * 0.95 else ("↑" if losses[-1] > avg10 * 1.05 else "→")
            else:
                trend = ""
            print(f"  [{step:4d}] loss={losses[-1]:.4f} lr={opt.param_groups[0]['lr']:.1e} {trend}")

    print(f"\n{'='*50}")
    print(f"Done! Initial: {losses[0]:.4f} Final: {losses[-1]:.4f}")
    if len(losses) >= 50:
        print(f"Last 50 avg: {sum(losses[-50:])/50:.4f}")
    print(f"Range: [{min(losses):.4f}, {max(losses):.4f}]")
    print(f"{'='*50}")

if __name__ == "__main__":
    run()
