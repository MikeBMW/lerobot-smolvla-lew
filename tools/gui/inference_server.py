#!/usr/bin/env python3
"""
Z-MAX 推理服务端 — gRPC PolicyServer 封装
从GUI启动/停止，加载SmolVLA模型，异步推理
"""
import os, sys, time, pickle, threading, logging
from concurrent import futures
from dataclasses import dataclass, field
from typing import Optional, Callable

import grpc
import torch

# 确保可以导入lerobot
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lerobot.transport import services_pb2, services_pb2_grpc
from lerobot.async_inference.configs import PolicyServerConfig
from lerobot.async_inference.policy_server import PolicyServer
from lerobot.async_inference.helpers import RemotePolicyConfig, TimedObservation
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from transformers import AutoTokenizer


@dataclass
class InferenceServerState:
    """服务端状态"""
    running: bool = False
    model_loaded: bool = False
    host: str = "0.0.0.0"
    port: int = 50051
    checkpoint_path: str = ""
    inference_count: int = 0
    last_inference_time: float = 0.0
    error_message: str = ""


class ZmaxInferenceServer:
    """
    Z-MAX推理服务端
    封装PolicyServer，提供start/stop/status接口
    自动注入定制预处理器以兼容SmolVLA的observation.image格式
    """
    
    def __init__(self, log_callback: Optional[Callable] = None):
        self.state = InferenceServerState()
        self._log = log_callback or (lambda msg: print(f"[Server] {msg}"))
        self._grpc_server: Optional[grpc.Server] = None
        self._policy_server: Optional[PolicyServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._tokenizer = None
    
    @property
    def running(self) -> bool:
        return self.state.running
    
    @property
    def model_loaded(self) -> bool:
        return self.state.model_loaded
    
    def _log_info(self, msg: str):
        self._log(f"ℹ️ {msg}")
    
    def _log_ok(self, msg: str):
        self._log(f"✅ {msg}")
    
    def _log_err(self, msg: str):
        self._log(f"❌ {msg}")
        self.state.error_message = msg
    
    def start_server(self, checkpoint_path: str, host: str = "0.0.0.0", port: int = 50051):
        """启动gRPC服务（不加载模型，等客户端发送策略指令后加载）"""
        if self.state.running:
            self._log_info("服务已在运行")
            return False
        
        self.state.host = host
        self.state.port = port
        self.state.checkpoint_path = checkpoint_path
        
        try:
            self._log_info(f"启动gRPC服务 @ {host}:{port}...")
            
            cfg = PolicyServerConfig(host=host, port=port)
            self._policy_server = PolicyServer(cfg)
            
            # 注入定制预处理器
            self._patch_preprocessor(checkpoint_path)
            
            self._grpc_server = grpc.server(
                futures.ThreadPoolExecutor(max_workers=4),
                options=[('grpc.max_send_message_length', 100*1024*1024)]
            )
            services_pb2_grpc.add_AsyncInferenceServicer_to_server(
                self._policy_server, self._grpc_server
            )
            self._grpc_server.add_insecure_port(f"{host}:{port}")
            self._grpc_server.start()
            
            self.state.running = True
            self._log_ok(f"服务就绪 @ {host}:{port}  模型: {os.path.basename(checkpoint_path)}")
            return True
            
        except Exception as e:
            self._log_err(f"启动失败: {e}")
            return False
    
    def _patch_preprocessor(self, checkpoint_path: str):
        """注入定制预处理器 — 绕过checkpoint的训练预处理器"""
        
        # 先临时加载模型获取tokenizer
        try:
            tmp_policy = SmolVLAPolicy.from_pretrained(checkpoint_path, local_files_only=True)
            vlm_model = tmp_policy.config.vlm_model_name
            del tmp_policy
            torch.cuda.empty_cache()
        except Exception:
            vlm_model = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
        
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(vlm_model)
        except Exception:
            self._tokenizer = None
            self._log_info("无法加载tokenizer，使用备用方案")
        
        # 注入到PolicyServer
        ps = self._policy_server
        ps._original_make_pre_post = None
        
        # 保存原始的SendPolicyInstructions以备后用
        original_spi = ps.SendPolicyInstructions
        
        def patched_spi(request, context):
            """先执行原始加载，再注入定制preprocessor"""
            result = original_spi(request, context)
            # 替换预处理器 + 修补_predict_action_chunk
            if ps.policy is not None:
                ps.preprocessor = lambda x: x  # no-op: 透传
                ps.postprocessor = lambda x: x
                
                # 注入_predict_action_chunk中的observation构建逻辑
                original_predict = ps._predict_action_chunk
                def patched_predict(observation_t):
                    """完全定制的推理管线"""
                    import numpy as np
                    raw_obs = observation_t.get_observation()
                    
                    # 直接从raw obs构建SmolVLA输入
                    obs = {}
                    
                    # State
                    if "observation.state" in raw_obs:
                        obs["observation.state"] = raw_obs["observation.state"]
                    elif "s0" in raw_obs:
                        state_vals = []
                        for i in range(10):
                            k = f"s{i}"
                            if k in raw_obs:
                                state_vals.append(float(raw_obs[k]))
                            else:
                                break
                        if state_vals:
                            obs["observation.state"] = torch.tensor([state_vals], device=ps.device)
                    
                    # Image
                    img_key = None
                    for key in raw_obs:
                        if "image" in key.lower():
                            img_key = key
                            break
                    if img_key:
                        img = raw_obs[img_key]
                        if isinstance(img, np.ndarray):
                            img = torch.from_numpy(img).float() / 255.0
                        elif isinstance(img, torch.Tensor):
                            img = img.float() / 255.0 if img.max() > 1.0 else img.float()
                        if img.ndim == 3:
                            img = img.unsqueeze(0)
                        obs["observation.image"] = img.to(ps.device)
                    
                    # Language tokens
                    task_text = raw_obs.get("task", "complete the task")
                    if isinstance(task_text, (list, tuple)):
                        task_text = str(task_text[0]) if task_text else "complete the task"
                    task_text = str(task_text)
                    
                    if self._tokenizer is not None and hasattr(ps.policy.config, 'tokenizer_max_length'):
                        encoded = self._tokenizer(
                            task_text, return_tensors="pt",
                            padding="max_length",
                            max_length=ps.policy.config.tokenizer_max_length,
                            truncation=True
                        )
                        obs[OBS_LANGUAGE_TOKENS] = encoded["input_ids"].to(ps.device)
                        obs[OBS_LANGUAGE_ATTENTION_MASK] = encoded["attention_mask"].to(torch.bool).to(ps.device)
                    
                    # 推理
                    chunk = ps._get_action_chunk(obs)
                    
                    # 构建TimedAction
                    B, chunk_size, action_dim = chunk.shape
                    from lerobot.async_inference.helpers import TimedAction
                    return [TimedAction(
                        timestamp=observation_t.get_timestamp(),
                        timestep=observation_t.get_timestep() * chunk_size + i,
                        action=chunk[0, i, :]
                    ) for i in range(chunk_size)]
                
                ps._predict_action_chunk = patched_predict
                
                self.state.model_loaded = True
                self._log_ok(f"模型加载完成，定制推理管线已注入")
            return result
        
        ps.SendPolicyInstructions = patched_spi
        self._log_info("预处理器补丁就绪")
    
    def _make_custom_preprocessor(self):
        """构建SmolVLA兼容的预处理器"""
        tokenizer = self._tokenizer
        ps = self._policy_server
        
        if tokenizer is None and ps.policy is not None:
            try:
                from transformers import AutoTokenizer
                tokenizer = AutoTokenizer.from_pretrained(ps.policy.config.vlm_model_name)
                self._tokenizer = tokenizer
            except:
                pass
        
        def custom_preprocessor(obs_dict):
            """手动构建SmolVLA输入"""
            import logging
            log = logging.getLogger("custom_preprocessor")
            log.info(f"Input keys: {list(obs_dict.keys())}")
            
            device = ps.device
            B = 1
            
            # 图像处理
            img = None
            for key in list(obs_dict.keys()):
                if 'image' in key.lower():
                    val = obs_dict[key]
                    log.info(f"Found image key: {key}, type: {type(val).__name__}")
                    if isinstance(val, torch.Tensor):
                        img = val
                    elif hasattr(val, '__array__'):
                        import numpy as np
                        img = torch.from_numpy(np.array(val)).float() / 255.0
                    break
            
            if img is not None:
                if img.ndim == 3:
                    img = img.unsqueeze(0)
                img = img.to(device)
                log.info(f"Image processed: shape={img.shape}, device={img.device}")
            else:
                log.warning("No image found in observation dict!")
            
            # 状态处理
            state = obs_dict.get("observation.state")
            if state is not None:
                if isinstance(state, __import__('numpy').ndarray):
                    state = torch.from_numpy(state).float()
                elif isinstance(state, list):
                    state = torch.tensor(state).float()
                state = state.to(device)
                if state.ndim == 1:
                    state = state.unsqueeze(0)
            
            # 语言token
            task_text = obs_dict.get("task", "complete the task")
            if isinstance(task_text, (list, tuple)):
                task_text = task_text[0] if task_text else "complete the task"
            task_text = str(task_text)
            
            result = {}
            if img is not None:
                result["observation.image"] = img
            if state is not None:
                result["observation.state"] = state
            
            if tokenizer is not None and ps.policy is not None:
                max_len = getattr(ps.policy.config, 'tokenizer_max_length', 48)
                encoded = tokenizer(task_text, return_tensors="pt", 
                                   padding="max_length", max_length=max_len, truncation=True)
                result[OBS_LANGUAGE_TOKENS] = encoded["input_ids"].to(device)
                result[OBS_LANGUAGE_ATTENTION_MASK] = encoded["attention_mask"].to(torch.bool).to(device)
            
            return result
        
        return custom_preprocessor
    
    def stop_server(self):
        """停止gRPC服务"""
        if not self.state.running:
            return
        
        self._log_info("正在停止服务...")
        try:
            if self._grpc_server:
                self._grpc_server.stop(2)
            self.state.running = False
            self.state.model_loaded = False
            self._policy_server = None
            self._grpc_server = None
            torch.cuda.empty_cache()
            self._log_ok("服务已停止")
        except Exception as e:
            self._log_err(f"停止失败: {e}")
    
    def get_status(self) -> dict:
        """获取状态快照"""
        return {
            "running": self.state.running,
            "model_loaded": self.state.model_loaded,
            "host": self.state.host,
            "port": self.state.port,
            "inference_count": self.state.inference_count,
            "last_time": self.state.last_inference_time,
            "error": self.state.error_message,
        }
