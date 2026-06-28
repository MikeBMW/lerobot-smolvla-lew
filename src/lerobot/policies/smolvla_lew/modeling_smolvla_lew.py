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

# ====== 改动点1：导入替换，删除简易SmolVLMInterface，改用专家版SmolVLMWithExpertModel ======
from .action_head import SmolVLALewActionHead
from .configuration_smolvla_lew import SmolVLALewConfig
# 替换：原生lerobot/policies/smolvla/smolvlm_with_expert.py 专家VLM
from lerobot.policies.smolvla.smolvlm_with_expert import SmolVLMWithExpertModel
# 内置轻量LeWorldModel
from lerobot.world_models.le_world_model import LeWorldModel

# ============================================================================
# Native SmolVLALew Model - SmolVLM(SigLIP Expert) + LeWorldModel + DiT Action Head
# 参考原starVLA输入格式，替换全部Qwen/V-JEPA为轻量专家模块
# ============================================================================


class SmolVLALewModel(nn.Module):
    """
    SmolVLA Expert + LeWorldModel 组合模型
    Components:
      - SmolVLMWithExpertModel(SigLIP): 专家版轻量视觉语言主干，图文融合嵌入
      - DiT-B: flow-matching action head 预测未来动作
      - LeWorldModel: 轻量单步时序世界模型（可选）

    Input: List[dict] starVLA兼容原生格式
      - "image": List[PIL.Image] (multi-view static observation)
      - "video": np.ndarray [V, T, H, W, 3] 时序画面
      - "lang": str task instruction 自然语言指令
      - "action": np.ndarray [T, action_dim] 真值动作（仅训练）
      - "state": np.ndarray [1, state_dim] 机器人本体状态（可选）
    """

    def __init__(self, config: SmolVLALewConfig) -> None:
        super().__init__()
        require_package("transformers", extra="smolvla_lew")
        self.config = config

        # ====== 改动点2：初始化替换为专家版SmolVLMWithExpertModel，传入全套配置参数 ======
        # 1. 替换简易SmolVLMInterface为专家版SmolVLMWithExpertModel
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
        # SmolVLM无需自定义action特殊token，删除原expand_tokenizer逻辑
        self.action_tokens = None
        self.action_token_ids = None
        self.embodied_action_token_id = None

        # 2. 初始化DiT动作头，修复config层级错误：self.smolvlm.vlm.config
        self.action_model = SmolVLALewActionHead(
            config, cross_attention_dim=self.smolvlm.vlm.config.text_config.hidden_size
        )

        # 3. 替换V-JEPA整套为LeWorldModel轻量世界模型
        if config.enable_lew_world_model:
            self.le_world_model = LeWorldModel(
                img_size=config.siglip_image_size,
                hidden_dim=config.lew_hidden_dim,
                num_layers=config.lew_num_layers,
                pred_horizon=config.num_video_frames - 1
            )
        else:
            self.le_world_model = None

        # 冻结轻量VLM主干（专家版内部已处理train_expert_only，此处保留兼容）
        if config.freeze_smolvlm:
            self.smolvlm.requires_grad_(False)

        # SmolVLM原生Prompt无需action占位字符串，删除replace_prompt相关逻辑
        self.replace_prompt = ""
        self.embodied_replace_prompt = ""

    # 新增：张量转PIL图像工具函数，修复tensor_to_pil不存在报错
    def tensor_to_pil(self, img_tensor: torch.Tensor) -> Image.Image:
        """
        将单张图像张量 [C, H, W] 转为 PIL.Image
        支持 float(0~1) / uint8 两种格式
        """
        if img_tensor.dtype == torch.float32:
            img_tensor = (img_tensor * 255).clamp(0, 255).to(torch.uint8)
        arr = img_tensor.permute(1, 2, 0).detach().cpu().numpy()
        return Image.fromarray(arr)

    # ====== 改动点3：重写图文融合编码函数，适配SmolVLMWithExpertModel处理流程 ======
    def _get_multimodal_embeds(self, images: list[list[Image.Image]], instructions: list[str]) -> torch.Tensor:
        """调用专家SmolVLM，预处理图像+文本，返回全局多模态条件特征"""
        processor = self.smolvlm.processor
        batch_size = len(images)
        all_pixel_values = []
        all_text_input_ids = []

        # 批量预处理多视角图像+指令
        for sample_imgs, text in zip(images, instructions):
            proc_out = processor(images=sample_imgs, text=text, return_tensors="pt")
            all_pixel_values.append(proc_out["pixel_values"])
            all_text_input_ids.append(proc_out["input_ids"])

        # 拼接批量张量送入VLM
        pixel_values = torch.cat(all_pixel_values, dim=0).to(next(self.smolvlm.parameters()).device)
        input_ids = torch.cat(all_text_input_ids, dim=0).to(next(self.smolvlm.parameters()).device)

        # 前向获取完整多模态输出，取文本最后一层隐藏作为条件特征
        vlm_out = self.smolvlm.vlm(
            pixel_values=pixel_values,
            input_ids=input_ids,
            output_hidden_states=True,
            return_dict=True
        )
        # 取文本编码器最后一层隐藏特征作为DiT交叉注意力输入
        multimodal_embeds = vlm_out.text_model_output.hidden_states[-1]
        return multimodal_embeds

    # ---- 训练前向传播 ----
    def forward(self, examples: list[dict]) -> dict[str, Tensor]:
        """
        训练前向，兼容starVLA List[dict]输入格式
        Args:
            examples: List[dict] 样本列表
        Returns:
            {"action_loss": 动作扩散损失, "lew_loss": 轻量世界模型时序预测损失}
        """
        # 解包starVLA原生输入
        batch_images = [ex["image"] for ex in examples]  # List[List[PIL.Image]]
        batch_videos = [ex["video"] for ex in examples]  # List[np.ndarray]
        instructions = [ex["lang"] for ex in examples]    # List[str]
        has_action = "action" in examples[0] and examples[0]["action"] is not None
        actions = [ex["action"] for ex in examples] if has_action else None
        has_state = "state" in examples[0] and examples[0]["state"] is not None
        state = [ex["state"] for ex in examples] if has_state else None
        action_is_pad = (
            [ex["action_is_pad"] for ex in examples]
            if has_action and "action_is_pad" in examples[0] and examples[0]["action_is_pad"] is not None
            else None
        )

        # 堆叠视频 [B, V, T, H, W, 3] -> [B, V, T, 3, H, W]
        batch_videos = np.stack(batch_videos)
        batch_videos = batch_videos.transpose(0, 1, 2, 5, 3, 4)

        # LeWorldModel仅取第一视角，无需多视图补齐逻辑，简化处理
        batch_videos = batch_videos[:, :1, :, :, :, :]

        # Step1: SmolVLM图文融合编码，获取全局条件特征
        device_type = next(self.parameters()).device.type
        with torch.autocast(device_type=device_type, dtype=torch.bfloat16):
            multimodal_embeds = self._get_multimodal_embeds(batch_images, instructions)
            b, seq_len, hidden_dim = multimodal_embeds.shape

        # Step2: LeWorldModel时序潜特征预测损失（替代原V-JEPA wm_loss）
        device_lew = multimodal_embeds.device
        if not self.config.enable_lew_world_model:
            lew_loss = torch.tensor(0.0, device=device_lew)
        else:
            # 取视频t帧作为输入，t+1帧作为真值
            b, v, t_frames, c, h_img, w_img = batch_videos.shape
            frame_t = torch.from_numpy(batch_videos[:, 0, 0]).permute(0, 3, 1, 2).to(device_lew, dtype=torch.float32) / 255.0
            frame_t1 = torch.from_numpy(batch_videos[:, 0, 1]).permute(0, 3, 1, 2).to(device_lew, dtype=torch.float32) / 255.0

            # LeWorldModel编码当前帧、预测下一帧潜表征
            latent_t = self.le_world_model.encode_frame(frame_t)
            latent_t1_gt = self.le_world_model.encode_frame(frame_t1)
            latent_t1_pred = self.le_world_model(latent_t)
            lew_loss = F.l1_loss(latent_t1_pred, latent_t1_gt)

        if not has_action:
            return {"lew_loss": lew_loss}

        # Step3: DiT动作头前向计算action_loss
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

            action_loss = self.action_model(
                conditioning_tokens=multimodal_embeds_rep,
                actions=actions_target,
                state=state_tensor,
                action_is_pad=action_is_pad_rep
            )

        # 总损失：动作损失 + 世界模型损失加权
        return {"action_loss": action_loss, "lew_loss": lew_loss * self.config.lew_loss_weight}

    # ---- 推理动作生成 ----
    @torch.no_grad()
    def predict_action(
        self,
        batch_images: list[list[Image.Image]],
        instructions: list[str],
        state: np.ndarray | None = None,
    ) -> np.ndarray:
        """推理，输入图像+指令，输出未来多步归一化动作"""
        if self.config.resize_images_to is not None:
            height, width = self.config.resize_images_to
            resampling = getattr(Image, "Resampling", Image).BOX
            batch_images = [
                [image.resize((width, height), resample=resampling) for image in sample_images]
                for sample_images in batch_images
            ]

        # SmolVLM获取图文融合特征
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
# LeRobot Policy 适配层：LeRobot标准batch ↔ starVLA List[dict]原生格式
# ============================================================================


class SmolVLALewPolicy(PreTrainedPolicy):
    """
    LeRobot顶层策略封装，适配lerobot-train训练脚本
    组合：SmolVLM(SigLIP Expert) + LeWorldModel轻量世界模型 + DiT流匹配动作头
    """
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

    # LeRobot标准张量batch → starVLA List[dict]原生输入
    def _prepare_model_inputs(self, batch: dict[str, Tensor]) -> list[dict]:
        image_keys = list(self.config.image_features.keys())
        if not image_keys:
            raise ValueError("SmolVLALew requires at least one visual input feature.")
        first_key = image_keys[0]
        first_tensor = batch[first_key]
        batch_size = first_tensor.shape[0]

        # 1. 组装多视角PIL静态图像，调用内部tensor_to_pil
        images_per_sample: list[list[Image.Image]] = [[] for _ in range(batch_size)]
        for key in image_keys:
            tensor = batch[key]
            if tensor.ndim == 5:
                tensor = tensor[:, 0]
            for b in range(batch_size):
                images_per_sample[b].append(self.model.tensor_to_pil(tensor[b]))

        # 2. 组装时序视频数组 [V, T, H, W, 3]
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
                t_np = t.permute(0, 2, 3, 1).detach().cpu().float().numpy()
                if t_np.max() <= 1.0:
                    t_np = t_np * 255.0
                t_np = np.rint(t_np.clip(0, 255)).astype(np.uint8)
                sample_views.append(t_np)
            videos_per_sample.append(np.stack(sample_views, axis=0))

        # 3. 任务自然语言指令
        tasks = batch.get("task")
        if tasks is None:
            instructions = ["Push target block."] * batch_size
        elif isinstance(tasks, str):
            instructions = [tasks] * batch_size
        else:
            instructions = list(tasks)

        # 4. 真值动作、padding掩码
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

        # 5. 机器人状态
        state_list = None
        state_tensor = batch.get(OBS_STATE)
        if state_tensor is not None:
            if state_tensor.ndim > 2:
                state_tensor = state_tensor[:, -1, :]
            if state_tensor.ndim == 2:
                state_tensor = state_tensor.unsqueeze(1)
            state_list = [state_tensor[b].detach().cpu().float().numpy() for b in range(batch_size)]

        # 组装starVLA标准样本字典列表
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

    # 训练正向：返回总损失+日志
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

    # 批量推理生成多步动作
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

    # 单步动作输出（带队列缓存滚动输出chunk）
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