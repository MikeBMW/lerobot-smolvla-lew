# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch
import torch.nn.functional as F  # noqa: N812
from PIL import Image
from torch import Tensor, nn

from lerobot.policies.pretrained import PreTrainedPolicy, T
from lerobot.policies.utils import populate_queues
from lerobot.utils.constants import ACTION, OBS_STATE
from lerobot.utils.import_utils import _transformers_available, require_package

# 移除原V-JEPA、Qwen无用导入
if TYPE_CHECKING or _transformers_available:
    from transformers import AutoModel
else:
    AutoModel = None

# ====== 改动点1：导入替换，使用专家版SmolVLM ======
from .action_head import SmolVLALewActionHead
from .configuration_smolvla_lew import SmolVLALewConfig
from lerobot.policies.smolvla.smolvlm_with_expert import SmolVLMWithExpertModel

# ====== 新增：导入LeWorldModel世界模型 ======
from .world_model_le import LeWorldModel

# ============================================================================
# Native SmolVLALew Model - SmolVLM(SigLIP Expert) + DiT Action Head
# ============================================================================


class SmolVLALewModel(nn.Module):
    """
    SmolVLA Expert 模型
    Components:
      - SmolVLMWithExpertModel(SigLIP): 轻量视觉语言主干
      - DiT-B: flow-matching action head 预测动作
    """

    def __init__(self, config: SmolVLALewConfig) -> None:
        super().__init__()
        require_package("transformers", extra="smolvla_lew")
        self.config = config

        # 初始化专家版SmolVLM
        self.smolvlm = SmolVLMWithExpertModel(
            model_id=config.smolvlm_name,
            load_vlm_weights=True,
            train_expert_only=config.freeze_smolvlm,
            freeze_vision_encoder=config.freeze_smolvlm,
            attention_mode="self_attn",
            num_expert_layers=getattr(config, "num_expert_layers", -1),
            num_vlm_layers=getattr(config, "num_vlm_layers", -1),
            self_attn_every_n_layers=getattr(config, "self_attn_every_n_layers", -1),
            expert_width_multiplier=getattr(config, "expert_width_multiplier", 0.5),
            device="auto"
        )
        self.action_tokens = None
        self.action_token_ids = None
        self.embodied_action_token_id = None

        # 初始化DiT动作头
        self.action_model = SmolVLALewActionHead(
            config, cross_attention_dim=self.smolvlm.vlm.config.text_config.hidden_size
        )

        # 关闭WorldModel
        self.le_world_model = None
        
        # ====== 新增：条件性初始化LeWorldModel世界模型 ======
        if config.enable_lew_world_model:
            # 获取SigLIP视觉编码器
            vision_encoder = self.smolvlm.vlm.model.vision_model
            # 获取视觉编码器输出维度
            vision_hidden_size = vision_encoder.config.vision_config.hidden_size
            
            # 初始化LeWorldModel
            self.le_world_model = LeWorldModel(
                vision_encoder=vision_encoder,
                action_dim=config.action_dim,
                obs_embed_dim=config.lew_hidden_dim,
                hidden_dim=config.lew_hidden_dim,
                num_layers=config.lew_num_layers,
                num_heads=8,
                dim_head=64,
                mlp_dim=config.lew_hidden_dim * 4,
                num_frames=config.num_video_frames,
                dropout=0.1,
            )
            print(f"✓ LeWorldModel initialized: hidden_dim={config.lew_hidden_dim}, layers={config.lew_num_layers}")

        # 冻结VLM主干
        if config.freeze_smolvlm:
            self.smolvlm.requires_grad_(False)

        self.replace_prompt = ""
        self.embodied_replace_prompt = ""

    def tensor_to_pil(self, img_tensor: torch.Tensor) -> Image.Image:
        """[C, H, W] tensor 转 PIL Image"""
        if img_tensor.dtype == torch.float32:
            img_tensor = (img_tensor * 255).clamp(0, 255).to(torch.uint8)
        arr = img_tensor.permute(1, 2, 0).detach().cpu().numpy()
        return Image.fromarray(arr)

    def _get_multimodal_embeds(self, images: list[list[Image.Image]], instructions: list[str]) -> torch.Tensor:
        processor = self.smolvlm.processor
        batch_size = len(images)
        
        all_pixel_values = []
        all_input_ids = []
        
        for sample_idx in range(batch_size):
            sample_imgs = images[sample_idx]
            text = instructions[sample_idx] if sample_idx < len(instructions) and instructions[sample_idx] else "push red block to target"
            
            if not sample_imgs:
                raise ValueError(f"Sample {sample_idx} has no images!")
            
            num_images = len(sample_imgs)
            image_tokens = "<image>" * num_images
            full_text = f"{image_tokens}{text}"
            
            proc_out = processor(
                images=sample_imgs,
                text=full_text,
                return_tensors="pt"
            )
            
            all_pixel_values.append(proc_out["pixel_values"])
            all_input_ids.append(proc_out["input_ids"])
        
        device = next(self.smolvlm.parameters()).device
        pixel_values = torch.cat(all_pixel_values, dim=0).to(device)
        input_ids = torch.cat(all_input_ids, dim=0).to(device)
        
        # 直接调用 vlm 模型
        vlm_out = self.smolvlm.vlm(
            pixel_values=pixel_values,
            input_ids=input_ids,
            output_hidden_states=True,
            return_dict=True
        )
        
        # SmolVLM 输出的是 CausalLMOutputWithPast
        # hidden_states 是 tuple，取最后一层
        if hasattr(vlm_out, 'hidden_states') and vlm_out.hidden_states is not None:
            # hidden_states 是 tuple of [batch, seq_len, hidden_dim]
            multimodal_embeds = vlm_out.hidden_states[-1]
        else:
            # 备选方案：使用模型的内部表示
            # 对于 SmolVLM，可以通过 model 的 forward 获取
            raise ValueError("No hidden_states in vlm output")
        
        return multimodal_embeds

    def forward(self, examples: list[dict]) -> dict[str, Tensor]:
        # breakpoint()
        batch_images = [ex["image"] for ex in examples]
        batch_videos = [ex["video"] for ex in examples]
        instructions = [ex["lang"] for ex in examples]
        has_action = "action" in examples[0] and examples[0]["action"] is not None
        actions = [ex["action"] for ex in examples] if has_action else None
        has_state = "state" in examples[0] and examples[0]["state"] is not None
        state = [ex["state"] for ex in examples] if has_state else None
        action_is_pad = (
            [ex["action_is_pad"] for ex in examples]
            if has_action and "action_is_pad" in examples[0] and examples[0]["action_is_pad"] is not None
            else None
        )

        batch_videos = np.stack(batch_videos)
        batch_videos = batch_videos.transpose(0, 1, 2, 5, 3, 4)
        lew_loss = torch.tensor(0.0, device=next(self.parameters()).device)
        
        # ====== 新增：LeWorldModel世界模型损失计算 ======
        if self.le_world_model is not None and has_action:
            # 将视频数据转换为tensor
            videos_tensor = torch.from_numpy(batch_videos).float().to(next(self.parameters()).device)
            
            # 准备动作数据 [B, T, action_dim]
            actions_np = np.array(actions)  # [B, T_chunk, action_dim]
            actions_tensor_wm = torch.from_numpy(actions_np).float().to(videos_tensor.device)
            
            # 计算LeWorldModel损失
            lew_loss = self.le_world_model(videos_tensor, actions_tensor_wm)
            lew_loss = lew_loss * self.config.lew_loss_weight

        device_type = next(self.parameters()).device.type
        with torch.autocast(device_type=device_type, dtype=torch.bfloat16):
            multimodal_embeds = self._get_multimodal_embeds(batch_images, instructions)
            b, seq_len, hidden_dim = multimodal_embeds.shape

        if not has_action:
            return {"action_loss": torch.tensor(0.0, device=multimodal_embeds.device), "lew_loss": lew_loss}

        with torch.autocast(device_type=device_type, dtype=torch.float32):
            actions_tensor = torch.tensor(
                np.array(actions), device=multimodal_embeds.device, dtype=torch.float32
            )
            action_horizon = self.config.chunk_size
            actions_target = actions_tensor[:, -action_horizon:, :]

            state_tensor = None
            if state is not None:
                state_tensor = torch.tensor(
                    np.array(state), device=multimodal_embeds.device, dtype=multimodal_embeds.dtype
                )

            repeated_diffusion_steps = self.config.repeated_diffusion_steps
            actions_target = actions_target.repeat(repeated_diffusion_steps, 1, 1)
            multimodal_embeds_rep = multimodal_embeds.repeat(repeated_diffusion_steps, 1, 1)
            if state_tensor is not None:
                state_tensor = state_tensor.repeat(repeated_diffusion_steps, 1, 1)

            action_is_pad_rep = None
            if action_is_pad is not None:
                pad_tensor = torch.stack(
                    [
                        p.to(actions_target.device)
                        if isinstance(p, Tensor)
                        else torch.tensor(p, device=actions_target.device)
                        for p in action_is_pad
                    ]
                )
                pad_tensor = pad_tensor[:, -action_horizon:]
                action_is_pad_rep = pad_tensor.repeat(repeated_diffusion_steps, 1)

            breakpoint()
            action_loss = self.action_model(
                conditioning_tokens=multimodal_embeds_rep,
                actions=actions_target,
                state=state_tensor,
                action_is_pad=action_is_pad_rep
            )

        return {"action_loss": action_loss, "lew_loss": lew_loss}

    @torch.no_grad()
    def predict_action(
        self,
        batch_images: list[list[Image.Image]],
        instructions: list[str],
        state: np.ndarray | None = None,
    ) -> np.ndarray:
        if self.config.resize_images_to is not None:
            height, width = self.config.resize_images_to
            resampling = getattr(Image, "Resampling", Image).BOX
            batch_images = [
                [image.resize((width, height), resample=resampling) for image in sample_images]
                for sample_images in batch_images
            ]

        device_type = next(self.parameters()).device.type
        with torch.autocast(device_type=device_type, dtype=torch.bfloat16):
            multimodal_embeds = self._get_multimodal_embeds(batch_images, instructions)

        state_tensor = None
        if state is not None:
            state_tensor = torch.from_numpy(np.array(state)).to(
                device=multimodal_embeds.device, dtype=multimodal_embeds.dtype
            )

        pred_actions = self.action_model.predict_action(
            conditioning_tokens=multimodal_embeds.float(),
            state=state_tensor.float() if state_tensor is not None else None
        )
        return pred_actions.detach().cpu().numpy()


# ============================================================================
# LeRobot Policy 顶层封装
# ============================================================================
class SmolVLALewPolicy(PreTrainedPolicy):
    config_class = SmolVLALewConfig
    name = "smolvla_lew"

    def __init__(self, config: SmolVLALewConfig, **kwargs) -> None:
        super().__init__(config)
        config.validate_features()
        if dataset_meta := kwargs.get("dataset_meta"):
            ds_features = dataset_meta.features
            if OBS_STATE in ds_features:
                config.state_dim = ds_features[OBS_STATE]["shape"][0]
            if ACTION in ds_features:
                config.action_dim = ds_features[ACTION]["shape"][0]

        self.model = SmolVLALewModel(config)
        self.reset()

    def reset(self) -> None:
        self._queues = {ACTION: deque(maxlen=self.config.n_action_steps)}

    def _prepare_model_inputs(self, batch: dict[str, Tensor]) -> list[dict]:
        image_keys = list(self.config.image_features.keys())
        if not image_keys:
            raise ValueError("SmolVLALew requires at least one visual input feature.")
        first_key = image_keys[0]
        first_tensor = batch[first_key]
        batch_size = first_tensor.shape[0]

        images_per_sample: list[list[Image.Image]] = [[] for _ in range(batch_size)]
        for key in image_keys:
            tensor = batch[key]
            if tensor.ndim == 5:
                tensor = tensor[:, 0]
            for b in range(batch_size):
                images_per_sample[b].append(self.model.tensor_to_pil(tensor[b]))

        video_source = None
        for k in image_keys:
            if k in batch:
                video_source = batch[k]
                break
        if video_source is None:
            raise ValueError("No image data found for video construction.")

        videos_per_sample = []
        for b in range(batch_size):
            sample_views = []
            for k in image_keys:
                t = batch[k][b]
                if t.ndim == 3:
                    t = t.unsqueeze(0)
                t_np = t.permute(0, 3, 1, 2).detach().cpu().float().numpy()
                if t_np.max() <= 1.0:
                    t_np = t_np * 255.0
                t_np = np.rint(t_np.clip(0, 255)).astype(np.uint8)
                sample_views.append(t_np)
            videos_per_sample.append(np.stack(sample_views, axis=0))

        # 兜底清洗空指令
        tasks = batch.get("task")
        if tasks is None:
            instructions = ["push red block to target"] * batch_size
        elif isinstance(tasks, str):
            instructions = [tasks] * batch_size
        else:
            instructions = list(tasks)
        for idx in range(len(instructions)):
            if not instructions[idx] or len(instructions[idx].strip()) == 0:
                instructions[idx] = "push red block to target"

        actions_list = None
        action_is_pad_list = None
        actions_tensor = batch.get(ACTION)
        if actions_tensor is not None:
            if actions_tensor.ndim == 2:
                actions_tensor = actions_tensor.unsqueeze(1)
            actions_list = [actions_tensor[b].detach().cpu().float().numpy() for b in range(batch_size)]
            action_is_pad_tensor = batch.get("action_is_pad")
            if action_is_pad_tensor is not None:
                action_is_pad_list = [action_is_pad_tensor[b].detach().cpu() for b in range(batch_size)]

        state_list = None
        state_tensor = batch.get(OBS_STATE)
        if state_tensor is not None:
            if state_tensor.ndim > 2:
                state_tensor = state_tensor[:, -1, :]
            if state_tensor.ndim == 2:
                state_tensor = state_tensor.unsqueeze(1)
            state_list = [state_tensor[b].detach().cpu().float().numpy() for b in range(batch_size)]

        examples = []
        for b in range(batch_size):
            example = {
                "image": images_per_sample[b],
                "video": videos_per_sample[b],
                "lang": instructions[b],
            }
            if actions_list is not None:
                example["action"] = actions_list[b]
            if action_is_pad_list is not None:
                example["action_is_pad"] = action_is_pad_list[b]
            if state_list is not None:
                example["state"] = state_list[b]
            examples.append(example)
        return examples

    def forward(self, batch: dict[str, Tensor]) -> tuple[Tensor, dict]:
        examples = self._prepare_model_inputs(batch)
        native_output = self.model.forward(examples)

        ref = next(iter(native_output.values()))
        zero = torch.zeros((), device=ref.device, dtype=ref.dtype)
        total_loss = native_output.get("action_loss", zero) + native_output.get("lew_loss", zero)
        logs = {k: v.detach().item() for k, v in native_output.items()}
        logs["loss"] = total_loss.detach().item()
        return total_loss, logs

    def get_optim_params(self) -> dict:
        return self.model.parameters()

    @torch.no_grad()
    def predict_action_chunk(self, batch: dict[str, Tensor], noise: Tensor | None = None) -> Tensor:
        self.eval()
        self._queues = populate_queues(self._queues, batch, exclude_keys=[ACTION])

        examples = self._prepare_model_inputs(batch)
        batch_images = [ex["image"] for ex in examples]
        instructions = [ex["lang"] for ex in examples]

        state_np = None
        if "state" in examples[0] and examples[0]["state"] is not None:
            state_np = np.stack([ex["state"] for ex in examples])

        actions_np = self.model.predict_action(batch_images, instructions, state_np)
        return torch.from_numpy(actions_np).to(device=self.config.device, dtype=torch.float32)

    @torch.no_grad()
    def select_action(self, batch: dict[str, Tensor], noise: Tensor | None = None) -> Tensor:
        self.eval()
        self._queues = populate_queues(self._queues, batch, exclude_keys=[ACTION])
        if len(self._queues[ACTION]) == 0:
            actions = self.predict_action_chunk(batch)
            self._queues[ACTION].extend(actions.transpose(0, 1)[: self.config.n_action_steps])
        return self._queues[ACTION].popleft()

    @classmethod
    def from_pretrained(
        cls: type[T],
        pretrained_name_or_path: str | Path,
        **kwargs,
    ):
        return super().from_pretrained(pretrained_name_or_path, **kwargs)

    @classmethod
    def _load_as_safetensor(cls, model: T, model_file: str, map_location: str, strict: bool) -> T:
        reinit_prefixes = model.config.reinit_modules
        if not reinit_prefixes:
            return super()._load_as_safetensor(model, model_file, map_location, strict)

        from safetensors.torch import load_file

        state_dict = load_file(model_file, device=map_location)
        current = model.state_dict()

        reinitialized: list[str] = []
        filtered: dict = {}
        for key, value in state_dict.items():
            if key in current and value.shape != current[key].shape:
                if not any(key.startswith(p) for p in reinit_prefixes):
                    raise ValueError(
                        f"Shape mismatch for '{key}' (checkpoint {tuple(value.shape)} vs model "
                        f"{tuple(current[key].shape)}) and its prefix is not in `reinit_modules`."
                    )
                reinitialized.append(
                    f"{key}: checkpoint {tuple(value.shape)} → model {tuple(current[key].shape)}"
                )
            else:
                filtered[key] = value

        if reinitialized:
            logging.warning(
                f"reinit_modules: skipping {len(reinitialized)} tensor(s) with mismatched shapes "
                f"(randomly re-initialised):\n  " + "\n  ".join(reinitialized)
            )

        from lerobot.policies.utils import log_model_loading_keys

        missing_keys, unexpected_keys = model.load_state_dict(filtered, strict=False)
        log_model_loading_keys(missing_keys, unexpected_keys)
        return model