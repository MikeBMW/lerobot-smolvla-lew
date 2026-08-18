"""
SmolVLA 模型内部逐步调试 — 进入每个子方法
断点设在每个模型方法的门口，让你亲眼看到张量怎么流
"""
import os, time
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import torch
from lerobot.configs import parser
from lerobot.configs.train import TrainPipelineConfig
from lerobot.datasets import make_dataset
from lerobot.policies import make_policy
from lerobot.policies.smolvla.modeling_smolvla import make_att_2d_masks
from lerobot.utils.constants import (
    OBS_IMAGES, OBS_STATE, OBS_LANGUAGE_TOKENS,
    OBS_LANGUAGE_ATTENTION_MASK, ACTION
)

@parser.wrap()
def deep_trace(cfg: TrainPipelineConfig):
    cfg.validate()
    cfg.policy.device = "cuda"

    # ── 加载数据集 ──
    print("加载数据集...")
    dataset = make_dataset(cfg)
    print(f"  {dataset.num_frames}帧\n")

    # ── 创建模型 ──
    print("创建 SmolVLA 模型...")
    policy = make_policy(cfg=cfg.policy, ds_meta=dataset.meta)
    policy = policy.cuda()
    policy.eval()  # 推理模式，不更新参数
    print(f"  总参数: {sum(p.numel() for p in policy.parameters()):,}")
    print(f"  可训练: {sum(p.numel() for p in policy.parameters() if p.requires_grad):,}\n")

    # ── 取一个batch ──
    raw = dataset[0]
    batch = {
        OBS_STATE: raw["observation.state"].to("cuda"),
        ACTION: raw["action"].to("cuda").unsqueeze(0),
    }
    for k in dataset.meta.camera_keys:
        img = raw[k].to("cuda").float() / 255.0
        batch[k] = img.unsqueeze(0) if img.ndim == 3 else img

    if "task" in raw:
        tok = policy.model.vlm_with_expert.processor.tokenizer
        tokens = tok([raw["task"]], return_tensors="pt", padding="max_length",
                     max_length=48, truncation=True)
        batch[OBS_LANGUAGE_TOKENS] = tokens["input_ids"].to("cuda")
        batch[OBS_LANGUAGE_ATTENTION_MASK] = tokens["attention_mask"].bool().to("cuda")

    print(f"Batch就绪: {list(batch.keys())}")
    print(f"  state: {list(batch[OBS_STATE].shape)}")
    print(f"  action: {list(batch[ACTION].shape)}")
    print(f"  image: {list(batch[dataset.meta.camera_keys[0]].shape)}")
    print(f"  lang: {list(batch[OBS_LANGUAGE_TOKENS].shape)}")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块1: prepare_images
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块1: prepare_images() — modeling_smolvla.py:415-455")
    print("=" * 60)
    print("作用: 把原始图片 resize+pad 到512×512, 归一化到[-1,1]")
    print()

    breakpoint()  # 停！输入 c 执行 prepare_images

    images, img_masks = policy.prepare_images(batch)
    for i, (img, m) in enumerate(zip(images, img_masks)):
        print(f"  image[{i}]: shape={list(img.shape)}, dtype={img.dtype}")
        print(f"            range=[{img.min().item():.3f}, {img.max().item():.3f}]")
        print(f"  mask[{i}]:  shape={list(m.shape)}, 有效={m.sum().item()}")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块2: prepare_state
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块2: prepare_state() — modeling_smolvla.py:484-488")
    print("=" * 60)
    print("作用: 状态填充到 max_state_dim=32")
    print()

    breakpoint()  # 停！输入 c 执行 prepare_state

    state = policy.prepare_state(batch)
    print(f"  输入: batch['{OBS_STATE}'] = {list(batch[OBS_STATE].shape)}")
    print(f"  输出: state = {list(state.shape)}")
    print(f"  示例: 前2维={state[0,:2].tolist()}, 后30维全是零")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块3: prepare_action
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块3: prepare_action() — modeling_smolvla.py:490-493")
    print("=" * 60)
    print("作用: 动作填充到 max_action_dim=32")
    print()

    breakpoint()  # 停！输入 c 执行 prepare_action

    action = policy.prepare_action(batch)
    print(f"  输入: batch['{ACTION}'] = {list(batch[ACTION].shape)}")
    print(f"  输出: action = {list(action.shape)}")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块4: embed_image (SigLIP + Connector)
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块4: embed_image() — smolvlm_with_expert.py:191-204")
    print("=" * 60)
    print("作用: 图片→SigLIP ViT→Connector→归一化 得到 [1,1024,960]")
    print()

    breakpoint()  # 停！输入 c 进入 SigLIP

    img_emb = policy.model.vlm_with_expert.embed_image(images[0])
    print(f"  输入图片: {list(images[0].shape)}")
    print(f"  SigLIP+Connector输出: {list(img_emb.shape)}")
    print(f"  1024个视觉token, 每个960维")
    print(f"  归一化: ×√960 = ×{960**0.5:.1f}")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块5: embed_language_tokens
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块5: embed_language_tokens() — smolvlm_with_expert.py:206-207")
    print("=" * 60)
    print("作用: token IDs→Embedding查表→归一化 得到 [1,48,960]")
    print()

    breakpoint()  # 停！输入 c 执行语言嵌入

    lang_emb = policy.model.vlm_with_expert.embed_language_tokens(
        batch[OBS_LANGUAGE_TOKENS]
    )
    print(f"  输入 token IDs: {list(batch[OBS_LANGUAGE_TOKENS].shape)}")
    print(f"  Embedding查表 [49152,960] → {list(lang_emb.shape)}")
    print(f"  48个语言token, 每个960维")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块6: state_proj
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块6: state_proj — modeling_smolvla.py:704-705")
    print("=" * 60)
    print("作用: Linear(32→960) ★可训练★ 把状态投影到VLM空间")
    print()

    breakpoint()  # 停！输入 c 执行状态投影

    state_emb = policy.model.state_proj(state)
    print(f"  state_proj = Linear(32, 960), weight=[960, 32]")
    print(f"  输入 state: {list(state.shape)}")
    print(f"  输出 state_emb: {list(state_emb.shape)}")
    print(f"  这个矩阵的960×32=30720个参数是★可训练★的")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块7: embed_prefix (拼接+送入VLM)
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块7: embed_prefix() — modeling_smolvla.py:637-729")
    print("=" * 60)
    print("作用: 图像+语言+状态拼接→送入VLM生成KV Cache")
    print("内部: img_emb×√960, lang_emb×√960, state_proj, cat→[1,1073,960]")
    print()

    breakpoint()  # 停！输入 c 执行 embed_prefix + VLM forward

    prefix_embs, prefix_pad_masks, prefix_att_masks = policy.model.embed_prefix(
        images, img_masks,
        batch[OBS_LANGUAGE_TOKENS],
        batch[OBS_LANGUAGE_ATTENTION_MASK],
        state=state
    )

    print(f"  prefix_embs:      {list(prefix_embs.shape)}")
    print(f"  prefix_pad_masks: {list(prefix_pad_masks.shape)}")
    print(f"  prefix_att_masks: {list(prefix_att_masks.shape)}")
    print(f"  共计 {prefix_embs.shape[1]} 个token (1024图+48语+1状)")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块8: VLM填充KV Cache
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块8: VLM 填充 KV Cache")
    print("=" * 60)
    print("作用: 把prefix送进VLM 16层Transformer, 每层存储K和V")
    print("内部: 16层×{K:[1073,5,64], V:[1073,5,64]}")
    print()

    breakpoint()  # 停！输入 c 执行VLM forward填充Cache

    prefix_att_2d = make_att_2d_masks(prefix_pad_masks, prefix_att_masks)
    prefix_pos = torch.cumsum(prefix_pad_masks, dim=1) - 1

    _, past_key_values = policy.model.vlm_with_expert.forward(
        attention_mask=prefix_att_2d,
        position_ids=prefix_pos,
        past_key_values=None,
        inputs_embeds=[prefix_embs, None],  # None=expert不参与
        use_cache=True,
        fill_kv_cache=True,
    )

    print(f"  KV Cache 层数: {len(past_key_values)}")
    for layer_idx in [0, 15]:  # 只看第0层和最后一层
        kv = past_key_values[layer_idx]
        print(f"  Layer {layer_idx}: K={list(kv['key_states'].shape)}, V={list(kv['value_states'].shape)}")
    print(f"  每层KV: K=[1073,5,64], V=[1073,5,64]")
    print(f"  每层KV总大小: 1073×5×64×2 = {1073*5*64*2:,}个float16")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块9: embed_suffix (动作+时间编码)
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块9: embed_suffix() — modeling_smolvla.py:731-772")
    print("=" * 60)
    print("作用: 加噪动作+时间编码→Expert输入")
    print("内部: action→Linear(32→720)→SiLU + time→sin-cos→cat→Linear(1440→720→720)")
    print()

    breakpoint()  # 停！输入 c 执行动作编码

    # 制造加噪动作
    bsize = state.shape[0]
    noise_shape = (bsize, 50, 32)
    noise = torch.randn(noise_shape, device="cuda")
    time_t = torch.tensor([0.5], device="cuda")
    x_t = time_t[:, None, None] * noise + (1 - time_t[:, None, None]) * action

    suffix_embs, suffix_pad, suffix_att = policy.model.embed_suffix(x_t, time_t)

    print(f"  输入 x_t (加噪动作): {list(x_t.shape)}")
    print(f"  输入 time: {time_t.item():.3f}")
    print(f"  输出 suffix_embs: {list(suffix_embs.shape)}")
    print(f"  50个动作token, 每个720维 (Expert空间)")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块10: 联合前向 (VLM+Expert)
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块10: vlm_with_expert.forward() — smolvlm_with_expert.py:415-510")
    print("=" * 60)
    print("作用: VLM prefix + Expert suffix 联合Transformer (训练模式)")
    print("内部: 16层, prefix+suffix一次性送入, 不使用预填充的Cache")
    print()

    breakpoint()  # 停！输入 c 执行联合前向

    full_pad = torch.cat([prefix_pad_masks, suffix_pad], dim=1)
    full_att = torch.cat([prefix_att_masks, suffix_att], dim=1)
    full_att_2d = make_att_2d_masks(full_pad, full_att)
    full_pos = torch.cumsum(full_pad, dim=1) - 1

    # 训练模式: past_key_values=None, prefix+suffix一起送
    (prefix_out, suffix_out), _ = policy.model.vlm_with_expert.forward(
        attention_mask=full_att_2d,
        position_ids=full_pos,
        past_key_values=None,           # 不读Cache，一次全算
        inputs_embeds=[prefix_embs, suffix_embs],
        use_cache=False,
        fill_kv_cache=False,
    )

    print(f"  prefix_out (VLM侧): {list(prefix_out.shape) if prefix_out is not None else 'None'}")
    print(f"  suffix_out (Expert侧): {list(suffix_out.shape)}")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块11: action_out_proj
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块11: action_out_proj — modeling_smolvla.py:587,808")
    print("=" * 60)
    print("作用: Linear(720→32) ★可训练★ Expert输出→动作空间")
    print()

    breakpoint()  # 停！输入 c 执行输出投影

    suffix_out = suffix_out[:, -50:].float()  # 取最后50个位置
    v_t = policy.model.action_out_proj(suffix_out)
    print(f"  suffix_out (取最后50): {list(suffix_out.shape)}")
    print(f"  action_out_proj = Linear(720, 32), weight=[32, 720]")
    print(f"  输出 v_t: {list(v_t.shape)}")
    print(f"  取有效维度[:2]: {list(v_t[:,:,:2].shape)}")
    print()

    # ══════════════════════════════════════════════════════════════
    # 模块12: 完整 forward
    # ══════════════════════════════════════════════════════════════
    print("=" * 60)
    print("模块12: 完整 SmolVLAPolicy.forward()")
    print("=" * 60)
    print("作用: 把以上所有模块串起来，返回loss")
    print()

    breakpoint()  # 停！输入 c 执行完整 forward

    policy.train()
    loss, loss_dict = policy.forward(batch)
    print(f"  loss: {loss.item():.4f}")
    print(f"  内部loss阶段:")
    for k, v in loss_dict.items():
        print(f"    {k}: {v}")
    print()

    # ══════════════════════════════════════════════════════════════
    breakpoint()  # 全部完成。输入 q 退出
    # ══════════════════════════════════════════════════════════════

    print("=" * 60)
    print("全部12个模块追踪完毕！")
    print("=" * 60)


if __name__ == "__main__":
    deep_trace()
