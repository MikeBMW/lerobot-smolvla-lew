# Z\-MAX 产品迭代技术路线与代码开发指南

本文档定义了 Z\-MAX 智蜂多模态动作专家从 Phase 0 到 Phase 4 的完整技术迭代路线，每个 Phase 对应一个独立的 LeRobot 策略包，指导代码开发工作。



---



## 一、迭代阶段总览



|Phase|技术等级|名称|核心能力|技术范式|对应系统|
|---|---|---|---|---|---|
|**Phase 0**|**L2**|人工编排原子功能|Unit Action Space \+ 标准原子功能库|分段式人工编排（运行，非训练）|系统0|
|**Phase 1**|**L3**|端到端VTLA|视触觉语言动作模型|端到端VLA（ACT/Diffusion）|系统1|
|**Phase 2**|**L3\+**|潜空间泛化|Z潜空间压缩 \+ 跨型号泛化 \+ 端侧部署|潜空间VLA|系统11|
|**Phase 3**|**L4**|空间感知闭环|3D空间感知 \+ 场景引导 \+ 认知闭环|空间感知VLA|系统12|
|**Phase 4**|**L4\+**|可选增强模块|JEPA世界模型 / 3DGS / 视听融合|世界模型增强|系统12\+|





## 二、目录结构



```Plain Text
src/lerobot/policies/zmax_policies/
├── __init__.py                          # 统一注册入口
├── README.md                            # 本文档
│
├── phase0_unit_action/                  # Phase 0 (L2): 人工编排原子功能
│   ├── __init__.py
│   ├── configuration.py
│   ├── modeling.py                      # 运行引擎（非训练）
│   ├── processor.py
│   └── README.md
│
├── phase1_zmax_vtla/                    # Phase 1 (L3): 端到端VTLA
│   ├── __init__.py
│   ├── configuration.py
│   ├── modeling.py
│   ├── processor.py
│   └── README.md
│
├── phase2_zmax_latent/                  # Phase 2 (L3+): 潜空间泛化 + 端侧部署
│   ├── __init__.py
│   ├── configuration.py
│   ├── modeling.py
│   ├── processor.py
│   └── README.md
│
├── phase3_zmax_spatial/                 # Phase 3 (L4): 空间感知 + 场景引导 + 认知闭环
│   ├── __init__.py
│   ├── configuration.py
│   ├── modeling.py
│   ├── processor.py
│   └── README.md
│
├── phase4_zmax_optional/                # Phase 4 (L4+): 可选增强模块
│   ├── __init__.py
│   ├── configuration.py
│   ├── modeling.py
│   ├── processor.py
│   └── README.md
│
├── zmax_configs/                        # YAML配置
│   ├── phase0_unit_action.yaml
│   ├── phase1_vtla.yaml
│   ├── phase2_latent.yaml
│   ├── phase3_spatial.yaml
│   └── phase4_optional.yaml
│
└── zmax_scripts/                        # 运行/训练脚本
    ├── run_phase0.py                    # Phase 0: 运行编排（非训练）
    ├── train_phase1.py                  # Phase 1: 训练VTLA
    ├── train_phase2.py                  # Phase 2: 训练潜空间
    ├── train_phase3.py                  # Phase 3: 训练空间感知
    ├── train_phase4.py                  # Phase 4: 训练可选增强
    └── inference.py                     # 通用推理脚本
```





## 三、各 Phase 详细定义



### Phase 0 \(L2\): 人工编排原子功能



**策略名：** `zmax_unit_action`



#### 3\.1 技术定位



建立标准原子功能库，通过人工编排实现光模块插拔全流程自动化操作，作为后续端到端模型的数据来源和基线参考。



> **⚠️ 关键说明：Phase 0 是“运行（Run）”而非“训练（Train）”。** 本阶段不涉及模型参数学习，而是通过人工编排的原子动作序列直接驱动机器人执行任务。原子功能库中的每个原子动作（如 `grasp_pick`、`insert_evb` 等）是预先编程的确定性控制逻辑，不包含可训练参数。Phase 0 的任务是验证产线流程的可行性，并为 Phase 1 的端到端模型采集训练数据。
> 
> 



#### 3\.2 操作流程



```Plain Text
取料 → 扫码识别 → 插入EVB → 等待测试 → 拔出模块 → AOI检测 → P/F分类 → 摆放
```



#### 3\.3 核心模块



|模块|功能|接口类型|
|---|---|---|
|AtomicActionLibrary|标准原子功能库|标准接口|
|ActionOrchestrator|人工编排引擎|流程配置|
|UnitActionSpace|单元动作空间|标准化动作编码|



#### 3\.4 配置文件



```Python
# phase0_unit_action/configuration.py
from dataclasses import dataclass
from lerobot.configs.policies import PreTrainedConfig

@PreTrainedConfig.register_subclass("zmax_unit_action")
@dataclass
class UnitActionConfig(PreTrainedConfig):
    """Phase 0 (L2): 人工编排原子功能配置"""
    
    # 原子功能库配置
    atomic_actions: list = None  # ["grasp_pick", "scan_code", ...]
    
    # 工作流编排
    workflow_sequence: list = None
    
    # Unit Action Space
    unit_action_dim: int = 12
    
    # 动作间通信接口
    interface_standard: str = "ROS2"
```



#### 3\.5 运行代码



```Python
# phase0_unit_action/modeling.py
from lerobot.policies.pretrained import PreTrainedPolicy
from .configuration import UnitActionConfig

class UnitActionPolicy(PreTrainedPolicy):
    """
    Phase 0 (L2): 人工编排原子功能
    
    注意：本策略不包含可训练参数，仅通过预定义的原子动作序列
    驱动机器人执行任务。适合作为产线流程验证和数据采集基线。
    """
    config_class = UnitActionConfig
    name = "zmax_unit_action"
    
    def __init__(self, config: UnitActionConfig, dataset_stats=None):
        super().__init__(config, dataset_stats)
        self.config = config
        self._build_atomic_library()
        self._build_orchestrator()
    
    def _build_atomic_library(self):
        """构建标准原子功能库"""
        self.atomic_library = {
            "grasp_pick": AtomicAction("grasp_pick", self.config.unit_action_dim),
            "scan_code": AtomicAction("scan_code", self.config.unit_action_dim),
            "insert_evb": AtomicAction("insert_evb", self.config.unit_action_dim),
            "wait_test": AtomicAction("wait_test", self.config.unit_action_dim),
            "pull_out": AtomicAction("pull_out", self.config.unit_action_dim),
            "aoi_inspect": AtomicAction("aoi_inspect", self.config.unit_action_dim),
            "pf_classify": AtomicAction("pf_classify", self.config.unit_action_dim),
            "place": AtomicAction("place", self.config.unit_action_dim),
        }
    
    def _build_orchestrator(self):
        """构建人工编排引擎"""
        self.orchestrator = ActionOrchestrator(
            sequence=self.config.workflow_sequence,
            atomic_lib=self.atomic_library
        )
    
    def forward(self, batch):
        """执行原子动作序列（运行模式）"""
        return self.orchestrator.execute(batch)
    
    def forward(self, batch):
        """执行原子动作序列（运行模式）"""
        return self.orchestrator.execute(batch)
```



#### 3\.6 运行脚本



```Python
# zmax_scripts/run_phase0.py
"""
Phase 0 (L2): 运行人工编排原子功能

使用方式:
    python zmax_scripts/run_phase0.py --config zmax_configs/phase0_unit_action.yaml
"""

import argparse
from lerobot.policies.zmax_policies.phase0_unit_action import UnitActionPolicy
from lerobot.environments import make_env

def run_phase0(config_path):
    # 加载配置
    config = load_config(config_path)
    
    # 创建策略（无训练参数）
    policy = UnitActionPolicy(config)
    
    # 创建环境
    env = make_env(config.env)
    
    # 执行编排流程
    obs = env.reset()
    for step in range(config.max_steps):
        action = policy.forward(obs)
        obs, reward, done, info = env.step(action)
        if done:
            break
    
    print("Phase 0 流程执行完成")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True)
    args = parser.parse_args()
    run_phase0(args.config)
```





### Phase 1 \(L3\): 端到端VTLA



**策略名：** `zmax_vtla`



#### 3\.1 技术定位



基于 VTLA（视觉\-触觉\-语言\-动作）多模态模型，建立从“感知”到“动作”的端到端执行能力，融合视觉与力觉反馈，完成高精度插拔基础动作。



#### 3\.2 核心模块



|模块|功能|技术选型|
|---|---|---|
|Vision Encoder|视觉特征提取|SigLIP / DINOv2|
|Tactile Encoder|触觉特征编码|结构化触觉编码器|
|Language Encoder|语言指令理解|SmolLM2|
|Action Expert|动作生成|Diffusion Transformer|



#### 3\.3 配置文件



```Python
# phase1_zmax_vtla/configuration.py
@PreTrainedConfig.register_subclass("zmax_vtla")
@dataclass
class ZMaxVTLAPolicyConfig(PreTrainedConfig):
    """Phase 1 (L3): 端到端VTLA配置"""
    
    # 多模态编码器
    vision_encoder: str = "siglip"  # siglip / dinov2
    tactile_encoder: str = "tactile_encoder"
    language_model: str = "smollm2"
    
    # 动作专家
    action_expert_type: str = "diffusion"  # diffusion / act
    
    # 尺寸参数
    vision_dim: int = 768
    tactile_dim: int = 128
    language_dim: int = 512
    action_dim: int = 7
    
    # 动作块参数
    horizon: int = 16
    n_action_steps: int = 8
```



#### 3\.4 模型代码



```Python
# phase1_zmax_vtla/modeling.py
class ZMaxVTLAPolicy(PreTrainedPolicy):
    """Phase 1 (L3): 端到端VTLA"""
    config_class = ZMaxVTLAPolicyConfig
    name = "zmax_vtla"
    
    def __init__(self, config, dataset_stats=None):
        super().__init__(config, dataset_stats)
        # 多模态编码器
        self.vision_encoder = SigLIPVisionEncoder()
        self.tactile_encoder = TactileEncoder()
        self.language_encoder = SmolLM2Encoder()
        # 动作专家
        self.action_expert = DiffusionTransformer(
            vision_dim=config.vision_dim,
            tactile_dim=config.tactile_dim,
            language_dim=config.language_dim,
            action_dim=config.action_dim
        )
    
    def forward(self, batch):
        # 多模态特征提取
        vis_feat = self.vision_encoder(batch["images"])
        tac_feat = self.tactile_encoder(batch["tactile"])
        lang_feat = self.language_encoder(batch["instruction"])
        # 生成动作块
        return self.action_expert(vis_feat, tac_feat, lang_feat)
```



#### 3\.5 训练脚本



```Python
# zmax_scripts/train_phase1.py
"""
Phase 1 (L3): 训练端到端VTLA

使用方式:
    python zmax_scripts/train_phase1.py --config zmax_configs/phase1_vtla.yaml
"""

import argparse
from lerobot.policies.zmax_policies.phase1_zmax_vtla import ZMaxVTLAPolicy
from lerobot.training import Trainer

def train_phase1(config_path):
    config = load_config(config_path)
    
    # 创建策略
    policy = ZMaxVTLAPolicy(config)
    
    # 创建训练器
    trainer = Trainer(policy, config)
    
    # 开始训练
    trainer.train()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True)
    args = parser.parse_args()
    train_phase1(args.config)
```





### Phase 2 \(L3\+\): 潜空间泛化 \+ 端侧部署



**策略名：** `zmax_latent`



#### 3\.1 技术定位



构建 Z 潜空间，对基础模型动作特征进行压缩和泛化，实现“一脑多能”，将泛化能力迁移至多型号模块（QSFP/OSFP/SFP）。通过端侧优化与量化压缩，支持边缘设备低延迟推理。



#### 3\.2 核心模块



|模块|功能|新增能力|
|---|---|---|
|Latent Encoder|潜空间压缩|动作特征降维|
|Latent Interpolator|潜空间插值|跨型号迁移泛化|
|Quantization|端侧量化|INT8/INT4压缩|
|ModelType Adapter|型号适配|QSFP/OSFP/SFP切换|



#### 3\.3 配置文件



```Python
# phase2_zmax_latent/configuration.py
@PreTrainedConfig.register_subclass("zmax_latent")
@dataclass
class ZMaxLatentPolicyConfig(ZMaxVTLAPolicyConfig):
    """Phase 2 (L3+): 潜空间泛化配置"""
    
    # 继承 Phase 1 配置
    inherit: str = "zmax_vtla"
    
    # 潜空间参数
    latent_dim: int = 128
    latent_encoder_type: str = "vae"  # vae / contrastive
    
    # 型号适配
    supported_models: list = None  # ["QSFP", "OSFP", "SFP"]
    model_type_adapter_dim: int = 32
    
    # 端侧部署
    quantization_method: str = "int8"  # int8 / int4 / fp16
    calibration_data: str = None
    
    # 潜空间插值
    latent_interpolator: str = "linear"  # linear / spline
```



#### 3\.4 模型代码



```Python
# phase2_zmax_latent/modeling.py
class ZMaxLatentPolicy(ZMaxVTLAPolicy):
    """Phase 2 (L3+): 潜空间泛化 + 端侧部署"""
    config_class = ZMaxLatentPolicyConfig
    name = "zmax_latent"
    
    def __init__(self, config, dataset_stats=None):
        super().__init__(config, dataset_stats)
        # 潜空间编码器
        self.latent_encoder = LatentEncoder(
            input_dim=config.hidden_dim,
            latent_dim=config.latent_dim
        )
        # 型号适配器
        self.model_adapter = ModelTypeAdapter(
            latent_dim=config.latent_dim,
            adapter_dim=config.model_type_adapter_dim,
            num_models=len(config.supported_models)
        )
        # 量化器
        self.quantizer = Quantizer(
            method=config.quantization_method
        )
    
    def forward(self, batch):
        # Phase 1 特征提取
        base_features = super().get_base_features(batch)
        # 潜空间压缩
        latent_z = self.latent_encoder(base_features)
        # 型号适配泛化
        if self.training and batch.get("model_type"):
            latent_z = self.model_adapter(latent_z, batch["model_type"])
        return self.action_expert(latent_z)
```



#### 3\.5 训练脚本



```Python
# zmax_scripts/train_phase2.py
"""
Phase 2 (L3+): 训练潜空间泛化 + 端侧部署

使用方式:
    python zmax_scripts/train_phase2.py --config zmax_configs/phase2_latent.yaml
"""
```





### Phase 3 \(L4\): 空间感知 \+ 场景引导 \+ 认知闭环



**策略名：** `zmax_spatial`



#### 3\.1 技术定位



引入场景引导模型，联合扩展 Z 潜空间的空间理解能力。系统从执行者升级为主动具身智能，融合全域场景信息与触觉反馈，实现认知级插拔策略。



#### 3\.2 核心模块



|模块|功能|新增能力|
|---|---|---|
|Spatial Encoder|3D空间感知编码|场景几何理解|
|Scene Guidance Model|场景引导推理|空间先验注入|
|Latent Joint Extender|潜空间联合扩展|动作\-空间对齐|
|Cognitive Planner|认知规划器|自主决策闭环|



#### 3\.3 配置文件



```Python
# phase3_zmax_spatial/configuration.py
@PreTrainedConfig.register_subclass("zmax_spatial")
@dataclass
class ZMaxSpatialPolicyConfig(ZMaxLatentPolicyConfig):
    """Phase 3 (L4): 空间感知 + 场景引导 + 认知闭环"""
    
    # 继承 Phase 2 配置
    inherit: str = "zmax_latent"
    
    # 空间感知
    spatial_encoder_type: str = "3d_encoder"
    spatial_input_dim: int = 512
    spatial_output_dim: int = 128
    
    # 场景引导
    scene_guidance_type: str = "transformer"  # transformer / graph
    num_guidance_heads: int = 8
    
    # 潜空间联合扩展
    fused_dim: int = 256
    joint_extender_type: str = "cross_attention"
    
    # 认知闭环
    cognitive_planner: bool = True
    planning_horizon: int = 32
```



#### 3\.4 模型代码



```Python
# phase3_zmax_spatial/modeling.py
class ZMaxSpatialPolicy(ZMaxLatentPolicy):
    """Phase 3 (L4): 空间感知 + 场景引导 + 认知闭环"""
    config_class = ZMaxSpatialPolicyConfig
    name = "zmax_spatial"
    
    def __init__(self, config, dataset_stats=None):
        super().__init__(config, dataset_stats)
        # 空间感知编码器
        self.spatial_encoder = SpatialEncoder(
            input_dim=config.spatial_input_dim,
            output_dim=config.spatial_output_dim
        )
        # 场景引导模型
        self.scene_guidance = SceneGuidanceModel(
            latent_dim=config.latent_dim,
            num_heads=config.num_guidance_heads
        )
        # 潜空间联合扩展
        self.latent_joint_extender = LatentJointExtender(
            action_dim=config.latent_dim,
            spatial_dim=config.spatial_output_dim,
            fused_dim=config.fused_dim
        )
        # 认知规划器
        if config.cognitive_planner:
            self.cognitive_planner = CognitivePlanner(
                latent_dim=config.fused_dim,
                horizon=config.planning_horizon
            )
    
    def forward(self, batch):
        # Phase 2 潜空间特征
        latent_action = super().get_latent_features(batch)
        # 空间感知编码
        spatial_features = self.spatial_encoder(batch["3d_scene"])
        # 场景引导
        guided_latent = self.scene_guidance(latent_action, spatial_features)
        # 潜空间联合扩展
        fused_latent = self.latent_joint_extender(latent_action, guided_latent)
        return self.action_expert(fused_latent)
```



#### 3\.5 训练脚本



```Python
# zmax_scripts/train_phase3.py
"""
Phase 3 (L4): 训练空间感知 + 场景引导 + 认知闭环

使用方式:
    python zmax_scripts/train_phase3.py --config zmax_configs/phase3_spatial.yaml
"""
```





### Phase 4 \(L4\+\): 可选增强模块



**策略名：** `zmax_spatial_plus`



#### 3\.1 技术定位



提供 JEPA 世界模型、3DGS 场景重建、视听融合等可选增强模块，通过配置文件开关灵活启用，实现 L4 基础能力的可插拔式增强。



#### 3\.2 可选模块



|模块|功能|激活参数|
|---|---|---|
|JEPA 世界模型|潜空间未来状态预测|`use_jepa: true`|
|3DGS 场景重建|三维高斯泼溅场景建模|`use_3dgs: true`|
|视听融合|音频信号处理与融合|`use_audio: true`|
|自监督预训练|无标签数据预训练|`use_ssl: true`|



#### 3\.3 配置文件



```Python
# phase4_zmax_optional/configuration.py
@PreTrainedConfig.register_subclass("zmax_spatial_plus")
@dataclass
class ZMaxSpatialPlusPolicyConfig(ZMaxSpatialPolicyConfig):
    """Phase 4 (L4+): 可选增强模块"""
    
    # 继承 Phase 3 配置
    inherit: str = "zmax_spatial"
    
    # 可选模块开关
    use_jepa: bool = False
    use_3dgs: bool = False
    use_audio: bool = False
    use_ssl: bool = False
    
    # JEPA 参数
    jepa_prediction_horizon: int = 16
    jepa_latent_dim: int = 256
    
    # 3DGS 参数
    gaussian_num_splats: int = 100000
    gaussian_rendering_resolution: int = 512
    
    # 视听融合参数
    audio_encoder_dim: int = 128
```



#### 3\.5 训练脚本



```Python
# zmax_scripts/train_phase4.py
"""
Phase 4 (L4+): 训练可选增强模块

使用方式:
    # 基础训练
    python zmax_scripts/train_phase4.py --config zmax_configs/phase4_optional.yaml
    
    # 启用 JEPA
    python zmax_scripts/train_phase4.py --config zmax_configs/phase4_optional.yaml --policy.use_jepa true
"""
```





## 四、配置 YAML 文件



### Phase 0 \(L2\): `zmax_configs/phase0_unit_action.yaml`



```YAML
# Phase 0 (L2): 人工编排原子功能（运行模式）
policy:
  type: zmax_unit_action
  unit_action_dim: 12
  workflow_sequence:
    - grasp_pick
    - scan_code
    - insert_evb
    - wait_test
    - pull_out
    - aoi_inspect
    - pf_classify
    - place
  interface_standard: ROS2

env:
  env_type: real_robot  # real_robot / simulation
  max_steps: 100

dataset:
  repo_id: lerobot/zmax_optical_module  # 仅用于数据采集
```



### Phase 1 \(L3\): `zmax_configs/phase1_vtla.yaml`



```YAML
# Phase 1 (L3): 端到端VTLA
policy:
  type: zmax_vtla
  vision_encoder: siglip
  tactile_encoder: tactile_encoder
  language_model: smollm2
  action_expert_type: diffusion
  vision_dim: 768
  tactile_dim: 128
  language_dim: 512
  action_dim: 7
  horizon: 16
  n_action_steps: 8

dataset:
  repo_id: lerobot/zmax_optical_module

training:
  steps: 100000
  batch_size: 16
  optimizer:
    lr: 1e-4
```



### Phase 2 \(L3\+\): `zmax_configs/phase2_latent.yaml`



```YAML
# Phase 2 (L3+): 潜空间泛化 + 端侧部署
policy:
  type: zmax_latent
  inherit: zmax_vtla
  latent_dim: 128
  latent_encoder_type: vae
  supported_models:
    - QSFP
    - OSFP
    - SFP
  model_type_adapter_dim: 32
  quantization_method: int8
  latent_interpolator: linear

dataset:
  repo_id: lerobot/zmax_optical_module_multi_model

training:
  steps: 80000
  batch_size: 16
```



### Phase 3 \(L4\): `zmax_configs/phase3_spatial.yaml`



```YAML
# Phase 3 (L4): 空间感知 + 场景引导 + 认知闭环
policy:
  type: zmax_spatial
  inherit: zmax_latent
  spatial_encoder_type: 3d_encoder
  spatial_input_dim: 512
  spatial_output_dim: 128
  scene_guidance_type: transformer
  num_guidance_heads: 8
  fused_dim: 256
  cognitive_planner: true
  planning_horizon: 32

dataset:
  repo_id: lerobot/zmax_optical_module_spatial

training:
  steps: 120000
  batch_size: 8
```



### Phase 4 \(L4\+\): `zmax_configs/phase4_optional.yaml`



```YAML
# Phase 4 (L4+): 可选增强模块
policy:
  type: zmax_spatial_plus
  inherit: zmax_spatial
  use_jepa: false
  use_3dgs: false
  use_audio: false
  use_ssl: false
  jepa_prediction_horizon: 16
  jepa_latent_dim: 256

dataset:
  repo_id: lerobot/zmax_optical_module_spatial

training:
  steps: 150000
  batch_size: 8
```



```YAML
# Phase 4 (L4+) 启用 JEPA 版本
# 使用: --config zmax_configs/phase4_optional_jepa.yaml
policy:
  inherit: zmax_configs/phase4_optional.yaml
  use_jepa: true
  jepa_prediction_horizon: 16
```





## 五、使用方式



### Phase 0 \(L2\): 运行（非训练）



```Bash
# 运行人工编排流程
python zmax_scripts/run_phase0.py --config zmax_configs/phase0_unit_action.yaml
```



### Phase 1\-4: 训练



```Bash
# Phase 1 (L3): 端到端VTLA
lerobot-train --policy.type zmax_vtla --config zmax_configs/phase1_vtla.yaml

# Phase 2 (L3+): 潜空间泛化
lerobot-train --policy.type zmax_latent --config zmax_configs/phase2_latent.yaml

# Phase 3 (L4): 空间感知闭环
lerobot-train --policy.type zmax_spatial --config zmax_configs/phase3_spatial.yaml

# Phase 4 (L4+): 可选增强（启用JEPA）
lerobot-train --policy.type zmax_spatial_plus --config zmax_configs/phase4_optional.yaml --policy.use_jepa true
```



### 推理（通用）



```Bash
# 推理
python zmax_scripts/inference.py --policy.type zmax_spatial --checkpoint ./outputs/phase3
```





## 六、迭代关系图



```Plain Text
┌─────────────────────────────────────────────────────────────────────┐
│                        Phase 4 (L4+)                               │
│  zmax_spatial_plus — JEPA世界模型 / 3DGS / 视听融合                 │
│  (通过配置文件开关启用可选模块)                      训练 ✓          │
│          ▼                                                         │
├─────────────────────────────────────────────────────────────────────┤
│                      Phase 3 (L4)                                  │
│  zmax_spatial — 空间感知 + 场景引导 + 潜空间联合扩展 + 认知闭环      │
│  新增：SpatialEncoder / SceneGuidance / CognitivePlanner  训练 ✓  │
│          ▼                                                         │
├─────────────────────────────────────────────────────────────────────┤
│                      Phase 2 (L3+)                                 │
│  zmax_latent — Z潜空间压缩 + 跨型号泛化 + 端侧部署                  │
│  新增：LatentEncoder / Quantizer / ModelTypeAdapter     训练 ✓    │
│          ▼                                                         │
├─────────────────────────────────────────────────────────────────────┤
│                       Phase 1 (L3)                                 │
│  zmax_vtla — VTLA多模态 + 端到端精细插拔                           │
│  新增：Vision/Tactile/Language Encoder + Action Expert   训练 ✓   │
│          ▼                                                         │
├─────────────────────────────────────────────────────────────────────┤
│                       Phase 0 (L2)                                 │
│  zmax_unit_action — 人工编排原子功能 + Unit Action Space           │
│  基线：原子功能库 + 编排引擎                         运行 ✓（非训练）│
└─────────────────────────────────────────────────────────────────────┘
```





## 七、开发检查清单



### Phase 0 \(L2\) —— 运行模式（无训练）

* [ ] 定义标准原子功能库（8个原子动作）

* [ ] 实现 Unit Action Space 标准化接口

* [ ] 实现人工编排引擎（支持流程配置）

* [ ] 实现动作间标准通信协议

* [ ] 与真实产线设备联调验证

* [ ] 数据采集功能验证（为 Phase 1 准备）

    

### Phase 1 \(L3\)

* [ ] 实现 SigLIP 视觉编码器

* [ ] 实现结构化触觉编码器

* [ ] 实现 Diffusion Transformer 动作专家

* [ ] 实现多模态特征融合模块

* [ ] 端到端训练管线搭建

* [ ] 真实场景插拔任务验证（成功率≥90%）

    

### Phase 2 \(L3\+\)

* [ ] 实现潜空间编码器

* [ ] 实现跨型号适配器（QSFP/OSFP/SFP）

* [ ] 实现潜空间插值泛化

* [ ] 实现 INT8 量化与端侧优化

* [ ] 端侧部署推理延迟验证（\<50ms）

    

### Phase 3 \(L4\)

* [ ] 实现 3D 空间感知编码器

* [ ] 实现场景引导模型

* [ ] 实现潜空间联合扩展

* [ ] 实现认知规划器

* [ ] L4 级认知闭环验证（成功率≥95%）

    

### Phase 4 \(L4\+\)

* [ ] 实现 JEPA 世界模型增强

* [ ] 实现 3DGS 场景重建

* [ ] 实现视听融合

* [ ] 配置文件开关机制

* [ ] L4\+ 增强效果验证

    

    

## 八、解耦与标准化要点



1. **继承复用**：每个 Phase 继承上一 Phase 的能力，仅新增差异化模块

2. **配置驱动**：通过 YAML 配置文件控制各 Phase 参数，无需修改代码

3. **版本独立**：各 Phase 独立维护，互不影响

4. **工厂组装**：`zmax_factory/` 负责按配置动态组装模型

5. **标准接口**：各模块遵循 LeRobot 标准接口规范

    

---



**文档版本：** v1\.1  

**最后更新：** 2026\-07\-03  

**维护者：** Z\-MAX 研发团队

