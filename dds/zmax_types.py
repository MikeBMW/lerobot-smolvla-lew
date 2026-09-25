#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 Z-MAX 三端消息中间件 —— DDS 数据模型（OMG DDS 风格, 用 Cyclone DDS）

老倪 2026-09-25: "ecs 4060 mac 消息中间件用DDS技术实现"

三端角色:
  · 4060 (静静/工作端)  → 发布 HardwareState(含 CUDA GPU) / TrainProgress ; 订阅 DeployCommand
  · Mac  (小芳/备份端)   → 发布 HardwareState(含 **MPS**)              ; 订阅 DeployCommand
  · ECS  (公网中转/汇聚) → 订阅全部 + 发布 DeployCommand

话题（4 个, 全部带 QoS）:
  zmax/hw_state      HardwareState   (RELIABLE, KEEP_LAST 1)   硬件实际值
  zmax/train_prog    TrainProgress   (RELIABLE, KEEP_LAST 1)   训练进度(真实)
  zmax/deploy_cmd    DeployCommand   (RELIABLE, KEEP_ALL)      部署/回滚指令
  zmax/heartbeat     Heartbeat       (BEST_EFFORT, KEEP_LAST 1) 节点存活

设计原则（与既有系统一致）:
  · 字段命名 = 物理量 + 单位（避免歧义: util_pct / mem_used_mb / power_w）
  · 缺测项用 -1.0 明确表示"未测到", 不用 0 冒充（0 是合法实测值）
  · 每个字段都能从真实数据源取到（nvidia-smi / sysctl / torch.backends.mps / 训练进度文件）
"""
from dataclasses import dataclass, field

from cyclonedds.idl import IdlStruct
from cyclonedds.idl.types import float64, int32, sequence   # ★ 该版本无 string 类型: IDL string 用 Python 内置 str


@dataclass
class HardwareState(IdlStruct, typename="zmax::HardwareState"):
    """硬件实际值（三端统一; 未测到的项 = -1.0, 不用 0 冒充）"""
    node: str = ""              # 主机名
    role: str = ""              # 工作端(4060) / 备份端(Mac) / 中转(ECS)
    backend: str = ""           # cuda / mps / cpu
    device_name: str = ""       # GPU 型号 或 Apple 芯片名
    ts: float64 = 0.0              # 采集时间戳(epoch 秒)
    # GPU / MPS
    util_pct: float64 = -1.0       # 利用率 %
    mem_used_mb: float64 = -1.0    # 显存/统一内存 已用
    mem_total_mb: float64 = -1.0   # 显存/统一内存 总量
    temp_c: float64 = -1.0         # 温度 °C
    power_w: float64 = -1.0        # 功耗 W
    clk_mhz: float64 = -1.0        # 时钟 MHz
    # 系统
    cpu_cores: int32 = -1
    cpu_util_pct: float64 = -1.0
    load1: float64 = -1.0
    mem_total_gb: float64 = -1.0
    mem_avail_gb: float64 = -1.0
    disk_total_gb: float64 = -1.0
    disk_free_gb: float64 = -1.0
    # 算力
    train_steps_per_s: float64 = -1.0
    note: str = ""              # 说明（如"本机 GPU 不报功耗上限"/"未装 torch"）


@dataclass
class TrainProgress(IdlStruct, typename="zmax::TrainProgress"):
    """训练进度（真实: 由训练脚本逐 N 步写出的进度文件驱动）"""
    node: str = ""
    job: str = ""               # 作业名
    layer: str = ""             # L4 / L4moe / L2 ...
    step: int32 = -1
    total: int32 = -1
    pct: float64 = -1.0
    loss: float64 = -1.0
    steps_per_s: float64 = -1.0
    best_obs: float64 = -1.0       # 留出集最佳观测 MAE
    best_act: float64 = -1.0
    gain_obs_pct: float64 = -1.0   # 相对平凡基线的提升 %
    gain_act_pct: float64 = -1.0
    running: int32 = 0             # 1=训练中 0=已停
    ts: float64 = 0.0


@dataclass
class DeployCommand(IdlStruct, typename="zmax::DeployCommand"):
    """部署指令（晋级/回滚; 带发起人与审计字段）"""
    issuer: str = ""            # 发起人/机器
    layer: str = ""             # 目标层
    artifact: str = ""          # 产物目录/文件
    action: str = ""            # promote / rollback / stop_train
    note: str = ""
    ts: float64 = 0.0


@dataclass
class Heartbeat(IdlStruct, typename="zmax::Heartbeat"):
    """节点存活"""
    node: str = ""
    role: str = ""
    alive: int32 = 1
    ts: float64 = 0.0
    extra: sequence[str] = field(default_factory=list)
