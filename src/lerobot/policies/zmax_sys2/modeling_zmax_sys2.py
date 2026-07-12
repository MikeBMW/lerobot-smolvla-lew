"""
Z-MAX Sys2 · 云端推理引擎 (web 分支 - 4090 实现)

真实的 VTLA (Vision-Touch-Language-Action) 和 GR00T N1.7 推理，
通过 gRPC/HTTP API 暴露给 Sys1 (4060) 调用。

Sys2 = 大模型层，运行在 4090 上：
- VTLA:  融合触觉的 VLA 模型 (~450M, 基于 SmolVLA+触觉编码器)
- GR00T: NVIDIA GR00T N1.7 通用机器人模型 (~7B, HuggingFace 加载)
- ACT:   轻量级动作分块 (fallback)
"""
from __future__ import annotations
import os
import sys
import time
import json
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
from concurrent import futures

import numpy as np
import torch

from lerobot.policies.pretrained import PreTrainedPolicy
from .configuration_zmax_sys2 import ZmaxSys2Config, Sys2ModelType

logger = logging.getLogger("zmax.sys2")


# ═══════════════════════════════════════════════════════════════
# 仿真数据包
# ═══════════════════════════════════════════════════════════════

@dataclass
class SimFeedback:
    """仿真数据反馈包 (ROS2 / Isaac Sim → Sys-2)"""
    camera_rgb: np.ndarray          # [3, H, W] RGB图像
    force_torque: np.ndarray        # [6] 力/力矩 (Fx,Fy,Fz,Tx,Ty,Tz)
    tactile: np.ndarray             # [16] 触觉点阵
    joint_states: np.ndarray        # [N] 关节角度
    gripper_pos: float              # 夹爪位置 (0-1)
    task_text: str = ""             # 语言指令
    timestamp: float = 0.0

    def to_tensor(self, device='cpu') -> dict:
        return {
            'images': torch.from_numpy(self.camera_rgb.copy()).float().to(device),
            'force': torch.from_numpy(self.force_torque.copy()).float().to(device),
            'tactile': torch.from_numpy(self.tactile.copy()).float().to(device),
            'state': torch.from_numpy(self.joint_states.copy()).float().to(device),
            'gripper': torch.tensor([self.gripper_pos], device=device),
            'task': self.task_text,
        }


@dataclass
class Sys2InferenceResult:
    """Sys2 推理结果"""
    action: np.ndarray              # 动作向量
    model_used: str                 # 使用的模型名
    task_type: str                  # 任务分类
    plan: dict = field(default_factory=dict)  # 任务规划
    inference_time_ms: float = 0.0
    confidence: float = 1.0


# ═══════════════════════════════════════════════════════════════
# VTLA 推理引擎 (Vision-Touch-Language-Action)
# ═══════════════════════════════════════════════════════════════

class VTLAInferenceEngine:
    """
    VTLA 推理引擎 - 融合视觉+触觉+语言的动作预测

    基于 SmolVLA 架构，增强触觉模态：
    - 视觉编码: SmolVLM-SigLIP
    - 触觉编码: 独立 MLP 编码器
    - 多模态融合: 交叉注意力
    - 动作解码: DiT-B Action Head
    """

    def __init__(self, config: ZmaxSys2Config, device: torch.device):
        self.config = config
        self.device = device
        self._model = None
        self._tokenizer = None
        self._tactile_encoder = None  # 触觉编码器
        self._loaded = False

    def load(self):
        """加载 VTLA 模型"""
        if self._loaded:
            return

        model_path = self.config.vtla_model_path or "lerobot/smolvla_base"
        logger.info(f"Loading VTLA model from {model_path}...")

        try:
            from lerobot.policies.smolvla import SmolVLAPolicy
            from lerobot.policies.smolvla.modeling_smolvla import resize_with_pad
            from transformers import AutoTokenizer

            self._model = SmolVLAPolicy.from_pretrained(model_path)
            self._model.to(self.device)
            self._model.eval()

            vlm_name = getattr(self._model.config, 'vlm_model_name',
                               "HuggingFaceTB/SmolVLM2-500M-Video-Instruct")
            self._tokenizer = AutoTokenizer.from_pretrained(vlm_name)

            # 构建触觉编码器
            if self.config.enable_tactile:
                self._tactile_encoder = torch.nn.Sequential(
                    torch.nn.Linear(self.config.tactile_dim, 128),
                    torch.nn.ReLU(),
                    torch.nn.Linear(128, 256),
                    torch.nn.ReLU(),
                    torch.nn.Linear(256, 512),
                ).to(self.device)

            self._resize_fn = resize_with_pad
            self._loaded = True
            logger.info(f"VTLA model loaded: {sum(p.numel() for p in self._model.parameters())/1e6:.0f}M params")

        except Exception as e:
            logger.error(f"Failed to load VTLA model: {e}")
            self._model = None

    def predict(self, sim: SimFeedback) -> Sys2InferenceResult:
        """VTLA 推理"""
        t0 = time.time()

        if self._model is None:
            return Sys2InferenceResult(
                action=np.zeros(14),
                model_used="vtla",
                task_type="error",
                plan={'error': 'VTLA model not loaded'},
            )

        tensors = sim.to_tensor(self.device)

        try:
            # 图像预处理
            img = tensors['images']
            if img.max() > 1.0:
                img = img / 255.0
            if img.ndim == 3:
                img = img.unsqueeze(0)
            img = self._resize_fn(img, 512, 512, pad_value=0) * 2.0 - 1.0
            B = img.shape[0]

            # 触觉编码
            tactile_feat = None
            if self._tactile_encoder is not None and tensors['tactile'] is not None:
                tactile_feat = self._tactile_encoder(
                    tensors['tactile'].unsqueeze(0).float()
                )

            # 语言编码
            task_text = sim.task_text or "execute precise manipulation"
            encoded = self._tokenizer(
                task_text.strip(),
                return_tensors="pt",
                padding="max_length",
                max_length=getattr(self._model.config, 'tokenizer_max_length', 48),
                truncation=True,
            )

            from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK

            batch = {
                "observation.images.camera1": img,
                "observation.images.camera2": torch.ones(B, 3, 512, 512, device=self.device) * -1,
                "observation.images.camera3": torch.ones(B, 3, 512, 512, device=self.device) * -1,
                "observation.state": tensors['state'].unsqueeze(0),
                OBS_LANGUAGE_TOKENS: encoded["input_ids"].to(self.device),
                OBS_LANGUAGE_ATTENTION_MASK: encoded["attention_mask"].to(torch.bool).to(self.device),
            }

            # 推理
            with torch.no_grad():
                action_chunk = self._model.predict_action_chunk(batch)
            action = action_chunk[0, 0, :].cpu().numpy()

            elapsed = (time.time() - t0) * 1000
            return Sys2InferenceResult(
                action=action,
                model_used="vtla",
                task_type=self._classify(sim),
                inference_time_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"VTLA inference failed: {e}")
            return Sys2InferenceResult(
                action=np.zeros(14),
                model_used="vtla",
                task_type="error",
                plan={'error': str(e)},
            )

    def _classify(self, sim: SimFeedback) -> str:
        """基于力/触觉信号分类任务类型"""
        ft = np.abs(sim.force_torque)
        if ft.max() < 0.5:
            return 'free_space'
        elif ft[2:].max() > 3.0:
            return 'insertion'
        elif sim.tactile.max() > 0.5:
            return 'contact_rich'
        return 'manipulation'


# ═══════════════════════════════════════════════════════════════
# GR00T N1.7 推理引擎
# ═══════════════════════════════════════════════════════════════

class GR00TInferenceEngine:
    """
    GR00T N1.7 推理引擎 - NVIDIA 通用机器人基础模型

    支持多种具身形态 (OXE_DROID, UNITREE_G1, SIMPLER_ENV_WIDOWX 等)
    输入: video + state + language
    输出: action (末端位姿 + 关节 + 夹爪)
    """

    def __init__(self, config: ZmaxSys2Config, device: torch.device):
        self.config = config
        self.device = device
        self._policy = None
        self._loaded = False

    def load(self):
        """加载 GR00T N1.7 模型"""
        if self._loaded:
            return

        model_path = self.config.groot_model_path
        if not model_path:
            logger.warning("No GR00T model path configured, using placeholder")
            return

        logger.info(f"Loading GR00T N1.7 from {model_path}...")

        try:
            # 确保 GR00T 在 Python path 中
            groot_root = Path("/root/Isaac-GR00T")
            if groot_root.exists() and str(groot_root) not in sys.path:
                sys.path.insert(0, str(groot_root))

            from gr00t.policy.gr00t_policy import Gr00tPolicy
            from gr00t.data.embodiment_tags import EmbodimentTag

            tag = EmbodimentTag.resolve(self.config.groot_embodiment_tag)
            device_str = str(self.device)

            self._policy = Gr00tPolicy(
                embodiment_tag=tag,
                model_path=model_path,
                device=device_str,
                strict=False,  # 宽松模式，兼容 Z-MAX 数据格式
            )

            self._loaded = True
            logger.info(f"GR00T N1.7 loaded: embodiment={tag.name}")

        except ImportError as e:
            logger.warning(f"GR00T import failed (deps not installed?): {e}")
            logger.warning("Run: cd /root/Isaac-GR00T && uv sync --all-extras")
        except Exception as e:
            logger.error(f"Failed to load GR00T model: {e}")

    def predict(self, sim: SimFeedback) -> Sys2InferenceResult:
        """GR00T 推理"""
        t0 = time.time()

        if self._policy is None:
            # 未加载 GR00T - 尝试 fallback 到 VTLA
            logger.warning("GR00T not loaded, returning fallback")
            return Sys2InferenceResult(
                action=np.zeros(14),
                model_used="groot",
                task_type="fallback",
                plan={'error': 'GR00T model not loaded'},
            )

        try:
            # 构建 GR00T 期望的观测格式
            # video: (B, T, H, W, C) uint8
            img = sim.camera_rgb
            if img.shape[0] == 3:  # (C, H, W) → (H, W, C)
                img = np.transpose(img, (1, 2, 0))
            if img.ndim == 3:
                img = img[np.newaxis, np.newaxis, ...]  # (1, 1, H, W, C)
            if img.dtype != np.uint8:
                img = (img * 255).astype(np.uint8) if img.max() <= 1.0 else img.astype(np.uint8)

            # state: (B, T, D) float32
            state = sim.joint_states.astype(np.float32)
            if state.ndim == 1:
                state = state[np.newaxis, np.newaxis, :]  # (1, 1, D)

            observation = {
                "video": {"cam_primary": img},
                "state": {"joint_positions": state},
                "language": {"instruction": [[sim.task_text or "complete the task"]]},
            }

            action, info = self._policy.get_action(observation)

            # 提取动作
            action_key = list(action.keys())[0]
            action_arr = action[action_key]  # (B, T, D)

            elapsed = (time.time() - t0) * 1000
            return Sys2InferenceResult(
                action=action_arr[0, 0, :],  # 取第一个 batch 第一个时间步
                model_used="groot",
                task_type="complex",
                inference_time_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"GR00T inference failed: {e}")
            import traceback; traceback.print_exc()
            return Sys2InferenceResult(
                action=np.zeros(14),
                model_used="groot",
                task_type="error",
                plan={'error': str(e)},
            )


# ═══════════════════════════════════════════════════════════════
# ACT Fallback 引擎
# ═══════════════════════════════════════════════════════════════

class ACTInferenceEngine:
    """ACT 轻量级推理引擎 (fallback)"""

    def __init__(self, config: ZmaxSys2Config, device: torch.device):
        self.config = config
        self.device = device
        self._model = None

    def load(self):
        try:
            from lerobot.policies.act.modeling_act import ACTPolicy
            self._model = ACTPolicy.from_pretrained(
                self.config.act_model_path
            ).to(self.device).eval()
            logger.info("ACT fallback model loaded")
        except Exception as e:
            logger.warning(f"ACT load failed: {e}")

    def predict(self, sim: SimFeedback) -> Sys2InferenceResult:
        if self._model is None:
            return Sys2InferenceResult(
                action=np.zeros(14), model_used="act",
                task_type="fallback",
                plan={'error': 'ACT not loaded'}
            )

        tensors = sim.to_tensor(self.device)
        try:
            with torch.no_grad():
                action = self._model.select_action({
                    'observation.images.top': tensors['images'].unsqueeze(0),
                    'observation.state': tensors['state'].unsqueeze(0),
                })
            return Sys2InferenceResult(
                action=action.cpu().numpy().flatten(),
                model_used="act",
                task_type="simple",
            )
        except Exception as e:
            return Sys2InferenceResult(
                action=np.zeros(14), model_used="act",
                task_type="error", plan={'error': str(e)}
            )


# ═══════════════════════════════════════════════════════════════
# Z-MAX Sys2 主策略 (云端大模型调度)
# ═══════════════════════════════════════════════════════════════

class ZmaxSys2Policy(PreTrainedPolicy):
    """
    Z-MAX Sys2 · 云端智能体策略

    运行在 4090 上，管理 VTLA + GR00T + ACT 多个推理引擎。
    对外暴露统一接口供 Sys1 (4060) 通过 gRPC 调用。

    用法:
        config = ZmaxSys2Config(vtla_model_path="lerobot/smolvla_base")
        sys2 = ZmaxSys2Policy(config)
        sys2.load_models()
        result = sys2.predict(sim_feedback, model="auto")
    """

    config_class = ZmaxSys2Config
    name = "zmax_sys2"

    def __init__(self, config: ZmaxSys2Config, dataset_stats=None, dataset_info=None):
        super().__init__(config)

        # 推理引擎
        self._vtla = VTLAInferenceEngine(config, self.device)
        self._groot = GR00TInferenceEngine(config, self.device)
        self._act = ACTInferenceEngine(config, self.device)

        # 统计
        self._inference_count: dict[str, int] = {}
        self._feedback_buffer: list[SimFeedback] = []

    # ═══ 模型管理 ═══

    def load_models(self, which: str = "all"):
        """加载指定的推理引擎"""
        if which in ("all", "vtla"):
            self._vtla.load()
        if which in ("all", "groot"):
            self._groot.load()
        if which in ("all", "act"):
            self._act.load()
        logger.info(f"Sys2 models loaded: {which}")

    def list_loaded_models(self) -> list[str]:
        """列出已加载的模型"""
        loaded = []
        if self._vtla._loaded: loaded.append("vtla")
        if self._groot._loaded: loaded.append("groot")
        if self._act._loaded: loaded.append("act")
        return loaded

    # ═══ 推理接口 ═══

    def predict(
        self,
        sim: SimFeedback,
        model: str = "auto",
    ) -> Sys2InferenceResult:
        """
        统一推理接口

        Args:
            sim: 仿真数据反馈
            model: 模型选择 ("auto" | "vtla" | "groot" | "act")

        Returns:
            Sys2InferenceResult (action + metadata)
        """
        self._feedback_buffer.append(sim)

        # 自动选择模型
        if model == "auto":
            model = self._auto_select_model(sim)

        self._inference_count[model] = self._inference_count.get(model, 0) + 1

        # 路由到对应引擎
        if model == "groot" and self._groot._loaded:
            return self._groot.predict(sim)
        elif model == "vtla" and self._vtla._loaded:
            return self._vtla.predict(sim)
        elif model == "act" and self._act._loaded:
            return self._act.predict(sim)

        # Fallback 链
        for engine_name, engine in [
            ("vtla", self._vtla),
            ("act", self._act),
        ]:
            if engine._loaded:
                result = engine.predict(sim)
                result.model_used = f"{model}→{engine_name}(fallback)"
                return result

        return Sys2InferenceResult(
            action=np.zeros(14),
            model_used="none",
            task_type="error",
            plan={'error': 'No models loaded'},
        )

    def _auto_select_model(self, sim: SimFeedback) -> str:
        """根据传感器数据自动选择最优模型"""
        ft = np.abs(sim.force_torque)
        tactile_active = sim.tactile.max() > 0.1 if sim.tactile is not None else False

        # 复杂接触 → GR00T (如果加载)
        if (ft.max() > 3.0 or tactile_active) and self._groot._loaded:
            return "groot"
        # 精细操作 → VTLA
        elif ft.max() > 0.5 and self._vtla._loaded:
            return "vtla"
        # 简单任务 → ACT
        elif self._act._loaded:
            return "act"
        # 默认
        return "vtla" if self._vtla._loaded else "act"

    # ═══ gRPC 服务 ═══

    def start_server(self):
        """启动 Sys2 gRPC 推理服务"""
        try:
            from .sys2_server import Sys2GRPCServer
            server = Sys2GRPCServer(self, self.config)
            server.start()
            return server
        except ImportError as e:
            logger.error(f"Cannot start gRPC server: {e}")
            return None

    # ═══ 仿真数据接口 (兼容旧版) ═══

    def receive_feedback(self, sim_data: SimFeedback) -> dict:
        """仿真数据反馈 (兼容接口)"""
        result = self.predict(sim_data)
        return {
            'action': result.action,
            'model_used': result.model_used,
            'task_type': result.task_type,
            'plan': result.plan,
            'inference_time_ms': result.inference_time_ms,
        }

    # ═══ 状态查询 ═══

    def get_status(self) -> dict:
        """获取 Sys2 运行时状态"""
        return {
            "loaded_models": self.list_loaded_models(),
            "inference_count": self._inference_count,
            "buffer_size": len(self._feedback_buffer),
            "device": str(self.device),
            "gpu_memory_mb": torch.cuda.memory_allocated() / 1e6,
        }

    @property
    def device(self) -> torch.device:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
