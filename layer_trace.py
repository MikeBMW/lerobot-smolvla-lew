"""
SmolVLA 逐层追踪 — 进入16层Transformer的每一层
观察每层的Q/K/V形状、注意力模式、输出变化
"""
import os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import torch
from lerobot.configs import parser
from lerobot.configs.train import TrainPipelineConfig
from lerobot.datasets import make_dataset
from lerobot.policies import make_policy
from lerobot.policies.smolvla.modeling_smolvla import make_att_2d_masks
from lerobot.utils.constants import (
    OBS_STATE, OBS_LANGUAGE_TOKENS,
    OBS_LANGUAGE_ATTENTION_MASK, ACTION
)

@parser.wrap()
def layer_trace(cfg: TrainPipelineConfig):
    cfg.validate()
    cfg.policy.device = "cuda"

    print("加载数据+模型...")
    dataset = make_dataset(cfg)
    policy = make_policy(cfg=cfg.policy, ds_meta=dataset.meta).cuda()
    policy.eval()

    # 准备batch
    raw = dataset[0]
    batch = {
        OBS_STATE: raw["observation.state"].to("cuda"),
        ACTION: raw["action"].to("cuda").unsqueeze(0),
    }
    for k in dataset.meta.camera_keys:
        img = raw[k].to("cuda").float()/255.0
        batch[k] = img.unsqueeze(0) if img.ndim==3 else img
    if "task" in raw:
        tok = policy.model.vlm_with_expert.processor.tokenizer
        t = tok([raw["task"]], return_tensors="pt", padding="max_length", max_length=48, truncation=True)
        batch[OBS_LANGUAGE_TOKENS] = t["input_ids"].to("cuda")
        batch[OBS_LANGUAGE_ATTENTION_MASK] = t["attention_mask"].bool().to("cuda")

    # ── 准备 prefix 和 suffix ──
    images, img_masks = policy.prepare_images(batch)
    state = policy.prepare_state(batch)
    action = policy.prepare_action(batch)

    prefix_embs, prefix_pad, prefix_att = policy.model.embed_prefix(
        images, img_masks, batch[OBS_LANGUAGE_TOKENS],
        batch[OBS_LANGUAGE_ATTENTION_MASK], state=state
    )

    bsize = state.shape[0]
    noise = torch.randn(bsize, 50, 32, device="cuda")
    time_t = torch.tensor([0.5], device="cuda")
    x_t = time_t[:,None,None]*noise + (1-time_t[:,None,None])*action
    suffix_embs, suffix_pad, suffix_att = policy.model.embed_suffix(x_t, time_t)

    # ── 拼接 mask ──
    full_pad = torch.cat([prefix_pad, suffix_pad], dim=1)
    full_att = torch.cat([prefix_att, suffix_att], dim=1)
    att_2d = make_att_2d_masks(full_pad, full_att)
    pos_ids = torch.cumsum(full_pad, dim=1) - 1

    # ── 获取模型内部结构 ──
    vwe = policy.model.vlm_with_expert
    models = [vwe.get_vlm_model().text_model, vwe.lm_expert]
    model_layers = vwe.get_model_layers(models)
    head_dim = vwe.vlm.config.text_config.head_dim
    num_layers = vwe.num_vlm_layers

    P = prefix_embs.shape[1]   # prefix token数 (约113)
    S = suffix_embs.shape[1]   # suffix token数 (50)
    print(f"\nPrefix: {P} tokens × 960维 | Suffix: {S} tokens × 720维")
    print(f"VLM层数: {num_layers} | 注意力模式: {vwe.attention_mode}")
    print(f"Self-attn每: {vwe.self_attn_every_n_layers}层")
    print()

    inputs_embeds = [prefix_embs, suffix_embs]

    for layer_idx in range(num_layers):
        is_self_attn = (
            vwe.self_attn_every_n_layers > 0 
            and layer_idx % vwe.self_attn_every_n_layers == 0
        )
        mode = "🔷 SELF+Cross" if is_self_attn else "🔶 Cross-only"
        
        # 统一dtype
        model_dtype = model_layers[0][layer_idx].self_attn.q_proj.weight.dtype
        inputs_embeds = [
            ie.to(model_dtype) if ie is not None else None 
            for ie in inputs_embeds
        ]

        print(f"{'─'*60}")
        print(f"Layer {layer_idx}/{num_layers-1}  {mode}")
        print(f"{'─'*60}")

        # ── QKV 投影 ──
        # VLM prefix
        vlm_layer = model_layers[0][layer_idx]
        
        p_norm = vlm_layer.input_layernorm(inputs_embeds[0])
        p_Q = vlm_layer.self_attn.q_proj(p_norm).view(1, P, 15, 64)
        p_K = vlm_layer.self_attn.k_proj(p_norm).view(1, P, 5, 64)
        p_V = vlm_layer.self_attn.v_proj(p_norm).view(1, P, 5, 64)

        # Expert suffix  
        exp_layer = model_layers[1][layer_idx]
        if exp_layer is not None and inputs_embeds[1] is not None:
            s_norm = exp_layer.input_layernorm(inputs_embeds[1])
            s_Q = exp_layer.self_attn.q_proj(s_norm).view(1, S, 15, 64)
            s_K = exp_layer.self_attn.k_proj(s_norm).view(1, S, 5, 64)
            s_V = exp_layer.self_attn.v_proj(s_norm).view(1, S, 5, 64)
        else:
            s_Q = s_K = s_V = None

        print(f"  VLM Q: {list(p_Q.shape)}  K: {list(p_K.shape)}(GQA)  V: {list(p_V.shape)}")
        if s_Q is not None:
            print(f"  Expert Q: {list(s_Q.shape)}  K: {list(s_K.shape)}(GQA)  V: {list(s_V.shape)}")

        breakpoint()  # 停！看QKV → 输入 c 做注意力

        # ── 拼接 Q, K, V ──
        Q = torch.cat([x for x in [p_Q, s_Q] if x is not None], dim=1)
        K = torch.cat([x for x in [p_K, s_K] if x is not None], dim=1)
        V = torch.cat([x for x in [p_V, s_V] if x is not None], dim=1)
        total_tokens = Q.shape[1]

        # GQA: 扩展K和V 5→15头
        K_exp = K[:,:,:,None,:].expand(-1,total_tokens,5,3,64).reshape(1,total_tokens,15,64)
        V_exp = V[:,:,:,None,:].expand(-1,total_tokens,5,3,64).reshape(1,total_tokens,15,64)

        # 转置 (用float32做attention, 更稳定)
        Q_t = Q.float().transpose(1,2)
        K_t = K_exp.float().transpose(1,2)
        V_t = V_exp.permute(0,2,1,3)

        # 注意力
        attn = (Q_t @ K_t.transpose(2,3)) / (head_dim**0.5)
        mask_slice = att_2d[:,:total_tokens,:total_tokens]
        attn = torch.where(mask_slice[:,None,:,:], attn, torch.finfo(attn.dtype).min)
        probs = torch.softmax(attn, dim=-1)

        # 显示注意力统计
        mean_attn = probs.mean(dim=(0,1))
        diag_attn = mean_attn.diagonal().mean().item()
        cross_prefix_suffix = mean_attn[:P, P:].mean().item()
        print(f"  注意力: 对角线均值={diag_attn:.4f} | Suffix→Prefix={cross_prefix_suffix:.4f}")
        print(f"          Token数={total_tokens} | QK^T=[{total_tokens},{total_tokens}]")

        # 加权V (float32 matmul确保精度, 然后转回)
        V_t_f = V_t.float()
        att_out = probs @ V_t_f
        att_out = att_out.permute(0,2,1,3).reshape(1, total_tokens, 15*64)
        att_out = att_out.to(model_dtype)

        # ── 输出投影 + 残差 + MLP ──
        outputs = []
        start = 0
        for i, hs in enumerate(inputs_embeds):
            lr = model_layers[i][layer_idx]
            if hs is None or lr is None:
                outputs.append(hs)
                continue
            end = start + hs.shape[1]
            ao = att_out[:, start:end]
            # 匹配层的dtype
            target_dtype = lr.self_attn.o_proj.weight.dtype
            ao = ao.to(target_dtype)
            hs = hs.to(target_dtype)
            out = lr.self_attn.o_proj(ao)
            out = out + hs
            after = out.clone()
            out = lr.post_attention_layernorm(out)
            out = lr.mlp(out)
            out = out + after
            outputs.append(out)
            start = end if len([x for x in [p_Q,s_Q] if x is not None]) == 1 else 0

        inputs_embeds = outputs

        # 显示每层输出变化
        p_out = inputs_embeds[0]
        s_out = inputs_embeds[1] if inputs_embeds[1] is not None else None
        print(f"  输出: prefix norm={p_out.norm().item():.2f}", end="")
        if s_out is not None:
            print(f" | suffix norm={s_out.norm().item():.2f}", end="")
        print()

        if layer_idx < num_layers - 1:
            breakpoint()  # 停！看这层输出 → 输入 c 下一层

    # 最终
    print(f"\n{'='*60}")
    print("16层全部完成")
    print(f"{'='*60}")
    print(f"Prefix最终: {list(inputs_embeds[0].shape)}")
    print(f"Suffix最终: {list(inputs_embeds[1].shape) if inputs_embeds[1] is not None else 'None'}")

    # 输出投影
    s_out = inputs_embeds[1][:, -S:].float()
    v_t = policy.model.action_out_proj(s_out)
    print(f"\n动作输出: {list(v_t[:,:,:2].shape)}")
    print(f"前3步: {v_t[0,:3,:2].detach().cpu().numpy()}")
    print(f"(输入 q 退出)")


if __name__ == "__main__":
    layer_trace()
