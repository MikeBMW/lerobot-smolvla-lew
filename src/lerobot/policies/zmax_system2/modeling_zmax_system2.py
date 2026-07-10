"""
Z-MAX Sys-2 · 云端 Agent 框架

Hermes Agent 封装，调度大参数模型(VTLA/GROOT/...)
接收仿真数据反馈，通过 skills 动态加载推理引擎
"""
from __future__ import annotations
import json
import torch
import numpy as np
from typing import Optional, Callable
from dataclasses import dataclass, field


@dataclass
class SimFeedback:
    """仿真数据反馈包 (ROS2 → Sys-2)"""
    camera_rgb: np.ndarray          # [3, 512, 512] RGB图像
    force_torque: np.ndarray        # [6] 力/力矩
    tactile: np.ndarray             # [16] 触觉阵列
    joint_states: np.ndarray        # [14] 关节角度
    gripper_pos: float              # 夹爪位置 (0-255)
    timestamp: float                # 时间戳
    
    def to_tensor(self, device='cpu'):
        return {
            'images': torch.from_numpy(self.camera_rgb).float().to(device),
            'force': torch.from_numpy(self.force_torque).float().to(device),
            'tactile': torch.from_numpy(self.tactile).float().to(device),
            'state': torch.from_numpy(self.joint_states).float().to(device),
        }


class Sys2Agent:
    """
    Z-MAX Sys-2 · 云端大模型调度
    
    架构:
      Hermes Agent (skills调度)
      ├── skill:zmax-vtla    → 完整VTLA推理 (VLM+FlowMatching)
      ├── skill:zmax-groot   → GROOT大模型推理
      ├── skill:zmax-act     → ACT轻量推理 (fallback)
      └── skill:zmax-plan    → 任务规划 (LLM)
    
    仿真交互:
      接收 SimFeedback → 选择模型 → 返回动作/规划
    """
    
    def __init__(self, device='cuda'):
        self.device = device
        self._skills: dict[str, Callable] = {}
        self._models: dict[str, object] = {}
        self._feedback_buffer: list[SimFeedback] = []
        
        # 注册默认skills
        self._register_skills()
    
    def _register_skills(self):
        """注册 Hermes Skills"""
        self._skills = {
            'zmax-act': self._run_act,
            'zmax-vtla': self._run_vtla,
            'zmax-groot': self._run_groot,
            'zmax-plan': self._run_plan,
        }
    
    # ═══ 仿真数据接口 ═══
    
    def receive_feedback(self, sim_data: SimFeedback) -> dict:
        """
        接收仿真数据反馈
        
        Args:
            sim_data: 来自 ROS2 仿真节点的传感器数据
            
        Returns:
            {'action': np.ndarray, 'plan': dict, 'model_used': str}
        """
        self._feedback_buffer.append(sim_data)
        
        # 任务类型判断
        task = self._classify_task(sim_data)
        
        # 选择模型
        model_name = self._select_model(task)
        
        # 推理
        result = self._skills[model_name](sim_data)
        
        return {
            **result,
            'model_used': model_name,
            'task_type': task,
        }
    
    def _classify_task(self, sim: SimFeedback) -> str:
        """根据传感器数据判断任务类型"""
        # 简单规则: 根据力信号判断
        if np.abs(sim.force_torque).max() < 1.0:
            return 'pick_place'     # 取放 → ACT
        elif np.abs(sim.force_torque[2:]).max() > 5.0:
            return 'insertion'       # 插拔 → smolvla
        else:
            return 'complex'         # 复杂 → VTLA/GROOT
    
    def _select_model(self, task: str) -> str:
        """任务 → 模型映射"""
        mapping = {
            'pick_place': 'zmax-act',
            'insertion':  'zmax-vtla',
            'complex':    'zmax-groot',
            'planning':   'zmax-plan',
        }
        return mapping.get(task, 'zmax-act')
    
    # ═══ Skills 实现 ═══
    
    def _run_act(self, sim: SimFeedback) -> dict:
        """ACT 推理 (52M, 8.4ms)"""
        try:
            from lerobot.policies.act.modeling_act import ACTPolicy
            if 'act' not in self._models:
                self._models['act'] = ACTPolicy.from_pretrained(
                    'lerobot/act_aloha_sim_transfer_cube_human'
                ).to(self.device).eval()
            
            model = self._models['act']
            tensors = sim.to_tensor(self.device)
            action = model.select_action({
                'observation.images.top': tensors['images'].unsqueeze(0),
                'observation.state': tensors['state'].unsqueeze(0),
            })
            return {'action': action.cpu().numpy(), 'plan': {}}
        except Exception as e:
            return {'action': np.zeros(14), 'plan': {'error': str(e)}}
    
    def _run_vtla(self, sim: SimFeedback) -> dict:
        """VTLA 完整版推理 (450M, ~215ms, 需云端GPU)"""
        try:
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
            if 'vtla' not in self._models:
                self._models['vtla'] = SmolVLAPolicy.from_pretrained(
                    'lerobot/smolvla_base'
                ).to(self.device).eval()
            
            tensors = sim.to_tensor(self.device)
            batch = {
                'observation.state': tensors['state'].unsqueeze(0),
                'observation.images.camera1': tensors['images'].unsqueeze(0),
                'task': ['execute insertion task'],
            }
            action = self._models['vtla'].select_action(batch)
            return {'action': action.cpu().numpy(), 'plan': {}}
        except Exception as e:
            # Fallback to ACT
            return self._run_act(sim)
    
    def _run_groot(self, sim: SimFeedback) -> dict:
        """GROOT 大模型推理 (HuggingFace skill)"""
        return {
            'action': np.zeros(14),
            'plan': {'status': 'GROOT skill 待加载 Hermes'},
        }
    
    def _run_plan(self, sim: SimFeedback) -> dict:
        """LLM 任务规划"""
        return {
            'action': np.zeros(14),
            'plan': {
                'steps': ['approach', 'grasp', 'insert', 'release'],
                'estimated_time': 3.5,
            },
        }
    
    # ═══ gRPC 桥接 (小芳仿真 ↔ Sys-2) ═══
    
    def start_grpc_server(self, port=50051):
        """启动 gRPC 服务，接收仿真数据"""
        # TODO: 完整 gRPC 实现
        # 见 hermes_gateway_mac/simulation_server.py
        pass
    
    def connect_to_simulation(self, host='192.168.23.10', port=50051):
        """连接 Orin 仿真节点"""
        # TODO: gRPC client 实现
        pass
