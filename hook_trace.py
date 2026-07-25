"""
SmolVLA 逐层追踪 — 用PyTorch hook拦截每层的输入/输出
观察16层中Q/K/V形状、注意力模式
"""
import os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import torch
from lerobot.configs import parser
from lerobot.configs.train import TrainPipelineConfig
from lerobot.datasets import make_dataset
from lerobot.policies import make_policy
from lerobot.utils.constants import (
    OBS_STATE, OBS_LANGUAGE_TOKENS,
    OBS_LANGUAGE_ATTENTION_MASK, ACTION
)

class LayerTracker:
    """用hook追踪每层的输入输出"""
    def __init__(self):
        self.layer_idx = 0
        self.vlm_layers = []
        self.expert_layers = []

    def track_vlm_layer(self, module, input, output):
        print(f"\n  ┌─ VLM Layer {self.layer_idx}")
        inp = input[0]
        print(f"  │ 输入: {list(inp.shape)}, dtype={inp.dtype}")
        if isinstance(output, tuple):
            out = output[0]
        else:
            out = output
        print(f"  │ 输出: {list(out.shape)}, norm={out.norm().item():.1f}")
        print(f"  └─")

    def track_expert_layer(self, module, input, output):
        inp = input[0]
        print(f"  ┌─ Expert Layer {self.layer_idx}")
        print(f"  │ 输入: {list(inp.shape)}, dtype={inp.dtype}")
        if isinstance(output, tuple):
            out = output[0]
        else:
            out = output
        print(f"  │ 输出: {list(out.shape)}, norm={out.norm().item():.1f}")
        print(f"  └─")
        self.layer_idx += 1


@parser.wrap()
def hook_trace(cfg: TrainPipelineConfig):
    cfg.validate()
    cfg.policy.device = "cuda"

    print("加载数据+模型...")
    dataset = make_dataset(cfg)
    policy = make_policy(cfg=cfg.policy, ds_meta=dataset.meta).cuda()
    policy.eval()

    # ── 注册hook ──
    vwe = policy.model.vlm_with_expert
    tracker = LayerTracker()
    hooks = []
    
    num_vlm = len(vwe.get_vlm_model().text_model.layers)
    num_exp = len(vwe.lm_expert.layers)
    print(f"\nVLM: {num_vlm}层 | Expert: {num_exp}层 | 实际用: {vwe.num_vlm_layers}层\n")
    
    # Hook VLM layers
    for i, layer in enumerate(vwe.get_vlm_model().text_model.layers):
        if i < vwe.num_vlm_layers:
            h = layer.register_forward_hook(tracker.track_vlm_layer)
            hooks.append(h)
    
    # Hook Expert layers
    for i, layer in enumerate(vwe.lm_expert.layers):
        h = layer.register_forward_hook(tracker.track_expert_layer)
        hooks.append(h)

    # ── 准备batch ──
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

    # ── 前向传播 ──
    print("="*60)
    print("开始前向传播 — Hook将拦截每层")
    print("="*60)
    
    breakpoint()  # 输入 c 执行整个forward

    policy.train()
    loss, _ = policy.forward(batch)
    
    print(f"\n{'='*60}")
    print(f"Loss: {loss.item():.4f}")
    print(f"{'='*60}")

    # 清理
    for h in hooks:
        h.remove()
    
    print("(输入 q 退出)")


if __name__ == "__main__":
    hook_trace()
