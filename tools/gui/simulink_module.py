#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX Simulink 模式 · GUI 控制台引擎
对标 Simulink 交互: 0帧起手 → 模块库拖拽 → 连线 → 双击参数 → 运行/单步/停止
与 Web comfyui.html 共用 simulink-spec.md v1.0 节点规范 (JSON 完全一致)
"""
import json, math, random, time, os, sys, glob
from PyQt5.QtCore import Qt, QRectF, QPointF, QTimer, pyqtSignal, QLineF, QThread
from PyQt5.QtGui import (QPainter, QPainterPath, QPainterPathStroker, QColor, QPen, QBrush, QFont,
                         QPolygonF, QLinearGradient, QRadialGradient, QKeySequence)
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView,
                             QGraphicsScene, QGraphicsItem, QGraphicsObject,
                             QLabel, QPushButton, QToolButton, QFrame, QSpinBox,
                             QDoubleSpinBox, QComboBox, QLineEdit, QDialog,
                             QFormLayout, QTextEdit, QScrollArea, QMenu,
                             QMessageBox, QSplitter, QDialogButtonBox,
                             QMdiArea, QMdiSubWindow)

# 🆕 节点逻辑库 (node_logic.py — 每个节点背后的可编辑逻辑, ✏️ 可修改区)
_GUI_DIR = os.path.dirname(os.path.abspath(__file__))
if _GUI_DIR not in sys.path:
    sys.path.insert(0, _GUI_DIR)
import node_logic
from node_logic_dialog import NodeLogicDialog

# ════════════════════════════════════════════════════════════════
# 规范常量 (与 simulink-spec.md / web comfyui.html 完全一致)
# ════════════════════════════════════════════════════════════════
NODE_TYPES = {
    "condition": {"cn": "条件", "color": "#a371f7"},
    "data":      {"cn": "数据", "color": "#58a6ff"},  # 📊 数据节点 (2026-08-09: 数据集/采集/回传)
    "model":     {"cn": "模型", "color": "#58a6ff"},
    "action":    {"cn": "动作", "color": "#00d4aa"},
    "system":    {"cn": "系统", "color": "#d4a800"},
    "hardware":  {"cn": "硬件", "color": "#ff4444"},
    "switch":    {"cn": "路由", "color": "#f0a030"},  # Simulink Switch 块: 数据源选择
    "train_gate": {"cn": "训练开关", "color": "#3fb950"},  # ☑ 训练使能开关 (2026-08-05 老倪: checkbox 打勾=训练)
    "yolo_gate":  {"cn": "YOLO开关", "color": "#d4a800"},  # 🎯 YOLO 感知开关 (2026-08-06 老倪: state 输入 switch, 默认开=39D)
    "coord_overlay": {"cn": "坐标叠加", "color": "#58a6ff"},  # 🧩 结构条件 (2026-08-08 老倪: 坐标逻辑主线, 图像背景)
    "row_bg":    {"cn": "背景行", "color": "#3a3f4b"},   # 🎨 Model Zoo: 整行彩色背景 + 左侧大字模型名 (可编辑/改名/改色)
    "pdf_report": {"cn": "PDF报告", "color": "#1f6feb"}, # 📄 Model Zoo技术选型报告生成 (2026-08-05 老倪)
    "skill":     {"cn": "原子技能", "color": "#00d4aa"},  # 🧩 原子技能 (2026-08-09 老倪: W²-VLA Token — 拖入画布→连结构条件→SYS1→action)
    "scene":     {"cn": "场景", "color": "#ff9f43"},     # 🏭 场景 (2026-08-09 老倪: 插拔/搬运/光学检测 — 点击打开 ECS 链接 + 建场景节点链)
}
COLORS = {t: v["color"] for t, v in NODE_TYPES.items()}
DH = 50  # 节点高度 (与 web 一致)

# 工作流分区 (对标 MathWorks 解决方案页 6 大功能) → 节点类型映射
WORKFLOW_TYPES = {
    "data":     "hardware",   # ① 访问·标注数据: Orin/MAC/相机/数据集
    "scene":    "system",     # ② 仿真场景: 调度/工作流/场景
    "plan":     "model",      # ③ 规划·控制: VLA/ACT/SmolVLA 策略
    "percept":  "condition",  # ④ 感知算法: 条件/触发/AOI/力控
    "deploy":   "model",      # ⑤ 部署: 远程推理/4090/代码生成
    "test":     "action",     # ⑥ 集成·测试: 原子动作/工位测试
}
# 参考应用模板 (对标 MathWorks 参考应用列表)
REFERENCE_APPS = [
    # 🎛 CICD 主控台: 全链路主要节点, 双击节点即可运行/切换 (老倪 2026-08-02 需求:
    # "控制台是主控点, 能看到CICD全局, 在node上要有所有链路主要node, 要能运行;
    #  既要有metaworld数据, 又要有Orin, 又要有ACT模型, 可随意切换如何训练")
    ("🎛 CICD 主控台", [
        ("train_gate", "☑ 训练开关", {"train_enabled": True,
                                      "desc": "checkbox: 打勾=训练 / 不打=不训练 · 双击切换"}),
        # 🎛 2026-08-08 老倪: 每模型训练开关 (放最前端 — YOLO开关位置, 用户感知开始即开/关)
        ("train_gate", "ACT 训练开关", {"train_enabled": True, "policy": "act", "desc": "ACT 训练: 开/关 · 双击切换"}),
        ("train_gate", "SmolVLA 训练开关", {"train_enabled": True, "policy": "smolvla", "desc": "SmolVLA 训练: 开/关 · 双击切换"}),
        ("train_gate", "SmolVLA+LEW 训练开关", {"train_enabled": True, "policy": "smolvla_lew", "desc": "SmolVLA+LEW 训练: 开/关 · 双击切换"}),
        ("train_gate", "VLA-Touch 训练开关", {"train_enabled": True, "policy": "vla_touch", "desc": "VLA-Touch 训练: 开/关 · 双击切换"}),
        ("train_gate", "AWE 训练开关", {"train_enabled": True, "policy": "awe_zflow", "desc": "AWE 训练: 开/关 · 双击切换"}),
        ("train_gate", "MLP蒸馏 训练开关", {"train_enabled": True, "policy": "expert_mlp", "desc": "MLP蒸馏 训练: 开/关 · 双击切换"}),
        ("train_gate", "官方专家 训练开关", {"train_enabled": True, "policy": "expert_policy", "desc": "官方专家 训练: 开/关 · 双击切换"}),
        ("hardware", "📥 Orin 数据源", {"ip": "192.168.23.10", "fps": 30, "source": "orin",
                                        "desc": "真实产线数据"}),
        ("hardware", "📦 metaworld_peg", {"steps": 4000, "source": "metaworld",
                                           "desc": "占位集·管道验证"}),
        ("switch", "🔀 Switch 数据源", {"switch": "orin", "desc": "双击切换 Orin/metaworld"}),
        ("model", "🧠 ACT 训练", {"steps": 4000, "chunk_size": 7, "dim_model": 256,
                                  "desc": "双击运行训练 (lerobot_train)"}),
        ("condition", "✅ 模型验证", {"strict": True, "desc": "双击运行验证 (validate_flow)"}),
        ("action", "📦 集成打包", {"target": "ECS", "desc": "双击上传 ECS (cicd_deploy push)"}),
        ("hardware", "🚚 部署 Orin", {"target": "192.168.23.10", "desc": "双击查部署状态"}),
    ], [(1, 3), (2, 3), (3, 0), (0, 4), (4, 5), (5, 6), (6, 7)]),
    # (2026-08-06 老倪: 参考应用条按钮太多没用 — 删除旧演示模板
    #  「⚙️ CI/CD 默认流水线」+「📦 取料·100G 闭环」; 保留 11 个有效模板)
    ("🎛 力控插入·Z700", [
        ("hardware", "机械臂", {"model": "Z700", "dof": 6}),
        ("condition", "C01 到位判断", {"tolerance": 0.01}),
        ("model", "VLA-T", {"remote": "4090:50054"}),
        ("action", "A04 力控插入", {"force": 3.0}),
    ], [(0, 1), (1, 2), (2, 3)]),
    ("📡 数据闭环·Orin→4090", [
        ("hardware", "Orin Nano", {"ip": "192.168.23.10", "fps": 30}),
        ("hardware", "MAC", {"ip": "192.168.23.1", "port": 8769}),
        ("hardware", "4090训练", {"host": "39.102.211.79", "port": 50054}),
        ("model", "H-JEPA", {"remote": "4090"}),
    ], [(0, 1), (1, 2), (2, 3)]),
    ("🏭 AOI检测·分拣", [
        ("hardware", "相机", {"res": "480x640", "fps": 30}),
        ("condition", "C04 AOI通过", {}),
        ("model", "SmolVLA", {"checkpoint": "smolvla-500m"}),
        ("action", "A09 AOI检测", {}),
        ("action", "A10 分拣", {"bin": 3}),
    ], [(0, 1), (1, 2), (2, 3), (3, 4)]),
    # 🧠 ACT-Meta 全新训练: 用 metaworld 数据训练 ACT, 模型按官方源码拆成 7 子模块
    # (2026-08-04 老倪: "在simulink功能页, 做一个用metaworld数据, 全新训练ACT的模型, 用simulink的模块搭建")
    # Action Head 适配 metaworld 4D 输出 (action_dim=4, 真机 6D 对比标注)
    ("🧠 ACT-Meta 全新训练", [
        ("hardware", "📦 metaworld_peg", {"source": "metaworld", "frames": 4800, "active": True,
                                           "dims": "4D/4D", "desc": "states 4D · actions 4D (sawyer 关节)"}),
        ("model", "🖼 视觉主干 ResNet18", {"backbone": "resnet18", "pretrained": True,
                                          "desc": "官方 ACT.backbone → layer4 特征图 (B,C,H,W)"}),
        ("model", "🚫 VAE 编码器（无）", {"use_vae": False, "latent_dim": 32,
                                        "desc": "官方 ACT.vae_encoder → 潜变量分布 (μ,logσ²)"}),
        ("model", "🔤 Transformer Encoder", {"n_layers": 4, "dim_model": 256, "n_heads": 8,
                                            "desc": "官方 ACT.encoder → 上下文 tokens (latent+state+图像)"}),
        ("model", "🔡 Transformer Decoder", {"n_layers": 4, "chunk_size": 7, "n_heads": 8,
                                            "desc": "官方 ACT.decoder → DETR queries 解码动作块"}),
        ("action", "🎯 Action Head 4D", {"action_dim": 4, "chunk_size": 7,
                                        "desc": "★适配 metaworld: 输出 (B,7,4) · 真机 Orin 为 6D"}),
        ("condition", "⏳ Temporal Ensemble", {"coeff": 0.01,
                                              "desc": "官方 ACTTemporalEnsembler → 动作块时间平滑"}),
        ("system", "🚀 全新训练", {"steps": 4000, "desc": "双击 → on_train (metaworld 占位集, 全新不续训)"}),
        ("action", "📊 Scope 示波器", {"desc": "双击 → 示波器: 训练 loss 曲线/执行效果 (Simulink Scope 对标)"}),
    ], [(0, 1), (1, 3), (0, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8)]),
    # 🎛 顶层总系统 (2026-08-08 老倪: 总系统节点标准化 — Subsystem 双击展开「🔬 Model Zoo」)
    ("🎛 顶层总系统", [
        ("hardware", "📦 metaworld_peg", {"source": "metaworld", "frames": 4800, "active": True,
                                           "dims": "4D/4D", "shared": True,
                                           "desc": "顶层输入: 统一 metaworld 数据集 (4800帧)"}),
        ("system", "🔬 总系统", {"subsystem": "🏗 三层总系统", "type_label": "Subsystem",
                                            "desc": "Simulink 子系统: 双击展开 → 三层系统 (SYS2 数据+GPU / SYS1 Model Zoo / SYS0 硬件)"}),
        ("system", "📊 对比评估 Scope (仿真)", {"shared": True,
                                        "desc": "顶层输出: 双击 → Model Zoo图表 · 🎮 仿真评估 (metaworld 环境)"}),
    ], [
        (0, 1, "数据"), (1, 2, "评估"),
    ],
    # 顶层布局: 单行三节点 (数据 → 总系统 → Scope)
    [
        ["📦 metaworld_peg", "🔬 总系统", "📊 对比评估 Scope (仿真)"],
    ]),
    # 🏗 三层总系统 (2026-08-09 老倪重写: 删全部功能块 — 只表达 SYS2 云端训练 → 部署 → SYS1)
    #   System 2 = 云端训练引擎; 训练好的模型部署到 System 1 动作系统
    ("🏗 三层总系统", [
        ("system", "🖥 SYS2 云端训练", {"layer": "sys2",
                                       "desc": "System 2 云端训练: 4090 GPU 引擎 — 训练 ACT/SmolVLA 等模型 (模型引擎容器化)"}),
        ("system", "🧠 SYS1 动作系统", {"layer": "sys1",
                                       "desc": "System 1 动作系统: 接收部署的模型 — 端侧执行精细操作"}),
    ], [
        (0, 1, "部署"),
    ],
    # 两行横排: SYS2 顶(云端训练) → SYS1 底(动作系统) — 部署链路
    [
        ["🖥 SYS2 云端训练", "", "", ""],
        ["🧠 SYS1 动作系统", "", "", ""],
    ]),
    # 🏗 Z-MAX 架构总览 (2026-08-08 老倪: system2/sys12/sys11/sys0 迁移到 simulink 模块库)
    # 三行横排 (老倪架构布局: SYS2 云端训练(顶) → SYS1含SYS11 VLA-T+SYS12 Z-Flow(中) → SYS0 红底(底))
    ("🏗 Z-MAX 架构", [
        ("system", "🖥 SYS2 云端训练", {"desc": "云端训练 · 4090 · 大模型训练/部署 (Z-MAX 架构顶层)"}),
        ("system", "🧠 SYS12 引导系统", {"desc": "SYS12 引导系统 · Z-Flow 数据流引擎 (SYS1 层, 与 SYS11 并列)"}),
        ("system", "🖐 SYS11 动作系统", {"desc": "SYS11 动作系统 · VLA-T 触觉大模型 (SYS1 层, 与 SYS12 并列)"}),
        ("system", "🔧 SYS0 硬件驱动", {"desc": "硬件驱动 + 原子功能 (Z-MAX 架构底层)"}),
    ], [
        (0, 1), (0, 2), (1, 3), (2, 3),
    ],
    # 三行横排布局: SYS2 顶行 / SYS12+SYS11 中行 / SYS0 底行
    [
        ["🖥 SYS2 云端训练", "", "", ""],
        ["", "🧠 SYS12 引导系统", "🖐 SYS11 动作系统", ""],
        ["", "", "🔧 SYS0 硬件驱动", ""],
    ]),
    # 🔬 Model Zoo (2026-08-05 老倪: "把 ACT SmolVLA smolvla+lew VLA-Touch AWE 5个模型
    #   放到一起, 纵向对比" — 技术选型终极画布)
    # 模块划分: ♻ 2 共用 (metaworld数据 / 对比评估 Scope / 推理效果对比) + 五模型分支
    #   ACT 7 (ResNet18→Encoder→Decoder→ActionHead→Ensemble→训练·无VAE)
    #   SmolVLA 4 (SmolVLM2→DiT-B→ActionHead→训练, 无 LEW)
    #   SmolVLA+LEW 5 (SmolVLM2→DiT-B→LeWorldModel→ActionHead→训练)
    #   VLA-Touch 6 (DINOv2→Marker→DiT-B base VLA→ActionHead→Interpolant→训练)
    #   AWE 6 (SigLIP视触觉→H-JEPA三层潜空间→zFlow世界引擎→未来决策交叉注意力→ActionHead→训练)
    # 布局: 每行一个模型; 同构模块同列垂直对齐 (视觉编码列/动作生成列/附加列/Action Head列/训练列)
    ("🔬 Model Zoo", [
        ("hardware", "📦 metaworld_peg", {"source": "metaworld", "frames": 4800, "active": True,
                                           "dims": "39D/4D", "shared": True,
                                           "desc": "♻ 七模型共用: 统一 metaworld 数据集 (peg-v6, state 39D 完整观测, action 4D)"}),
        # ── YOLO 感知前端 (2026-08-06 老倪: YOLO 加所有模型最前端, 自动标注+真机感知) ──
        ("train_gate", "🎯 YOLO 感知开关", {"yolo_enabled": True, "state_dim": 39,
                                          "desc": "state 输入 switch: 开=39D(YOLO检测产出, 含销钉/孔坐标) / 关=3D(仅末端) · 默认开"}),
        # 🧩 结构条件 (2026-08-08 老倪: 简化 — 5 个合并为 1 个共享, 放公共感知链)
        ("coord_overlay", "🧩 结构条件", {"gate": 0.5, "state_dim": 39, "dim_mode": "concat", "shared": True,
                                        "desc": "♻ 坐标叠加 (七模型共用): 坐标逻辑主线(state 含销钉/孔坐标) 叠加图像背景特征; 训练注入, 推理可剥离 (双击改 gate/state_dim)"}),
        ("model", "🎯 YOLO 目标检测", {"model": "yolov8s", "classes": "peg/hole/hand", "shared": True,
                                     "desc": "♻ 感知前端 (真机必需): 相机图像 → YOLO 检测销钉/插孔/末端 2D框 → 3D坐标。仿真=模拟器直给39D(等价完美YOLO)"}),
        ("condition", "📐 2D→3D 解算", {"intrinsics": "camera_K", "method": "depth|hand-eye",
                                      "desc": "♻ 坐标解算: YOLO 2D框中心 + 深度/单目标定 → 目标 3D 坐标 → 拼入 39D state"}),
        ("model", "🔌 State Adapter", {"in_dim": 39, "out_dim": 39, "normalize": True,
                                      "desc": "state 适配器 (2026-08-06 老倪): YOLO 3D检测输出(目标坐标+置信度) → 统一 state 格式。开=39D含目标坐标, 关=3D仅末端, 适配各策略输入维度", "shared": True}),
        # ── ACT 分支 (7) ──
        ("model", "🖼 视觉主干 ResNet18", {"backbone": "resnet18", "pretrained": True,
                                          "desc": "ACT.backbone → layer4 特征图 (B,C,H,W)"}),
        ("model", "🚫 VAE 编码器（无）", {"use_vae": False, "latent_dim": 32,
                                        "desc": "ACT.vae_encoder → 潜变量分布 (μ,logσ²)"}),
        ("model", "🔤 Transformer Encoder", {"n_layers": 4, "dim_model": 256, "n_heads": 8,
                                            "desc": "ACT.encoder → 上下文 tokens (latent+state+图像)"}),
        ("model", "🔡 Transformer Decoder", {"n_layers": 4, "chunk_size": 7, "n_heads": 8,
                                            "desc": "ACT.decoder → DETR queries 解码动作块"}),
        ("model", "🎯 Action Head 4D · ACT", {"action_dim": 4, "chunk_size": 7,
                                              "desc": "ACT 专用: 输出 (B,7,4)"}),
        ("condition", "⏳ Temporal Ensemble", {"coeff": 0.01,
                                              "desc": "ACTTemporalEnsembler → 动作块时间平滑 (仅 ACT 用)"}),
        ("system", "🚀 ACT 训练", {"policy": "act", "steps": 4000,
                                  "desc": "双击 → on_train(policy=act) · metaworld 训练"}),
        # ── SmolVLA 纯动作分支 (4, 无 LEW) ──
        ("model", "🧠 SmolVLM2-500M", {"freeze": True,
                                       "smolvlm": "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
                                       "desc": "SmolVLA 视觉语言主干 (冻结, 多模态编码)"}),
        ("model", "🌀 DiT-B 动作解码", {"hidden": 256, "layers": 1, "timesteps": 2,
                                       "desc": "SmolVLA action_model DiT-B → 动作去噪生成 (无世界模型)"}),
        ("model", "🎯 Action Head 4D · SmolVLA", {"action_dim": 4, "chunk_size": 7,
                                                  "desc": "SmolVLA 纯动作版: 输出 (B,7,4) · 无 LEW"}),
        ("system", "🚀 SmolVLA 训练", {"policy": "smolvla", "steps": 4000,
                                      "desc": "双击 → on_train(policy=smolvla) · 纯动作, 无 LeWorldModel"}),
        # ── SmolVLA+LEW 分支 (5, 串行世界模型) ──
        ("model", "🧠 SmolVLM2-500M · LEW", {"freeze": False,
                                             "smolvlm": "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
                                             "desc": "SmolVLA 视觉语言主干 (参与训练 — LEW 要求 VLM 不冻结)"}),
        ("model", "🌀 DiT-B 动作解码 · LEW", {"hidden": 256, "layers": 1, "timesteps": 2,
                                              "desc": "SmolVLA action_model DiT-B → 动作去噪生成"}),
        ("model", "🌐 LeWorldModel", {"lew_loss_weight": 0.1, "num_video_frames": 2,
                                      "desc": "世界模型旁路: 输入=视频帧+动作 (官方 forward(videos,actions)), SigLIP 编码→AdaLN-zero 条件调制→预测下一帧; 与 DiT-B 并列, 非串行"}),
        ("model", "🎯 Action Head 4D · SmolVLA+LEW", {"action_dim": 4, "chunk_size": 7,
                                                      "desc": "SmolVLA+LEW 专用: 输出 (B,7,4)"}),
        ("system", "🚀 SmolVLA+LEW 训练", {"policy": "smolvla_lew", "steps": 4000,
                                          "desc": "双击 → on_train(policy=smolvla_lew) · 冻结关 + 世界模型开"}),
        # ── VLA-Touch 分支 (6) ──
        ("model", "🖼 DINOv2 视觉编码", {"backbone": "dinov2-small", "freeze": True,
                                        "desc": "官方 visual_encoder: 视觉嵌入条件 (22M 冻结)"}),
        ("condition", "📍 Marker 触觉跟踪", {"grid": "7x9", "dim": 4,
                                            "desc": "官方 marker_tracker: GelSight 标记位移 → 低维力信号 m"}),
        ("model", "🌀 DiT-B base VLA", {"hidden": 256, "layers": 1, "freeze": True,
                                        "desc": "base VLA 动作生成 (与 SmolVLA 同构, 冻结不训练)"}),
        ("model", "🎯 Action Head · VLA", {"action_dim": 4, "chunk_size": 7,
                                           "desc": "VLA 动作块 a_t → Interpolant 精炼输入"}),
        ("model", "🌉 Interpolant 控制器", {"diffuse_steps": 10, "hidden": 256,
                                           "desc": "官方 StochasticInterpolants: 桥式扩散精炼动作 (输入=VLA动作+视觉+触觉, 只训练此模块)"}),
        ("system", "🚀 VLA-Touch 训练", {"policy": "vla_touch", "steps": 4000,
                                        "desc": "双击 → on_train(policy=vla_touch) · 冻结 VLA 只训 Interpolant (4060 精简)"}),
        # ── AWE 分支 (6) ──
        ("model", "🖐 SigLIP 视触觉编码", {"backbone": "siglip-base", "freeze": True,
                                          "tactile_dim": 4, "force_dim": 3,
                                          "desc": "场景原生视触觉编码: SigLIP视觉 + 力觉/触觉 原生融合 (86M 冻结; ⚠️ metaworld 无真触觉, 力觉为状态差分模拟, 真机换 H06)"}),
        ("model", "🧠 H-JEPA 三层潜空间", {"d_z1": 128, "d_z2": 128, "d_z3": 64,
                                          "desc": "z₁空间/ z₂物体/ z₃语义 三层潜表示 (场景原生融合)"}),
        ("model", "🌊 zFlow 世界引擎", {"gru": 128, "layers": 1,
                                       "desc": "GRU 预测器: 潜空间推演未来状态/接触演化 (轻量)"}),
        ("model", "🔀 未来决策交叉注意力", {"gates": "1.0/0.1/0.01",
                                      "desc": "预测潜状态 K/V 注入动作解码 (分层门控; 推理可剥离)"}),
        ("model", "🎯 Action Head · AWE", {"action_dim": 4, "chunk_size": 7,
                                           "desc": "隐空间动作 → 真实动作"}),
        ("system", "🚀 AWE 训练", {"policy": "awe_zflow", "steps": 4000,
                                  "desc": "双击 → on_train(policy=awe_zflow) · 场景原生+zFlow 世界模型"}),
        # ── 评估 ──
        ("system", "📊 对比评估 Scope (仿真)", {"shared": True,
                                        "desc": "♻ 共用: 双击 → 五模型 训练速度/精确度/鲁棒性 对比图表 · 🎮 仿真评估 (metaworld, 非 Orin 真机)"}),
        ("system", "🎮 仿真推理对比", {"video": "all", "auto": True,
                                          "desc": "训练完自动触发: 🎮 本地仿真 rollout (metaworld 环境, 非 Orin 真机) 多窗口同步播放对比"}),
        # ── 5 个视频对比 node (2026-08-05 老倪: 推理效果对比之后, 每模型一个视频) ──
        ("system", "🎮 仿真视频 · ACT", {"video": True, "video_policy": "act",
                                          "desc": "🎮 ACT 仿真 rollout 视频 (metaworld 环境, 非 Orin 真机), 双击播放"}),
        ("system", "🎮 仿真视频 · SmolVLA", {"video": True, "video_policy": "smolvla",
                                              "desc": "🎮 SmolVLA 仿真 rollout 视频 (metaworld 环境, 非 Orin 真机), 双击播放"}),
        ("system", "🎮 仿真视频 · SmolVLA+LEW", {"video": True, "video_policy": "smolvla_lew",
                                                  "desc": "🎮 SmolVLA+LEW 仿真 rollout 视频 (metaworld 环境, 非 Orin 真机), 双击播放"}),
        ("system", "🎮 仿真视频 · VLA-Touch", {"video": True, "video_policy": "vla_touch",
                                                "desc": "🎮 VLA-Touch 仿真 rollout 视频 (metaworld 环境, 非 Orin 真机), 双击播放"}),
        ("system", "🎮 仿真视频 · AWE", {"video": True, "video_policy": "awe_zflow",
                                          "desc": "🎮 AWE 仿真 rollout 视频 (metaworld 环境, 非 Orin 真机), 双击播放"}),
        # ── 📄 PDF 技术选型报告 (2026-08-05 老倪: 报告含概况/分系统/接口/参数/架构/功能/性价比/优劣势) ──
        ("pdf_report", "📄 PDF 技术选型报告", {"auto": True,
                                             "desc": "双击生成 11 章技术选型 PDF: 实验概况·系统全貌·分系统功能·接口说明·参数对比·架构区别·功能分析·性价比·优势劣势·视频对比·结论"}),
        # ── MLP 蒸馏分支 (2026-08-07 老倪: MLP 强化学习入七模型画布; 蒸馏自官方专家) ──
        ("model", "📥 全观测编码 39D", {"in_dim": 39, "out_dim": 128,
                                        "desc": "39D 完整观测编码 (含 peg/孔 3D 坐标 — 五模型失败根因修复): 状态→128D 特征"}), 
        ("model", "🔗 全连接层 512·1", {"hidden": 512, "layers": 1,
                                        "desc": "BC 蒸馏 MLP: 128D 特征 → 4D 动作 (expert_mlp.pt)"}),
        ("model", "🎯 Action Head 4D · MLP", {"action_dim": 4, "chunk_size": 7,
                                              "desc": "MLP 蒸馏输出 (B,7,4) · 抓起18/20 插入11/20 (55%)"}),
        ("system", "🎓 专家蒸馏训练", {"policy": "expert_mlp", "steps": 300,
                                     "desc": "双击 → BC 蒸馏: 300 episodes 官方专家数据 → MLP (tools/distill_expert.py) · 学专家的插拔路径"}),
        # ── 官方专家基准分支 (🏆 真值锚点: 最好的真值, 让用户理解目标) ──
        ("condition", "🧭 位置控制律", {"method": "PD+前馈", "rate": "500Hz",
                                       "desc": "🏆 真值: metaworld 内置规则专家 — PD 位置控制律 (接近 peg→抓取→抬起→转移→插入)"}),
        ("condition", "🤏 夹爪状态机", {"states": "open→grasp→hold→release",
                                       "desc": "🏆 真值: 夹爪状态机 (接近→合拢→夹持→释放)"}),
        ("model", "🎯 Action Head 4D · 专家", {"action_dim": 4, "chunk_size": 7,
                                              "desc": "🏆 真值动作: 规则专家输出 · 抓起19/20 插入17/20 (85%) — 七模型最高基准"}),
        ("system", "📏 官方专家基准", {"policy": "expert_policy", "success": "85%",
                                     "desc": "🏆 真值锚点 (非训练): 85% 成功率参考基准 — 所有学习模型的目标; 双击=执行一次基准演示"}),
        # ── MLP/专家 视频对比 (2026-08-07) ──
        ("system", "🎮 仿真视频 · MLP", {"video": True, "video_policy": "expert_mlp",
                                        "desc": "🎮 MLP 蒸馏仿真 rollout 插拔成功视频 (metaworld, 非 Orin 真机; 抓起✅ 插入✅ 距孔 0.020m), 双击播放"}),
        ("system", "🎮 仿真视频 · 专家", {"video": True, "video_policy": "expert_policy",
                                        "desc": "🎮 官方专家仿真 rollout 插拔成功视频 (metaworld, 非 Orin 真机; 🏆 抓起✅ 插入✅ 距孔 0.011m, 85%), 双击播放"}),
        # ── 🎮 仿真推理节点 (2026-08-07 老倪: 训练右侧 = 仿真推理, 每个模型一个; 再右侧 = 仿真视频) ──
        ("system", "🎮 仿真推理 · ACT", {"video": True, "video_policy": "act", "infer": True,
                                        "desc": "🎮 ACT 本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"}),
        ("system", "🎮 仿真推理 · SmolVLA", {"video": True, "video_policy": "smolvla", "infer": True,
                                            "desc": "🎮 SmolVLA 本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"}),
        ("system", "🎮 仿真推理 · SmolVLA+LEW", {"video": True, "video_policy": "smolvla_lew", "infer": True,
                                                "desc": "🎮 SmolVLA+LEW 本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"}),
        ("system", "🎮 仿真推理 · VLA-Touch", {"video": True, "video_policy": "vla_touch", "infer": True,
                                              "desc": "🎮 VLA-Touch 本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"}),
        ("system", "🎮 仿真推理 · AWE", {"video": True, "video_policy": "awe_zflow", "infer": True,
                                        "desc": "🎮 AWE 本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"}),
        ("system", "🎮 仿真推理 · MLP", {"video": True, "video_policy": "expert_mlp", "infer": True,
                                        "desc": "🎮 MLP 蒸馏本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"}),
        ("system", "🎮 仿真推理 · 专家", {"video": True, "video_policy": "expert_policy", "infer": True,
                                        "desc": "🎮 官方专家本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"}),
        # ── 🧩 结构条件 (2026-08-08 老倪: 潜在空间叠加 — 每模型行一个, 在视觉主干后; 输入=state几何+模型latent → 输出=latent+叠加)
        ("coord_overlay", "🧩 结构条件 · ACT", {"gate": 0.5, "state_dim": 39, "dim_mode": "concat",
                                               "desc": "🧩 ACT 结构条件: latent += proj(state)×gate — 目标结构坐标(39D)叠加进潜空间, 图像作背景 (双击改 gate/state_dim)"}),
        ("coord_overlay", "🧩 结构条件 · SmolVLA", {"gate": 0.5, "state_dim": 39, "dim_mode": "concat",
                                                   "desc": "🧩 SmolVLA 结构条件: latent += proj(state)×gate — 目标结构坐标叠加进多模态embeds (双击改 gate/state_dim)"}),
        ("coord_overlay", "🧩 结构条件 · LEW", {"gate": 0.5, "state_dim": 39, "dim_mode": "concat",
                                               "desc": "🧩 SmolVLA+LEW 结构条件: latent += proj(state)×gate — 结构坐标叠加进多模态embeds (双击改 gate/state_dim)"}),
        ("coord_overlay", "🧩 结构条件 · VLA-Touch", {"gate": 0.5, "state_dim": 39, "dim_mode": "concat",
                                                     "desc": "🧩 VLA-Touch 结构条件: latent += proj(state)×gate — 结构坐标叠加进视觉嵌入 (双击改 gate/state_dim)"}),
        ("coord_overlay", "🧩 结构条件 · AWE", {"gate": 0.5, "state_dim": 39, "dim_mode": "concat",
                                               "desc": "🧩 AWE 结构条件: latent += proj(state)×gate — 结构坐标叠加进视触觉潜状态 (双击改 gate/state_dim)"}),
    ], [
        # 感知链 (2026-08-06 老倪修正: YOLO 只做 state 适配, 视频直接进各模型视觉 ViT):
        #   state 通道: 数据→YOLO开关→YOLO检测→2D→3D→StateAdapter→各模型 state 输入
        #   图像通道: 数据→各模型视觉主干 (ResNet18/SmolVLM2/DINOv2/SigLIP) 直接进, 不经 YOLO
        (0, 1, "图像"), (1, 3, "开=39D"), (3, 4, "2D框"), (4, 5, "3D坐标"),  # 感知链: 开关→YOLO→2D→3D→StateAdapter (共享🧩已下放)
        # ACT 路: 图像→ResNet18(6); State→🧩结构·ACT(59); 主干latent→🧩; latent+→Encoder(7)
        (0, 6, "图像"), (5, 59, "state39D"), (6, 59, "图像特征"), (59, 7, "latent+"), (7, 8), (8, 9), (9, 10), (10, 11),
        # SmolVLA 路: 图像→SmolVLM2(13); State→🧩结构·SmolVLA(60); latent+→DiT-B(14)
        (0, 13, "图像"), (5, 60, "state39D"), (13, 60, "多模态embeds"), (60, 14, "latent+"), (14, 15),
        # SmolVLA+LEW 路: 图像→SmolVLM2·LEW(17); State→🧩(61); latent+→DiT-B·LEW(19); LeWorldModel 旁路
        (0, 17, "图像"), (5, 61, "state39D"), (17, 61, "多模态embeds"), (61, 19, "latent+"), (19, 20),
        (0, 18, "视频+动作"), (18, 20, "世界预测"),
        # VLA-Touch 路: 图像→DINOv2(23); State→🧩(62); latent+→base VLA(24); Marker 触觉
        (0, 23, "图像"), (5, 62, "state39D"), (23, 62, "视觉嵌入"), (62, 24, "latent+"),
        (0, 22, "触觉图"), (21, 23, "视觉嵌入"), (21, 25, "视觉嵌入"), (22, 25, "触觉信号m"), (24, 25, "VLA动作a"),
        (25, 26, "精炼动作"),
        # AWE 路: 图像+力觉→SigLIP(28); State→🧩(63); latent+→H-JEPA(29)
        (0, 28, "图像+力觉"), (5, 63, "state39D"), (28, 63, "视触觉特征"), (63, 29, "latent+"),
        (29, 30, "未来潜状态"), (30, 31, "注入动作"), (31, 32, "动作"),
        # 评估: 五训练 → 对比 Scope
        (11, 33), (15, 33), (20, 33), (26, 33), (32, 33),
        # 推理对比: 五训练 → 推理对比节点
        (11, 34), (15, 34), (20, 34), (26, 34), (32, 34),
        # 视频对比: 五训练 → 各自视频节点 + 推理对比 → 5 视频节点 (2026-08-05 老倪)
        (11, 35, "rollout"), (15, 36, "rollout"), (20, 37, "rollout"),
        (26, 38, "rollout"), (32, 39, "rollout"),
        (34, 35), (34, 36), (34, 37), (34, 38), (34, 39),
        # PDF 报告: 5 视频节点 + Scope + 推理对比 → PDF (数据支撑: 曲线+视频+评估)
        (33, 40, "评估结果"), (34, 40, "推理对比"),
        (35, 40, "ACT视频"), (36, 40, "SmolVLA视频"), (37, 40, "SmolVLA+LEW视频"),
        (38, 40, "VLA-Touch视频"), (39, 40, "AWE视频"),
        # MLP 蒸馏路: StateAdapter(39D) → 全观测编码 → 全连接 → ActionHead·MLP → 蒸馏训练
        (4, 41, "state39D"), (41, 42, "特征"), (42, 43, "动作"), (43, 44, "MLP动作"),
        (44, 33, "MLP评估"), (44, 34, "MLP推理"), (44, 49, "rollout"),
        # 官方专家路: StateAdapter(39D) → 位置控制律 → 夹爪状态机 → ActionHead·专家 → 基准
        (4, 45, "state39D"), (45, 46, "控制量"), (46, 47, "动作"), (47, 48, "专家动作"),
        (48, 33, "专家评估"), (48, 34, "专家推理"), (48, 50, "rollout"),
        # 推理对比 → MLP/专家视频; 新视频 → PDF
        (34, 49), (34, 50),
        (49, 40, "MLP视频"), (50, 40, "专家视频"),
        # 🎮 仿真推理链 (2026-08-07 老倪: 训练→仿真推理→仿真视频, 每个模型对应)
        (11, 51, "仿真推理"), (15, 52, "仿真推理"), (20, 53, "仿真推理"),
        (26, 54, "仿真推理"), (32, 55, "仿真推理"), (44, 56, "仿真推理"), (48, 57, "仿真推理"),
        (51, 35, "rollout"), (52, 36, "rollout"), (53, 37, "rollout"),
        (54, 38, "rollout"), (55, 39, "rollout"), (56, 49, "rollout"), (57, 50, "rollout"),
    ],
    # 🗂 多行展开布局 (每行一个模型; 同构模块同列垂直对齐)
    # 列: 数据 | YOLO感知 | YOLO检测 | 2D→3D | StateAdapter | 输入编码 | 处理 | 附加 | Action Head | 训练/基准 | 仿真推理 | 仿真视频
    # 对齐约定 (2026-08-07): 列3=输入编码/主干 · 列7=Action Head · 列9=训练/基准 · 列10=🎮仿真推理 · 列11=🎮仿真视频(对应本行模型)
    [
        # 感知前端链 (共享): 数据→YOLO开关→YOLO检测→2D→3D→StateAdapter (🧩结构条件已下放到各模型行 latent 处)
        ["📦 metaworld_peg", "🎯 YOLO 感知开关", "🎯 YOLO 目标检测", "📐 2D→3D 解算", "🔌 State Adapter", "", "", "", "", "", "", ""],
        # ACT 行: 训练 → 🎮仿真推理·ACT → 🎮仿真视频·ACT
        ["📦 metaworld_peg", "🎯 YOLO 感知开关", "🔌 State Adapter", "🖼 视觉主干 ResNet18", "🧩 结构条件 · ACT", "🚫 VAE 编码器（无）", "🔤 Transformer Encoder", "🔡 Transformer Decoder", "🎯 Action Head 4D · ACT", "⏳ Temporal Ensemble", "🚀 ACT 训练", "🎮 仿真推理 · ACT", "🎮 仿真视频 · ACT"],
        # SmolVLA 纯动作行
        ["📦 metaworld_peg", "🎯 YOLO 感知开关", "🔌 State Adapter", "🧠 SmolVLM2-500M", "🧩 结构条件 · SmolVLA", "🌀 DiT-B 动作解码", "", "", "🎯 Action Head 4D · SmolVLA", "", "🚀 SmolVLA 训练", "🎮 仿真推理 · SmolVLA", "🎮 仿真视频 · SmolVLA"],
        # SmolVLA+LEW 行
        ["📦 metaworld_peg", "🎯 YOLO 感知开关", "🔌 State Adapter", "🧠 SmolVLM2-500M · LEW", "🧩 结构条件 · LEW", "🌀 DiT-B 动作解码 · LEW", "🌐 LeWorldModel", "", "🎯 Action Head 4D · SmolVLA+LEW", "", "🚀 SmolVLA+LEW 训练", "🎮 仿真推理 · SmolVLA+LEW", "🎮 仿真视频 · SmolVLA+LEW"],
        # VLA-Touch 行: 拓扑 ActionHead→Interpolant→训练, Marker→Interpolant (ActionHead 对齐列7)
        ["📦 metaworld_peg", "🎯 YOLO 感知开关", "🔌 State Adapter", "🖼 DINOv2 视觉编码", "🧩 结构条件 · VLA-Touch", "🌀 DiT-B base VLA", "📍 Marker 触觉跟踪", "", "🎯 Action Head · VLA", "🌉 Interpolant 控制器", "🚀 VLA-Touch 训练", "🎮 仿真推理 · VLA-Touch", "🎮 仿真视频 · VLA-Touch"],
        # AWE 行: 拓扑 zFlow→交叉注意力→ActionHead→训练
        ["📦 metaworld_peg", "🎯 YOLO 感知开关", "🔌 State Adapter", "🖐 SigLIP 视触觉编码", "🧩 结构条件 · AWE", "🧠 H-JEPA 三层潜空间", "🌊 zFlow 世界引擎", "🔀 未来决策交叉注意力", "🎯 Action Head · AWE", "", "🚀 AWE 训练", "🎮 仿真推理 · AWE", "🎮 仿真视频 · AWE"],
        # MLP 蒸馏行 (2026-08-07 老倪: MLP 强化学习入七模型画布)
        ["📦 metaworld_peg", "🎯 YOLO 感知开关", "🔌 State Adapter", "📥 全观测编码 39D", "🔗 全连接层 512·1", "", "", "🎯 Action Head 4D · MLP", "", "🎓 专家蒸馏训练", "🎮 仿真推理 · MLP", "🎮 仿真视频 · MLP"],
        # 官方专家行 (🏆 真值锚点: 最好的真值, 目标基准)
        ["📦 metaworld_peg", "", "", "🧭 位置控制律", "🤏 夹爪状态机", "", "", "🎯 Action Head 4D · 专家", "", "📏 官方专家基准", "🎮 仿真推理 · 专家", "🎮 仿真视频 · 专家"],
        # 评估行: 全模型仿真推理对比(列7) + Scope 对比图表(列10) + PDF 报告(最右列11, 2026-08-07 老倪)
        ["", "", "", "", "", "", "", "🎮 仿真推理对比", "", "", "📊 对比评估 Scope (仿真)", "📄 PDF 技术选型报告"],
    ]),
    # 🖐 VLA-Touch 触觉对比 (2026-08-05 老倪: "参考VLA-Touch项目, 4060资源有限要改造,
    #   纵向对比不同模型的区别, 用于技术选型" — github.com/jxbi1010/VLA-Touch, RA-L 2026)
    # 官方 Manipulation 层拓扑 (bridge_controller.py / bridge_model.py):
    #   base VLA π(a|s,I) 生成动作块 → Interpolant π_I(â|s,a,m) 用触觉精炼动作
    #   Interpolant 输入 = DINOv2 视觉嵌入 + GelSight marker 触觉信号 m + VLA 动作 a
    # 4060 精简: base VLA 冻结 (官方: without fine-tuning the base VLA) → 只训轻量控制器
    #   DINOv2-small 22M 冻结 · Marker 触觉 CV 轻量 · Interpolant MLP ~1M — 显存无忧
    # 模块划分: ♻ 2 共用 (metaworld数据 / 对比评估 Scope) + VLA-Touch 分支 7
    #   ①🖼 DINOv2 视觉 (官方 visual_encoder.py) ②📍 Marker 触觉跟踪 (marker_tracker.py)
    #   ③🌀 DiT-B base VLA (与 SmolVLA 同构, 冻结) ④🎯 Action Head (VLA 动作输出)
    #   ⑤🌉 Interpolant 触觉控制器 (bridge_model.py StochasticInterpolants)
    #   ⑥🚀 训练 (只训控制器) ⑦📊 对比评估 Scope (仿真) (共用)
    ("🖐 VLA-Touch 触觉对比", [
        ("hardware", "📦 metaworld_peg", {"source": "metaworld", "frames": 4800, "active": True,
                                           "dims": "4D/4D", "shared": True,
                                           "desc": "♻ 统一数据集 (训练/评估共用, 与其他模型同源可比)"}),
        ("model", "🖼 DINOv2 视觉编码", {"backbone": "dinov2-small", "freeze": True,
                                        "desc": "官方 visual_encoder: 视觉嵌入条件 (22M 冻结)"}),
        ("condition", "📍 Marker 触觉跟踪", {"grid": "7x9", "dim": 4,
                                            "desc": "官方 marker_tracker: GelSight 标记位移 → 低维力信号 m (⚠️ metaworld 无真触觉, 当前为状态差分模拟, 真机换 H06 力觉)"}), 
        ("model", "🌀 DiT-B base VLA", {"hidden": 256, "layers": 1, "freeze": True,
                                        "desc": "base VLA 动作生成 (与 SmolVLA 同构, 冻结不训练)"}),
        ("model", "🎯 Action Head · VLA", {"action_dim": 4, "chunk_size": 7,
                                           "desc": "VLA 动作块 a_t → Interpolant 精炼输入"}), 
        ("model", "🌉 Interpolant 控制器", {"diffuse_steps": 10, "hidden": 256,
                                           "desc": "官方 StochasticInterpolants: 桥式扩散精炼动作 (输入=VLA动作+视觉+触觉, 只训练此模块)"}),
        ("system", "🚀 VLA-Touch 训练", {"policy": "vla_touch", "steps": 4000,
                                        "desc": "双击 → on_train(policy=vla_touch) · 冻结 VLA 只训 Interpolant (4060 精简)"}),
        ("system", "📊 对比评估 Scope (仿真)", {"shared": True,
                                        "desc": "♻ 共用: 双击 → 多模型 训练速度/精确度/鲁棒性 对比图表"}),
    ], [
        # 官方 forward 数据流 (VLA/residual_controller):
        # 数据 → DINOv2 视觉 (0,1) · 数据 → Marker 触觉 (0,2) · 数据 → DiT-B (0,3)
        # DINOv2 视觉嵌入 → Interpolant 条件 (1,5) · Marker 触觉 m → Interpolant 条件 (2,5)
        # DiT-B → Action Head (3,4) · VLA 动作 a → Interpolant x0 (4,5)
        # Interpolant 精炼动作 → 训练 (5,6) · 训练 → 对比 Scope (6,7)
        (0, 1, "图像"), (0, 2, "触觉图"), (0, 3, "状态+指令"),
        (1, 5, "视觉嵌入"), (2, 5, "触觉信号m"), (3, 4, "动作块"), (4, 5, "VLA动作a"),
        (5, 6, "精炼动作"), (6, 7, "评估"),
    ],
    # 🗂 单行展开布局 (数据 → 双路感知 → VLA 动作 → Interpolant → 训练 → 评估)
    [
        ["📦 metaworld_peg", "🖼 DINOv2 视觉编码", "🌉 Interpolant 控制器", "🚀 VLA-Touch 训练", "📊 对比评估 Scope (仿真)"],
        ["", "📍 Marker 触觉跟踪", "🌀 DiT-B base VLA", "🎯 Action Head · VLA", ""],
    ]),
    # 🧿 AWE 场景原生对比 (2026-08-05 老倪: "增加它石的AWE模型, 同样原则要纵向对比,
    #   根据当前模块的抽象结构, 同构模型要纵向对比" — 它石智航 AWE 3.5/OmniVTA)
    # Z-MAX 场景原生路线 (老倪架构参考): 视觉·触觉·力觉·动作 场景级深度融合
    #   + zFlow 世界模型 (H-JEPA 三层潜空间: z₁空间/z₂物体/z₃语义 + GRU预测器
    #   + 未来决策交叉注意力, 门控 1.0/0.1/0.01)
    # 4060 精简: SigLIP-base 冻结 + 潜空间等比缩小 (256/256/128→128/128/64), 可训练≈15M
    # 模块划分: ♻ 2 共用 (metaworld数据 / 对比评估 Scope) + AWE 分支 6
    #   ①🖼 SigLIP 视觉 (与 VLA-Touch DINOv2 同列 — 视觉编码列) ②🧠 H-JEPA 三层潜空间
    #   ③🌊 zFlow 世界引擎 (GRU 预测器 — 世界模型列, 与 LEW ARPredictor / VLA-Touch
    #     Interpolant 同列对比) ④🔀 未来决策交叉注意力 ⑤🎯 Action Head (同列)
    #   ⑥🚀 训练 (同列) ⑦📊 对比评估 Scope (仿真) (共用)
    ("🧿 AWE 场景原生对比", [
        ("hardware", "📦 metaworld_peg", {"source": "metaworld", "frames": 4800, "active": True,
                                           "dims": "4D/4D", "shared": True,
                                           "desc": "♻ 统一数据集 (训练/评估共用, 与其他模型同源可比)"}),
        ("model", "🖐 SigLIP 视触觉编码", {"backbone": "siglip-base", "freeze": True,
                                          "tactile_dim": 4, "force_dim": 3,
                                          "desc": "场景原生视触觉编码: SigLIP视觉 + 力觉/触觉 原生融合 (86M 冻结, 非乐高拼接; ⚠️ metaworld 无真触觉, 力觉为状态差分模拟, 真机换 H06)"}),
        ("model", "🧠 H-JEPA 三层潜空间", {"d_z1": 128, "d_z2": 128, "d_z3": 64,
                                          "desc": "z₁空间/ z₂物体/ z₃语义 三层潜表示 (场景原生融合, 非乐高拼接)"}),
        ("model", "🌊 zFlow 世界引擎", {"gru": 128, "layers": 1,
                                       "desc": "GRU 预测器: 潜空间推演未来状态/接触演化 (轻量, 适合 Orin Nano)"}),
        ("model", "🔀 未来决策交叉注意力", {"gates": "1.0/0.1/0.01",
                                      "desc": "预测潜状态 K/V 注入动作解码 (分层门控; 推理可剥离零开销)"}),
        ("model", "🎯 Action Head · AWE", {"action_dim": 4, "chunk_size": 7,
                                           "desc": "隐空间动作 → 真实动作 (与其它模型 Action Head 同列)"}),
        ("system", "🚀 AWE 训练", {"policy": "awe_zflow", "steps": 4000,
                                  "desc": "双击 → on_train(policy=awe_zflow) · 场景原生+zFlow 世界模型 (4060 精简)"}),
        ("system", "📊 对比评估 Scope (仿真)", {"shared": True,
                                        "desc": "♻ 共用: 双击 → 多模型 训练速度/精确度/鲁棒性 对比图表"}),
    ], [
        # 官方数据流 (场景原生视触觉: 数据 → 视触觉编码/潜空间/世界引擎/注入/动作头 → 训练 → Scope)
        (0, 1, "图像+力觉"), (0, 2, "状态+力觉"), (1, 2, "视触觉特征"), (2, 3, "三层潜状态"),
        (3, 4, "未来潜状态"), (4, 5, "注入动作"), (5, 6, "动作"), (6, 7, "评估"),
    ],
    # 🗂 单行展开布局 (与 VLA-Touch 同构: 数据 → 视触觉编码 → 世界模型 → ActionHead → 训练 → 评估)
    [
        ["📦 metaworld_peg", "🖐 SigLIP 视触觉编码", "🧠 H-JEPA 三层潜空间", "🌊 zFlow 世界引擎", "🔀 未来决策交叉注意力", "🎯 Action Head · AWE", "🚀 AWE 训练", "📊 对比评估 Scope (仿真)"],
    ]),
    # 🎥 推理对比 (2026-08-05 老倪: "训练完后继续推理, 对比3个模型的推理效果,
    #   要有视频显示的node, 3个视频display窗口")
    # 数据 → 3 训练 → 3 视频显示 (双击任意视频节点 → 3 窗口同步播放推理效果)
    ("🎮 仿真推理对比", [
        ("hardware", "📦 metaworld_peg", {"source": "metaworld", "frames": 4800, "active": True,
                                           "dims": "4D/4D", "shared": True,
                                           "desc": "统一 metaworld 数据集 (训练 + 推理共用)"}),
        ("system", "🚀 ACT 训练", {"policy": "act", "steps": 4000,
                                    "desc": "训练 ACT (metaworld, 150步)"}),
        ("system", "🚀 SmolVLA 训练", {"policy": "smolvla", "steps": 4000,
                                        "desc": "训练 SmolVLA 纯动作 (metaworld, 150步)"}),
        ("system", "🚀 SmolVLA+LEW 训练", {"policy": "smolvla_lew", "steps": 4000,
                                            "desc": "训练 SmolVLA+LeWorldModel (metaworld, 150步)"}),
        ("system", "🎥 视频显示 · ACT", {"video": "act", "desc": "双击 → 3 窗口同步播放: ACT 推理效果 (metaworld push-v3 rollout)"}),
        ("system", "🎥 视频显示 · SmolVLA", {"video": "smolvla", "desc": "双击 → 3 窗口同步播放: SmolVLA 推理效果"}),
        ("system", "🎥 视频显示 · SmolVLA+LEW", {"video": "smolvla_lew", "desc": "双击 → 3 窗口同步播放: SmolVLA+LEW 推理效果"}),
    ], [
        (0, 1), (0, 2), (0, 3), (1, 4), (2, 5), (3, 6),
    ],
    [
        ["📦 metaworld_peg", "🚀 ACT 训练", "🎥 视频显示 · ACT"],
        ["", "🚀 SmolVLA 训练", "🎥 视频显示 · SmolVLA"],
        ["", "🚀 SmolVLA+LEW 训练", "🎥 视频显示 · SmolVLA+LEW"],
    ]),
]

# 模块库 (左侧拖拽面板) — 与 web comfyui.html 的模块组一致
LIBRARY = [
    # 🚀 Z700 工程完整模块组 (2026-08-12 老倪: Z700 画布全部节点 → 库中集中可找, 自动 VEH.5 编号)
    ("model", "🚀 Z700 工程 (插拔)", [
        {"name": "📦 metaworld_peg", "params": {"source": "metaworld", "frames": 4800, "active": True,
                                                "dims": "4D/4D", "source": "tools/gen_metaworld_data.py",
                                                "desc": "metaworld 插拔数据集: 39D+图像 4800帧, 喂感知+训练"}},
        {"name": "🎯 YOLO 3D", "params": {"model": "yolov8s", "classes": "peg/hole/hand", "yolo_enabled": True,
                                          "state_dim": 39, "source": "src/lerobot/policies/yolo_3d",
                                          "desc": "相机图像 → YOLO 检测销钉/插孔/末端 → 2D框 (mAP 0.994)"}},
        {"name": "📐 2D→3D 解算", "params": {"intrinsics": "camera_K", "method": "depth|hand-eye",
                                             "source": "src/lerobot/policies/yolo_3d",
                                             "desc": "YOLO 2D框中心 + 深度/标定 → 目标 3D 坐标 → 拼入 state"}},
        {"name": "🔌 State Adapter", "params": {"in_dim": 43, "out_dim": 43, "normalize": True,
                                                "source": "src/lerobot/policies/yolo_3d",
                                                "desc": "视觉39D + 触觉4D = 43D 统一输入 (喂双脑)"}},
        {"name": "📍 Marker 触觉跟踪", "params": {"grid": "7x9", "dim": 4, "tactile_dim": 4,
                                                 "source": "src/lerobot/policies/yolo_3d",
                                                 "desc": "GelSight 标记位移 → 4D 触觉力信号 (夹持/接触/滑觉)"}},
        {"name": "📊 43D obs 输入", "params": {"dims": 43, "source": "src/lerobot/policies/left_right",
                                              "desc": "统一状态输入: 感知链与策略的接口"}},
        {"name": "🧠 左脑 LeftBrainMLP", "params": {"source": "src/lerobot/policies/left_right",
                                                   "desc": "动作生成器 39D→4D; 偏置接近训练突破 0 成功率"}},
        {"name": "🧠 右脑 RightBrainWM", "params": {"source": "src/lerobot/policies/left_right",
                                                   "desc": "世界模型: 接触时机/阶段判断, contact 只喂状态机"}},
        {"name": "❖ 接触判定", "params": {"source": "src/lerobot/policies/left_right",
                                         "desc": "d_hp<0.06 且 contact>0.5 联合判定 → 夹持触发"}},
        {"name": "◉ LeftRightPolicy", "params": {"source": "src/lerobot/policies/left_right",
                                                 "desc": "双脑策略总控: 编排状态机与动作输出"}},
        {"name": "➤ 接近", "params": {"stage": "approach", "bias": "act*0.3 + hand→peg*2.0",
                                     "source": "src/lerobot/policies/left_right", "desc": "偏置接近 (5/8 vs 0/8)"}},
        {"name": "➤ 抓取", "params": {"stage": "grasp", "effort": 0.6, "source": "src/lerobot/policies/left_right",
                                     "desc": "专家式夹持 0.6 + 位置锁定"}},
        {"name": "➤ 抬起", "params": {"stage": "lift", "height": 0.08, "force": 0.8,
                                     "source": "src/lerobot/policies/left_right", "desc": "+8cm 避台面"}},
        {"name": "➤ 转移", "params": {"stage": "transfer", "tolerance": 0.05,
                                     "source": "src/lerobot/policies/left_right", "desc": "容差 5cm (peg 有导向)"}},
        {"name": "➤ 插入", "params": {"stage": "insert", "tolerance": 0.05,
                                     "source": "src/lerobot/policies/left_right", "desc": "完成插拔动作"}},
        {"name": "➤ 完成", "params": {"stage": "done", "source": "src/lerobot/policies/left_right",
                                     "desc": "释放/复位, 进入下一循环"}},
        {"name": "🚀 训练", "params": {"steps": 3000, "policy": "left_right",
                                      "source": "src/lerobot/policies/left_right",
                                      "desc": "训练 left_right 双脑策略 (metaworld_peg 数据)"}},
        {"name": "▶ 生成插拔视频", "params": {"insert_video": True, "source": "tools/gen_insert_video.py",
                                           "desc": "后台 rollout 生成演示 mp4 → 自动发飞书"}},
        {"name": "📄 PDF 插拔方案报告", "params": {"insert_report": True, "source": "tools/gen_insert_report.py",
                                               "desc": "6章插拔方案报告 → 自动发飞书"}},
        {"name": "🌐 方案介绍", "params": {"solution_web": True,
                                          "desc": "双击 → 打开方案介绍分页 (datadrive.world/solution.html)"}},
    ]),
    # 🧩 原子技能入口 (2026-08-09 老倪: 模块库最顶部 — 打开原子技能 → 结构条件 → SYS1 → action)
    ("skill", "🧩 原子技能入口", [
        {"name": "🧩 原子", "params": {"atomic_gate": True},
         "desc": "打开原子技能库 → 选技能 → 自动建节点链: 技能 → 结构条件 → SYS1 → 导出 action JSON"},
    ]),
    # 🏭 场景功能块 (2026-08-09 老倪: 光模块工厂三大场景 — 点击打开 ECS 链接 + 建场景节点链)

    # 🎯 YOLO 3D感知模块 (2026-08-06 老倪: 控制台要明显看到 yolo 3d 检测模块, state 输入来源)
    ("model", "🎯 YOLO 3D (感知)", [
        {"name": "🎯 YOLO 3D", "params": {"model": "yolov8s", "classes": "peg/hole/hand",
                                             "yolo_enabled": True, "state_dim": 39,
                                             "desc": "相机图像 → YOLO 检测销钉/插孔/末端 → 2D→3D解算 → 39D state 输入。控制台常驻感知前端, 默认开 (关=3D仅末端)"}},
        {"name": "🎯 YOLO 感知开关", "params": {"yolo_enabled": True, "state_dim": 39,
                                             "desc": "state 输入 switch: 开=39D(YOLO产出) / 关=3D(仅末端) · 默认开"}},
        {"name": "📐 2D→3D 解算", "params": {"intrinsics": "camera_K", "method": "depth|hand-eye",
                                           "desc": "YOLO 2D框中心 + 深度/标定 → 目标 3D 坐标 → 拼入 state"}},
        {"name": "🔌 State Adapter", "params": {"in_dim": 39, "out_dim": 39, "normalize": True,
                                              "desc": "state 适配器: YOLO 3D检测输出 → 统一 state 格式 (开=39D含目标坐标/关=3D仅末端), 适配各策略输入维度"}},
        {"name": "🎯 YOLO 目标检测", "params": {"model": "yolov8s", "classes": "peg/hole/hand",
                                            "desc": "YOLO 目标检测: 销钉/插孔/末端 2D 检测 (Model Zoo画布节点)"}},
    ]),
    ("condition", "条件 (11)", [
        {"name": "C00 信号触发", "params": {"threshold": 0.5}},
        {"name": "C01 到位判断", "params": {"tolerance": 0.01}},
        {"name": "C02 扫码OK",   "params": {}},
        {"name": "C03 力控达标", "params": {"max_force": 5.0}},
        {"name": "C04 AOI通过",  "params": {}},
        {"name": "C05 温控阈值", "params": {"limit": 45.0}},
    ]),
    ("model", "模型 (9)", [
        {"name": "M00 SmolVLA", "params": {"checkpoint": "smolvla-500m", "fps": 100}},
        {"name": "M04 LEW",     "params": {"horizon": 16}},   # 🗑 2026-08-10 老倪: M03 GR00T 已删 (VEH.5.14)
        {"name": "M05 H-JEPA",  "params": {"remote": "4090"}},
    ]),
    # 🧠 ACT 模型·官方子模块 (2026-08-04 老倪: "在左侧模块库里分个类, 将ACT-meta保存到模块库里;
    #  引导从最基础的模块库搭建成最终模型, 全程提示")
    # 对应 modeling_act.py: backbone → vae_encoder → encoder → decoder → action_head → ACTTemporalEnsembler
    ("model", "🧠 ACT 模型·子模块", [
        # 2026-08-08 老倪: 数据源条目删除 (数据集组已有, 子模块链不含数据源)
        # 🗑 2026-08-10 老倪: VEH.5.16/17 (视觉主干 ResNet18 + VAE 编码器) 已删 → 换成「双脑」入口
        {"name": "🧠 双脑 (left_right)", "params": {"desc": "打开 left_right 工程完整画布: 左脑LeftBrainMLP+右脑RightBrainWM+状态机 (抓起8/8 插入7/8)"},
         "flow": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "flows", "dual_brain_peg.json"),
         "desc": "打开 left_right 工程 (src/lerobot/policies/left_right/): 双脑+状态机完整插拔模型"},
        {"name": "🔤 Transformer Encoder", "params": {"n_layers": 4, "dim_model": 256, "n_heads": 8,
                                                      "desc": "官方 ACT.encoder → 上下文 tokens"}},
        {"name": "🔡 Transformer Decoder", "params": {"n_layers": 4, "chunk_size": 7, "n_heads": 8,
                                                      "desc": "官方 ACT.decoder → DETR queries 动作块"}},
        {"name": "🎯 Action Head 4D", "params": {"action_dim": 4, "chunk_size": 7,
                                                "desc": "★适配 metaworld: 输出 (B,7,4) · 真机 6D"}},
        {"name": "⏳ Temporal Ensemble", "params": {"coeff": 0.01,
                                                   "desc": "官方 ACTTemporalEnsembler → 动作平滑"}},
        {"name": "🚀 全新训练", "params": {"steps": 4000,
                                          "desc": "双击 → on_train (metaworld 占位集, 全新不续训)"}},
        {"name": "📊 Scope 示波器", "params": {"desc": "双击 → 示波器: 训练 loss 曲线/执行效果"}},
        {"name": "🧠 ACT-Meta 完整模型", "params": {}, "template": "🧠 ACT-Meta 全新训练",
         "desc": "一键搭建完整模型 (8节点8连线) · 或按上方子模块逐步搭建"},
        {"name": "🏗 Z-MAX 架构", "params": {}, "template": "🏗 Z-MAX 架构",
         "desc": "一键搭建 Z-MAX 四层架构: SYS2 云端训练(顶) → SYS12 Z-Flow + SYS11 VLA-T(中) → SYS0 硬件驱动+原子功能(底)"},
    ]),
    # 🌐 LeWorldModel·官方子模块 (2026-08-05 老倪: "ARPredictor Transformer 还能拆解出来么"
    #   + "action 与潜在空间做真正的 cross-attention (K/V 注入)")
    # 对应 world_model_le.py: SigLIP帧编码 → ActionEmbedder → 位置编码 → 投影 → CrossAttn块×N → 输出投影
    # lew_attn_mode=cross: action 作为 K/V 注入每层潜在空间 (CrossAttention, 非 AdaLN 调制)
    ("model", "🌐 LeWorldModel·子模块", [
        {"name": "🖼 SigLIP 帧编码", "params": {"hidden": 192,
          "desc": "world_model_le.encode_frame: SigLIP(共享SmolVLM视觉) → CLS → projector → 帧嵌入 [B,T,obs]"},
          },
        {"name": "🎛 Action Embedder", "params": {"emb_dim": 192, "mlp_scale": 4,
          "desc": "world_model_le.Embedder: Conv1d + MLP(SiLU) → 动作嵌入 [B,T,obs] — 作为交叉注意 K/V"},
          },
        {"name": "🔤 位置编码", "params": {"num_frames": 2,
          "desc": "ARPredictor.pos_embedding: 帧嵌入加时序位置 (可学习参数)"},
          },
        {"name": "🔀 输入/条件投影", "params": {"input_dim": 192, "hidden_dim": 192,
          "desc": "Transformer.input_proj(x) + cond_proj(c=action) → hidden 空间"},
          },
        {"name": "🧠 CrossAttn 块 ×N", "params": {"depth": 6, "heads": 8, "dim_head": 24, "mlp_dim": 768,
          "desc": "CrossConditionalBlock: ①自注意力(帧内) ②交叉注意力 Q=帧 K/V=action ③MLP — action 真注入潜在空间"},
          },
        {"name": "📤 输出投影", "params": {"output_dim": 192,
          "desc": "Transformer.norm + output_proj → 下一帧嵌入预测"},
          },
    ]),
    # 🖐 VLA-Touch·触觉控制器子模块 (2026-08-05 老倪: 参考 VLA-Touch 项目 —
    #   4060 精简版: base VLA 冻结只训 Interpolant, DINOv2-small 22M + Marker CV + MLP)
    # 对应官方 VLA/residual_controller/: visual_encoder.py → marker_tracker.py →
    #   bridge_controller.py (StateEncoder) → bridge/bridge_model.py (StochasticInterpolants)
    ("model", "🖐 VLA-Touch·触觉子模块", [
        {"name": "🖼 DINOv2 视觉编码", "params": {"backbone": "dinov2-small", "freeze": True,
          "desc": "官方 visual_encoder: DINOv2-small 视觉嵌入 (22M 冻结, 4060 无压力)"},
          },
        {"name": "📍 Marker 触觉跟踪", "params": {"grid": "7x9", "dim": 4,
          "desc": "官方 marker_tracker: GelSight 标记位移 → 低维力信号 m_t (CV 轻量)"},
          },
        {"name": "🌀 DiT-B base VLA", "params": {"hidden": 256, "layers": 1, "freeze": True,
          "desc": "base VLA 动作生成 (与 SmolVLA 同构 — 同构模型放同位置, 冻结不训练)"},
          },
        {"name": "🌉 Interpolant 控制器", "params": {"diffuse_steps": 10, "hidden": 256,
          "desc": "官方 StochasticInterpolants: 桥式扩散 (velocity_loss) 精炼 VLA 动作 — 唯一训练模块"},
          },
    ]),
    # 🧿 AWE·场景原生子模块 (2026-08-05 老倪: 参考它石 AWE 3.5 原生架构 + Z-MAX 场景原生路线 —
    #   H-JEPA 三层潜空间 zFlow 世界模型, 4060 精简)
    # 对应 train_awe_zflow.py: SigLIP视触觉编码 → HJEPAEncoder(三层潜空间) → GRUPredictor(zFlow世界引擎)
    #   → CrossAttnInject(未来决策交叉注意力) → ActionHead
    ("model", "🧿 AWE·场景原生子模块", [
        {"name": "🖐 SigLIP 视触觉编码", "params": {"backbone": "siglip-base", "freeze": True,
          "tactile_dim": 4, "force_dim": 3,
          "desc": "场景原生视触觉编码: SigLIP视觉 + 力觉/触觉 原生融合 (86M 冻结; ⚠️ metaworld 力觉为模拟)"},
          },
        {"name": "🧠 H-JEPA 三层潜空间", "params": {"d_z1": 128, "d_z2": 128, "d_z3": 64,
          "desc": "z₁空间/ z₂物体/ z₃语义 三层潜表示 (场景原生融合, 非乐高拼接)"},
          },
        {"name": "🌊 zFlow 世界引擎", "params": {"gru": 128, "layers": 1,
          "desc": "GRU 预测器: 潜空间推演未来状态/接触演化 (轻量, Orin Nano 可部署)"},
          },
        {"name": "🔀 未来决策交叉注意力", "params": {"gates": "1.0/0.1/0.01",
          "desc": "预测潜状态 K/V 注入动作解码 (分层门控; 推理可剥离零开销)"},
          },
        {"name": "🖐 VLA-Touch 完整模型", "params": {}, "template": "🖐 VLA-Touch 触觉对比",
         "desc": "一键搭建 VLA-Touch 对比管道 (8节点9连线: 数据→DINOv2/Marker/DiT-B→ActionHead→Interpolant→训练→Scope)"},
        {"name": "🧿 AWE 完整模型", "params": {}, "template": "🧿 AWE 场景原生对比",
         "desc": "一键搭建 AWE 场景原生对比管道 (8节点8连线: 数据→SigLIP视触觉编码→三层潜空间→zFlow世界引擎→注入→ActionHead→训练→Scope)"},
    ]),
    # 🧠 双脑+状态机 (2026-08-10 老倪: left_right 工程封装 — src/lerobot/policies/left_right/ 8ed1c9e8)
    ("model", "🧠 双脑+状态机 (插拔)", [
        {"name": "🧠 左脑 LeftBrainMLP", "params": {
            "class": "LeftBrainMLP", "role": "连续动作生成", "in_dim": 39, "out_dim": 4, "hidden": 512,
            "structure": "Linear(39,512)→ReLU→Dropout(0.1)→Linear(512,512)→ReLU→Dropout(0.1)→Linear(512,512)→ReLU→Linear(512,4)",
            "params": "547K", "loss": "MSE (动作回归)", "optimizer": "AdamW lr=1e-4",
            "desc": "左脑: 39D obs → 4D 动作 (MLP偏置接近 act*0.3+delta*2.0, 5/8 vs 纯解析 0/8)"}},
        {"name": "🧠 右脑 RightBrainWM", "params": {
            "class": "RightBrainWM", "role": "抓取时机判断", "in_dim": "39D obs + 4D action", "hidden": 256,
            "structure": "enc: Linear(43,256)→ReLU→Linear(256,256)→ReLU; pred_next: Linear(256,39); contact_head: Linear(256,1)→sigmoid",
            "params": "87K", "contact_acc": "1.00", "loss": "MSE(next obs) + 0.5×BCE(contact)",
            "desc": "右脑: obs+action → next obs 预测 + contact 概率 (该抓了吗)"}},
        {"name": "🧠 双脑+状态机 完整模型",
         "params": {"desc": "一键加载 left_right 完整模型画布 (19节点14连线): 39D→左脑LeftBrainMLP+右脑RightBrainWM→接触判定→LeftRightPolicy状态机6阶段→完成"},
         "flow": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "flows", "dual_brain_peg.json"),
         "desc": "一键加载 left_right 双脑+状态机完整模型: 抓起8/8 插入7/8 (抓起超越官方专家)"},
        {"name": "🔬 转移速度自适应实验",
         "params": {"desc": "一键加载实验总结画布 (18节点17连线): 固定0.6 vs 自适应对比 → 降波动三实验 → 物理碰撞根因 → 真机方向"},
         "flow": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "flows", "transfer_adaptive.json"),
         "desc": "一键加载转移速度自适应实验 (a0f0f9cf): 抓起6-8 插入4-6, 根因=仿真物理碰撞"},
    ]),
    ("action", "动作 (11)", [
        {"name": "A00 Action输出", "params": {}},
        {"name": "A01 取料·100G",  "params": {"pos": [0.1, 0.2, 0.3]}},
        {"name": "A02 扫码·100G",  "params": {}},
        {"name": "A03 放置·100G",  "params": {"pos": [0.5, 0.6, 0.7]}},
        {"name": "A04 力控插入",   "params": {"force": 3.0}},
        {"name": "A05 推入",       "params": {"depth": 0.02}},
        {"name": "A06 取出",       "params": {}},
        {"name": "A07 翻转",       "params": {"angle": 180}},
        {"name": "A08 定位",       "params": {"precision": "0.02mm"}},
        {"name": "A09 AOI检测",    "params": {}},
        {"name": "A10 分拣",       "params": {"bin": 3}},
    ]),
    ("system", "系统 (8)", [
        {"name": "S00 任务调度", "params": {"policy": "fifo"}},
        {"name": "S01 工作流",   "params": {"file": "flow.json"}},
        {"name": "S02 数据闭环", "params": {"mode": "auto"}},
        {"name": "S03 日志",     "params": {"level": "info"}},
        {"name": "S04 W&B监控",  "params": {}},
        {"name": "S05 心跳",     "params": {"interval": 5}},
        {"name": "S06 Switch 数据源", "params": {"switch": "orin"}},
        {"name": "☑ 训练开关", "params": {"train_enabled": True},
         "desc": "checkbox: 打勾=训练 / 不打=不训练 (双击切换, 放最前边控全链路)"},
        {"name": "📄 PDF 技术选型报告", "params": {},
         "desc": "Model Zoo实验 → 11 章技术选型 PDF (概况/系统全貌/分系统功能/接口/参数/架构/功能/性价比/优劣势/视频对比/结论)"},
    ]),
    # 🏗 Z-MAX 架构分组 (2026-08-08 老倪: system2/sys12/sys11/sys0 迁移到 simulink 模块库 —
    #   主页左侧 SystemLayerCard 四层架构, 可拖入画布)
    ("system", "🏗 Z-MAX 架构 (4)", [
        {"name": "🖥 SYS2 云端训练", "params": {"desc": "云端训练 · 4090 · 大模型训练/部署 (架构顶层, L4 大脑)"}},
        {"name": "🧠 SYS12 引导系统", "params": {"desc": "SYS12 引导系统 · Z-Flow 数据流引擎 (SYS1 层)"}},
        {"name": "🖐 SYS11 动作系统", "params": {"desc": "SYS11 动作系统 · VLA-T 触觉大模型 (SYS1 层)"}},
        {"name": "🔧 SYS0 硬件驱动", "params": {"desc": "SYS0 · 硬件驱动 + 原子功能 (架构底层)"}},
    ]),
    # 🧠 模型主干组 (2026-08-08 老倪: Model Zoo所有模块都要能从左侧拖出 — SmolVLM2/DiT-B/LEW)
    ("model", "🧠 模型主干 (5)", [
        {"name": "🧠 SmolVLM2-500M", "params": {"freeze": False, "desc": "视觉语言主干 · 500M (SmolVLM2-500M-Video-Instruct)"}},
        {"name": "🧠 SmolVLM2-500M · LEW", "params": {"freeze": False, "desc": "视觉语言主干 · LEW 版 (enable_lew:true)"}},
        {"name": "🌀 DiT-B 动作解码", "params": {"diT": "B", "desc": "DiT-B 扩散动作生成器 (纯动作版)"}},
        {"name": "🌀 DiT-B 动作解码 · LEW", "params": {"diT": "B", "lew": True, "desc": "DiT-B 动作解码 · LEW 串行版"}},
        {"name": "🌐 LeWorldModel", "params": {"n_layers": 4, "desc": "LeWorldModel 世界模型 (官方 forward 串行)"}},
        # 2026-08-08 老倪: 模板名别名 (力控插入/数据闭环模板)
        {"name": "VLA-T", "params": {"desc": "VLA-T 触觉大模型 (力控插入模板)"}},
        {"name": "SmolVLA", "params": {"desc": "SmolVLA 动作模型 (AOI 检测模板)"}},
        {"name": "H-JEPA", "params": {"desc": "H-JEPA 三层潜空间 (数据闭环模板)"}},
        # 2026-08-08 飞书端: 🧩 结构条件 — 可拖入画布 (双击改 gate/state_dim)
        {"name": "🧩 结构条件", "params": {"gate": 0.5, "state_dim": 39, "dim_mode": "concat",
                                        "desc": "坐标叠加: 坐标逻辑主线(state 含销钉/孔坐标) 叠加图像背景; 训练注入, 推理可剥离"}},
    ]),
    # 🚀 训练组 (2026-08-08 老倪: Model Zoo的训练节点全部可拖)
    ("system", "🚀 训练 (7)", [
        {"name": "🚀 ACT 训练", "params": {"policy": "act", "steps": 4000, "desc": "双击 → 训练 ACT (metaworld 插销数据)"}},
        {"name": "🚀 SmolVLA 训练", "params": {"policy": "smolvla", "steps": 4000, "desc": "双击 → 训练 SmolVLA (纯动作)"}},
        {"name": "🚀 SmolVLA+LEW 训练", "params": {"policy": "smolvla_lew", "steps": 4000, "desc": "双击 → 训练 SmolVLA+LEW"}},
        {"name": "🚀 VLA-Touch 训练", "params": {"policy": "vla_touch", "steps": 4000, "desc": "双击 → 训练 VLA-Touch (Interpolant 控制器)"}},
        {"name": "🚀 AWE 训练", "params": {"policy": "awe_zflow", "steps": 4000, "desc": "双击 → 训练 AWE-zFlow"}},
        {"name": "🎓 专家蒸馏训练", "params": {"policy": "expert_mlp", "desc": "双击 → MLP 从官方专家策略蒸馏 (最快学插拔)"}},
        {"name": "📏 官方专家基准", "params": {"policy": "expert_policy", "desc": "官方专家策略 (🏆 真值锚点 85%)"}},
    ]),
    # 🎛 CICD 环节组 (2026-08-08 老倪: CICD 主控台/仿真推理对比模板节点全覆盖)
    ("system", "🎛 CICD 环节 (6)", [
        {"name": "📥 Orin 数据源", "params": {"ip": "192.168.23.10", "fps": 30, "source": "orin",
                                            "desc": "📥 Orin 数据源 · 真实产线数据"}},
        {"name": "🔀 Switch 数据源", "params": {"switch": "orin", "desc": "双击切换 Orin/metaworld 数据源"}},
        {"name": "🧠 ACT 训练", "params": {"policy": "act", "steps": 4000, "desc": "双击 → 训练 ACT (CICD 主控台环节)"}},
        {"name": "✅ 模型验证", "params": {"desc": "③ 验证 — 流程拓扑合规检查 (validate_flow)"}},
        {"name": "📦 集成打包", "params": {"desc": "④ 集成 — 打包 checkpoint → 上传 ECS 中转"}},
        {"name": "🚚 部署 Orin", "params": {"desc": "⑤ 部署 — 部署状态检查与推送"}},
    ]),
    # 🔬 总系统节点 (2026-08-08 老倪: 总系统 Subsystem 可拖 — 双击展开Model Zoo)
    ("system", "🔬 总系统 (1)", [
    ]),
    # 🎯 Action Head 组 (2026-08-08 老倪: Model Zoo各模型 Action Head 均可拖)
    ("action", "🎯 Action Head (7)", [
        {"name": "🎯 Action Head 4D · ACT", "params": {"action_dim": 4, "chunk_size": 7, "desc": "ACT 动作头 · 输出 (B,7,4)"}},
        {"name": "🎯 Action Head 4D · SmolVLA", "params": {"action_dim": 4, "desc": "SmolVLA 动作头 · 4D"}},
        {"name": "🎯 Action Head 4D · SmolVLA+LEW", "params": {"action_dim": 4, "desc": "SmolVLA+LEW 动作头 · 4D"}},
        {"name": "🎯 Action Head · VLA", "params": {"action_dim": 4, "desc": "VLA-Touch 动作头"}},
        {"name": "🎯 Action Head · AWE", "params": {"action_dim": 4, "desc": "AWE 动作头"}},
        {"name": "🎯 Action Head 4D · MLP", "params": {"action_dim": 4, "desc": "MLP 蒸馏动作头 · 4D"}},
        {"name": "🎯 Action Head 4D · 专家", "params": {"action_dim": 4, "desc": "官方专家动作头 · 4D"}},
    ]),
    # 🧠 MLP 蒸馏 / 🧭 官方专家 结构组 (2026-08-08 老倪)
    ("model", "🧠 MLP 蒸馏 (2)", [
        {"name": "📥 全观测编码 39D", "params": {"dim": 39, "desc": "全观测编码 · 39D 状态 (robot+env)"}},
        {"name": "🔗 全连接层 512·1", "params": {"hidden": 512, "desc": "全连接层 · 512 单层 (MLP 蒸馏)"}},
    ]),
    ("model", "🧭 官方专家 (2)", [
        {"name": "🧭 位置控制律", "params": {"desc": "官方专家位置控制律 (peg-insert-side)"}},
        {"name": "🤏 夹爪状态机", "params": {"desc": "官方专家夹爪状态机 (抓取/释放)"}},
    ]),
    # 🎮 仿真推理/视频组 (2026-08-08 老倪: 每模型推理/视频节点均可拖 — 与Model Zoo行一致)
    ("action", "🎮 仿真推理/视频 (14)", [
        {"name": f"🎮 仿真推理 · {m}", "params": {"video": "infer", "model": m, "auto": True,
                                              "desc": f"🎮 仿真评估 (metaworld 非 Orin) · {m} 推理对比"}}
        for m in ["ACT", "SmolVLA", "SmolVLA+LEW", "VLA-Touch", "AWE", "MLP", "专家"]
    ] + [
        {"name": f"🎮 仿真视频 · {m}", "params": {"video": "play", "model": m,
                                              "desc": f"🎮 仿真评估 (metaworld 非 Orin) · {m} 推理视频"}}
        for m in ["ACT", "SmolVLA", "SmolVLA+LEW", "VLA-Touch", "AWE", "MLP", "专家"]
    ] + [
        # 2026-08-08 老倪: 🎥 视频显示节点 (仿真推理对比模板)
        {"name": f"🎥 视频显示 · {m}", "params": {"video": "display", "model": m,
                                              "desc": f"🎥 视频显示窗口 · {m} (推理对比模板)"}}
        for m in ["ACT", "SmolVLA", "SmolVLA+LEW"]
    ]),
    ("hardware", "硬件 (8)", [
        {"name": "H00 Orin Nano",  "params": {"ip": "192.168.23.10", "port": 8765, "fps": 30}},
        {"name": "H01 MAC",        "params": {"ip": "192.168.23.1", "port": 8769}},
        {"name": "H02 4090训练",   "params": {"host": "39.102.211.79", "port": 50054}},
        {"name": "H03 机械臂",     "params": {"model": "Z700", "dof": 6}},
        {"name": "H04 EtherCAT",   "params": {"rate": 1000}},
        {"name": "H05 相机",       "params": {"res": "480x640", "fps": 30}},
        {"name": "H06 力传感器",   "params": {"range": 50}},
        {"name": "H07 扫码枪",     "params": {}},
        # 2026-08-08 老倪: 模板名别名 (力控插入/AOI/数据闭环模板节点 — 与 H 编号条目功能相同)
        {"name": "机械臂", "params": {"model": "Z700", "dof": 6, "desc": "Z700 机械臂 (力控插入模板)"}},
        {"name": "相机", "params": {"res": "480x640", "fps": 30, "desc": "相机 (AOI 检测模板)"}},
        {"name": "Orin Nano", "params": {"ip": "192.168.23.10", "port": 8765, "fps": 30, "desc": "Orin Nano 边缘计算 (数据闭环模板)"}},
        {"name": "MAC", "params": {"ip": "192.168.23.1", "port": 8769, "desc": "MAC 中转 (数据闭环模板)"}},
        {"name": "4090训练", "params": {"host": "39.102.211.79", "port": 50054, "desc": "4090 云端训练 (数据闭环模板)"}},
    ]),
    # 📊 评估分组 (2026-08-06 老倪: Scope 放到左侧 node 库, 直接拖到主窗口)
    ("system", "📊 评估 (3)", [
        {"name": "📊 Scope 示波器", "params": {"scope": True},
         "desc": "双击 → 示波器: 训练 loss 曲线/执行效果 (Simulink Scope 对标)"},
        {"name": "📊 对比评估 Scope (仿真)", "params": {"shared": True},
         "desc": "♻ 共用: 双击 → 多模型 训练速度/精确度/鲁棒性 对比图表"},
        {"name": "🎮 仿真推理对比", "params": {"video": "all", "auto": True},
         "desc": "多模型 metaworld rollout 视频 → 窗口同步播放对比 (推理效果)"},
    ]),
]

# 🧩 原子技能组件区 (2026-08-09 老倪: W²-VLA Token — 从 atomic_skill_tokens.json 动态加载 9 大类)
def _load_skill_library_groups():
    """加载原子技能 token 库 → LIBRARY 分组 (每大类一组, 每条技能一个组件)
    技能组件拖入画布 → 连 🧩结构条件 → 进 SYS1 → 导出 action JSON"""
    import os as _os, json as _j
    p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "flows", "atomic_skill_tokens.json")
    try:
        data = _j.load(open(p, encoding="utf-8"))
        skills = data.get("skills", [])
    except Exception:
        return []
    from collections import OrderedDict
    by_cat = OrderedDict()
    for s in skills:
        by_cat.setdefault(s["category"], []).append(s)
    groups = []
    for cat, items in by_cat.items():
        entries = []
        for s in items:
            entries.append({
                "name": f"🧩 {s['skill_id']} {s['name'][:16]}",
                "params": {
                    "skill_id": s["skill_id"],
                    "tokens": s.get("tokens", {}),
                    "action": s.get("action", "operate"),
                    "modalities": s.get("modalities", []),
                    "encoding": s.get("encoding", {}),
                    "gate": s.get("gate", 0.5),
                    "desc": s.get("desc", "")[:80],
                },
            })
        groups.append(("skill", f"🧩 原子技能 · {cat} ({len(items)})", entries))
    return groups

# 🧩 2026-08-09 老倪: 原子技能组件区 — 从 atomic_skill_tokens.json 动态加载 (W²-VLA Token)
try:
    LIBRARY += _load_skill_library_groups()
except Exception:
    pass  # 技能库缺失不影响模块库其余部分

# 🌐 2026-08-09 老倪: LIBRARY 模块 → 稳定序号 (模块库按钮与画布节点 ID 一致)
LIBRARY_SEQ = {}
_lib_seq = 0
for _gtype, _gname, _items in LIBRARY:
    for _it in _items:
        _lib_seq += 1
        LIBRARY_SEQ[_it["name"]] = _lib_seq
# 🐛 2026-08-09 老倪: 模板节点名也注册 (总系统 SYS1动作系统/数据集合 等在 LIBRARY 无对应 → 画布回退随机撞号)
for _app in REFERENCE_APPS:
    for _n in _app[1]:
        _nm = _n[1]
        if _nm and _nm not in LIBRARY_SEQ:
            _lib_seq += 1
            LIBRARY_SEQ[_nm] = _lib_seq
# 🐛 2026-08-09 老倪: CICD 流水线环节也注册 (采集/训练/验证/集成/部署/推理 — sid 是字符串)
for _st in ("① 采集", "② 训练", "③ 验证", "④ 集成", "⑤ 部署", "⑥ 推理"):
    if _st not in LIBRARY_SEQ:
        _lib_seq += 1
        LIBRARY_SEQ[_st] = _lib_seq


def lib_seq_of(name):
    """模块/模板 name → 稳定序号 (未找到 → None)"""
    return LIBRARY_SEQ.get(name)


def gen_id():
    """节点 id: n + 时间戳 + 3位随机 (与 web 同规则)"""
    return "n%d%s" % (int(time.time() * 1000), ''.join(
        random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(3)))


# ── 深色对话框 QSS (2026-08-05 老倪: 训练配置对话框黑字看不清 → 统一深底白字) ──
_DLG_DARK_QSS = """
QDialog { background:#0d1117; }
QLabel { color:#e6edf3; font-size:12px; }
QLabel#dim { color:#8b949e; font-size:11px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background:#010409; color:#e6edf3; border:1px solid #30363d; border-radius:6px;
    padding:4px 8px; min-height:22px; selection-background-color:#1f6feb; }
QComboBox::drop-down { border:none; width:22px; }
QComboBox QAbstractItemView { background:#161b22; color:#e6edf3; selection-background-color:#1f6feb; }
QPushButton { background:#21262d; color:#e6edf3; border:1px solid #30363d; border-radius:6px;
    padding:6px 14px; font-size:12px; font-weight:600; }
QPushButton:hover { border-color:#00d4aa; }
QDialogButtonBox QPushButton { min-width:72px; }
"""


def link_id():
    return "l%d%s" % (int(time.time() * 1000), ''.join(
        random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(2)))


# ════════════════════════════════════════════════════════════════
# 参数面板 (Block Parameters — 对标 Simulink 双击弹窗)
# ════════════════════════════════════════════════════════════════
class TrainConfigDialog(QDialog):
    """⚙️ 训练配置对话框 (2026-08-05 老倪: "增加一个训练步数调整的功能, 在训练模块,
    双击打开配置或右键打开" — 训练节点双击/右键 → 调整 steps/batch/lr, 保存到节点
    params, node_logic 透传生效)"""

    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node = node
        self.setWindowTitle(f"⚙️ 训练配置 — {node['name']}")
        self.setMinimumWidth(420)
        self.setStyleSheet(_DLG_DARK_QSS)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        head = QLabel(f"🎛 {node['name']} 训练参数")
        head.setStyleSheet("font-size:14px; font-weight:700; color:#e6edf3; padding:2px;")
        lay.addWidget(head)

        note = QLabel("保存后对下次训练生效 (当前 50 步快速验证, 跑通后可加大)")
        note.setStyleSheet("color:#8b949e; font-size:11px;")
        lay.addWidget(note)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        p = node.get("params", {})
        self.ed_steps = QSpinBox()
        self.ed_steps.setRange(10, 5000)
        self.ed_steps.setSingleStep(50)
        self.ed_steps.setValue(int(p.get("steps", 10)))
        form.addRow("训练步数 steps", self.ed_steps)

        self.ed_batch = QSpinBox()
        self.ed_batch.setRange(1, 64)
        self.ed_batch.setValue(int(p.get("batch_size", 8)))
        form.addRow("批次 batch", self.ed_batch)

        self.ed_lr = QDoubleSpinBox()
        self.ed_lr.setRange(1e-6, 1e-2)
        self.ed_lr.setDecimals(6)
        self.ed_lr.setSingleStep(1e-5)
        self.ed_lr.setValue(float(p.get("lr", 1e-4)))
        form.addRow("学习率 lr", self.ed_lr)

        tip = QLabel("当前: " + (f"steps={p.get('steps', 10)}" if "steps" in p else "steps=10(默认)") +
                     (f" · batch={p['batch_size']}" if "batch_size" in p else "") +
                     (f" · lr={p['lr']}" if "lr" in p else ""))
        tip.setStyleSheet("color:#8b949e; font-size:11px;")
        lay.addWidget(tip)
        lay.addLayout(form)

        btns = QHBoxLayout()
        b_ok = QPushButton("✅ 保存并应用到训练")
        b_ok.clicked.connect(self._apply)
        b_cancel = QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(b_ok)
        btns.addWidget(b_cancel)
        lay.addLayout(btns)

    def _apply(self):
        p = self.node.setdefault("params", {})
        p["steps"] = self.ed_steps.value()
        p["batch_size"] = self.ed_batch.value()
        p["lr"] = self.ed_lr.value()
        self.accept()


class BlockParamsDialog(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node = node
        self.setWindowTitle(f"Block Parameters: {node['name']}")
        self.setMinimumWidth(380)
        self.setStyleSheet(_DLG_DARK_QSS)
        lay = QVBoxLayout(self)

        head = QLabel(f"{NODE_TYPES.get(node['type'], {}).get('cn', node['type'])} · {node['name']}")
        head.setStyleSheet("font-size:14px; font-weight:700; color:#e6edf3; padding:4px;")
        lay.addWidget(head)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._edits = {}

        # 名称 (行内编辑)
        self._edits["name"] = QLineEdit(node["name"])
        form.addRow("名称", self._edits["name"])

        # 参数
        params = node.get("params", {})
        if not params:
            lab = QLabel("(无参数)")
            lab.setStyleSheet("color:#8b949e; font-size:11px;")
            form.addRow("参数", lab)
        for k, v in params.items():
            if isinstance(v, bool):
                cb = QComboBox(); cb.addItems(["true", "false"])
                cb.setCurrentText("true" if v else "false")
                self._edits[k] = cb
            elif isinstance(v, (int, float)):
                if isinstance(v, float):
                    sb = QDoubleSpinBox()
                    sb.setRange(-1e9, 1e9)
                    sb.setValue(v)
                else:
                    sb = QSpinBox()
                    sb.setRange(-10**9, 10**9)
                    sb.setValue(int(v))
                self._edits[k] = sb
            else:
                # 🎨 bg/背景色 参数 → 颜色下拉 (row_bg 节点改色用, 2026-08-05 老倪)
                if k in ("bg", "bg_color", "color"):
                    cb = QComboBox()
                    _preset = ["#26418f", "#8f6a26", "#1f7a4d", "#6a2d8f", "#8f2d4d",
                               "#3a3f4b", "#2d7a5c", "#7a5c2d", "#5c2d7a", "#7a2d4a",
                               "#0d1117", "#f0a030"]
                    _labels = {"#26418f": "蓝 (ACT)", "#8f6a26": "黄褐 (SmolVLA)",
                               "#1f7a4d": "绿 (SmolVLA+LEW)", "#6a2d8f": "紫 (VLA-Touch)",
                               "#8f2d4d": "玫红 (AWE)", "#3a3f4b": "灰", "#2d7a5c": "深绿",
                               "#7a5c2d": "深黄", "#5c2d7a": "深紫", "#7a2d4a": "深红",
                               "#0d1117": "黑", "#f0a030": "橙"}
                    for _c in _preset:
                        cb.addItem(f"● {_labels.get(_c, _c)}  {_c}", _c)
                    idx = _preset.index(v) if v in _preset else 0
                    cb.setCurrentIndex(idx)
                    self._edits[k] = cb
                else:
                    le = QLineEdit(str(v))
                    self._edits[k] = le
            form.addRow(k, self._edits[k])

        lay.addLayout(form)

        # 端口说明
        info = QLabel(f"输入: {len(node.get('inputs', []))} · 输出: {len(node.get('outputs', []))}")
        info.setStyleSheet("color:#8b949e; font-size:10px;")
        lay.addWidget(info)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _apply(self):
        n = self.node
        n["name"] = self._edits["name"].text().strip() or n["name"]
        for k, w in self._edits.items():
            if k == "name":
                continue
            if k not in n.get("params", {}):
                continue
            cur = n["params"][k]
            if isinstance(cur, bool):
                n["params"][k] = w.currentText() == "true"
            elif isinstance(cur, int):
                n["params"][k] = int(w.value())
            elif isinstance(cur, float):
                n["params"][k] = float(w.value())
            elif isinstance(w, QComboBox):
                n["params"][k] = w.currentData() or w.currentText()  # 🎨 颜色取 itemData
            else:
                n["params"][k] = w.text()
        self.accept()


# ════════════════════════════════════════════════════════════════
# CI/CD 后台工作线程 (避免阻塞 GUI 主线程)
# ════════════════════════════════════════════════════════════════
class CICDWorker(QThread):
    log = pyqtSignal(str)      # 日志行 → 主线程
    finished_ok = pyqtSignal(bool, str)  # (成功?, 摘要)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            ok, summary = self._fn(*self._args, **self._kwargs)
            self.finished_ok.emit(ok, summary)
        except Exception as ex:
            self.log.emit(f"❌ 后台任务异常: {ex}")
            self.finished_ok.emit(False, str(ex))


# ════════════════════════════════════════════════════════════════
# CI/CD 全链路面板: 可视化流水线 (4环节节点+箭头连线, 运行中脉冲,
# 状态色与 Simulink 画布一致: 灰=未开始 青=运行中 绿=成功 红=失败)
# ════════════════════════════════════════════════════════════════
class CICDStageItem(QGraphicsObject):
    """流水线环节节点 (可点击执行)"""
    clicked = pyqtSignal(str)

    def __init__(self, sid, title, desc, state=0):
        super().__init__()
        self.sid = sid
        self.title = title
        self.desc = desc
        self.state = state
        self.w, self.h = 150, 88
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)
        self._hover = False

    def boundingRect(self):
        return QRectF(-8, -8, self.w + 16, self.h + 16)

    def paint(self, painter, opt, widget=None):
        c = QColor(["#9aa4b2", "#00d4aa", "#3fb950", "#ff4444"][self.state])
        painter.setRenderHint(QPainter.Antialiasing)
        pal = THEMES[_CUR_THEME]  # 🎨 主题调色板
        # 主体
        grad = QLinearGradient(0, 0, 0, self.h)
        grad.setColorAt(0, QColor(pal["node_top"]))
        grad.setColorAt(1, QColor(pal["node_bot"]))
        painter.setBrush(grad)
        pen = QPen(c, 2.2 if (self._hover or self.state == 1) else 1.6)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(0, 0, self.w, self.h), 8, 8)
        # 标题 (🎨 主题色 — 硬编码 #1f2328 深色主题下黑字黑底看不见)
        painter.setPen(QColor(pal["title"]))
        painter.setFont(QFont("Arial", 11, QFont.Bold))
        painter.drawText(QRectF(8, 8, self.w - 16, 22), Qt.AlignVCenter | Qt.AlignLeft, self.title)
        # 描述
        painter.setPen(QColor(pal["label"]))
        painter.setFont(QFont("Arial", 8))
        painter.drawText(QRectF(8, 32, self.w - 16, 34), Qt.AlignTop | Qt.AlignLeft, self.desc)
        # 状态徽章
        icon = {1: "● 运行中", 2: "✓ 成功", 3: "✕ 失败", 0: "○ 未开始"}[self.state]
        painter.setPen(c)
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(QRectF(8, 66, self.w - 16, 18), Qt.AlignVCenter | Qt.AlignLeft, icon)
        # 🌐 2026-08-08 老倪: 节点全局 ID — 🐛 2026-08-09 老倪: 仅悬停显示 (左下角小字青色)
        try:
            # 🐛 2026-08-09 老倪: CICD 环节 ID 常显
            painter.setPen(QColor("#8b949e"))
            painter.setFont(QFont("Arial", 7))
            nid = getattr(self, "nid", None) or (
                f"VEH.5.{lib_seq_of(self.title):03d}" if lib_seq_of(self.title) else
                f"VEH.5.CICD.{self.sid}")  # 🐛 sid 字符串不能 % 100
            painter.drawText(QRectF(6, self.h - 13, self.w - 12, 12), Qt.AlignLeft | Qt.AlignVCenter, nid)
        except Exception:
            pass

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.sid)
            e.accept()

    def hoverEnterEvent(self, e):
        self._hover = True; self.update(); e.accept()

    def hoverLeaveEvent(self, e):
        self._hover = False; self.update(); e.accept()


class CICDLinkItem(QGraphicsObject):
    """环节间箭头连线 (数据流方向)"""
    def __init__(self, a, b, src_item, dst_item):
        super().__init__()
        self.a, self.b = a, b
        self.src_item, self.dst_item = src_item, dst_item
        self.setZValue(5)
        self._flow = 0.0
        self._t = QTimer()
        self._t.timeout.connect(self._tick)
        self._t.start(90)

    def _tick(self):
        if self.src_item.state in (1, 2):
            self._flow += 2.0
            self.update()

    def boundingRect(self):
        return QRectF(min(self.a.x(), self.b.x()) - 6, min(self.a.y(), self.b.y()) - 6,
                      abs(self.b.x() - self.a.x()) + 12, abs(self.b.y() - self.a.y()) + 12)

    def paint(self, painter, opt, widget=None):
        active = self.src_item.state in (1, 2)
        c = QColor("#00d4aa" if active else "#9aa4b2")
        painter.setRenderHint(QPainter.Antialiasing)
        pal = THEMES[_CUR_THEME]  # 🎨 主题调色板
        pen = QPen(c, 2.2)
        if active:
            pen.setStyle(Qt.DashLine)
            pen.setDashPattern([7, 5])
            pen.setDashOffset(-self._flow)
        painter.setPen(pen)
        painter.drawLine(self.a, self.b)
        # 箭头
        ang = math.atan2(self.b.y() - self.a.y(), self.b.x() - self.a.x())
        painter.setBrush(c)
        painter.setPen(Qt.NoPen)
        for da in (0.35, -0.35):
            painter.drawPolygon(QPolygonF([
                QPointF(self.b.x(), self.b.y()),
                QPointF(self.b.x() - 10 * math.cos(ang - da), self.b.y() - 10 * math.sin(ang - da)),
                QPointF(self.b.x() - 10 * math.cos(ang + da), self.b.y() - 10 * math.sin(ang + da)),
            ]))


class CICDPanel(QDialog):
    def __init__(self, module, parent=None):
        super().__init__(parent)
        self.module = module
        self.setWindowTitle("CI/CD 全链路 · Z-MAX")
        self.setMinimumSize(980, 460)
        # 🎨 2026-08-06 老倪: CICD 面板改回深色背景 (与整体暗色调统一)
        self.setStyleSheet("QDialog { background:#0d1117; }")
        self._stage_items = {}
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse)
        self._pulse_timer.start(500)
        self._build()
        self._refresh()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        # 标题
        t = QLabel("🔗 CI/CD 全链路流水线 · 采集 → 训练 → 验证 → 集成 → 部署 → 推理")
        t.setStyleSheet("color:#ffd700; font-size:15px; font-weight:700; background:transparent; border:none;")
        lay.addWidget(t)
        tip = QLabel("点击环节节点执行该环节 · ▶ 全流程 = 依次自动流转 · 运行中青色脉冲 · 完成后状态回显")
        tip.setStyleSheet("color:#57606a; font-size:10px; background:transparent; border:none;")
        lay.addWidget(tip)

        # 流水线画布 (QGraphicsView)
        self._view = QGraphicsView()
        self._view.setRenderHints(QPainter.Antialiasing)
        self._view.setStyleSheet("background:#0d1117; border:1px solid #1e2740; border-radius:8px;")
        self._view.setDragMode(QGraphicsView.NoDrag)
        self._scene = QGraphicsScene(self)
        self._view.setScene(self._scene)
        self._view.setFixedHeight(180)
        lay.addWidget(self._view)

        # 6 环节定义 (数据闭环全链路: 采集→训练→验证→集成→部署→推理)
        self._stages = [
            ("collect",  "① 采集", "拉取 Orin 真实数据\nrelay → 修复 action → 落地", self.module.on_collect),
            ("train",    "② 训练", "ACT 训练 lerobot_train\n优先 Orin 真实数据", self.module.on_train),
            ("validate", "③ 验证", "模型标准合规校验\nModel Advisor 对标", self.module.on_validate),
            ("integrate","④ 集成", "打包 checkpoint → ECS\ncicd_deploy push", self.module.on_integrate),
            ("deploy",   "⑤ 部署", "推送模型 → Orin\n心跳验证", self.module.on_deploy),
            ("infer",    "⑥ 推理", "Orin 推理状态\ninfer_count / 延迟", self.module.on_infer),
        ]
        # 放置节点 (横排, 带箭头)
        x0, y0 = 30, 40
        gap = 140
        prev_item = None
        for i, (sid, title, desc, fn) in enumerate(self._stages):
            it = CICDStageItem(sid, title, desc, 0)
            it.setPos(x0 + i * gap, y0)
            it.clicked.connect(self._on_stage_clicked)
            self._scene.addItem(it)
            self._stage_items[sid] = it
            if prev_item is not None:
                a = QPointF(prev_item.x() + prev_item.w, prev_item.y() + prev_item.h / 2)
                b = QPointF(it.x(), it.y() + it.h / 2)
                self._scene.addItem(CICDLinkItem(a, b, prev_item, it))
            prev_item = it
        self._scene.setSceneRect(-20, 0, x0 + 3 * gap + 160 + 40, 180)

        # 日志行 (显示当前环节输出)
        self._stage_log = QLabel("就绪 · 点击环节节点开始")
        self._stage_log.setStyleSheet("color:#8b949e; font-size:11px; font-family:Consolas; background:#161b22; border:1px solid #1e2740; border-radius:6px; padding:8px;")
        self._stage_log.setWordWrap(True)
        lay.addWidget(self._stage_log)

        # 底部: 全流程 + 保存工作流 + 刷新 + 关闭
        bl = QHBoxLayout()
        self.btn_full = QPushButton("▶ 全流程 (采集→训练→验证→集成→部署→推理)")
        self.btn_full.setStyleSheet("""
            QPushButton { background:#ffd70022; color:#ffd700; border:1px solid #ffd70066;
            border-radius:4px; padding:5px 14px; font-size:11px; font-weight:700; }
            QPushButton:hover { background:#ffd70044; }
        """)
        self.btn_full.clicked.connect(self.module._run_full_flow)
        bl.addWidget(self.btn_full)
        bl.addStretch()
        self.btn_save_flow = QPushButton("💾 保存工作流 JSON")
        self.btn_save_flow.setStyleSheet("""
            QPushButton { background:#ffd70022; color:#ffd700; border:1px solid #ffd70066;
            border-radius:4px; padding:5px 14px; font-size:11px; font-weight:600; }
            QPushButton:hover { background:#ffd70044; }
        """)
        self.btn_save_flow.clicked.connect(self._save_flow)
        bl.addWidget(self.btn_save_flow)
        self.btn_refresh = QPushButton("🔄 刷新状态")
        self.btn_refresh.setStyleSheet("""
            QPushButton { background:#21262d; color:#c9d1d9; border:1px solid #1e2740;
            border-radius:4px; padding:5px 14px; font-size:11px; }
            QPushButton:hover { border-color:#ffd700; color:#ffd700; }
        """)
        self.btn_refresh.clicked.connect(self._refresh)
        bl.addWidget(self.btn_refresh)
        self.btn_close = QPushButton("✕ 关闭")
        self.btn_close.setStyleSheet(self.btn_refresh.styleSheet())
        self.btn_close.clicked.connect(self.accept)
        bl.addWidget(self.btn_close)
        lay.addLayout(bl)

    def _stage_state(self, sid):
        return self.module._cicd_state.get(sid, 0)

    def _refresh(self):
        """刷新环节节点状态 + 日志"""
        for sid, _, _, fn in self._stages:
            it = self._stage_items[sid]
            s = self._stage_state(sid)
            it.state = s
            it.update()
        self._view.viewport().update()

    def _pulse(self):
        """运行中环节脉冲动画 (青色边框呼吸)"""
        self._pulse_on = not getattr(self, "_pulse_on", False)
        for sid, it in self._stage_items.items():
            if self._stage_state(sid) == 1:
                it.setScale(1.0 + (0.03 if self._pulse_on else -0.03))
                it.update()

    def _on_stage_clicked(self, sid):
        """点击环节节点 → 执行该环节"""
        fn = dict((s[0], s[3]) for s in self._stages).get(sid)
        if fn is None:
            return
        title = dict((s[0], s[1]) for s in self._stages).get(sid, sid)
        self.module._cicd_state[sid] = 1
        self._stage_log.setText(f"▶ 执行 {title} …")
        self._refresh()
        fn()

    def _run_stage(self, fn):
        """兼容旧调用: 直接执行"""
        fn()

    def _save_flow(self):
        """保存主画布工作流 DAG 为 JSON (与 web simulink-spec 一致)"""
        import json as _json
        flow = {"format": "zmax-simulink", "version": "1.0",
                "name": "cicd_workflow",
                "sim": {"dt": self.module._sim_dt, "t_end": self.module._sim_t_end, "solver": "fixed-step"},
                "nodes": self.module.nodes, "links": self.module.links}
        path = os.path.join(os.path.expanduser("~"), "lerobot-smolvla-lew", "flows",
                            "cicd_workflow.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(flow, f, ensure_ascii=False, indent=2)
            self._stage_log.setText(f"💾 工作流已保存: {path} ({len(flow['nodes'])}节点 {len(flow['links'])}连线)")
        except Exception as ex:
            self._stage_log.setText(f"❌ 保存失败: {ex}")


# ════════════════════════════════════════════════════════════════
# 三阶段渐进式训练管线面板 (老倪策略 2026-08-02)
#   Stage1 MetaWorld 仿真训练 → Stage2 Sim-to-Real 零样本测试 → Stage3 Orin 微调
#   自动流转, steps 可配置, 状态读 docs/PIPELINE_STATE.json
# ════════════════════════════════════════════════════════════════
class PipelinePanel(QDialog):
    STAGE_DEFS = {
        1: ("Stage 1", "MetaWorld 仿真训练", "backbone 冻结 · lr 1e-4 · kl 10 · chunk 100 · 仿真快速验证"),
        2: ("Stage 2", "Sim-to-Real 零样本测试", "stage1 模型 → Orin 真实数据 · 量化 Reality Gap"),
        3: ("Stage 3", "Orin 真实数据微调", "stage1 权重初始化 · lr 1e-5 · backbone 1e-6 · ensemble 0.01"),
    }
    _STATE = os.path.join(os.path.expanduser("~"), "lerobot-smolvla-lew", "docs", "PIPELINE_STATE.json")
    _PY = os.path.join(os.path.expanduser("~"), "lerobot-smolvla-lew", ".venv", "bin", "python")
    _STATUS_COLOR = {"pending": "#57606a", "running": "#00d4aa", "success": "#3fb950", "failed": "#ff4444"}
    _STATUS_ICON = {"pending": "○ 未开始", "running": "● 运行中", "success": "✓ 成功", "failed": "✕ 失败"}

    def __init__(self, module, parent=None):
        super().__init__(parent)
        self.module = module
        self.setWindowTitle("🎯 数据闭环 CICD 控制台 · Z-MAX")
        self.setMinimumSize(920, 560)
        # 🎨 2026-08-06 老倪: 数据闭环控制台改回深色背景 (浅色与整体暗色调不协调)
        self.setStyleSheet("QDialog { background:#0d1117; }")
        self._cards = {}
        self._spin = {}
        self._build()
        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)
        # 远程状态轮询 (relay/orin, 后台线程不卡 UI)
        self._remote_timer = QTimer(self)
        self._remote_timer.timeout.connect(self._poll_remote)
        self._remote_timer.start(10000)
        self._poll_remote()

    def _read_state(self):
        try:
            return json.load(open(self._STATE, encoding="utf-8"))
        except Exception:
            return {}

    def _mk_card(self, sid):
        num, title, desc = self.STAGE_DEFS[sid]
        card = QFrame()
        card.setObjectName(f"stage{sid}")
        card.setStyleSheet("QFrame#stage%d { background:#161b22; border:1px solid #1e2740; border-radius:10px; }" % sid)
        card.setFixedWidth(250)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        h = QHBoxLayout()
        t = QLabel(f"{num}  {title}")
        t.setStyleSheet("color:#c9d1d9; font-size:13px; font-weight:700; background:transparent; border:none;")
        h.addWidget(t)
        h.addStretch()
        st = QLabel("○")
        st.setStyleSheet("color:#57606a; font-size:13px; font-weight:700; background:transparent; border:none;")
        h.addWidget(st)
        lay.addLayout(h)
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet("color:#57606a; font-size:10px; background:transparent; border:none;")
        lay.addWidget(d)
        # steps 配置 (stage2 无)
        if sid in (1, 3):
            row = QHBoxLayout()
            row.addWidget(QLabel("steps"))
            sp = QSpinBox()
            sp.setRange(1, 50000)
            sp.setValue(300)
            sp.setStyleSheet("background:#0d1117; color:#c9d1d9; border:1px solid #1e2740; border-radius:4px; padding:2px 6px;")
            row.addWidget(sp)
            row.addStretch()
            lay.addLayout(row)
            self._spin[sid] = sp
        info = QLabel("—")
        info.setWordWrap(True)
        info.setStyleSheet("color:#58a6ff; font-size:10px; font-family:Consolas; background:transparent; border:none;")
        lay.addWidget(info)
        btn = QPushButton("▶ 运行本阶段")
        btn.setStyleSheet("QPushButton { background:#1a2230; color:#00d4aa; border:1px solid #00d4aa44; border-radius:5px; padding:5px; font-size:11px; font-weight:600; }"
                          "QPushButton:hover { border-color:#00d4aa; }")
        btn.clicked.connect(lambda _, s=sid: self._run_stage(s))
        lay.addWidget(btn)
        self._cards[sid] = (card, st, info)
        return card

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        t = QLabel("🎯 数据闭环 CICD 控制台 · 采集 → 训练 → 模型 → 部署 → 推理 → 迭代")
        t.setStyleSheet("color:#00d4aa; font-size:15px; font-weight:700; background:transparent; border:none;")
        lay.addWidget(t)
        tip = QLabel("三阶段自动流转 · steps 可配置 · 闭环状态每 10s 刷新 (Orin 心跳/推理/数据量)")
        tip.setStyleSheet("color:#57606a; font-size:10px; background:transparent; border:none;")
        lay.addWidget(tip)

        # ── 闭环状态栏 (数据/模型/URL/Orin/推理) ──
        bar = QFrame()
        bar.setStyleSheet("QFrame { background:#161b22; border:1px solid #1e2740; border-radius:8px; }")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(14)
        self.lbl_data = QLabel("📥 数据: —")
        self.lbl_model = QLabel("🧠 模型: —")
        self.lbl_url = QLabel("🔗 URL: —")
        self.lbl_orin = QLabel("🤖 Orin: —")
        self.lbl_infer = QLabel("⚡ 推理: —")
        for lb in (self.lbl_data, self.lbl_model, self.lbl_url, self.lbl_orin, self.lbl_infer):
            lb.setStyleSheet("color:#c9d1d9; font-size:11px; font-family:Consolas; background:transparent; border:none;")
            bl.addWidget(lb)
        bl.addStretch()
        lay.addWidget(bar)

        # ── 🤖 模型选择 + 属性 (2026-08-07 老倪: 看所有训练模型/选一个/sim-to-real/stage3) ──
        mbar = QFrame()
        mbar.setStyleSheet("QFrame { background:#161b22; border:1px solid #1e2740; border-radius:8px; }")
        ml = QHBoxLayout(mbar)
        ml.setContentsMargins(12, 8, 12, 8)
        ml.setSpacing(10)
        lab = QLabel("🤖 模型")
        lab.setStyleSheet("color:#00d4aa; font-size:11px; font-weight:700; background:transparent; border:none;")
        ml.addWidget(lab)
        self.cmb_model = QComboBox()
        self.cmb_model.setMinimumWidth(240)
        self.cmb_model.setStyleSheet("QComboBox { background:#21262d; color:#c9d1d9; border:1px solid #1e2740; border-radius:6px; padding:4px 8px; font-size:11px; }")
        ml.addWidget(self.cmb_model)
        self.lbl_model_attr = QLabel("属性: —")
        self.lbl_model_attr.setStyleSheet("color:#8b949e; font-size:10px; font-family:Consolas; background:transparent; border:none;")
        self.lbl_model_attr.setMinimumWidth(300)
        ml.addWidget(self.lbl_model_attr)
        ml.addStretch()
        self.btn_sim2real = QPushButton("🎯 Sim-to-Real (S2)")
        self.btn_sim2real.setStyleSheet("QPushButton { background:#58a6ff22; color:#58a6ff; border:1px solid #58a6ff66; border-radius:6px; padding:5px 12px; font-size:11px; font-weight:700; }"
                                        "QPushButton:hover { background:#58a6ff33; }")
        self.btn_stage3 = QPushButton("🚀 Stage 3 真机微调")
        self.btn_stage3.setStyleSheet("QPushButton { background:#00d4aa22; color:#00d4aa; border:1px solid #00d4aa66; border-radius:6px; padding:5px 12px; font-size:11px; font-weight:700; }"
                                      "QPushButton:hover { background:#00d4aa33; }")
        ml.addWidget(self.btn_sim2real)
        ml.addWidget(self.btn_stage3)
        lay.addWidget(mbar)
        self._reload_models()
        self.cmb_model.currentIndexChanged.connect(self._show_model_attr)
        self.btn_sim2real.clicked.connect(self._on_sim2real)
        self.btn_stage3.clicked.connect(self._on_stage3)

        # ── 6 环节流水线 (采集→训练→验证→集成→部署→推理) ──
        pipe = QHBoxLayout()
        pipe.setSpacing(8)
        self._pipe_btns = {}
        pipe_defs = [
            ("collect", "① 采集", self.module.on_collect),
            ("train", "② 训练", self.module.on_train),
            ("validate", "③ 验证", self.module.on_validate),
            ("integrate", "④ 集成", self.module.on_integrate),
            ("deploy", "⑤ 部署", self.module.on_deploy),
            ("infer", "⑥ 推理", self.module.on_infer),
        ]
        for sid, label, fn in pipe_defs:
            b = QPushButton(label)
            b.setStyleSheet("QPushButton { background:#21262d; color:#8b949e; border:1px solid #1e2740; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:600; }"
                            "QPushButton:hover { border-color:#00d4aa; color:#00d4aa; }")
            b.clicked.connect(lambda _, s=sid, f=fn: (self.module._cicd_state.__setitem__(s, 1), self._refresh(), f()))
            self._pipe_btns[sid] = b
            pipe.addWidget(b)
        self.btn_pipe_full = QPushButton("▶ 流水线全流程")
        self.btn_pipe_full.setStyleSheet("QPushButton { background:#00d4aa22; color:#00d4aa; border:1px solid #00d4aa66; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:700; }"
                                         "QPushButton:hover { background:#00d4aa33; }")
        self.btn_pipe_full.clicked.connect(self.module._run_full_flow)
        pipe.addWidget(self.btn_pipe_full)
        pipe.addStretch()
        lay.addLayout(pipe)

        row = QHBoxLayout()
        row.setSpacing(12)
        for sid in (1, 2, 3):
            row.addWidget(self._mk_card(sid))
        lay.addLayout(row)

        bar = QHBoxLayout()
        self.btn_full = QPushButton("▶ 全流程自动运行 (1→2→3)")
        self.btn_full.setStyleSheet("QPushButton { background:#00d4aa22; color:#00d4aa; border:1px solid #00d4aa66; border-radius:6px; padding:8px 20px; font-size:13px; font-weight:700; }"
                                    "QPushButton:hover { background:#00d4aa33; }")
        self.btn_full.clicked.connect(self._run_full)
        bar.addWidget(self.btn_full)
        bar.addStretch()
        self.lbl_stage_now = QLabel("当前: 未运行")
        self.lbl_stage_now.setStyleSheet("color:#57606a; font-size:11px; font-family:Consolas; background:transparent; border:none;")
        bar.addWidget(self.lbl_stage_now)
        lay.addLayout(bar)

        # 运行日志统一走主界面底部日志框 (SimulinkModule.log_box), Panel 不再内置终端
        self.module.log_signal.emit("🎯 数据闭环控制台已打开 · 6环节流水线 + 三阶段训练 · 运行日志见主界面底部")

    def _reload_models(self):
        """2026-08-07 老倪: 列出所有已训练模型 (名字+训练时间), 供选择 sim-to-real/stage3"""
        self._model_meta = {}
        self.cmb_model.clear()
        import glob as _g
        for f in sorted(_g.glob(os.path.join(self.module._repo_root(), "reports", "train_curve_*.json"))):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            pol = d.get("policy", os.path.basename(f)[12:-5])
            _DISP = {"act": "ACT", "smolvla": "SmolVLA", "smolvla_lew": "SmolVLA+LEW",
                     "vla_touch": "VLA-Touch", "awe_zflow": "AWE", "expert_mlp": "MLP 蒸馏",
                     "expert_policy": "官方专家"}
            name = _DISP.get(pol, pol)
            _ts = d.get("ts", "")
            ts = f"{_ts[4:6]}-{_ts[6:8]} {_ts[9:11]}:{_ts[11:13]}" if len(_ts) == 15 and _ts[:8].isdigit() else time.strftime(
                "%m-%d %H:%M", time.localtime(os.path.getmtime(f)))
            cv = d.get("curve") or []
            tail = cv[-1][1] if cv else float("nan")
            self._model_meta[name] = {"policy": pol, "ckpt": d.get("ckpt", "?"),
                                      "loss": tail, "ts": ts, "steps": cv[-1][0] if cv else 0}
            self.cmb_model.addItem(f"{name} · {ts}")
        if self.cmb_model.count() == 0:
            self.cmb_model.addItem("(无已训练模型)")
        self.cmb_model.setCurrentIndex(2 if self.cmb_model.count() > 2 else 0)  # 默认 AWE(第3个)
        self._show_model_attr()

    def _show_model_attr(self):
        name = self.cmb_model.currentText().split(" · ")[0]
        m = self._model_meta.get(name)
        if not m:
            self.lbl_model_attr.setText("属性: —")
            return
        self.lbl_model_attr.setText(
            f"属性: ckpt={m['ckpt']} · 训练 {m['ts']} · {m['steps']} 步 · 尾loss {m['loss']:.3f}")

    def _on_sim2real(self):
        """2026-08-07 老倪: 选中模型 → Sim-to-Real 零样本测试 (S2)"""
        name = self.cmb_model.currentText().split(" · ")[0]
        m = self._model_meta.get(name)
        if not m:
            self.module.log_signal.emit("⚠️ 无选中模型")
            return
        st = self._read_state()
        st.setdefault("stages", {})["2"] = {"model": name, "policy": m["policy"],
                                            "status": "running", "ts": time.strftime("%m-%d %H:%M")}
        json.dump(st, open(self._STATE, "w", encoding="utf-8"), ensure_ascii=False)
        self.module.log_signal.emit(f"🎯 Sim-to-Real (S2): {name} → Orin 真实数据零样本测试 (量化 Reality Gap)")
        self._refresh()

    def _on_stage3(self):
        """2026-08-07 老倪: 选中模型 → Stage 3 真机微调"""
        name = self.cmb_model.currentText().split(" · ")[0]
        m = self._model_meta.get(name)
        if not m:
            self.module.log_signal.emit("⚠️ 无选中模型")
            return
        st = self._read_state()
        st.setdefault("stages", {})["3"] = {"model": name, "policy": m["policy"],
                                            "status": "running", "ts": time.strftime("%m-%d %H:%M")}
        json.dump(st, open(self._STATE, "w", encoding="utf-8"), ensure_ascii=False)
        self.module.log_signal.emit(f"🚀 Stage 3 真机微调: {name} · 权重初始化 {m['ckpt']} · lr 1e-5 · backbone 1e-6")
        self._refresh()

    def _refresh(self):
        st = self._read_state()
        stages = st.get("stages", {}) or {}
        # 闭环状态栏: 本地部分 (数据量/模型)
        try:
            n_train, n_pkgs = self._local_data_frames()
            self.lbl_data.setText(f"📥 数据: 训练集{n_train}帧" + (f" · 落地{n_pkgs}帧" if n_pkgs else ""))
        except Exception:
            pass
        ck3 = stages.get("3", {}).get("ckpt") or stages.get("1", {}).get("ckpt")
        if ck3:
            self.lbl_model.setText("🧠 模型: " + ck3.replace("\\", "/").split("/")[-4])
        # 最后运行时间标注 (状态文件 ts, 提示新旧)
        ts = st.get("ts") or ""
        self.lbl_stage_now.setText("当前: 未运行" if st.get("state") == "pending" else
                                   f"最后运行: {ts[5:16] if ts else '?'} · 状态{st.get('state', '?')}")
        for sid, b in self._pipe_btns.items():
            s = self.module._cicd_state.get(sid, 0)
            if s == 1:
                b.setStyleSheet("QPushButton { background:#00d4aa22; color:#00d4aa; border:1px solid #00d4aa; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:700; }")
            elif s == 2:
                b.setStyleSheet("QPushButton { background:#3fb95022; color:#3fb950; border:1px solid #3fb950; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:700; }")
            elif s == 3:
                b.setStyleSheet("QPushButton { background:#ff444422; color:#ff4444; border:1px solid #ff4444; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:700; }")
            else:
                b.setStyleSheet("QPushButton { background:#21262d; color:#8b949e; border:1px solid #1e2740; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:600; }"
                                "QPushButton:hover { border-color:#00d4aa; color:#00d4aa; }")
        for sid, (card, st_lbl, info) in self._cards.items():
            sid_st = stages.get(str(sid), {}).get("state", "pending")
            st_lbl.setText(self._STATUS_ICON.get(sid_st, "○"))
            st_lbl.setStyleSheet(f"color:{self._STATUS_COLOR.get(sid_st,'#57606a')}; font-size:13px; font-weight:700; background:transparent; border:none;")
            card.setStyleSheet("QFrame#stage%d { background:#161b22; border:2px solid %s; border-radius:10px; }"
                               % (sid, self._STATUS_COLOR.get(sid_st, "#1e2740")))
            sdata = stages.get(str(sid), {})
            def _ckpt_name(ck):
                parts = ck.replace("\\", "/").split("/")
                return parts[-4] if len(parts) >= 4 else ck
            if sid == 1 and sdata.get("ckpt"):
                info.setText("✓ 已完成 · " + _ckpt_name(sdata["ckpt"]))
            elif sid == 2 and sdata.get("result"):
                r = sdata["result"]
                sim = r.get("sim", {})
                if sim.get("action_mse") is not None:
                    line = f"仿真 MSE={sim['action_mse']:.4f} 成功率={sim.get('success_rate',0)*100:.0f}%"
                    if r.get("sim2real", {}).get("dim_mismatch"):
                        line += " · Sim2Real 维度不匹配→S3"
                    else:
                        rr = r.get("sim2real", {})
                        line += f" · Sim2Real MSE={rr.get('action_mse',0):.4f}"
                    info.setText(line)
                else:
                    info.setText("⚠️ 维度不匹配 → 必须微调 (S3)")
            elif sid == 3 and sdata.get("ckpt"):
                info.setText("✓ 已完成 · " + _ckpt_name(sdata["ckpt"]))
        now = st.get("stage", "?")
        stt = stages.get(str(now), {}).get("state", st.get("state", "pending"))
        self.lbl_stage_now.setStyleSheet(f"color:{self._STATUS_COLOR.get(stt,'#57606a')}; font-size:11px; font-family:Consolas; background:transparent; border:none;")

    def _run_pipeline_cmd(self, cmd):
        if getattr(self, "_worker", None) and self._worker.isRunning():
            self.module.log_signal.emit("⏳ 上一个任务还在跑…")
            return
        self.module.log_signal.emit("▶ " + " ".join(cmd))
        worker = CICDWorker(lambda: self._run_cli(cmd))
        worker.log.connect(self.module.log_signal.emit)
        worker.finished.connect(lambda: None)
        self._worker = worker
        worker.start()

    def _run_cli(self, cmd):
        import subprocess
        try:
            p = subprocess.Popen(cmd, cwd=self.module._repo_root(),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1, encoding="utf-8", errors="replace")
            for line in p.stdout:
                self.module.log_signal.emit(line.rstrip()[:200])
            p.wait()
            return (p.returncode == 0), ("管线命令完成 rc=%d" % p.returncode)
        except Exception as ex:
            return False, str(ex)

    def _run_full(self):
        s1 = self._spin[1].value() if 1 in self._spin else 300
        s3 = self._spin[3].value() if 3 in self._spin else 300
        self.module.log_signal.emit(f"🚀 全流程启动: Stage1={s1}步 → Stage2 → Stage3={s3}步")
        self._run_pipeline_cmd([self._PY, os.path.join(self.module._repo_root(), "tools", "cicd_pipeline.py"),
                                "run", "--steps1", str(s1), "--steps3", str(s3)])

    def _run_stage(self, sid):
        steps = self._spin[sid].value() if sid in self._spin else 0
        cmd = [self._PY, os.path.join(self.module._repo_root(), "tools", "cicd_pipeline.py"),
               "stage", str(sid)]
        if steps:
            cmd += ["--steps", str(steps)]
        self._run_pipeline_cmd(cmd)

    def closeEvent(self, e):
        self._timer.stop()
        self._remote_timer.stop()
        # 🛡 采集轮询线程清理 (2026-08-05 崩溃修复: QThread: Destroyed while thread is still running
        #   exit 134 SIGABRT — closeEvent 只停 _timer/_remote_timer, 没停 _acq_timer 且没等 _acq_worker,
        #   退出时 worker 还在跑 → 析构 QThread 崩溃)
        acq_timer = getattr(self, "_acq_timer", None)
        if acq_timer is not None:
            acq_timer.stop()
        aw = getattr(self, "_acq_worker", None)
        if aw is not None and aw.isRunning():
            try:
                aw.wait(3000)  # 最多等 3s, 避免退出时 worker 未结束
            except Exception:
                pass
        self._acq_worker = None
        # 🛡 全流程 worker 清理 (2026-08-05 崩溃修复#6: CICDPanel 的 _worker(CICDWorker)
        #   947行创建, closeEvent 漏清 → 训练/评估中关面板 → QThread destroyed exit 134)
        cw = getattr(self, "_worker", None)
        if cw is not None and cw.isRunning():
            try:
                import subprocess as _sp
                # 2026-08-12: 训练走 sudo docker run → sudo pkill 才能杀 root 进程
                for _pat in ("lerobot.scripts.lerobot_train", "tools.cicd_pipeline"):
                    _sp.run(["sudo", "-n", "pkill", "-9", "-f", _pat],
                            capture_output=True, timeout=8)
                # 🐳 容器训练兜底: docker kill (容器内进程 root, pkill 杀不掉)
                try:
                    _out = _sp.run(["sudo", "-n", "docker", "ps", "-q",
                                    "--filter", "ancestor=zmax-std:1.0"],
                                   capture_output=True, text=True, timeout=10).stdout or ""
                    for _cid in _out.split():
                        _sp.run(["sudo", "-n", "docker", "kill", _cid],
                                capture_output=True, timeout=10)
                except Exception:
                    pass
                if not cw.wait(15000):
                    self._keep_worker = cw  # 保留引用防 GC (崩溃修复#9 同款)
            except Exception:
                pass
        self._worker = None
        # 🛡 远程轮询 worker 清理 (2026-08-05 崩溃修复#8: CICDPanel 的 _remote_worker
        #   1103行创建, closeEvent 漏清 → 远程状态查询中关面板 → QThread destroyed exit 134)
        rw = getattr(self, "_remote_worker", None)
        if rw is not None and rw.isRunning():
            try:
                rw.wait(3000)
            except Exception:
                pass
        self._remote_worker = None
        # 🛡 录屏定时器清理 (2026-08-05 崩溃修复#2: 用户在录制中关闭窗口 → _rec_timer 还在跑
        #   → QThread: Destroyed while thread is still running exit 134)
        rec_timer = getattr(self, "_rec_timer", None)
        if rec_timer is not None:
            rec_timer.stop()
        self._rec_timer = None
        super().closeEvent(e)

    # ── 数据闭环状态: 本地数据量 + 远程轮询 ──
    def _local_data_frames(self):
        """训练数据集帧数 (orin_real_v1, 与训练口径一致) + 中转落地包帧数"""
        root = self.module._repo_root()
        n_train = 0
        info = os.path.join(root, "data", "orin_real_v1", "meta", "info.json")
        if os.path.exists(info):
            try:
                n_train = int(json.load(open(info, encoding="utf-8")).get("total_frames", 0))
            except Exception:
                pass
        n_pkgs = 0
        # 2026-08-07 老倪: closed_loop/orin 数据已删 — 采集包统计置 0 (目录不存在 glob 空)
        return n_train, n_pkgs

    def _poll_remote(self):
        """后台线程拉 relay/orin 状态 (不卡 UI)"""
        if getattr(self, "_remote_worker", None) and self._remote_worker.isRunning():
            return

        def _work():
            import requests as _rq
            out = {}
            try:
                r = _rq.get("https://datadrive.world/api/relay/status", timeout=6)
                if r.status_code == 200:
                    st = r.json()
                    out["pkgs"] = st.get("packages", 0)
                    meta = st.get("latest_meta") or {}
                    out["frames"] = meta.get("frames", None)
                    out["src"] = meta.get("source", None)
            except Exception:
                pass
            try:
                r = _rq.get("https://datadrive.world/api/relay/orin/status", timeout=6)
                if r.status_code == 200:
                    o = r.json()
                    out["online"] = o.get("online", False)
                    out["model"] = o.get("model", "?")
                    out["infer"] = o.get("infer_count", 0)
                    out["ms"] = o.get("last_infer_ms")
                    out["seen"] = o.get("last_seen", "?")
            except Exception:
                pass
            try:
                r = _rq.head("https://datadrive.world/models/act_cartesian.safetensors", timeout=6)
                out["url"] = r.status_code
            except Exception:
                out["url"] = None
            import json as _json
            return True, _json.dumps(out)

        def _done(ok, info):
            import json as _json
            try:
                d = _json.loads(info)
            except Exception:
                return
            pkgs = d.get("pkgs", 0)
            frm = d.get("frames")
            if pkgs is not None:
                extra = f" · 中转{pkgs}包" + (f"·{frm}帧" if frm else "")
                try:
                    n_train, _ = self._local_data_frames()
                    self.lbl_data.setText(f"📥 数据: 训练集{n_train}帧{extra}")
                except Exception:
                    self.lbl_data.setText(f"📥 数据: 中转{pkgs}包")
            online = d.get("online")
            if online is not None:
                color = "#3fb950" if online else "#ff4444"
                self.lbl_orin.setText(f"🤖 Orin: {'●在线' if online else '○离线'} · {d.get('model','?')} · 心跳{d.get('seen','?')}")
                self.lbl_orin.setStyleSheet(f"color:{color}; font-size:11px; font-family:Consolas; background:transparent; border:none;")
            if d.get("infer") is not None:
                ms = d.get("ms")
                self.lbl_infer.setText(f"⚡ 推理: {d.get('infer')}次" + (f" · {ms}ms" if ms else ""))
            if d.get("url"):
                self.lbl_url.setText(f"🔗 URL: {'✅' if d['url'] == 200 else '⚠️' + str(d['url'])} act_cartesian")

        worker = CICDWorker(_work)
        worker.finished_ok.connect(_done)
        worker.finished.connect(lambda: None)
        self._remote_worker = worker
        worker.start()


# ════════════════════════════════════════════════════════════════
# 画布节点 (QGraphicsItem)
# ════════════════════════════════════════════════════════════════
class SimNodeItem(QGraphicsObject):
    def __init__(self, node, scene_ref):
        super().__init__()
        self.node = node
        self.scene_ref = scene_ref
        self.w = node.get("w", 150)
        self.h = node.get("h", DH)   # 🎨 row_bg 背景行节点自定义高度 (2026-08-05)
        self.setPos(node["x"], node["y"])
        # 不用 ItemIsMovable: 拖动由 SimCanvas 手动 setPos 接管,
        # 避免 QGraphicsScene 默认"移动所有选中项"导致联动
        self.setFlags(QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(1 if node.get("type") == "row_bg" else 10)  # 🐛 2026-08-09: row_bg 垫底 (否则盖在节点上颜色模糊)
        # 🐛 2026-08-12 老倪: SimNodeItem 补 hover 机制 (原类无 hover 事件 →
        # _hover 恒 False → 悬停 ID 不显示; setAcceptHoverEvents 只在 SimLinkItem)
        self.setAcceptHoverEvents(True)
        self._hover = False

    def hoverEnterEvent(self, e):
        self._hover = True
        self.update()
        e.accept()

    def hoverLeaveEvent(self, e):
        self._hover = False
        self.update()
        e.accept()

    def mouseDoubleClickEvent(self, e):
        """🐛 2026-08-12 老倪: 节点双击处理 — 原类从未实现 (只有连线 SimLinkItem 有),
        用户双击节点一直无反应 (双击▶生成插拔视频/数据源切换等全靠右键菜单运行)"""
        self.scene_ref.on_node_activated(self.node)
        e.accept()

    def boundingRect(self):
        # 🐛 2026-08-12 老倪: 顶部扩 18px — 悬停 ID 浮在节点上方 (y=-18~-2) 需在 boundingRect 内才显示
        return QRectF(0, 0, self.w, self.h).adjusted(-12, -18, 12, 12)

    def paint(self, painter, opt, widget=None):
        t = self.node["type"]
        # 🎨 背景行节点 (Model Zoo): 整行彩色半透明色带 + 左侧大字模型名
        # 可编辑: 右键参数框改 name (大字)/ params.bg (背景色); 不与普通节点同规格绘制
        if t == "row_bg":
            p = self.node.get("params", {})
            color = QColor(p.get("bg", "#26418f"))
            w = self.node.get("w", 150)
            h = self.node.get("h", 214)
            painter.setRenderHint(QPainter.Antialiasing)
            # 整行色带: 深色底(alpha 120) + 色相(alpha 90) 叠加 — 深色画布上颜色清晰可见,
            # 不会因 alpha 过低显示成黑色块 (2026-08-05 修复: 原 alpha=40 在 #0a0a0f 画布上≈黑)
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 200), 1.2))
            painter.setBrush(QBrush(QColor(13, 17, 23, 120)))
            painter.drawRoundedRect(QRectF(0, 0, w, h), 10, 10)
            # 色相薄层 (让颜色明显)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 90)))
            painter.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 8, 8)
            # 左侧模型名 (竖向居中; 2026-08-05 修复: 去 emoji 前缀, 名字长则拆两行,
            #   大字区 130px 与节点列 (x≥120) 隔离 → 不再"重复/叠字")
            name = self.node.get("name", "")
            if name.startswith("🎨 "):
                name = name[2:]
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Arial", 15, QFont.Bold))
            # 拆行: "+" 处断开 (SmolVLA+LEW → SmolVLA / LEW)
            line1, line2 = name, ""
            if "+" in name:
                line1, line2 = name.split("+", 1)
            if line1 and line2:
                painter.drawText(QRectF(8, h / 2 - 24, 126, 24), Qt.AlignVCenter | Qt.AlignLeft, line1)
                painter.drawText(QRectF(8, h / 2 + 2, 126, 24), Qt.AlignVCenter | Qt.AlignLeft, line2)
            else:
                painter.drawText(QRectF(8, 0, 126, h), Qt.AlignVCenter | Qt.AlignLeft, name)
            # 左上角小标: 可编辑提示
            painter.setPen(QColor(255, 255, 255, 140))
            painter.setFont(QFont("Arial", 7))
            painter.drawText(QRectF(8, 4, 110, 12), Qt.AlignLeft | Qt.AlignTop,
                             "▤ 背景行")
            return
        color = QColor(COLORS.get(t, "#58a6ff"))
        # 运行状态色: idle=类型色 running=青色脉冲 success=绿 error=红
        status = self.node.get("status", "idle")
        if status == "running":
            color = QColor("#00d4aa")
        elif status == "success":
            color = QColor("#3fb950")
        elif status == "error":
            color = QColor("#ff4444")
        painter.setRenderHint(QPainter.Antialiasing)
        pal = THEMES[_CUR_THEME]  # 🎨 主题调色板
        # 主体
        grad = QLinearGradient(0, 0, 0, self.h)
        grad.setColorAt(0, QColor(pal["node_top"]))
        grad.setColorAt(1, QColor(pal["node_bot"]))
        painter.setBrush(grad)
        pen = QPen(color, 1.6)
        # 激活的数据源节点 (CICD 主控台): 金色加粗边框 + ▶ 徽章
        params = self.node.get("params", {})
        is_active_src = params.get("source") and params.get("active")
        if is_active_src:
            pen = QPen(QColor("#ffd700"), 2.6)
        if self.isSelected():
            pen.setWidthF(2.4)
            pen.setStyle(Qt.DashLine)
        # 引导高亮 (ACT-Meta 训练完成 → 金色粗框指引下一步节点)
        if self.node.get("hl"):
            pen = QPen(QColor("#ffd700"), 3.2)
        # ♻ 复用节点 (ACT vs SmolVLA 对比): 紫色粗框 + 复用徽章, 让用户清晰感知被两模型共用
        shared = self.node.get("params", {}).get("shared")
        if shared:
            pen = QPen(QColor("#a371f7"), 2.8)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(0, 0, self.w, self.h), 6, 6)
        # 标题 (2026-08-07 老倪: YOLO 3D显示不全 — 字符数截断改像素宽度自适应字号, 不截断)
        painter.setPen(QColor(pal["title"]))
        name = self.node["name"]
        f = QFont("Arial", 9, QFont.Bold)
        painter.setFont(f)
        fm = painter.fontMetrics()
        avail = max(40, self.w - 20)
        for pt in (9, 8, 7):
            if fm.horizontalAdvance(name) <= avail:
                break
            f = QFont("Arial", pt, QFont.Bold)
            painter.setFont(f)
            fm = painter.fontMetrics()
        disp = name
        if fm.horizontalAdvance(disp) > avail:
            disp = fm.elidedText(disp, Qt.ElideRight, avail)  # 兜底: 超宽省略号
        if params.get("video"):
            # 🎮 视频/推理节点: 名字放节点左下角 (2026-08-07 老倪: 居中仍偏上,
            #   改为左下角像图片说明), 不显示类型标签
            painter.setFont(QFont("Arial", 8, QFont.Bold))
            painter.drawText(QRectF(6, self.h - 18, self.w - 12, 14), Qt.AlignVCenter | Qt.AlignLeft, disp)
        else:
            painter.drawText(QRectF(12, 4, self.w - 16, 20), Qt.AlignVCenter | Qt.AlignLeft, disp)
        # 🤖 2026-08-09 老倪: 场景节点 — 右上角画小机器人图标 (参考半导体产线机器人)
        if t == "scene":
            try:
                _rx = self.w - 26
                _ry = 2
                _rc = QColor("#00d4aa")
                painter.setRenderHint(QPainter.Antialiasing)
                # 天线
                painter.setPen(QPen(_rc, 1.2))
                painter.drawLine(QPointF(_rx + 8, _ry - 1), QPointF(_rx + 8, _ry + 4))
                painter.drawEllipse(QPointF(_rx + 8, _ry - 3), 2.5, 2.5)
                # 头 (圆角矩形)
                painter.setBrush(QColor(0, 212, 170, 60))
                painter.drawRoundedRect(QRectF(_rx, _ry + 4, 16, 13), 3, 3)
                # 眼睛
                painter.setPen(QPen(_rc, 1.1))
                painter.drawPoint(QPointF(_rx + 5, _ry + 9))
                painter.drawPoint(QPointF(_rx + 11, _ry + 9))
                # 身体
                painter.drawRoundedRect(QRectF(_rx + 3, _ry + 19, 10, 9), 2, 2)
                # 手臂
                painter.drawLine(QPointF(_rx + 1, _ry + 21), QPointF(_rx - 2, _ry + 26))
                painter.drawLine(QPointF(_rx + 15, _ry + 21), QPointF(_rx + 18, _ry + 26))
            except Exception:
                pass
        # 🌐 2026-08-08 老倪: 画布节点全局 ID — 🐛 2026-08-12 老倪: 仅悬停显示
        # (右上角青色粗体 9px) — 常显占视觉, 用户要求鼠标放上才显示
        try:
            if getattr(self, "_hover", False) and self.node.get("type") != "row_bg":
                # 🐛 2026-08-12 老倪: ID 显示在右下角 (用户要求, 不遮挡标题/desc 主区)
                painter.setPen(QColor("#e6edf3"))
                painter.setFont(QFont("Arial", 9, QFont.Bold))
                nid = self.node.get("nid") or str(self.node.get("id", ""))
                painter.drawText(QRectF(8, self.h - 16, self.w - 16, 14), Qt.AlignRight | Qt.AlignVCenter, nid)
        except Exception:
            pass
        # 类型标签 (Switch 显示当前选择: SEL: orin/metaworld) — 浅色主题下用深灰文字
        painter.setPen(QColor(pal["label"]))
        painter.setFont(QFont("Arial", 7))
        if params.get("video"):
            pass  # 视频节点: 无类型标签 (名字已居中)
        if t == "switch":
            painter.drawText(QRectF(12, 22, self.w - 16, 14), Qt.AlignVCenter | Qt.AlignLeft,
                             f"🔀 SEL: {params.get('switch', 'orin')}")
        elif t == "yolo_gate":
            # 🎯 YOLO 感知开关 (2026-08-06 老倪: state 输入 switch, 默认开=39D)
            en = params.get("yolo_enabled", True)
            gate_col = QColor("#d4a800") if en else QColor("#8b949e")
            cb = QRectF(12, 24, 13, 13)
            painter.setBrush(QColor("#0d1117"))
            painter.setPen(QPen(gate_col, 1.4))
            painter.drawRect(cb)
            if en:
                painter.setPen(QPen(gate_col, 1.8))
                painter.drawLine(QPointF(cb.x()+2, cb.y()+7), QPointF(cb.x()+5, cb.y()+10))
                painter.drawLine(QPointF(cb.x()+5, cb.y()+10), QPointF(cb.x()+11, cb.y()+3))
            painter.setPen(QColor(pal["label"]))
            painter.drawText(QRectF(30, 24, self.w - 34, 14), Qt.AlignVCenter | Qt.AlignLeft,
                             f"YOLO: {'39D 开' if en else '3D 关'}")
        elif t == "coord_overlay":
            # 🧩 结构条件 (2026-08-08 老倪: 坐标是逻辑主线, 图像是背景 — 叠加进 latent)
            gate = params.get("overlay_gate", 1.0)
            sd = params.get("state_dim", 45)
            # 画 + 号 (叠加标志)
            px, py = 18, 30
            painter.setPen(QPen(QColor("#58a6ff"), 1.8))
            painter.drawLine(QPointF(px-6, py), QPointF(px+6, py))
            painter.drawLine(QPointF(px, py-6), QPointF(px, py+6))
            painter.setPen(QColor(pal["label"]))
            painter.drawText(QRectF(30, 24, self.w - 34, 14), Qt.AlignVCenter | Qt.AlignLeft,
                             f"叠加: latent += state×{gate:.1f} ({sd}D)")
        elif t == "train_gate":
            # ☑ 训练开关 (2026-08-05 老倪: checkbox 打勾=训练 / 不打=不训练)
            en = params.get("train_enabled", True)
            gate_col = QColor("#3fb950") if en else QColor("#f85149")
            # 绘制 checkbox 方块 + 对号
            cb = QRectF(12, 24, 13, 13)
            painter.setBrush(QColor("#0d1117"))
            painter.setPen(QPen(gate_col, 1.4))
            painter.drawRect(cb)
            if en:
                painter.setPen(QPen(gate_col, 1.8))
                painter.drawLine(QPointF(cb.left() + 2.5, cb.top() + 6.5),
                                 QPointF(cb.left() + 5.5, cb.top() + 9.5))
                painter.drawLine(QPointF(cb.left() + 5.5, cb.top() + 9.5),
                                 QPointF(cb.left() + 10.5, cb.top() + 3.5))
            painter.setFont(QFont("Arial", 8, QFont.Bold))
            painter.setPen(QColor("#e6edf3") if en else QColor("#f85149"))
            painter.drawText(QRectF(29, 22, self.w - 40, 16), Qt.AlignVCenter | Qt.AlignLeft,
                             "训练: 开" if en else "训练: 关")
        else:
            if not params.get("video"):
                # 视频节点名字已居中, 不画类型标签 (2026-08-07 老倪)
                painter.drawText(QRectF(12, 22, self.w - 16, 14), Qt.AlignVCenter | Qt.AlignLeft,
                                 NODE_TYPES.get(t, {}).get("cn", t))
        # 状态徽章 (右上角: ● 运行中 / ✓ 成功 / ✕ 失败)
        st_icon = {"running": "●", "success": "✓", "error": "✕"}.get(status, "")
        if is_active_src:
            st_icon = "▶"  # 激活数据源
        if shared:
            st_icon = "♻"  # 复用节点 (被两模型共用, 紫框)
        if st_icon:
            painter.setPen(color)
            painter.setFont(QFont("Arial", 9, QFont.Bold))
            painter.drawText(QRectF(self.w - 22, 2, 20, 16), Qt.AlignRight | Qt.AlignVCenter, st_icon)
        # 端口: Switch 双输入 (左上下) + 单输出 (右中); 其他节点单进单出
        if t == "switch":
            sel = params.get("switch", "orin")
            for idx, key in ((0, "orin"), (1, "metaworld")):
                py = 12 + idx * 26  # 上: in1(orin) 下: in2(metaworld)
                active = (key == sel)
                painter.setBrush(QColor("#3fb950") if active else color)
                painter.setPen(QPen(QColor(pal["port_edge"]), 1))
                r = 7 if active else 5
                painter.drawEllipse(QPointF(0, py), r, r)
            painter.setBrush(color)
            painter.setPen(QPen(QColor(pal["port_edge"]), 1))
            painter.drawEllipse(QPointF(self.w, self.h / 2), 5, 5)
        else:
            # 📐 端口垂直分布 (2026-08-07): 多入/多出节点端口散开, 与连线终点对齐;
            # 无连线保持中间单端口 (拖线起点/终点交互不变)
            nid = self.node["id"]
            n_in = sum(1 for l in self.scene_ref.links if l["t"] == nid)
            n_out = sum(1 for l in self.scene_ref.links if l["f"] == nid)
            if n_in:
                for i in range(n_in):
                    py = self.h * (i + 1) / (n_in + 1)
                    painter.setBrush(color)
                    painter.setPen(QPen(QColor(pal["port_edge"]), 1))
                    painter.drawEllipse(QPointF(0, py), 5, 5)
            else:
                painter.setBrush(color)
                painter.setPen(QPen(QColor(pal["port_edge"]), 1))
                painter.drawEllipse(QPointF(0, self.h / 2), 5, 5)
            if n_out:
                for i in range(n_out):
                    py = self.h * (i + 1) / (n_out + 1)
                    painter.setBrush(color)
                    painter.setPen(QPen(QColor(pal["port_edge"]), 1))
                    painter.drawEllipse(QPointF(self.w, py), 5, 5)
            else:
                painter.setBrush(color)
                painter.setPen(QPen(QColor(pal["port_edge"]), 1))
                painter.drawEllipse(QPointF(self.w, self.h / 2), 5, 5)
        # 参数摘要
        params = self.node.get("params", {})
        if params:
            first = list(params.items())[0]
            painter.setPen(QColor(pal["label"]))
            painter.setFont(QFont("Consolas", 7))
            painter.drawText(QRectF(12, 36, self.w - 16, 12), Qt.AlignVCenter | Qt.AlignLeft,
                             f"{first[0]}={first[1]}")

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            self.node["x"] = round(value.x())
            self.node["y"] = round(value.y())
            self.scene_ref.on_node_moved(self)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, e):
        # CICD 主控台: 双击节点 → 数据源切换 / 运行环节 / 参数框
        self.scene_ref.on_node_activated(self.node)
        e.accept()

    # ⚠️ 无 contextMenuEvent — 右键统一走 SimCanvas.mousePressEvent(RightButton) 分支:
    #   系统 QContextMenuEvent 的 screenPos 在 WSLg 虚拟屏坐标异常(菜单弹出屏幕外=没反应),
    #   且与 canvas 分支会双弹. 菜单用 viewport().mapToGlobal(e.pos()) 坐标最可靠.


# ════════════════════════════════════════════════════════════════
# 连线 (贝塞尔, 与 web 同款)
# ════════════════════════════════════════════════════════════════
class SimLinkItem(QGraphicsObject):
    def __init__(self, link, src, dst, scene_ref):
        super().__init__()
        self.link = link
        self.src = src
        self.dst = dst
        self.scene_ref = scene_ref
        self.setZValue(5)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self._hover = False
        self._flow_offset = 0.0   # 流动动画偏移 (运行中)
        self._anim_timer = QTimer()
        self._anim_timer.timeout.connect(self._tick_flow)
        self._anim_timer.start(80)

    def _switch_active(self):
        """链路流入 Switch 节点时, 是否被当前路由选中:
        选中 → 正常(可流动); 未选中 → 停流+暗灰 (老倪 2026-08-02: '选metaworld, orin那条线不该流动')"""
        dst = self.dst.node
        if dst.get("type") != "switch":
            return True
        sel = dst.get("params", {}).get("switch", "orin")
        src = self.src.node
        side = src.get("params", {}).get("source")
        if side:
            return side == sel
        nm = src.get("name", "").lower()
        if "orin" in nm:
            return sel == "orin"
        if "metaworld" in nm:
            return sel == "metaworld"
        return True

    def _tick_flow(self):
        """流动动画: 链路被 switch 选中 且 源节点运行/成功 → 推进偏移; 否则停流"""
        if self._switch_active() and self.src.node.get("status") in ("success", "running"):
            self._flow_offset += 2.0
            self.update()
        elif self._flow_offset != 0:
            self._flow_offset = 0
            self.update()

    def boundingRect(self):
        """动态覆盖实际路径区域 (Simulink 连线命中区), 避免固定矩形"""
        path = self._path()
        r = path.boundingRect()
        return r.adjusted(-12, -12, 12, 12)

    def shape(self):
        """连线命中区域 = 路径本身 (细长), 避免巨大矩形误吞点击"""
        stroker = QPainterPathStroker()
        stroker.setWidth(14)
        return stroker.createStroke(self._path())

    def _path(self):
        a = self.src.scenePos()
        b = self.dst.scenePos()
        # 📐 端口垂直分布 (2026-08-07): 按 _draw_links 预分配的序号/总数,
        #   switch 特殊双输入端口保持固定位置
        if self.src.node.get("type") == "switch":
            ax, ay = a.x() + self.src.w, a.y() + self.src.h / 2
        else:
            fo, no = self.link.get("_fo", 0), self.link.get("_no", 1)
            ax = a.x() + self.src.w
            ay = a.y() + self.src.h * (fo + 1) / (no + 1)
        if self.dst.node.get("type") == "switch":
            bx, by = b.x(), b.y() + self.dst.h / 2
        else:
            ti, mi = self.link.get("_ti", 0), self.link.get("_mi", 1)
            bx = b.x()
            by = b.y() + self.dst.h * (ti + 1) / (mi + 1)
        c1x, c2x = ax + (bx - ax) * .5, bx - (bx - ax) * .5
        path = QPainterPath(QPointF(ax, ay))
        path.cubicTo(c1x, ay, c2x, by, bx, by)
        return path

    def paint(self, painter, opt, widget=None):
        t = self.src.node["type"]
        color = QColor(COLORS.get(t, "#58a6ff"))
        painter.setRenderHint(QPainter.Antialiasing)
        path = self._path()
        active = self._switch_active()
        # 未选中链路 (switch 未选该输入): 暗灰实线, 永不流动 — 与选中链路明显区分
        # 🐛 2026-08-06 修复: 原 pal["inactive"] 引用已删除的主题字典 → NameError 反复崩溃
        if not active:
            color = QColor("#8b949e")  # 未选中暗灰
        pen = QPen(color, 2.5 if self._hover or self.isSelected() else 1.8)
        # 数据流动画: 链路被 switch 选中 且 源节点成功/运行中 → 虚线流动
        flowing = active and self.src.node.get("status") in ("success", "running")
        if flowing:
            pen.setStyle(Qt.DashLine)
            pen.setDashPattern([6, 4])
            pen.setDashOffset(-self._flow_offset)
        elif self.isSelected():
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawPath(path)
        # 🏷 数据流标签 (2026-08-05 老倪: 数据节点三路输出 图像/状态/动作 要标清楚)
        # 画在贝塞尔中点, 半透明底 + 主题色文字, 不干扰连线
        lbl = self.link.get("label", "")
        if lbl:
            mid = path.pointAtPercent(0.5)
            painter.setFont(QFont("Consolas", 7))
            fm = painter.fontMetrics()
            lw = fm.horizontalAdvance(lbl) + 8
            lh = fm.height() + 2
            lr = QRectF(mid.x() - lw / 2, mid.y() - lh / 2, lw, lh)
            painter.setBrush(QColor(0, 0, 0, 160))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(lr, 3, 3)
            painter.setPen(QColor("#e6edf3"))
            painter.drawText(lr, Qt.AlignCenter, lbl)
        # 箭头 (指向输入, 2026-08-07: 与端口分布一致)
        b = self.dst.scenePos()
        if self.dst.node.get("type") == "switch":
            bx, by = b.x(), b.y() + self.dst.h / 2
        else:
            ti, mi = self.link.get("_ti", 0), self.link.get("_mi", 1)
            bx = b.x()
            by = b.y() + self.dst.h * (ti + 1) / (mi + 1)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        tri = QPolygonF([QPointF(bx - 3, by - 4), QPointF(bx - 3, by + 4), QPointF(bx + 4, by)])
        painter.drawPolygon(tri)

    def hoverEnterEvent(self, e):
        self._hover = True; self.update(); e.accept()

    def hoverLeaveEvent(self, e):
        self._hover = False; self.update(); e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 点击连线删除 (对标 web: 点击连线中点删除)
            self.scene_ref.delete_link(self.link)
            e.accept()
        else:
            super().mousePressEvent(e)


# ════════════════════════════════════════════════════════════════
# 画布视图
# ════════════════════════════════════════════════════════════════
class SimCanvas(QGraphicsView):
    flow_changed = pyqtSignal()
    log = pyqtSignal(str)

    def __init__(self, module):
        super().__init__()
        self.module = module
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QColor(THEMES[_CUR_THEME]["canvas"]))
        # 🐛 2026-08-12 老倪: 必须开 mouseTracking — 否则无按键时 QGraphicsView
        # 不分发 hover 事件给节点 → _hover 永远 False → 悬停 ID 不显示
        self.setMouseTracking(True)
        # NoDrag: 让 ItemIsMovable 的节点可自由拖动 (RubberBandDrag 会拦截节点移动)
        self.setDragMode(QGraphicsView.NoDrag)
        # 空格键临时平移 (Simulink 习惯: 按住空格拖动画布)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self._drag_from = None       # 连线起点 (SimNodeItem)
        self._tmp_line = None        # 临时连线
        self._drag_node = None       # 手动拖动的节点 (只移动它, 绕开scene多选)
        self._drag_offset = QPointF()  # 按下点与节点原点的偏移
        self._drag_start = None      # 拖动起始 (id, x, y) — Ctrl+Z 回退用 (2026-08-07)
        self._panning = False
        self._pan_start = None
        self._hover_items = set()  # 🐛 2026-08-12 老倪: hover 节点集合
        # 🐛 2026-08-12 老倪: 悬停轮询 — VcXsrv 下无按键 mouseMove 事件不达画布
        # (点击才有响应) → QCursor 150ms 轮询; 鼠标不动不重绘 (防狂闪); parent=this 防关闭崩溃
        self._hover_timer = QTimer(self)
        self._hover_timer.timeout.connect(self._poll_hover)
        self._hover_timer.start(150)
        self._last_hover_pos = None
        self._scale = 1.0
        # ↩️ Ctrl+Z 撤销 (2026-08-07 老倪: 挪动背景行回不去上一步)
        # WidgetWithChildrenShortcut: 焦点在画布内才触发, 不抢搜索框/输入框的原生撤销
        from PyQt5.QtWidgets import QShortcut
        self._sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._sc_undo.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_undo.activated.connect(self.module.undo)

    def drawBackground(self, painter, rect):
        # 网格点 (Simulink 画布风格) — 颜色走主题 (2026-08-05 修复: 硬编码 #f0f2f5 浅色
        # 每次重绘盖住深色 backgroundBrush → 画布永远白色, palette 设置无效)
        pal = THEMES[_CUR_THEME]
        painter.fillRect(rect, QColor(pal["canvas"]))
        grid = 40
        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)
        painter.setPen(QPen(QColor(pal["grid"]), 1))
        for x in range(left, int(rect.right()), grid):
            for y in range(top, int(rect.bottom()), grid):
                painter.drawPoint(x, y)

    def wheelEvent(self, e):
        # Ctrl+滚轮 = 缩放 (对标 web)
        if e.modifiers() & Qt.ControlModifier:
            factor = 1.1 if e.angleDelta().y() > 0 else 0.9
            self._scale = max(0.2, min(3.0, self._scale * factor))
            self.scale(factor, factor)
            self.module.on_zoom(self._scale)
        else:
            super().wheelEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.RightButton:
            # 🆕 右键节点 → 查看/编辑节点逻辑.
            # ⚠️ 不用 QGraphicsSceneContextMenuEvent.screenPos() (WSLg 虚拟屏下坐标异常, 菜单弹出屏幕外=没反应)
            # 用 viewport 事件坐标 mapToGlobal, WSLg 可靠.
            item = self.itemAt(e.pos())
            if isinstance(item, SimNodeItem):
                self._show_node_menu(item, e.pos())
                return
            super().mousePressEvent(e)
            return
        if e.button() == Qt.LeftButton:
            item = self.itemAt(e.pos())
            # 点击节点
            if isinstance(item, SimNodeItem):
                p = self.mapToScene(e.pos())
                n = item
                rp = n.scenePos()
                out_x = rp.x() + n.w
                mid_y = rp.y() + n.h / 2
                # 输出端口 → 连线模式
                if abs(p.x() - out_x) < 12 and abs(p.y() - mid_y) < 12:
                    self._drag_from = n
                    self._tmp_line = self._scene.addLine(0, 0, 0, 0,
                        QPen(QColor(COLORS.get(n.node["type"], "#58a6ff")), 2, Qt.DashLine))
                    return
                # 节点主体 → 手动拖动 (只移动它, 绕开 scene 多选联动)
                # 🐛 2026-08-12 老倪: 双击检测 — 本分支 return 拦截 press, item 收不到
                # 双击事件 (SimNodeItem.mouseDoubleClickEvent 永不触发) → 手动检测
                import time as _t
                _now = _t.time()
                if (getattr(self, "_last_dbl", None) and _now - self._last_dbl[0] < 0.4
                        and self._last_dbl[1] is item):
                    self._last_dbl = None
                    self.module.on_node_activated(item.node)
                    return
                self._last_dbl = (_now, item)
                if not (e.modifiers() & Qt.ControlModifier):
                    for it in self._scene.selectedItems():
                        if it is not item:
                            it.setSelected(False)
                    item.setSelected(True)
                self._drag_node = item
                self._drag_offset = p - rp
                self._drag_start = (item.node["id"], rp.x(), rp.y())  # ↩️ 撤销起点
                return
        super().mousePressEvent(e)
        # 点击空白处 (非Ctrl): 清除所有选中
        if e.button() == Qt.LeftButton and not (e.modifiers() & Qt.ControlModifier):
            item = self.itemAt(e.pos())
            if not isinstance(item, (SimNodeItem, SimLinkItem)):
                self._scene.clearSelection()

    def _show_node_menu(self, item, view_pos):
        """右键节点菜单 (viewport 全局坐标, WSLg 可靠; 深色QSS防黑字)
        🐛 2026-08-10 老倪: 菜单跑到另外屏幕 — mapToGlobal 在 WSLg 多屏下屏幕归属错位
        → 用 QCursor.pos() 跟随系统光标真实位置, 菜单必在鼠标处弹出"""
        menu = QMenu()
        # 🐛 2026-08-12 老倪: 深色 QSS 在 VcXsrv 下渲染成黑屏无字 (border-radius 或
        # 背景色合成失败) → 完全去掉 QSS 用系统默认菜单; 菜单项去 emoji (字体缺字形→黑块)
        a_logic = menu.addAction("查看/编辑节点逻辑")
        a_param = menu.addAction("节点参数")
        # 2026-08-05 老倪: 训练节点右键 → 训练配置 (步数/batch/lr)
        a_train = None
        if "训练" in item.node.get("name", ""):
            a_train = menu.addAction("训练配置 (步数/batch/lr)")
        # 📂 打开源代码 (2026-08-12 老倪: YOLO/双脑等节点 params.source 映射源码目录;
        #   仅 src/ 开头显示 — 数据源节点的 source 是数据源标识非代码路径)
        a_src = None
        _nsrc = item.node.get("params", {}).get("source", "")
        if _nsrc.startswith("src/"):
            a_src = menu.addAction("打开源代码")
        a_run = menu.addAction("运行节点")
        from PyQt5.QtGui import QCursor
        chosen = menu.exec_(QCursor.pos())  # 🐛 2026-08-10: 光标真实位置, 多屏不跑偏
        if chosen == a_logic:
            self.module.on_show_node_logic(item.node)
        elif chosen == a_param:
            self.module.on_node_params(item.node)
        elif a_train is not None and chosen == a_train:
            self.module.on_train_config(item.node)
        elif a_src is not None and chosen == a_src:
            self.module.open_node_source(item.node)
        elif chosen == a_run:
            self.module.on_node_activated(item.node)

    def _poll_hover(self):
        """🐛 2026-08-12 老倪: 150ms 轮询鼠标位置 → 悬停显示 ID (VcXsrv 无按键 mouseMove 不达)"""
        try:
            from PyQt5.QtGui import QCursor
            gp = QCursor.pos()
            if gp == self._last_hover_pos:
                return  # 鼠标没动 → 不重绘 (防狂闪)
            self._last_hover_pos = gp
            if not self.isVisible() or not self.underMouse():
                self._clear_hover()
                return
            vp = self.mapFromGlobal(gp)
            if not self.viewport().rect().contains(vp):
                self._clear_hover()
                return
            self._update_hover_at(vp)
        except Exception:
            pass

    def _clear_hover(self):
        for it in list(self._hover_items):
            try:
                if it.scene() is not None:
                    it._hover = False
                    it.update()
            except Exception:
                pass
        self._hover_items = set()

    def _update_hover_at(self, vp_pos):
        """根据 viewport 坐标更新 hover 状态 (mouseMove 与轮询共用)"""
        item = self.itemAt(vp_pos)
        node_item = item if isinstance(item, SimNodeItem) and item.node.get("type") != "row_bg" \
            and item.scene() is not None else None
        for it in list(self._hover_items):
            if it.scene() is None or it is not node_item:
                try:
                    it._hover = False
                    it.update()
                except Exception:
                    pass
        if node_item is not None and not node_item._hover:
            node_item._hover = True
            node_item.update()
        self._hover_items = {node_item} if node_item is not None else set()

    def mouseMoveEvent(self, e):
        # 🐛 2026-08-12 老倪: hover 状态由鼠标位置直接驱动 (QGraphicsItem hover 事件
        # 在 VcXsrv 下迟钝/不触发 → ID 显示异常; itemAt 实时检测, 反应即时)
        try:
            self._update_hover_at(e.pos())
        except Exception:
            pass
        if self._panning:
            delta = e.pos() - self._pan_start
            self._pan_start = e.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        if self._drag_from and self._tmp_line:
            p = self.mapToScene(e.pos())
            s = self._drag_from.scenePos()
            self._tmp_line.setLine(s.x() + self._drag_from.w, s.y() + self._drag_from.h / 2, p.x(), p.y())
            return
        if self._drag_node:
            # 手动拖动: 只移动按下的节点
            p = self.mapToScene(e.pos())
            self._drag_node.setPos(p - self._drag_offset)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            return
        if self._drag_from and self._tmp_line:
            self._scene.removeItem(self._tmp_line)
            self._tmp_line = None
            item = self.itemAt(e.pos())
            if isinstance(item, SimNodeItem) and item is not self._drag_from:
                self.module.add_link(self._drag_from, item)
            self._drag_from = None
            return
        if self._drag_node:
            nid, ox, oy = self._drag_start or (None, 0, 0)
            self._drag_node = None
            self._drag_start = None
            # ↩️ 位置变了才入撤销栈 (2026-08-07: 拖动结束回退一步)
            if nid is not None:
                it = self.module._items.get(nid) if self.module else None
                if it is not None and (abs(it.scenePos().x() - ox) > 0.5
                                       or abs(it.scenePos().y() - oy) > 0.5):
                    self.module._push_undo(("move", [(nid, ox, oy)]))
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            self.module.delete_selected()
            return
        if e.modifiers() & Qt.ControlModifier and e.key() == Qt.Key_D:
            self.module.duplicate_selected()
            return
        super().keyPressEvent(e)


# ════════════════════════════════════════════════════════════════
# 模块库面板 (左侧, 对标 Simulink Library Browser)
# ════════════════════════════════════════════════════════════════
class LibraryPanel(QFrame):
    # 📚 模块库左侧栏折叠信号 (2026-08-06 老倪: 太占地方, 可缩到左边)
    collapse_requested = pyqtSignal()

    def __init__(self, module):
        super().__init__()
        self.module = module
        self.setFixedWidth(220)
        self.setStyleSheet("background:#f6f8fa; border-right:1px solid #d0d7de;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        # 标题行: 📚 模块库 + 折叠按钮 ◀ (2026-08-06 老倪: 隐藏左侧栏省地方;
        #   v2 2026-08-06: 按钮加大加醒目 + 双击标题也可折叠)
        head = QHBoxLayout()
        title = QLabel("📚 模块库")
        title.setStyleSheet("color:#1f2328; font-size:13px; font-weight:700; padding:4px;")
        head.addWidget(title)
        head.addStretch()
        btn_collapse = QPushButton("◀ 收起")
        btn_collapse.setFixedWidth(72)
        btn_collapse.setToolTip("隐藏模块库左侧栏, 画布占满 (再点左缘 ▶ 展开)")
        # 🎨 用浅底样式 (switch_theme 会正确转深色; 之前 #1f6feb 蓝底白字被
        # switch_theme 把白字替换成深色 → 蓝底深字看不清, 老倪反馈找不到)
        btn_collapse.setStyleSheet("""
            QPushButton{background:#e9edf2; color:#1f6feb; border:1px solid #d0d7de;
                        border-radius:4px; font-size:11px; font-weight:700; padding:4px 8px;}
            QPushButton:hover{border-color:#1f6feb; background:#dbe9ff;}
        """)
        btn_collapse.clicked.connect(self.collapse_requested.emit)
        head.addWidget(btn_collapse)
        lay.addLayout(head)
        # 双击「📚 模块库」标题也可折叠 (2026-08-06 v2: 更易发现)
        title.mousePressEvent = self._title_clicked

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.v = QVBoxLayout(self.inner)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(2)

        # 工作流标签页 → 显示全部
        self._current_wf = None
        self._rebuild()

        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll)

        hint = QLabel("点击添加 · 双击改参 · 输出→输入连线\n点线删除 · Ctrl+滚轮缩放")
        hint.setStyleSheet("color:#57606a; font-size:9px; padding:4px;")
        lay.addWidget(hint)

    def _title_clicked(self, ev):
        """双击标题 → 折叠左侧栏 (2026-08-06 v2: 用户反馈找不到 ◀ 按钮)"""
        import time as _t
        now = _t.time()
        last = getattr(self, "_title_click_ts", 0.0)
        self._title_click_ts = now
        if now - last < 0.4:  # 双击
            self.collapse_requested.emit()

    def _rebuild(self):
        """重建模块库列表 (按工作流过滤)"""
        # 清空
        while self.v.count():
            item = self.v.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._lib_btns = {}  # 模块名 → 按钮 (引导高亮用)
        # 📚 分组折叠状态 (2026-08-06 老倪: System2/SYS1/SYS0 列表栏也要能隐藏 —
        #   点击分组标题 折叠/展开 该组模块按钮, ▾ 展开 / ▸ 收起)
        if not hasattr(self, "_group_collapsed"):
            self._group_collapsed = {}
        for ntype, gname, items in LIBRARY:
            # 工作流过滤: 按节点类型匹配
            wf_of = {t: wf for wf, t in WORKFLOW_TYPES.items()}
            if self._current_wf and wf_of.get(ntype) != self._current_wf:
                continue
            collapsed = self._group_collapsed.get(gname, False)
            marker = "▸ " if collapsed else "▾ "
            lab = QLabel(f"{marker}{gname}")
            lab.setStyleSheet(f"color:{COLORS[ntype]}; font-size:11px; font-weight:700; padding:6px 2px 2px;")
            lab.setToolTip("点击 折叠/展开 该分组")
            lab.setCursor(Qt.PointingHandCursor)
            # 点击标题 → toggle 该组按钮可见性
            lab.mousePressEvent = lambda ev, gn=gname, lbl=lab: self._toggle_group(gn, lbl)
            self.v.addWidget(lab)
            for it in items:
                btn = QToolButton()
                _seq = lib_seq_of(it['name'])
                btn.setText(f"⬡  {it['name']}" + (f"  ·  VEH.5.{_seq:03d}" if _seq else ""))
                btn.setToolTip((f"VEH.5.{_seq:03d} — " if _seq else "") + f"{it['name']} (与画布节点 ID 一致)")
                btn.setStyleSheet(f"""
                    QToolButton {{ background:#e9edf2; color:#24292f; border:1px solid #d0d7de;
                    border-radius:4px; padding:4px 8px; font-size:11px; text-align:left; }}
                    QToolButton:hover {{ border-color:{COLORS[ntype]}; color:#1f2328; }}
                """)
                if it.get("params", {}).get("scene_id"):
                    # 🏭 场景 (2026-08-09 老倪: 点击 → 只打开 3D 链接, 不建子模块)
                    btn.clicked.connect(lambda _, sid=it["params"]["scene_id"]: self.module.open_scene_link(sid))
                elif it.get("params", {}).get("atomic_gate"):
                    # 🧩 原子 (2026-08-09 老倪: 打开原子技能 → 结构条件 → SYS1 → action)
                    btn.clicked.connect(lambda _, nm=it["name"]: self.module.open_atomic_skill_flow(nm))
                elif it.get("flow"):
                    # 🐛 2026-08-09 老倪: 点击加载保存的工作流 JSON (总系统)
                    btn.clicked.connect(lambda _, fl=it["flow"]: self.module.load_flow_file(fl))
                elif it.get("template"):
                    # 完整模型条目: 点击加载模板
                    btn.clicked.connect(lambda _, tpl=it["template"]: self.module.load_reference_app_by_name(tpl))
                else:
                    btn.clicked.connect(lambda _, t=ntype, nm=it["name"], ps=it["params"]:
                                        self.module.add_node_at_center(t, nm, ps))
                self._lib_btns[it["name"]] = btn
                btn.setVisible(not collapsed)  # 分组折叠时隐藏组内按钮
                self.v.addWidget(btn)
        # 📦 数据集组 (2026-08-07 老倪: 功能块同步显示已有数据集 — 插销/套环/Orin)
        root = self.module._repo_root() if hasattr(self.module, "_repo_root") else os.path.expanduser("~/lerobot-smolvla-lew")
        _dset_cands = [
            ("metaworld_peg", "插销插拔 (lerobot)", "metaworld"),
        ]
        _exists = [c for c in _dset_cands if os.path.isdir(os.path.join(root, "data", c[0]))]
        if _exists:
            lab = QLabel(f"▾ 📦 数据集 (已有 {len(_exists)})")
            lab.setStyleSheet("color:#d29922; font-size:11px; font-weight:700; padding:6px 2px 2px;")
            lab.setToolTip("已有训练数据集 (插销/套环/Orin) — 点击拖入画布作为数据源")
            self.v.addWidget(lab)
            for d, desc, src in _exists:
                btn = QToolButton()
                btn.setText(f"📦 {d}")
                btn.setStyleSheet("QToolButton { background:#e9edf2; color:#24292f; border:1px solid #d0d7de;"
                                  " border-radius:4px; padding:4px 8px; font-size:11px; text-align:left; }"
                                  "QToolButton:hover { border-color:#d29922; color:#1f2328; }")
                btn.setToolTip(f"{desc} — 双击画布数据源节点可切换")
                btn.clicked.connect(lambda _, dd=d, ds=desc, ss=src:
                                    self.module.add_node_at_center(
                                        "data", f"📦 {dd} 数据",
                                        {"source": ss, "data_dir": dd, "frames": "?", "active": True,
                                         "desc": f"{ds} · data/{dd} (功能块同步显示)"}))
                self.v.addWidget(btn)
        # 🏭 场景分组 (2026-08-09 老倪: 数据集分组下面 — 三场景 node, 点击打开 ECS 链接 + 建节点链)
        try:
            import json as _j
            _sp = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "flows", "scene_skills_3scenarios.json")
            _scenes = _j.load(open(_sp, encoding="utf-8")).get("scenes", [])
        except Exception:
            _scenes = []
        if _scenes:
            lab = QLabel("▾ 🏭 场景 (光模块工厂三大工艺)")
            lab.setStyleSheet("color:#00d4aa; font-size:11px; font-weight:700; padding:6px 2px 2px;")
            lab.setToolTip("光模块工厂真实场景 — 点击打开 ECS 可视化链接 + 建场景节点链")
            self.v.addWidget(lab)
            _ICON = {"SCN-01": "🔌", "SCN-02": "🤖", "SCN-03": "🔍"}
            for s in _scenes:
                _perf = s.get("performance", {})
                btn = QToolButton()
                btn.setText(f"{_ICON.get(s['id'], '🏭')} {s['id']} {s['name'][:14]} · {_perf.get('operation_success_rate', '')}")
                btn.setStyleSheet("QToolButton { background:#0d1117; color:#e6edf3; border:1px solid #0d3b33;"
                                  " border-radius:4px; padding:4px 8px; font-size:11px; text-align:left; }"
                                  "QToolButton:hover { border-color:#00d4aa; color:#00d4aa; }")
                btn.setToolTip(f"{s['name']} — 成功率{_perf.get('operation_success_rate','')} · 节拍{_perf.get('cycle_time','')} · 点击打开 ECS 链接 + 建节点链")
                btn.clicked.connect(lambda _, sid=s["id"]: self.module.open_scene_link(sid))
                self.v.addWidget(btn)
        # 🤝 合作闭环 (2026-08-09 老倪: 供应商底座→实验室微调→数据不出实验室 — 加载合作JSON画布)
        try:
            _cp = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "flows", "cooperation_closed_loop.json")
            if os.path.exists(_cp):
                lab = QLabel("▾ 🤝 合作闭环 (供应商·数据合规)")
                lab.setStyleSheet("color:#a371f7; font-size:11px; font-weight:700; padding:6px 2px 2px;")
                lab.setToolTip("供应商提供底座模型 → 实验室微调专有模型 → 数据闭环不出实验室 (点击加载画布)")
                self.v.addWidget(lab)
                btn = QToolButton()
                btn.setText("🤝 合作数据闭环流程")
                btn.setStyleSheet("QToolButton { background:#0d1117; color:#e6edf3; border:1px solid #a371f733;"
                                  " border-radius:4px; padding:4px 8px; font-size:11px; text-align:left; }"
                                  "QToolButton:hover { border-color:#a371f7; color:#a371f7; }")
                btn.setToolTip("加载合作合规数据闭环画布: 供应商底座→SYS2微调→评估→SYS1/SYS0, 数据不出实验室")
                btn.clicked.connect(lambda _, fl=_cp: self.module.load_flow_file(fl))
                self.v.addWidget(btn)
        except Exception:
            pass
        self.v.addStretch()

    def _toggle_group(self, gname, lab):
        """📚 点击分组标题 → 折叠/展开该组 (2026-08-06 老倪: System2/SYS1/SYS0 列表栏可隐藏)"""
        self._group_collapsed[gname] = not self._group_collapsed.get(gname, False)
        collapsed = self._group_collapsed[gname]
        # 更新标题 marker
        lab.setText(f"{'▸ ' if collapsed else '▾ '}{gname}")
        # 该组的按钮 → 显示/隐藏
        group_items = []
        for ntype, g, items in LIBRARY:
            if g == gname:
                group_items = items
                break
        for it in group_items:
            btn = self._lib_btns.get(it["name"])
            if btn is not None:
                btn.setVisible(not collapsed)

    def set_filter(self, wf_key):
        """按工作流过滤模块库 (None=全部)"""
        self._wf_key = wf_key
        self._current_wf = wf_key
        self._rebuild()


# ════════════════════════════════════════════════════════════════
# Simulink 模式主模块
# ════════════════════════════════════════════════════════════════
class FloatingCanvasDialog(QDialog):
    """⛶ 浮动画布窗口 (2026-08-05 老倪: "节点操作和显示的窗口变成独立浮动窗口, 可最大化, 看得范围更大")
    非模态 show() + 标题栏最大化/拖边缩放; 关闭时自动把画布还原回主界面 split。
    """

    def __init__(self, module, canvas, parent=None):
        super().__init__(parent)
        self._module = module
        self._canvas = canvas
        self.setWindowTitle("⛶ Simulink 画布 · 浮动窗口 (关闭自动还原)")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint
                            | Qt.WindowMinimizeButtonHint)
        self.setStyleSheet("QDialog{background:#f6f8fa;}")
        self.resize(1280, 820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(canvas)  # 画布 reparent 到浮动窗口

    def closeEvent(self, ev):
        self._module._restore_canvas()
        super().closeEvent(ev)


# 🎨 风格主题 (2026-08-05 老倪: "增加风格切换功能, UI操作你设计, 放在哪里你根据软件惯例, 在配置setting里改")
# light = 对标 MATLAB Simulink / CANoe 浅色; dark = 原版深色。主窗口配置中心可切换。
THEMES = {
    "light": {
        "node_top": "#ffffff", "node_bot": "#e8ebf0", "title": "#24292f",
        "label": "#57606a", "port_edge": "#f0f2f5", "inactive": "#9aa4b2",
        "canvas": "#f0f2f5", "bg": "#f6f8fa", "bg2": "#eef1f5", "panel": "#ffffff",
        "input": "#e9edf2", "border": "#d0d7de", "border2": "#b6bdc7",
        "btn": "#e9edf2", "text": "#24292f", "text2": "#57606a", "hover": "#dbe9ff",
        "scope_top": "#ffffff", "scope_bot": "#eef1f5", "grid": "#d0d7de",
        "grid_major": "#b6bdc7",
    },
    "dark": {
        "node_top": "#1a1f2b", "node_bot": "#111318", "title": "#ddd",
        "label": "#8b949e", "port_edge": "#0a0a0f", "inactive": "#3a3f4b",
        "canvas": "#0a0a0f", "bg": "#0d1117", "bg2": "#0a0e14", "panel": "#161b22",
        "input": "#14181f", "border": "#1e2740", "border2": "#30363d",
        "btn": "#21262d", "text": "#c9d1d9", "text2": "#8b949e", "hover": "#1a2230",
        "scope_top": "#161b22", "scope_bot": "#0d1117", "grid": "#1e2740",
        "grid_major": "#30363d",
    },
}
_CUR_THEME = "dark"  # 当前主题 (🎨 switch_theme 切换; 默认深色 — 老倪 2026-08-05: 还是用暗色调风格)


class SimulinkModule(QWidget):
    # 信号 (类级声明, worker 线程 → 主线程)
    log_signal = pyqtSignal(str)
    flow_synced = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("simulink")  # 🌐 2026-08-09 老倪: Simulink 页识别 (VEH-5 功能卡编号 — VEH.5.xx)
        self.nodes = []    # [{id,type,name,x,y,w,params,inputs,outputs,actions}]
        self.links = []    # [{id,f,t,f_port,t_port}]
        self._items = {}   # node_id -> SimNodeItem
        self._link_items = []
        self._sim_running = False
        self._sim_t = 0.0
        self._sim_dt = 0.01
        self._sim_t_end = 10.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        # 教程状态
        self._tutorial_active = False
        self._tutorial_step = -1
        self._tutorial_hl = None      # 当前高亮 widget
        self._tutorial_orig_ss = {}   # 原样式表备份
        self._tutorial_timer = QTimer(self)
        self._tutorial_timer.timeout.connect(self._tutorial_pulse)
        self._tutorial_pulse_on = False
        # CI/CD 后台线程信号 (worker 线程 → 主线程日志)
        self.log_signal.connect(self._log)
        self._worker = None
        # CI/CD 环节状态: 0未开始 1运行中 2成功 3失败
        self._cicd_state = {"validate": 0, "train": 0, "integrate": 0, "deploy": 0}
        self._build()
        self._seed_default_flow()
        self._model_engine = None  # 🌐 Model Engine 中枢 (2026-08-08: 训练走 GPU 引擎选择)

    def _veh5_apply(self):
        """🌐 VEH.5 (Simulink 页) 控件编号 (2026-08-09 老倪: 所有可见控件 VEH.5.xx 悬浮显示)
        独立窗口 — 不走 studio 全局循环, 自身遍历编号"""
        try:
            from PyQt5.QtWidgets import QLabel, QScrollArea, QScrollBar, QFrame
            ws = []
            _lib_btn_ids = set()
            try:
                _lib = getattr(self, "library", None)
                if _lib is not None:
                    _lib_btn_ids = set(id(b) for b in getattr(_lib, "_lib_btns", {}).values())
            except Exception:
                pass
            for w in self.findChildren(QWidget):
                if w is self:
                    continue
                if id(w) in _lib_btn_ids:
                    continue  # 🐛 2026-08-09: 模块库按钮跳过 (用 lib_seq 编号, 与画布一致)
                if isinstance(w, (QScrollArea, QScrollBar)):
                    continue
                from PyQt5.QtWidgets import QGraphicsView
                if isinstance(w, QGraphicsView) or isinstance(w, QGraphicsView.viewport().__class__):
                    continue  # 🐛 画布/场景不编号 (节点 ID 由 paint 常显)
                if isinstance(w, QFrame) and (w.layout() is not None or w.children()):
                    continue  # 容器卡片
                if isinstance(w, QLabel):
                    txt = (w.text() or "").strip()
                    if not txt:
                        continue
                    if txt.startswith("VEH."):
                        continue
                ws.append(w)
            def _ay(w):
                try:
                    return w.mapTo(self, w.rect().topLeft()).y()
                except Exception:
                    return 0
            def _ax(w):
                try:
                    return w.mapTo(self, w.rect().topLeft()).x()
                except Exception:
                    return 0
            ws.sort(key=lambda w: (_ay(w), _ax(w)))
            self._veh5_ids = {}
            for i, w in enumerate(ws, 1):
                h_id = f"VEH.5.{i:02d}"
                w.setToolTip(f"{h_id} — {w.__class__.__name__}")
                self._veh5_ids[id(w)] = h_id
        except Exception:
            pass

    def showEvent(self, ev):
        """🌐 窗口显示时编号 (VEH.5)"""
        super().showEvent(ev)
        try:
            if not getattr(self, "_veh5_done", False):
                self._veh5_apply()
                self._veh5_done = True
        except Exception:
            pass

    def set_model_engine(self, engine):
        """🌐 绑定 Model Engine (studio 传入 — 训练节点双击 → 引擎选择/启动训练)"""
        self._model_engine = engine

    def closeEvent(self, ev):
        """🛡 关闭时清理所有 QThread + 定时器 (2026-08-05 崩溃修复#3:
        SimulinkModule 主类原本无 closeEvent → _worker(CICDWorker QThread)/_acq_worker/
        _rec_timer 在窗口关闭时未清理 → QThread: Destroyed while thread is still running
        exit 134 SIGABRT (用户在录屏/训练/评估中关闭窗口必崩)"""
        for attr in ("_timer", "_remote_timer", "_acq_timer", "_rec_timer", "_tutorial_timer", "_rec_blink"):
            t = getattr(self, attr, None)
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
        for attr in ("_worker", "_acq_worker"):
            w = getattr(self, attr, None)
            if w is not None and hasattr(w, "isRunning") and w.isRunning():
                try:
                    # 2026-08-05 崩溃修复#5: 训练中关闭窗口 → CICDWorker(阻塞训练 subprocess)
                    # wait(3000) 不够 → 先终止训练子进程让 worker 快速结束再 wait
                    # 2026-08-12: 训练走 sudo docker run → 统一 sudo pkill + docker kill
                    self._kill_train_processes()
                    # 2026-08-05 崩溃修复#9: wait 超时若置 None → worker 被 GC 时线程还在跑
                    # → QThread destroyed SIGABRT; 改 pkill -9 强杀 + wait 15s, 失败保留引用
                    if not w.wait(15000):
                        # 仍没结束: 保留引用防 GC (不置 None), 由 Qt 进程退出时统一处理
                        self._keep_worker = w
                except Exception:
                    pass
        self._worker = None
        self._acq_worker = None
        self._rec_timer = None
        super().closeEvent(ev)

    # ── UI ──
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Hero 标题条 (对标 MathWorks 解决方案页 Hero) ──
        # (2026-08-06 老倪: 「Z-MAX 具身智能 · Simulink 模式」大标题行太黑看不清且占
        #  64px → 删除, 标题提升到主窗口菜单栏 (studio.py); 顶部直接是工具栏, 更紧凑)

        # ── 工作流导航条 (对标 MathWorks 6 大功能分区) ──
        # (2026-08-06 老倪: 工作流过滤按钮行「① 访问·标注数据…」白色按钮没用占地方 → 删除;
        #  set_filter/_filter_library 方法保留, 无 UI 入口不影响任何功能)
        # 工具栏 (对标 Simulink 工具条)
        tb = QFrame()
        tb.setStyleSheet("background:#f6f8fa; border-bottom:1px solid #d0d7de;")
        tb.setFixedHeight(44)
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(10, 4, 10, 4)
        tl.setSpacing(8)

        def mk_btn(text, tip, fn, color="#58a6ff"):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setStyleSheet(f"""
                QPushButton {{ background:#e9edf2; color:{color}; border:1px solid #d0d7de;
                border-radius:5px; padding:5px 14px; font-size:12px; font-weight:600; }}
                QPushButton:hover {{ border-color:{color}; background:#dbe9ff; }}
                QPushButton:disabled {{ color:#555; border-color:#222; }}
            """)
            b.clicked.connect(fn)
            return b

        self.btn_run = mk_btn("▶ 运行", "按拓扑执行仿真 (Simulink Run)", self.start_sim, "#00d4aa")
        self.btn_step = mk_btn("⏭ 单步", "执行一个时间步", self.step_sim)
        self.btn_stop = mk_btn("⏹ 停止", "停止仿真", self.stop_sim, "#ff4444")
        self.btn_stop.setEnabled(False)
        self.btn_tutorial = mk_btn("🧭 数据闭环引导", "引导程序: 一步一步带你走通数据闭环 (采集→训练→验证→集成→部署→推理), 全程鼠标", self.start_tutorial, "#d4a800")
        # (2026-08-06 老倪: Scope 移到左侧 node 库后, 工具栏「🖥 Scope」按钮删除 — 只留库入口)
        tl.addWidget(self.btn_run)
        tl.addWidget(self.btn_step)
        tl.addWidget(self.btn_stop)
        tl.addSpacing(8)
        tl.addWidget(self.btn_tutorial)
        # (2026-08-06 老倪: Scope 移到 node 库, 工具栏按钮已删; btn_scope 移除)
        self.btn_float = mk_btn("⛶ 浮动", "画布独立成浮动窗口, 鼠标拖边/最大化扩大视野 (关闭自动还原)", self.toggle_float_canvas, "#58a6ff")
        tl.addWidget(self.btn_float)
        # (2026-08-06 老倪: 「🪟 画布窗口」按钮没用 → 删除; 画布子窗口已不可
        #  最小化/关闭 (be1ba44a), show_canvas_win 恢复逻辑无存在必要)

        tl.addSpacing(16)
        # (2026-08-06 老倪: 「时间 10.0s / dt」仿真参数控件没用 → 删除;
        #  仿真用内部 _sim_t_end/_sim_dt 默认值, 无逻辑引用)

        btn_save = mk_btn("💾 另存为", "保存当前画布 (含节点位置/连线) 为 JSON 文件, 可下次加载回来", self.export_flow, "#3fb950")
        btn_load = mk_btn("📂 加载", "从 JSON 文件加载工作流 (恢复节点位置与连线)", self.import_flow, "#58a6ff")
        self.btn_save = btn_save
        self.btn_load = btn_load
        tl.addWidget(btn_save)
        tl.addWidget(btn_load)

        # 🎥 录屏 + 💾 保存模型 (工具类, 2026-08-06 老倪: 归类一行)
        self.btn_save_model = mk_btn("💾 保存模型", "把当前已训练的模型 checkpoint 固化为「已保存模型」, 推理服务下次可直接选择加载 (复制到 models/saved/)", self.save_trained_model, "#3fb950")
        tl.addWidget(self.btn_save_model)
        self.btn_record = mk_btn("🔴 录制", "开始录屏: 定时截取本窗口 (画布+终端输出+模型结果), 训练→推理→部署全程记录", self.start_recording, "#ff4444")
        tl.addWidget(self.btn_record)
        self.btn_stop_rec = mk_btn("⏹ 停止", "停止录屏: ffmpeg 合成 MP4 (2fps采集, 可加速, 总长<1分钟)", self.stop_recording, "#f0883e")
        self.btn_stop_rec.setEnabled(False)
        tl.addWidget(self.btn_stop_rec)

        # ┃ 分割线: 工具类 | 数据典型应用 (2026-08-06 老倪: 归类, 中间分割线分开)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedHeight(28)
        sep.setStyleSheet("color:#b6bdc7; background:#b6bdc7; border:none; width:1px; margin:0 4px;")
        tl.addWidget(sep)

        # ── 数据典型应用按钮 (第二行并入第一行, 2026-08-06 老倪: 放工具按钮右侧) ──
        # 全链路入口 (最醒目, 打开 CI/CD 全景面板)
        self.btn_pipeline = mk_btn("🎯 数据闭环控制台", "数据闭环 CICD 控制台: 6环节流水线 + 三阶段训练 + 闭环状态 (自动流转, steps可配)",
                                   self.open_pipeline_panel, "#00d4aa")
        tl.addWidget(self.btn_pipeline)
        self.btn_compare5 = mk_btn("🔬 Model Zoo", "ACT + SmolVLA + SmolVLA+LEW + VLA-Touch + AWE + MLP + 专家 七模型纵向对比: 同构模块同列对齐 (视觉编码列/世界模型列/Action Head列/训练列) · ▶运行依次训练 → 双击 Scope 出对比图表", self.open_compare5, "#d4a800")
        tl.addWidget(self.btn_compare5)
        # 🚀 Z700 快捷入口 (2026-08-12 老倪: 一键打开 Z700 完整工程 — YOLO感知+双脑+状态机+交付)
        self.btn_z700 = mk_btn("🚀 Z700", "Z700 完整工程: 🎯YOLO感知链 → 🧠双脑+状态机 → ▶交付 (flows/dual_brain_peg_yolo.json, 感知源码 src/lerobot/policies/yolo_3d/)", self.open_z700_flow, "#00d4aa")
        tl.addWidget(self.btn_z700)
        # (🗑 2026-08-12 老倪: 工具栏 🌐方案介绍按钮已删 — 改用画布节点 (交付行))
        self.btn_atomic = mk_btn("🧩 原子", "打开原子技能库 (242条, W²-VLA Token) → 选技能 → 自动建节点链: 技能→结构条件→SYS1→action JSON", self.open_atomic_skill_flow, "#00d4aa")
        tl.addWidget(self.btn_atomic)
        self.btn_awe = mk_btn("🧿 AWE", "AWE 场景原生对比管道 (它石架构, 4060 精简): SigLIP视触觉编码冻结 + H-JEPA 三层潜空间(z₁/z₂/z₃) + zFlow GRU 世界引擎 + 未来决策交叉注意力 · 纵向对比世界模型架构", self.open_awe, "#a371f7")
        tl.addWidget(self.btn_awe)
        self.btn_topsys = mk_btn("🎛 总系统", "顶层系统: 数据→总系统块→评估Scope · 双击总系统块展开 ACT/SmolVLA/SmolVLA+LEW 三条训练线 (Simulink Subsystem)", self.open_topsys, "#a371f7")
        tl.addWidget(self.btn_topsys)
        # 🗑 2026-08-10 老倪: 工具栏「🧠 左脑/🧠 右脑」按钮已删 (left_right 入口在模块库「🧠 双脑 (left_right)」)
        # 🎛 子系统返回 (2026-08-05 老倪: 顶层总系统双击展开内部三线, 返回恢复顶层)
        self.btn_back = mk_btn("⬅ 返回总系统", "从子系统内部返回上一层 (Simulink Subsystem 语义)", self.back_to_subsystem, "#3fb950")
        self.btn_back.setVisible(False)
        tl.addWidget(self.btn_back)

        tl.addStretch()
        # (2026-08-06 老倪: 右上角 t= 时钟与底部状态栏 t 重复 → 删除; 底部 lbl_rt 已显示)

        outer.addWidget(tb)

        # (2026-08-06 老倪: 「参考应用」整行删除 — 白色字体按钮与上方彩色工具栏
        #  按钮重复 (三/Model Zoo·VLA-Touch·AWE·总系统·ACT-Meta 都有彩色入口);
        #  REFERENCE_APPS 数据保留, 模块库完整模型条目/load_reference_app_by_name 仍可用)

        # (2026-08-06 老倪: 📡 实时采集状态条「采集中/数据包:24」整行删除 —
        #  无 UI 入口, 轮询只做展示; _poll_acquisition 方法一并删)
        self._theme = _CUR_THEME  # 🎨 当前风格 (light/dark)

        # 主体: 库 + MDI 画布子窗口 (2026-08-05 老倪: 对标 MATLAB Simulink / CANoe —
        # 主要操作窗口首次打开嵌在主窗口内部, 子窗口带 最小化/最大化/关闭)
        split = QSplitter(Qt.Horizontal)
        self._main_split = split
        self.canvas = SimCanvas(self)
        self.canvas.flow_changed.connect(lambda: self._sync())
        self.canvas.log.connect(self._log)
        # (🗑 2026-08-12 老倪: 右上角 🌐方案介绍浮动按钮已删 — 改用画布节点 (交付行))
        # MDI 容器 (画布作为子窗口, 可最小化/最大化/关闭/移动/缩放)
        self._mdi = QMdiArea()
        self._mdi.setViewMode(QMdiArea.SubWindowView)
        self._mdi.setStyleSheet("""
            QMdiArea { background:#eef1f5; }
            QMdiSubWindow { background:#f6f8fa; border:1px solid #d0d7de; }
            QMdiSubWindow::title { background:#ffffff; color:#24292f;
                                   padding-left:10px; font-size:12px; font-weight:600; }
            QMdiSubWindow::close-button, QMdiSubWindow::minimize-button,
            QMdiSubWindow::maximize-button { background:#e9edf2; border-radius:3px; }
            QMdiSubWindow::close-button:hover { background:#f85149; }
            QMdiSubWindow::minimize-button:hover, QMdiSubWindow::maximize-button:hover { background:#1f6feb; }
        """)
        self._canvas_win = QMdiSubWindow()
        self._canvas_win.setWidget(self.canvas)
        # 🖥 2026-08-06 老倪: 画布窗口标题栏按钮(最小化/最大化/关闭)点击没用且关闭后
        # 画布消失难以恢复 → 去掉这些按钮, 画布始终铺满 MDI 区不可关闭
        self._canvas_win.setWindowFlags(
            self._canvas_win.windowFlags()
            & ~Qt.WindowMinimizeButtonHint & ~Qt.WindowMaximizeButtonHint
            & ~Qt.WindowCloseButtonHint)
        self._canvas_win.setWindowTitle("画布")
        self._canvas_win.resize(920, 620)
        self._mdi.addSubWindow(self._canvas_win)
        # 首次打开铺满 MDI 操作区 (老倪: 窗口应充满嵌入的原来空间, 不露背景; 可还原/缩放)
        self._canvas_win.showMaximized()
        self.library = LibraryPanel(self)
        # 📚 左侧栏折叠/展开 (2026-08-06 老倪: 太占地方可缩到左边)
        self._lib_expand_bar = QPushButton("▶")
        self._lib_expand_bar.setFixedWidth(16)
        self._lib_expand_bar.setToolTip("展开模块库左侧栏")
        self._lib_expand_bar.setStyleSheet("""
            QPushButton{background:#e9edf2; color:#1f6feb; border:none;
                        border-left:1px solid #d0d7de; font-size:11px; font-weight:700;}
            QPushButton:hover{background:#d0d7de;}
        """)
        self._lib_expand_bar.clicked.connect(self._expand_library)
        self._lib_expand_bar.setVisible(False)
        self.library.collapse_requested.connect(self._collapse_library)
        split.addWidget(self.library)
        split.addWidget(self._lib_expand_bar)
        split.addWidget(self._mdi)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 0)
        split.setStretchFactor(2, 1)
        outer.addWidget(split, 1)

        # 实时状态栏 (节点状态 + 时钟 + 运行状态)
        st = QFrame()
        st.setStyleSheet("background:#f6f8fa; border-top:1px solid #d0d7de;")
        st.setFixedHeight(28)
        stl = QHBoxLayout(st)
        stl.setContentsMargins(10, 3, 10, 3)
        stl.setSpacing(14)
        self.lbl_sys_state = QLabel("⏸ 待机")
        self.lbl_sys_state.setStyleSheet("color:#57606a; font-size:11px; font-weight:600; background:transparent; border:none;")
        self.lbl_node_status = QLabel("节点: 0 | 成功: 0 | 运行中: 0 | 失败: 0")
        self.lbl_node_status.setStyleSheet("color:#57606a; font-size:11px; font-family:Consolas; background:transparent; border:none;")
        self.lbl_rt = QLabel("")
        self.lbl_rt.setStyleSheet("color:#00d4aa; font-size:11px; font-family:Consolas; background:transparent; border:none;")
        stl.addWidget(self.lbl_sys_state)
        stl.addWidget(self.lbl_node_status)
        stl.addStretch()
        stl.addWidget(self.lbl_rt)
        outer.addWidget(st)

        # 底部日志 (对标 Simulink 诊断) — 📋 可折叠 (2026-08-06 老倪: 下面的终端窗口也要能隐藏)
        log_head = QHBoxLayout()
        log_title = QLabel("📋 日志")
        log_title.setStyleSheet("color:#57606a; font-size:10px; font-weight:700; background:transparent; border:none;")
        log_head.addWidget(log_title)
        log_head.addStretch()
        self.btn_log_toggle = QPushButton("◀ 收起")
        self.btn_log_toggle.setFixedWidth(64)
        self.btn_log_toggle.setToolTip("隐藏底部日志区")
        self.btn_log_toggle.setStyleSheet("""
            QPushButton{background:#e9edf2; color:#1f6feb; border:1px solid #d0d7de;
                        border-radius:4px; font-size:10px; font-weight:700; padding:2px 8px;}
            QPushButton:hover{border-color:#1f6feb;}
        """)
        self.btn_log_toggle.clicked.connect(self._toggle_log_box)
        log_head.addWidget(self.btn_log_toggle)
        outer.addLayout(log_head)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(110)
        self.log_box.setStyleSheet("background:#f6f8fa; color:#57606a; border:none; border-top:1px solid #d0d7de; font-size:11px; font-family:Consolas;")
        outer.addWidget(self.log_box)
        # 🎨 应用当前主题 (QSS 硬编码为浅色模板, 构建后按 _CUR_THEME 重设为深/浅)
        # (老倪 2026-08-05: 默认暗色调, 配置中心可切)
        self._theme = _CUR_THEME
        try:
            self.switch_theme(_CUR_THEME)
        except Exception:
            pass
        # 📺 外部命令行训练日志监视 (2026-08-06 老倪: 终端要有东西)
        try:
            self._start_ext_log_watch()
        except Exception:
            pass
        self._log("Simulink 模式就绪 · 0帧起手, 从左侧模块库开始搭建")

    # ── 初始工作流: 空画布 (0帧起手) ──
    def _seed_default_flow(self):
        pass  # 空画布, 用户从零搭建

    # ════════════════════════════════════════════════════════════
    # 交互式教程 (高亮 + 文字提示, 全程鼠标)
    # ════════════════════════════════════════════════════════════
    TUTORIAL_STEPS = [
        ("pipeline", None,
         "① 点击工具栏「🎯 数据闭环控制台」\n打开闭环控制台 (6环节: 采集→训练→验证→集成→部署→推理)"),
        ("collect", None,
         "② 点击「① 采集」→ 从 ECS 中转拉取 Orin 真实数据,\naction 恒等自动修复并落地 (队列空则提示无新包)"),
        ("train", None,
         "③ 点击「② 训练」→ 智能选数据源 (Orin真实 / metaworld占位),\n启动 ACT 训练 (~40s, 4060 CUDA)"),
        ("validate", None,
         "④ 点击「③ 验证」→ validate_flow.py 校验模型标准合规\n(通过才能进入集成)"),
        ("integrate", None,
         "⑤ 点击「④ 集成」→ 打包最新 checkpoint 上传 ECS 中转"),
        ("deploy", None,
         "⑥ 点击「⑤ 部署」→ 查询 Orin 部署状态 (心跳/模型)"),
        ("infer", None,
         "⑦ 点击「⑥ 推理」→ 检查 Orin 在线 / 推理次数 / 延迟"),
        ("done", None,
         "🎉 数据闭环引导完成! 你已走通全链路:\n采集 → 训练 → 验证 → 集成 → 部署 → 推理\n点击任意处退出引导"),
    ]

    def start_tutorial(self):
        """开始交互式教程"""
        if self._tutorial_active:
            self._tutorial_cleanup()
            return
        self._tutorial_active = True
        self._tutorial_step = -1
        self._log("🧭 数据闭环引导开始 · 跟着高亮提示一步一步操作, 全程鼠标")
        self._tutorial_next()

    def _tutorial_next(self):
        """推进到下一步: 高亮目标 + 气泡提示"""
        self._tutorial_step += 1
        if self._tutorial_step >= len(self.TUTORIAL_STEPS):
            self._tutorial_cleanup()
            self._log("📖 教程完成!")
            return
        kind, target, msg = self.TUTORIAL_STEPS[self._tutorial_step]

        if kind == "pipeline":
            widget = self.btn_pipeline
        elif kind in ("collect", "train", "validate", "integrate", "deploy", "infer"):
            # 6 环节引导: 高亮控制台面板内的环节按钮
            panel = getattr(self, "_pipeline_panel", None)
            if panel is not None and hasattr(panel, "_pipe_btns") and kind in panel._pipe_btns:
                widget = panel._pipe_btns[kind]
            else:
                widget = self.btn_pipeline  # 面板未打开 → 高亮入口按钮
        elif kind in ("btn_run", "btn_step", "btn_stop", "btn_save"):
            widget = getattr(self, {"btn_run": "btn_run", "btn_step": "btn_step",
                                    "btn_stop": "btn_stop", "btn_save": "btn_save"}[kind])
        else:  # done
            self._tutorial_show_bubble("🎉 完成!", msg)
            return

        if widget is None:
            widget = self.canvas
        self._tutorial_highlight(widget)
        self._tutorial_show_bubble(f"📖 第{self._tutorial_step + 1}/{len(self.TUTORIAL_STEPS)}步", msg)

    def _tutorial_highlight(self, widget):
        """高亮目标控件: 记录原样式, 应用金色发光边框"""
        self._tutorial_cleanup_highlight()
        self._tutorial_hl = widget
        self._tutorial_orig_ss[id(widget)] = widget.styleSheet()
        self._tutorial_apply_border(widget, "#ffd700")
        self._tutorial_pulse_on = True
        self._tutorial_timer.start(400)

    def _tutorial_apply_border(self, widget, color):
        """从原样式备份重建 + 追加高亮边框规则。

        QSS 同选择器多规则 = 属性合并: 追加的 border 覆盖原 border,
        background/color/padding 等原规则完整保留 (不再 rsplit 逆向截断)。
        QToolButton 必须用 QToolButton 选择器 (它不是 QPushButton 子类,
        裸属性/无选择器规则会被 Qt 忽略 → 原样式损坏回退黑字)。
        """
        base = self._tutorial_orig_ss.get(id(widget), "")
        if isinstance(widget, QPushButton):
            widget.setStyleSheet(base + f" QPushButton {{ border:3px solid {color}; border-radius:6px; }}")
        elif isinstance(widget, QToolButton):
            widget.setStyleSheet(base + f" QToolButton {{ border:3px solid {color}; border-radius:4px; }}")
        else:
            widget.setStyleSheet(base + f" {{ border:3px solid {color}; }}")

    def _tutorial_pulse(self):
        """高亮脉冲闪烁 (金色 ↔ 青色)"""
        if self._tutorial_hl is None:
            return
        self._tutorial_pulse_on = not self._tutorial_pulse_on
        color = "#ffd700" if self._tutorial_pulse_on else "#00d4aa"
        self._tutorial_apply_border(self._tutorial_hl, color)

    def _tutorial_cleanup_highlight(self):
        """清除高亮, 恢复原样式"""
        if self._tutorial_timer.isActive():
            self._tutorial_timer.stop()
        if self._tutorial_hl is not None:
            orig = self._tutorial_orig_ss.get(id(self._tutorial_hl), "")
            self._tutorial_hl.setStyleSheet(orig)
            self._tutorial_hl = None

    def _tutorial_show_bubble(self, title, msg):
        """气泡提示: 用日志 + 状态栏显示 (轻量实现)"""
        self._log(f"{title}\n{msg}")

    def _tutorial_on_action(self, action):
        """用户执行了动作 → 检查是否匹配当前步骤, 匹配则推进"""
        if not self._tutorial_active:
            return
        # 任意环节完成 = 已掌握 → 直接结束教程 (清除高亮)
        kind, target, _ = self.TUTORIAL_STEPS[self._tutorial_step] if 0 <= self._tutorial_step < len(self.TUTORIAL_STEPS) else (None, None, None)
        matched = False
        if kind == "pipeline" and action == "pipeline":
            matched = True
        elif kind in ("collect", "train", "validate", "integrate", "deploy", "infer") and action == kind:
            matched = True
        if matched:
            self._tutorial_next()
        else:
            # 点错目标: 给出明确指引 (不静默)
            self._tutorial_hint_mismatch(action, kind)

    def _tutorial_finish_early(self):
        """用户提前完成关键操作(导出) → 结束教程, 清除高亮"""
        self._tutorial_cleanup()
        self._log("🎉 教程完成 · 高亮已清除, 可自由操作")

    def _tutorial_on_node_moved(self):
        """节点被拖动 → 推进教程 (node 步骤)"""
        if not self._tutorial_active:
            return
        if self._tutorial_step < len(self.TUTORIAL_STEPS) and self.TUTORIAL_STEPS[self._tutorial_step][0] == "node":
            self._tutorial_next()

    def _tutorial_hint_mismatch(self, action, expected_kind):
        """点错目标时给明确提示: 该点哪个高亮按钮"""
        kind_labels = {"pipeline": "工具栏「🎯 数据闭环控制台」按钮(金色高亮)",
                       "collect": "控制台「① 采集」按钮(金色高亮)",
                       "train": "控制台「② 训练」按钮(金色高亮)",
                       "validate": "控制台「③ 验证」按钮(金色高亮)",
                       "integrate": "控制台「④ 集成」按钮(金色高亮)",
                       "deploy": "控制台「⑤ 部署」按钮(金色高亮)",
                       "infer": "控制台「⑥ 推理」按钮(金色高亮)"}
        target = kind_labels.get(expected_kind, "高亮的位置")
        self._log(f"❓ 不是这一步哦 — 请点击: {target}")
        # 自绘深色气泡 (替代 QToolTip: WSLg 下系统原生渲染黑字看不清)
        try:
            from PyQt5.QtCore import Qt as _Qt
            if self._tutorial_hl is not None and self._tutorial_hl.isVisible():
                pos = self._tutorial_hl.mapToGlobal(self._tutorial_hl.rect().center())
                self._show_bubble(pos, f"👆 请点击这里:\n{target}")
        except Exception:
            pass

    def _pal(self):
        """🎨 当前主题调色板 (light/dark)"""
        return THEMES.get(getattr(self, "_theme", _CUR_THEME), THEMES["light"])

    def switch_theme(self, name="light"):
        """🎨 风格切换 (light=浅色 Simulink/CANoe 风 · dark=原深色):
        重设全部控件 QSS + 画布背景 + 节点重绘 + 同步 Scope 图表主题"""
        global _CUR_THEME
        if name not in THEMES:
            name = "light"
        self._theme = name
        _CUR_THEME = name
        # 1) 全部控件 QSS: 浅↔深色值替换 (light值去重 — 同色多个 key 只保留首个 dark 值)
        seen = {}
        for k in THEMES["light"]:
            seen.setdefault(THEMES["light"][k], THEMES["dark"][k])
        pairs = list(seen.items()) + [("#dbe9ff", "#1a2230"),   # 按钮 hover 底色
                                       ("#1f2328", "#c9d1d9")]  # 🐛 2026-08-09: hover 文字色 (深色下黑字看不清)
        for wdg in [self] + self.findChildren(QWidget):
            ss = wdg.styleSheet()
            if not ss:
                continue
            for lc, dc in pairs:
                ss = ss.replace(lc, dc) if name == "dark" else ss.replace(dc, lc)
            wdg.setStyleSheet(ss)
        # 2) 画布背景 + viewport 深色 (边缘/缩放间隙不露白) + 场景重绘
        pc = self._pal()
        self.canvas.setBackgroundBrush(QColor(pc["canvas"]))
        for wv, key in ((self.canvas.viewport(), "canvas"),
                        (self._mdi.viewport(), "bg2")):
            pal = wv.palette()
            pal.setColor(pal.Window, QColor(pc[key]))
            pal.setColor(pal.Base, QColor(pc[key]))
            wv.setPalette(pal)
            wv.setAutoFillBackground(True)
        self.canvas.viewport().update()
        self.canvas._scene.update()
        # 3) 同步 Scope 图表主题
        try:
            import simulink_scope as _sc
            _sc.CUR_THEME = name
        except Exception:
            pass
        self._log(f"🎨 风格已切换: {'浅色 · MATLAB Simulink/CANoe' if name == 'light' else '深色 · 原版'}")

    def _show_bubble(self, global_pos, text, ms=4000):
        """自绘深色气泡浮层 (无边框置顶, 深底白字)"""
        try:
            from PyQt5.QtWidgets import QLabel
            from PyQt5.QtCore import Qt as _Qt
            if getattr(self, "_bubble", None) is not None:
                try:
                    self._bubble.close()
                    self._bubble.deleteLater()
                except Exception:
                    pass
            bub = QLabel(text)
            bub.setWindowFlags(_Qt.ToolTip | _Qt.WindowStaysOnTopHint | _Qt.FramelessWindowHint)
            pal = self._pal()
            bub.setStyleSheet(f"QLabel {{ background:{pal['panel']}; color:{pal['text']}; border:1px solid #00d4aa;"
                              "border-radius:6px; padding:10px 14px; font-size:12px; }")
            bub.adjustSize()
            x = global_pos.x() - bub.width() // 2
            y = global_pos.y() + 16
            bub.move(x, y)
            bub.show()
            bub.raise_()
            self._bubble = bub
            QTimer.singleShot(ms, lambda: self._close_bubble(bub))
        except Exception:
            pass

    def _close_bubble(self, bub):
        """定时关闭气泡 (只关自己, 防误关新气泡)"""
        try:
            if getattr(self, "_bubble", None) is bub:
                bub.close()
                bub.deleteLater()
                self._bubble = None
        except Exception:
            pass

    def _tutorial_cleanup(self):
        """退出教程: 清除高亮"""
        self._tutorial_active = False
        self._tutorial_cleanup_highlight()
        self._tutorial_step = -1

    # ── 工作流过滤 (对标 MathWorks 6 大分区导航) ──
    # (2026-08-06: 工作流过滤按钮行已删, _filter_library 随之移除 — 无 UI 入口不调用;
    #  LibraryPanel.set_filter 保留供内部使用)
    # ── 参考应用模板 (对标 MathWorks 参考应用列表) ──
    def load_reference_app_by_name(self, name):
        """按模板名加载参考应用 (模块库完整模型条目用)"""
        for item in REFERENCE_APPS:
            nm = item[0]
            if nm == name:
                nodes, links = item[1], item[2]
                layout = item[3] if len(item) > 3 else None
                self.load_reference_app(nm, nodes, links, layout=layout)
                return True
        self._log(f"❌ 找不到模板: {name}")
        return False

    def load_flow_file(self, path):
        """💾 加载保存的工作流 JSON (2026-08-09 老倪: 模块库总系统 → flows/system.json)
        解析 {format,nodes[],links[]} → 恢复节点+连线 (复用 add_node 建节点, 保留位置)"""
        import os as _os
        if not _os.path.exists(path):
            self._log(f"❌ 工作流文件不存在: {path}")
            return False
        try:
            import json as _j
            flow = _j.load(open(path, encoding="utf-8"))
        except Exception as e:
            self._log(f"❌ 工作流 JSON 解析失败: {e}")
            return False
        nodes = flow.get("nodes", [])
        links = flow.get("links", [])
        if self.nodes:
            if not self._qmsg_yes("加载工作流", f"加载「{path}」将清空当前画布，继续？"):
                return
        self.clear()
        old_sync = self._sync
        self._sync = lambda: None
        old_undo = getattr(self, "_suspend_undo", False)
        self._suspend_undo = True
        try:
            id_map = {}
            for spec in nodes:
                n = self.add_node(spec.get("type", "system"), spec.get("name", "?"),
                                  spec.get("x", 0), spec.get("y", 0), spec.get("params", {}))
                id_map[spec["id"]] = n["id"]
                n["w"] = spec.get("w", 150)
            for spec in links:
                f = id_map.get(spec.get("f"))
                t = id_map.get(spec.get("t"))
                if f and t:
                    fi = self._items.get(f)
                    ti = self._items.get(t)
                    if fi and ti:
                        self.add_link(fi, ti, spec.get("label"))
            self._log(f"💾 已加载工作流: {path} ({len(nodes)}节点 {len(links)}连线)")
        except Exception as e:
            self._log(f"⚠️ 工作流加载部分失败: {e}")
        finally:
            self._sync = old_sync
            self._suspend_undo = old_undo
            self._sync()
            self.canvas._scene.update()
        self._assign_veh5_ids()  # 🐛 2026-08-12 老倪: 画布节点 ID = VEH.5.顺序号
        return True

    def load_reference_app(self, name, node_specs, link_specs, layout=None):
        if self.nodes:
            if not self._qmsg_yes("加载参考应用", f"加载「{name}」将清空当前画布，继续？"):
                return
        self.clear()
        # ⚠️ 批量加载性能 (2026-08-05 实测): add_node 每次 _sync() 会 POST web 同步,
        # 13 节点模板 = 13 次串行网络请求 (web comfy mock 常挂 → 每个超时数秒) → 按钮卡死。
        # 加载期间禁用 _sync, 末尾统一同步一次。
        # ↩️ 加载期间也挂起撤销栈 (2026-08-07: 模板加载是整体操作, 不该逐节点入栈)
        old_sync = self._sync
        self._sync = lambda: None
        old_undo = getattr(self, "_suspend_undo", False)
        self._suspend_undo = True
        try:
            ids = []
            base_x, base_y = 120, 80
            # 🗂 多行展开布局 (2026-08-05): layout 是 [[节点名...]每行] 网格 —
            # 行 = 模型分支, 列 = 功能角色, 同名节点多行出现→垂直对齐(如 Action Head 共第5列);
            # 空串 = 占位跳过。无 layout → 传统单行横排 (兼容旧模板)。
            # ⚠️ 列距 200 (2026-08-07 老倪: 节点跑到显示区右侧太远 → 260 太宽, 10 列网格
            #    也放得下; specs 无 layout 位置的节点走兜底单行会甩到 x=6000+, 必须补全 layout!)
            index_to_id = {}  # 🐛 2026-08-08 老倪: 定义索引→实际节点id (共享跳过导致 ids 错位 — SmolVLM2/SigLIP 没接)
            if layout:
                pos = {}
                for r, row in enumerate(layout):
                    for c, nm in enumerate(row):
                        if not nm:
                            continue  # 占位空串, 跳过
                        pos.setdefault(nm, []).append((base_x + c * 200, base_y + r * 230))
                used = set()
                for i, (ntype, nm, params) in enumerate(node_specs):
                    cands = pos.get(nm, [])
                    # 🧩 2026-08-08 老倪: 共享结构条件定义(无 · 后缀)已下放各模型行 — 跳过不创建 (保定义索引, edges 不引用)
                    if not cands and "结构条件" in nm and "·" not in nm:
                        continue
                    xy = next((p for p in cands if p not in used), None)
                    if xy is None:
                        xy = (base_x + i * 200, base_y)  # 兜底单行
                    used.add(xy)
                    n = self.add_node(ntype, nm, xy[0], xy[1], params)
                    ids.append(n["id"])
                    index_to_id[i] = n["id"]
            else:
                for i, (ntype, nm, params) in enumerate(node_specs):
                    n = self.add_node(ntype, nm, base_x + i * 200, base_y, params)
                    ids.append(n["id"])
                    index_to_id[i] = n["id"]
            for fi, ti, *label in link_specs:
                fid, tid = index_to_id.get(fi), index_to_id.get(ti)
                if fid and tid:
                    self.add_link(self._items[fid], self._items[tid],
                                  label=label[0] if label else None)
        finally:
            self._sync = old_sync
            self._suspend_undo = old_undo
        self._sync()  # 一次同步到位
        self.canvas._scene.update()
        self._log(f"🗂 已加载参考应用: {name} ({len(ids)}节点 {len(link_specs)}连线) · 双击节点改参数")
        self._tutorial_on_action("ref")
        self._assign_veh5_ids()  # 🐛 2026-08-12 老倪: 画布节点 ID = VEH.5.顺序号 (布局排序)

    def _assign_veh5_ids(self):
        """simulink 画布节点 ID = VEH.5.顺序号 (2026-08-12 老倪: 按布局 y→x 排序, 悬停显示)
        模块库按钮仍用库编号; 画布节点用画布顺序号 — 与库按钮 ID 解耦"""
        try:
            funcs = [n for n in self.nodes if n.get("type") != "row_bg"]
            funcs.sort(key=lambda n: (n.get("y", 0), n.get("x", 0)))
            for i, n in enumerate(funcs, 1):
                n["nid"] = f"VEH.5.{i:03d}"
        except Exception:
            pass

    # ── 节点操作 ──
    def add_node_at_center(self, ntype, name, params=None):
        c = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        n = self.add_node(ntype, name, int(c.x() - 75 + random.uniform(-30, 30)),
                          int(c.y() - 25 + random.uniform(-30, 30)), params)
        # 🧠 ACT-Meta 逐步搭建引导: 匹配当前步骤模块则推进
        self._act_build_on_add(name)
        return n

    def add_node(self, ntype, name, x, y, params=None):
        node = {
            "id": gen_id(),
            "type": ntype,
            "name": name,
            "x": int(x), "y": int(y), "w": 150,
            "icon": {"condition": "❖", "model": "◈", "action": "➤",
                     "system": "◉", "hardware": "▣", "switch": "🔀",
                     "train_gate": "☑", "row_bg": "▤", "pdf_report": "📄", "skill": "🧩", "scene": "🤖", "data": "📊",
                     "coord_overlay": "🧩"}[ntype],
            "color": COLORS[ntype],
            "params": params or {},
            "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
            "outputs": [{"id": "out1", "label": "out", "dtype": "any"}],
            "actions": [],
        }
        self.nodes.append(node)
        item = SimNodeItem(node, self)
        self._items[node["id"]] = item
        self.canvas._scene.addItem(item)
        self.canvas._scene.update()
        self._log(f"➕ 添加节点 [{NODE_TYPES[ntype]['cn']}] {name}")
        self._push_undo(("del_node", node["id"]))  # ↩️ 撤销: 删掉刚加的节点
        self._sync()
        return node

    def add_link(self, src_item, dst_item, label=None):
        src, dst = src_item.node, dst_item.node
        if src["id"] == dst["id"]:
            return
        # 防重复
        for lk in self.links:
            if lk["f"] == src["id"] and lk["t"] == dst["id"]:
                self._log("⚠️ 连线已存在")
                return
        link = {"id": link_id(), "f": src["id"], "t": dst["id"],
                "f_port": "out1", "t_port": "in1"}
        if label:
            link["label"] = label  # 🏷 数据流标签: 图像/状态/动作 (2026-08-05 老倪)
        self.links.append(link)
        self._draw_links()
        self._log(f"🔗 {src['name']} → {dst['name']}")
        self._push_undo(("del_link", link["id"]))  # ↩️ 撤销: 断开这条线
        self._sync()

    def delete_link(self, link):
        if link in self.links:
            import copy as _cp
            self._push_undo(("restore_link", _cp.deepcopy(link)))  # ↩️ 撤销: 恢复连线
            self.links.remove(link)
            self._draw_links()
            self._log("🗑 连线已删除")
            self._sync()

    def delete_selected(self):
        sel = [it for it in self._items.values() if it.isSelected()]
        if not sel:
            return
        ids = {it.node["id"] for it in sel}
        # ↩️ 撤销: 保存被删节点 + 关联连线 (深拷贝, 2026-08-07)
        import copy as _cp
        saved = []
        for it in sel:
            n = _cp.deepcopy(it.node)
            rel = [_cp.deepcopy(l) for l in self.links if l["f"] == n["id"] or l["t"] == n["id"]]
            saved.append((n, rel))
        self._push_undo(("restore_nodes", saved))
        for it in sel:
            self.canvas._scene.removeItem(it)
        self.nodes = [n for n in self.nodes if n["id"] not in ids]
        self.links = [l for l in self.links if l["f"] not in ids and l["t"] not in ids]
        self._items = {k: v for k, v in self._items.items() if k not in ids}
        self._draw_links()
        self._log(f"🗑 删除 {len(sel)} 个节点")
        self._sync()

    # ════════════════════════════════════════════════════════════════
    # ↩️ 撤销栈 (2026-08-07 老倪: 挪动背景/节点回不去上一步 → Ctrl+Z)
    # 记录用户交互操作: 移动 / 添加 / 删除 / 连线 / 断线; 模板加载挂起
    # ════════════════════════════════════════════════════════════════
    def _push_undo(self, entry):
        """入撤销栈 (限深 50)。模板加载/批量布局期间挂起 (_suspend_undo)"""
        if getattr(self, "_suspend_undo", False):
            return
        if not hasattr(self, "_undo_stack"):
            self._undo_stack = []
        self._undo_stack.append(entry)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def undo(self):
        """↩️ Ctrl+Z 回退一步 (画布快捷键绑定; 无操作时日志提示)"""
        if not getattr(self, "_undo_stack", None):
            self._log("↩ 无操作可回退")
            return
        entry = self._undo_stack.pop()
        kind = entry[0]
        try:
            if kind == "move":  # 移动回退: setPos → itemChange 自动同步 node dict
                for nid, ox, oy in entry[1]:
                    it = self._items.get(nid)
                    if it is not None:
                        it.setPos(ox, oy)
                self._log(f"↩ 回退: 移动 {len(entry[1])} 个节点")
            elif kind == "del_node":  # 撤销"添加节点" → 删掉它
                self._remove_node(entry[1])
                self._log("↩ 回退: 撤销添加节点")
            elif kind == "restore_nodes":  # 撤销"删除节点" → 恢复节点+连线
                old = getattr(self, "_suspend_undo", False)
                self._suspend_undo = True
                try:
                    # ⚠️ add_node 生成新 id — 旧连线引用须重映射 (2026-08-07)
                    idmap = {}
                    for n, rel in entry[1]:
                        new = self.add_node(n["type"], n["name"], n["x"], n["y"], n.get("params"))
                        idmap[n["id"]] = new["id"]
                    for n, rel in entry[1]:
                        for lk in rel:
                            # ⚠️ 两端 id: 被删节点→新 id, 存活节点→原 id (2026-08-07 实测)
                            s = self._items.get(idmap.get(lk["f"], lk["f"]))
                            d = self._items.get(idmap.get(lk["t"], lk["t"]))
                            if s and d:
                                self.add_link(s, d, label=lk.get("label"))
                finally:
                    self._suspend_undo = old
                self._log(f"↩ 回退: 恢复 {len(entry[1])} 个被删节点")
            elif kind == "del_link":  # 撤销"连线" → 断开
                self.links = [l for l in self.links if l["id"] != entry[1]]
                self._draw_links()
                self._log("↩ 回退: 撤销连线")
            elif kind == "restore_link":  # 撤销"断线" → 恢复连线
                old = getattr(self, "_suspend_undo", False)
                self._suspend_undo = True
                try:
                    lk = entry[1]
                    s, d = self._items.get(lk["f"]), self._items.get(lk["t"])
                    if s and d:
                        self.add_link(s, d, label=lk.get("label"))
                finally:
                    self._suspend_undo = old
                self._log("↩ 回退: 恢复连线")
            else:
                self._log(f"↩ 未知撤销类型: {kind}")
                return
        except Exception as ex:
            self._log(f"❌ 回退失败: {ex}")
            return
        self._sync()
        self.canvas._scene.update()

    def _remove_node(self, nid):
        """内部: 移除单个节点 + 关联连线 (撤销添加用)"""
        it = self._items.pop(nid, None)
        if it is not None:
            self.canvas._scene.removeItem(it)
        self.nodes = [n for n in self.nodes if n["id"] != nid]
        self.links = [l for l in self.links if l["f"] != nid and l["t"] != nid]
        self._draw_links()

    def duplicate_selected(self):
        sel = [it for it in self._items.values() if it.isSelected()]
        for it in sel:
            n = it.node
            self.add_node(n["type"], n["name"] + " (副本)",
                          n["x"] + 40, n["y"] + 40, dict(n.get("params", {})))

    # ── 连线绘制 ──
    def _draw_links(self):
        for li in self._link_items:
            self.canvas._scene.removeItem(li)
        self._link_items = []
        # 📐 端口分布 (2026-08-07 老倪: LeWorldModel/Scope 长线被中间节点盖住 + 同端口
        #   线束重叠 → 按节点出入线数垂直分布端口 y, 每条线独立起点/终点)
        out_n, in_n = {}, {}
        for lk in self.links:
            out_n[lk["f"]] = out_n.get(lk["f"], 0) + 1
            in_n[lk["t"]] = in_n.get(lk["t"], 0) + 1
        out_done, in_done = {}, {}
        for lk in self.links:
            s, d = self._items.get(lk["f"]), self._items.get(lk["t"])
            if not (s and d):
                continue
            fo = out_done.get(lk["f"], 0)
            out_done[lk["f"]] = fo + 1
            ti = in_done.get(lk["t"], 0)
            in_done[lk["t"]] = ti + 1
            lk["_fo"], lk["_no"] = fo, out_n[lk["f"]]
            lk["_ti"], lk["_mi"] = ti, in_n[lk["t"]]
            item = SimLinkItem(lk, s, d, self)
            self._link_items.append(item)
            self.canvas._scene.addItem(item)

    def on_node_moved(self, item):
        # ⚠️ 必须 prepareGeometryChange (2026-08-05 修复): 连线 boundingRect 随节点位置
        # 动态变化, 只 update() 时 QGraphicsView 渲染索引仍缓存旧矩形 → 节点移出旧矩形
        # 后连线不重绘=消失, 再移动碰回范围又出现. prepareGeometryChange 通知场景几何已变
        for li in self._link_items:
            li.prepareGeometryChange()
            li.update()
        self._tutorial_on_node_moved()

    def on_zoom(self, scale):
        self._log(f"🔍 {round(scale * 100)}%")

    # ── 仿真 (对标 Simulink Run/Step) ──
    def _tick(self):
        """定时器驱动连续仿真"""
        self.step_sim()
        if self._sim_t >= self._sim_t_end:
            self.stop_sim()

    def _compare_load_hint(self):
        """对比模板加载后的气泡引导: 高亮对比评估节点 + 气泡提示"""
        try:
            scope = next((n for n in self.nodes if "对比评估" in n.get("name", "")), None)
            if scope is not None:
                self._highlight_node(scope, ms=6000)
                it = self._items.get(scope["id"])
                if it is not None:
                    gp = self.canvas.mapToGlobal(
                        self.canvas.mapFromScene(it.sceneBoundingRect().center()))
                    self._show_bubble(gp, "👆 双击金色高亮「📊 对比评估 Scope (仿真)」→ 查看两Model Zoo图表\n"
                                         "(先点「▶ 运行」训练 ACT + SmolVLA)", ms=6000)
        except Exception:
            pass

    def open_compare5(self):
        """🔬 Model Zoo (2026-08-05 老倪: "ACT SmolVLA smolvla+lew VLA-Touch AWE 5个模型
        放到一起, 纵向对比" — 技术选型终极画布):
        加载「🔬 Model Zoo」模板 — 五条模型线同画布, 同构模块同列垂直对齐"""
        if self.nodes:
            if not self._qmsg_yes("🔬 Model Zoo",
                                  "将清空当前画布, 加载 Model Zoo?\\n\\n"
                                  "模块划分: ♻共用 (metaworld数据 / 对比评估Scope / 推理对比)\\n"
                                  "          五模型分支: ACT 7 + SmolVLA 4 + SmolVLA+LEW 5\\n"
                                  "                     + VLA-Touch 6 + AWE 6\\n"
                                  "🔬 五模型: ACT / SmolVLA / SmolVLA+LEW / VLA-Touch / AWE\\n"
                                  "同构模块同列: 视觉编码列 / 世界模型列 / ActionHead列 / 训练列\\n"
                                  "▶ 点「▶ 运行」→ 依次训练 5 模型 → 双击 Scope 看对比图表"):
                return
        self.clear()
        if not self.load_reference_app_by_name("🔬 Model Zoo"):
            self._qmsg_info("🔬 Model Zoo", "模板加载失败")
            return
        self._log("════ 🔬 Model Zoo (统一 metaworld 数据集 · 纵向对比) ════")
        self._log("📦 模块划分: ♻共用 3 (metaworld数据 / 对比评估Scope / 推理效果对比) + 五模型分支")
        self._log("🔬 ① ACT 7: ResNet18→Encoder→Decoder→ActionHead→Ensemble→训练 (无VAE确定性回归)")
        self._log("🔬 ② SmolVLA 4: SmolVLM2→DiT-B→ActionHead→训练 (扩散, 无世界模型)")
        self._log("🔬 ③ SmolVLA+LEW 5: SmolVLM2→DiT-B→LeWorldModel→ActionHead→训练 (扩散+世界模型)")
        self._log("🖐 ④ VLA-Touch 6: DINOv2→Marker→DiT-B base VLA→ActionHead→Interpolant→训练 (触觉增强)")
        self._log("🧿 ⑤ AWE 6: SigLIP视触觉编码→H-JEPA三层潜空间→zFlow世界引擎→未来决策交叉注意力→ActionHead→训练 (场景原生)")
        self._log("📍 同构模块同列垂直对齐: 视觉编码列 / 动作生成列 / 世界模型列 / ActionHead列 / 训练列")
        self._log("▶ 点「▶ 运行」→ 依次训练 5 模型 (各 50 步快速验证) → 双击「📊 对比评估 Scope (仿真)」看Model Zoo")
        # 🎨 8 行彩色背景 + 左侧大字模型名 (2026-08-07: YOLO 感知链独占首行 + 七模型;
        # 背景行从首行开始排, 否则 ACT 背景会盖在感知行上 → 背景与模型行错位)
        # n_cols=12 (2026-08-07 老倪: 训练右侧=仿真推理, 再右侧=仿真视频 — 12 列布局)
        self._draw_model_rows(["YOLO 3D", "ACT", "SmolVLA", "SmolVLA+LEW",
                               "VLA-Touch", "AWE", "MLP 蒸馏", "官方专家"], n_cols=12)
        QTimer.singleShot(300, lambda: self._compare_load_hint())

    def open_z700_flow(self):
        """🚀 Z700 快捷打开 (2026-08-12 老倪): 一键加载 Z700 完整工程 —
        🎯YOLO感知链 → 🧠双脑+状态机 → ▶交付 (flows/dual_brain_peg_yolo.json)"""
        flow = os.path.join(self._repo_root(), "flows", "dual_brain_peg_yolo.json")
        if not os.path.exists(flow):
            self._log("⚠️ 缺 flows/dual_brain_peg_yolo.json — 先跑 tools/gui/gen_dual_brain_yolo_flow.py")
            self._qmsg_info("🚀 Z700", "缺 flows/dual_brain_peg_yolo.json\n\n先运行:\npython3 tools/gui/gen_dual_brain_yolo_flow.py")
            return
        if self.nodes:
            if not self._qmsg_yes("🚀 Z700",
                                  "将清空当前画布, 加载 Z700 完整工程?\n\n"
                                  "🎨 YOLO感知: 🎯YOLO 3D → 📐2D→3D解算 → 🔌State Adapter\n"
                                  "🎨 双脑: 39D obs → 左脑MLP → 右脑WM → 接触判定\n"
                                  "🎨 状态机: LeftRightPolicy → 接近→抓取→抬起→转移→插入→完成\n"
                                  "🎨 交付: ▶插拔视频 | 📄PDF报告\n"
                                  "感知源码: src/lerobot/policies/yolo_3d/"):
                return
        self._log("🚀 打开 Z700 完整工程 (YOLO感知链 → 双脑+状态机 → 交付)…")
        self.load_flow_file(flow)

    def open_node_source(self, node):
        """📂 打开节点源代码 (2026-08-12 老倪: 右键 YOLO/双脑等节点)
        🐛 WSL 路径 Windows 打不开 (UNC 被拒) → 复制到 C:\\zmax_src_view + explorer 打开"""
        src = node.get("params", {}).get("source", "")
        if not src:
            self._log("⚠️ 该节点无源码映射 (params.source)")
            return
        path = os.path.join(self._repo_root(), src)
        if not os.path.exists(path):
            self._log(f"⚠️ 源码不存在: {path}")
            return
        import shutil, subprocess as _sp
        # 🐛 2026-08-12 老倪: 复制目标必须 WSL 路径 (/mnt/c/...), Windows 路径 "C:\\..." 
        # 在 Linux 是相对路径 → 复制到错误位置 → 右键打不开
        _name = os.path.basename(src.rstrip("/\\"))
        dst_mnt = os.path.join("/mnt/c/zmax_src_view", _name)   # shutil 复制用 (WSL)
        dst_win = os.path.join(r"C:\zmax_src_view", _name).replace("/", "\\")  # explorer 用 (Windows 反斜杠)
        try:
            if os.path.isdir(path):
                if os.path.exists(dst_mnt):
                    shutil.rmtree(dst_mnt)
                shutil.copytree(path, dst_mnt, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                os.makedirs(os.path.dirname(dst_mnt), exist_ok=True)
                shutil.copy2(path, dst_mnt)
            # 🐛 2026-08-12 老倪: cmd start 打开目录/.py 静默失败 (无关联程序) →
            # 改用 explorer.exe (资源管理器, 记忆验证过的链路)
            _sp.Popen(["explorer.exe", dst_win], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            self._log(f"📂 已打开源码: {dst_win} ({src})")
        except Exception as e:
            self._log(f"⚠️ 打开源码失败: {e}")

    def open_solution_web(self):
        """🌐 方案介绍 (2026-08-12 老倪: 画板直达方案介绍分页 — 不干扰主页)
        🐛 WSL 无 xdg-open → QDesktopServices 找不到浏览器 → cmd.exe start;
        🐛 2026-08-12: cwd 必须 Windows 目录 — WSL 当前目录是 UNC, cmd start 静默失败"""
        import subprocess as _sp
        url = "https://datadrive.world/solution.html"  # 📄 方案介绍分页 (主页保持不动)
        try:
            _sp.Popen(["cmd.exe", "/c", "start", "", url],
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, cwd="/mnt/c/Windows")
            self._log(f"🌐 打开方案介绍分页: {url} → Windows 浏览器")
        except Exception as e:
            self._log(f"⚠️ 打开链接失败: {e}")

    def open_vlatouch(self):
        """🖐 VLA-Touch 触觉对比 (2026-08-05 老倪: 参考 VLA-Touch 项目, 4060 精简):
        加载「🖐 VLA-Touch 触觉对比」模板 — base VLA 冻结只训 Interpolant 触觉控制器"""
        if self.nodes:
            if not self._qmsg_yes("🖐 VLA-Touch 触觉对比",
                                  "将清空当前画布, 加载 VLA-Touch 触觉对比?\\n\\n"
                                  "模块划分: ♻共用2 (metaworld数据 / 对比评估Scope) + VLA-Touch 6\\n"
                                  "🖐 VLA-Touch: DINOv2视觉 + Marker触觉 + DiT-B base VLA(冻结)\\n"
                                  "            + Interpolant 触觉控制器 (唯一训练模块)\\n"
                                  "▶ 点「▶ 运行」→ 训练控制器 → 双击 Scope 看对比图表"):
                return
        self.clear()
        if not self.load_reference_app_by_name("🖐 VLA-Touch 触觉对比"):
            self._qmsg_info("🖐 VLA-Touch 触觉对比", "模板加载失败")
            return
        self._log("════ 🖐 VLA-Touch 触觉对比 (4060 精简) ════")
        self._log("📦 模块划分: ♻共用 2 (metaworld数据 / 对比评估Scope) + VLA-Touch 6")
        self._log("🖐 官方 Manipulation 层: base VLA π(a|s,I) 生成动作 → Interpolant π_I(â|s,a,m) 用触觉精炼")
        self._log("🔧 4060 精简: DINOv2-small 冻结 + Marker 触觉跟踪 + DiT-B base VLA 冻结 + Interpolant 控制器 (唯一训练)")
        self._log("▶ 点「▶ 运行」→ 训练控制器 (50步快速验证) → 双击「📊 对比评估 Scope (仿真)」看对比")

    def open_awe(self):
        """🧿 AWE 场景原生对比 (2026-08-05 老倪: 它石 AWE 3.5/OmniVTA 架构):
        加载「🧿 AWE 场景原生对比」模板 — SigLIP 视触觉编码 + H-JEPA 三层潜空间 + zFlow GRU 世界引擎"""
        if self.nodes:
            if not self._qmsg_yes("🧿 AWE 场景原生对比",
                                  "将清空当前画布, 加载 AWE 场景原生对比?\\n\\n"
                                  "模块划分: ♻共用2 (metaworld数据 / 对比评估Scope) + AWE 6\\n"
                                  "🧿 AWE: SigLIP视触觉编码 + H-JEPA三层潜空间(z₁/z₂/z₃)\\n"
                                  "        + zFlow GRU 世界引擎 + 未来决策交叉注意力\\n"
                                  "▶ 点「▶ 运行」→ 训练 → 双击 Scope 看对比图表"):
                return
        self.clear()
        if not self.load_reference_app_by_name("🧿 AWE 场景原生对比"):
            self._qmsg_info("🧿 AWE 场景原生对比", "模板加载失败")
            return
        self._log("════ 🧿 AWE 场景原生对比 (它石架构 · 4060 精简) ════")
        self._log("📦 模块划分: ♻共用 2 (metaworld数据 / 对比评估Scope) + AWE 6")
        self._log("🧿 场景原生: SigLIP视触觉编码 (视觉+力觉+触觉原生融合) + H-JEPA 三层潜空间 (z₁空间/z₂物体/z₃语义) + zFlow GRU 世界引擎 + 未来决策交叉注意力")
        self._log("▶ 点「▶ 运行」→ 训练 (50步快速验证) → 双击「📊 对比评估 Scope (仿真)」看对比")

    def open_topsys(self):
        """🎛 顶层总系统 (2026-08-05 老倪: Simulink 子系统语义):
        加载 3 节点顶层 (数据→总系统块→评估Scope), 双击总系统块展开内部三条训练线"""
        if self.nodes:
            if not self._qmsg_yes("🎛 顶层总系统",
                                  "将清空当前画布, 加载顶层总系统?\n\n"
                                  "顶层: 📦metaworld数据 → 🔬总系统块 → 📊评估Scope\n"
                                  "双击总系统块 → 展开 ACT / SmolVLA / SmolVLA+LEW 三条训练线\n"
                                  "⬅ 在子系统内点「⬅ 返回总系统」恢复顶层"):
                return
        self.clear()
        if not self.load_reference_app_by_name("🎛 顶层总系统"):
            self._qmsg_info("🎛 顶层总系统", "模板加载失败")
            return
        self._log("════ 🎛 顶层总系统 (Simulink Subsystem) ════")
        self._log("顶层: 📦metaworld数据 → 🔬总系统块 → 📊对比评估Scope")
        self._log("双击「🔬 总系统」块 → 展开内部「🔬 Model Zoo」七模型训练线")
        self._log("⬅ 在子系统内点工具栏「⬅ 返回总系统」恢复顶层")
        QTimer.singleShot(300, lambda: self._topsys_hint())

    def _topsys_hint(self):
        """顶层总系统加载后气泡引导: 高亮总系统块提示双击展开"""
        try:
            sys_node = next((n for n in self.nodes if n.get("params", {}).get("subsystem")), None)
            if sys_node is not None:
                self._highlight_node(sys_node, ms=6000)
                it = self._items.get(sys_node["id"])
                if it is not None:
                    gp = self.canvas.mapToGlobal(
                        self.canvas.mapFromScene(it.sceneBoundingRect().center()))
                    self._show_bubble(gp, "👆 双击金色高亮「🔬 总系统」\n"
                                         "→ 展开 ACT / SmolVLA / SmolVLA+LEW 三条训练线", ms=6000)
        except Exception:
            pass

    def toggle_float_canvas(self):
        """⛶ 浮动画布: 画布从 MDI 子窗口取出 → 独立可最大化窗口 (非模态, 日志栏仍可见)
        再点按钮或关闭浮动窗口 → 自动还原回 MDI"""
        dlg = getattr(self, "_float_dlg", None)
        if dlg is not None and dlg.isVisible():
            dlg.close()  # closeEvent → _restore_canvas
            return
        mdi = getattr(self, "_mdi", None)
        if mdi is not None:
            win = getattr(self, "_canvas_win", None)
            if win is None or win not in mdi.subWindowList():
                return
            mdi.removeSubWindow(win)  # 从 MDI 移除 (canvas 仍在 subwin 内, 不销毁)
            win.hide()
        # FloatingCanvasDialog 构造时 lay.addWidget(canvas) 自动 reparent
        dlg = FloatingCanvasDialog(self, self.canvas, self.window())
        self._float_dlg = dlg
        dlg.show()  # 非模态: 主窗口日志/按钮仍可操作
        self._log("⛶ 画布已浮动 — 拖标题栏移动 · 拖边缩放 · 点最大化看全图; 关闭浮动窗口自动还原")

    def _restore_canvas(self):
        """浮动窗口关闭 → 画布还原回主窗口 MDI 子窗口"""
        mdi = getattr(self, "_mdi", None)
        if mdi is None:
            self._float_dlg = None
            return
        old = getattr(self, "_canvas_win", None)
        if old is not None:
            old.deleteLater()  # 旧空子窗口清理 (canvas 已 reparent, 不受影响)
        self._canvas_win = QMdiSubWindow()
        self._canvas_win.setWidget(self.canvas)  # 自动 reparent 回 MDI 子窗口
        # 🖥 2026-08-06: 与主窗口创建一致 — 去掉标题栏按钮 + 铺满 MDI (修复:
        # 浮动关闭后还原 show() 只有 920x620 → 露灰色背景)
        self._canvas_win.setWindowFlags(
            self._canvas_win.windowFlags()
            & ~Qt.WindowMinimizeButtonHint & ~Qt.WindowMaximizeButtonHint
            & ~Qt.WindowCloseButtonHint)
        self._canvas_win.setWindowTitle("画布")
        self._canvas_win.resize(920, 620)
        self._mdi.addSubWindow(self._canvas_win)
        self._canvas_win.showMaximized()  # 铺满 MDI, 不露背景
        self._mdi.setActiveSubWindow(self._canvas_win)
        self._log("⛶ 画布已还原回主窗口 (铺满)")
        self._float_dlg = None

    # (2026-08-06 老倪: 「🪟 画布窗口」按钮+show_canvas_win 方法删除 — 画布子窗口
    #  已不可最小化/关闭, 恢复逻辑无存在必要)

    # ── 🎛 Simulink 子系统 (2026-08-05 老倪: "顶层系统用一个模块表示, 双击打开看到三条线") ──
    def _open_subsystem(self, node):
        """双击子系统节点: 保存当前顶层 flow → 加载子系统内部模板"""
        sub_name = node.get("params", {}).get("subsystem", "")
        if not sub_name:
            return
        # 保存顶层 flow (含节点位置) 到子系统栈, 供「⬅ 返回」恢复
        top_flow = {"format": "zmax-simulink", "version": "1.0", "name": node.get("name", "top"),
                    "sim": {"dt": self._sim_dt, "t_end": self._sim_t_end, "solver": "fixed-step"},
                    "nodes": self.nodes, "links": self.links}
        if not hasattr(self, "_subsystem_stack"):
            self._subsystem_stack = []
        self._subsystem_stack.append(top_flow)
        # 加载子系统内部模板 (三Model Zoo: 三条并行训练线)
        if not self.load_reference_app_by_name(sub_name):
            self._subsystem_stack.pop()
            self._qmsg_info("🎛 子系统", f"找不到子系统模板: {sub_name}")
            return
        self._subsystem_active = True
        self._update_back_btn()
        self._log(f"🎛 已进入子系统「{sub_name}」— ACT / SmolVLA / SmolVLA+LEW 三条并行训练线")
        self._log("   ▶ 点「▶ 运行」依次训练三模型 → 双击「📊 对比评估 Scope (仿真)」出对比图表")
        self._log("   ⬅ 完成后点工具栏「⬅ 返回总系统」恢复顶层")
        QTimer.singleShot(300, lambda: self._compare_load_hint())

    def back_to_subsystem(self):
        """⬅ 返回上一层: 恢复子系统栈顶的 flow"""
        if not getattr(self, "_subsystem_stack", None):
            self._log("已在顶层, 无上级系统")
            return
        top_flow = self._subsystem_stack.pop()
        self.load_flow(top_flow)
        if not self._subsystem_stack:
            self._subsystem_active = False
        self._update_back_btn()
        self._log(f"⬅ 已返回: {top_flow.get('name', '总系统')} ({len(top_flow.get('nodes', []))}节点)")

    def _update_back_btn(self):
        """子系统返回按钮显隐: 在子系统内才显示"""
        btn = getattr(self, "btn_back", None)
        if btn is None:
            return
        btn.setVisible(bool(getattr(self, "_subsystem_stack", None)))

    # ── 🎥 录屏 (2026-08-05 老倪: 训练→推理→部署全程录制, 可加速, 总长<1分钟) ──
    def start_recording(self):
        """🔴 录制: QTimer 定时 grab 整窗 (画布+终端+模型结果) → 存 JPG 序列
        2026-08-05 反馈修复: 加醒目录制中指示 (按钮变「⏺ 录制中…」红色呼吸闪烁),
        用户点录制要有明确视觉反馈"""
        if getattr(self, "_rec_timer", None) and self._rec_timer.isActive():
            return
        root = self._repo_root()
        self._rec_dir = os.path.join(root, "reports", f"screenrec_{time.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(self._rec_dir, exist_ok=True)
        self._rec_idx = 0
        self._rec_start = time.time()
        self._rec_timer = QTimer(self)
        self._rec_timer.timeout.connect(self._rec_tick)
        self._rec_timer.start(1000)  # 1fps 采集 (2026-08-05: 500ms grab 大窗卡UI停止按钮无响应 → 1s 减负)
        # 🎬 录制中视觉指示: 按钮变红字 + 呼吸闪烁 (500ms 交替样式)
        self.btn_record.setText("⏺ 录制中…")
        self.btn_record.setEnabled(True)   # 保持可点? 不, 录制中禁点(防重复), 用样式表强调
        self.btn_record.setEnabled(False)
        self._rec_busy = False  # 防堆积: 上一次 grab 未完成则跳过本次
        self._rec_blink = QTimer(self)
        self._rec_blink.timeout.connect(self._rec_blink_tick)
        self._rec_blink.start(500)
        self._rec_blink_on = True
        self._rec_style_normal = self.btn_record.styleSheet()
        self.btn_stop_rec.setEnabled(True)
        self._log(f"🔴 录屏开始 → {os.path.relpath(self._rec_dir, root)} (1fps 采集, 停止后合成 MP4)")

    def _rec_blink_tick(self):
        """呼吸闪烁: 交替按钮背景红/深红"""
        try:
            self._rec_blink_on = not self._rec_blink_on
            bg = "#b32424" if self._rec_blink_on else "#7a1a1a"
            self.btn_record.setStyleSheet(
                f"QPushButton {{ background:{bg}; color:white; border:2px solid #ff5555; "
                f"border-radius:5px; padding:5px 14px; font-size:12px; font-weight:800; }}")
        except Exception:
            pass

    def _rec_tick(self):
        """采集一帧: 整窗截图 (含终端输出/模型结果/画布) — JPEG 快速保存 (2026-08-05:
        PNG 压缩大图慢 → UI 卡顿停止按钮无响应; JPEG q85 快 ~10x; 防堆积: busy 标志
        上一次 grab 未完成跳过, 保证事件循环不被占满)"""
        if getattr(self, "_rec_busy", False):
            return  # 上一帧还在处理 (grab+save 超 1s), 跳过保持 UI 响应
        try:
            self._rec_busy = True
            pm = self.grab()
            if not pm.isNull():
                pm.save(os.path.join(self._rec_dir, f"frame_{self._rec_idx:04d}.jpg"), "JPG", 85)
                self._rec_idx += 1
                # 状态提示: 每 30 帧 (30s) 更新一次
                if self._rec_idx % 30 == 0:
                    self._log(f"⏺ 录屏中: {self._rec_idx} 帧 · {time.time() - self._rec_start:.0f}s")
        except Exception:
            pass
        finally:
            self._rec_busy = False

    def stop_recording(self):
        """⏹ 停止: 停定时器 → 后台线程 ffmpeg 合成 MP4 (2026-08-05: 合成移后台,
        停止按钮立即响应不再卡 UI)"""
        if getattr(self, "_rec_timer", None):
            self._rec_timer.stop()
        # 停呼吸闪烁, 恢复按钮
        blink = getattr(self, "_rec_blink", None)
        if blink is not None:
            blink.stop()
        self.btn_record.setText("🔴 录制")
        try:
            self.btn_record.setStyleSheet(getattr(self, "_rec_style_normal", ""))
        except Exception:
            pass
        self.btn_record.setEnabled(True)
        self.btn_stop_rec.setEnabled(False)
        rec_dir = getattr(self, "_rec_dir", "")
        n = getattr(self, "_rec_idx", 0)
        if not rec_dir or n == 0:
            self._log("⚠️ 无录屏帧 (录制时间过短)")
            return
        dur = time.time() - getattr(self, "_rec_start", time.time())
        fps = 1.0  # 1fps 采集 → 合成 2fps 输出 = 2x 加速
        out_mp4 = os.path.join(rec_dir, "screen_rec.mp4")
        self._log(f"⏳ 正在合成视频 ({n} 帧, ffmpeg 后台)…")
        import threading
        t = threading.Thread(target=self._ffmpeg_compose, args=(rec_dir, out_mp4, fps, n, dur), daemon=True)
        t.start()

    def _ffmpeg_compose(self, rec_dir, out_mp4, fps, n, dur):
        """(后台线程) ffmpeg 合成 MP4 — 1fps 采集帧以 2fps 播放 = 2x 加速
        2026-08-05: -framerate 1 + -r 2 不加速 (时长按输入帧数), 直接 -framerate 2 播放"""
        import subprocess
        play_fps = fps * 2  # 1fps 采集 → 2fps 播放 = 2x 加速
        cmd = ["ffmpeg", "-y", "-framerate", str(play_fps), "-i",
               os.path.join(rec_dir, "frame_%04d.jpg"),
               "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
               "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-r", str(play_fps), out_mp4]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                vlen = dur / 2.0
                self.log_signal.emit(
                    f"✅ 录屏完成: {os.path.relpath(out_mp4, self._repo_root())} · {n}帧 · "
                    f"录制{dur:.0f}s → 视频{vlen:.0f}s (加速2x, 总长<1min)")
            else:
                self.log_signal.emit(f"❌ ffmpeg 合成失败: {r.stderr[-200:]}")
        except Exception as ex:
            self.log_signal.emit(f"❌ 录屏合成异常: {ex}")

    def save_trained_model(self):
        """💾 保存模型 (2026-08-05 老倪: 训练好的模型保存, 下次直接应用):
        读 reports/train_curve_<policy>.json 的 ckpt 路径 → 复制 last/pretrained_model
        到 models/saved/<policy>_<ts>/ → 写 models/saved/registry.json (推理服务下拉读取)"""
        import shutil
        root = self._repo_root()
        saved_dir = os.path.join(root, "models", "saved")
        os.makedirs(saved_dir, exist_ok=True)
        # 1) 收集所有已训练策略的 checkpoint
        found = []
        for f in sorted(glob.glob(os.path.join(root, "reports", "train_curve_*.json"))):
            policy = os.path.basename(f).replace("train_curve_", "").replace(".json", "")
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            ckpt_base = d.get("ckpt", "")
            last_pm = os.path.join(root, ckpt_base, "last", "pretrained_model")
            if not os.path.isdir(last_pm):
                last_pm = os.path.join(root, ckpt_base, "000300", "pretrained_model")
            if not os.path.isdir(last_pm):
                self._log(f"⚠️ {policy}: 无可用 checkpoint ({ckpt_base})")
                continue
            found.append((policy, d.get("name", policy), last_pm, d.get("step_s", 0)))
        if not found:
            self._qmsg_info("💾 保存模型", "没有已训练的模型 — 先点「▶ 运行」训练至少一个模型")
            return
        # 2) 复制到 models/saved/
        saved_names = []
        for policy, pname, pm_path, step_s in found:
            dst = os.path.join(saved_dir, f"{policy}_{time.strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(dst, exist_ok=True)
            try:
                shutil.copytree(pm_path, os.path.join(dst, "pretrained_model"), dirs_exist_ok=True)
                saved_names.append({"policy": policy, "name": pname, "path": dst,
                                    "step_s": step_s, "ts": time.strftime("%Y%m%d_%H%M%S")})
                self._log(f"💾 已保存模型: {pname} ({policy}) → {os.path.relpath(dst, root)}")
            except Exception as ex:
                self._log(f"❌ 保存失败 {policy}: {ex}")
        # 3) 写 registry.json (推理面板下拉读)
        reg_path = os.path.join(saved_dir, "registry.json")
        reg = []
        if os.path.exists(reg_path):
            try:
                reg = json.load(open(reg_path, encoding="utf-8"))
            except Exception:
                reg = []
        reg.extend(saved_names)
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
        self._log(f"💾 已更新模型注册表: {os.path.relpath(reg_path, root)} ({len(saved_names)} 个新模型)")
        # 4) 气泡提示
        try:
            gp = self.mapToGlobal(self.btn_save_model.rect().center())
            self._show_bubble(gp, f"✅ 已保存 {len(saved_names)} 个模型\n"
                                  f"推理服务 → 推理页「已保存模型」下拉直接选\n"
                                  f"路径: models/saved/", ms=5000)
        except Exception:
            pass

    def show_compare(self):
        """性能对比弹窗: 基础模型 vs 微调模型 (读取 CICD_COMPARE_*.json)"""
        import glob
        proj = str(Path(__file__).parent.parent.parent)
        jsons = sorted(glob.glob(os.path.join(proj, "docs", "CICD_COMPARE_*.json")))
        if not jsons:
            self._qmsg_info("性能对比", "⚠️ 无对比数据\n\n请先运行:\n  python3 tools/act_compare.py\n生成 CICD_COMPARE_*.json")
            return
        d = json.load(open(jsons[-1]))
        base, cand = d["baseline"], d["candidate"]
        imp = d.get("mse_improve_pct", 0)
        improved = imp > 0
        verdict = "✅ 提升" if improved else "❌ 未提升 (需改进重训)"
        color = "#2ea043" if improved else "#f85149"

        # 构造对比面板 (QDialog)
        dlg = QDialog(self)
        dlg.setWindowTitle("📊 模型性能对比 (基础 vs 微调)")
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)

        head = QLabel(f"<span style='font-size:15px;font-weight:700;color:{color}'>{verdict}</span> "
                      f"<span style='color:#57606a'> · MSE 提升 {imp:+.1f}%</span>")
        lay.addWidget(head)

        table = QTextEdit()
        table.setReadOnly(True)
        table.setStyleSheet("background:#f6f8fa; color:#24292f; border:1px solid #d0d7de; font-family:Consolas; font-size:12px;")
        rows = [
            ("指标", "基础模型", "微调模型", "提升"),
            ("动作 MSE", f"{base['action_mse']:.2f}", f"{cand['action_mse']:.2f}", f"{imp:+.1f}%"),
            ("成功率", f"{base['success_rate']*100:.1f}%", f"{cand['success_rate']*100:.1f}%",
             f"{(cand['success_rate']-base['success_rate'])*100:+.1f}pp"),
            ("推理延迟", f"{base['latency_ms']:.1f}ms", f"{cand['latency_ms']:.1f}ms",
             f"{cand['latency_ms']-base['latency_ms']:+.1f}ms"),
            ("测试帧数", str(base['frames']), str(cand['frames']), "-"),
        ]
        # 对齐列宽
        w0 = max(len(r[0]) for r in rows) + 2
        w1 = max(len(r[1]) for r in rows) + 2
        w2 = max(len(r[2]) for r in rows) + 2
        text = "\n".join(f"{r[0].ljust(w0)}{r[1].ljust(w1)}{r[2].ljust(w2)}{r[3]}" for r in rows)
        table.setPlainText(text)
        lay.addWidget(table)

        note = QLabel(f"<span style='color:#57606a;font-size:11px'>对比文件: {os.path.basename(jsons[-1])}<br>"
                      f"提升路径: 基础(300步) → 更多数据 → 更长训练 → 超参调优 → 架构升级(SmolVLA)</span>")
        lay.addWidget(note)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        self._show_nonmodal(dlg)  # 非模态, 2026-08-05 防卡死

    def show_scope(self):
        """打开 Scope 示波器对比 (新老模型动作曲线)"""
        try:
            from simulink_scope import ScopeCompareDialog
        except ImportError:
            self._qmsg_info("Scope", "缺少 simulink_scope.py 模块")
            return
        dlg = ScopeCompareDialog(self)
        self._show_nonmodal(dlg)  # 非模态, 2026-08-05 防卡死

    def start_sim(self):
        # 🚀 即时反馈 (2026-08-05 老倪: "运行, 还是没反应" — 点击瞬间按钮变运行中+状态栏提示)
        self.btn_run.setText("⏳ 运行中…")
        self.btn_run.setEnabled(False)
        self._log("▶ 运行指令已接收, 正在解析画布…")
        if not self.nodes:
            self.btn_run.setText("▶ 运行")
            self.btn_run.setEnabled(True)
            self._log("⚠️ 画布为空 — 点击上方「🗂 参考应用」一键加载模板, 或从左侧模块库添加节点")
            if self._tutorial_active:
                self._tutorial_hint_mismatch("run", "pipeline")
            return
        # 🧠 2026-08-10 老倪: ▶ 运行 = left_right 工程画布 → 自动启动标准训练 (优先于环节节点
        #   — 画布含「📄 PDF 报告」节点会命中 NODE_RUN_ACTIONS 的 on_pdf_report, 必须放最前)
        if any(n.get("name") == "◉ LeftRightPolicy" for n in self.nodes):
            self._log("🧠 检测到 left_right 工程 (双脑+状态机) — ▶ 运行 = 自动启动标准训练 (lerobot_train --policy left_right)")
            self._log("   └ 配置: config_left_right.yaml · 39D 数据集 · 3000 步 · 容器强制 (zmax-std:1.0)")
            self.on_train(policy="left_right")
            return
        # 🆕 ▶ 运行 = 画布真实全流程: 画布上有环节节点(采集/训练/验证/集成/部署/推理)
        #   就按拓扑顺序真实执行 (老倪: "运行按钮应该启动整个流程"), 没有环节节点才走拓扑仿真
        stages = self._canvas_stage_nodes()
        if stages:
            self._start_canvas_flow(stages)
            return
        # 2026-08-05 老倪: "点击运行, 感觉没反应, 没有反馈" — 有节点但无执行环节
        #   (总系统/Scope 观察模板) → 自动展开子系统块后重试, 仍无环节才明确提示
        sub_node = next((n for n in self.nodes if n.get("params", {}).get("subsystem")), None)
        if sub_node is not None:
            self._log(f"🎛 检测到子系统块「{sub_node['name']}」— 自动展开内部流程…")
            self._open_subsystem(sub_node)
            _app = __import__("PyQt5.QtWidgets", fromlist=["QApplication"]).QApplication.instance()
            if _app is not None:
                _app.processEvents()
            stages = self._canvas_stage_nodes()
            if stages:
                self._log("▶ 子系统已展开, 启动内部真实流程…")
                self._start_canvas_flow(stages)
                return
            self._log("⚠️ 子系统内部也无执行环节节点")
            self._show_bubble(self.rect().center(), "子系统内部无执行环节 — 加载「🔬 三Model Zoo」模板再运行", 5000)
            return
        self._log("ℹ️ 画布无执行环节节点 (采集/训练/验证/部署/推理) — 进入观察模式")
        self._show_bubble(self.rect().center(), "画布无执行环节 — 加载「🔬 三Model Zoo」等模板再运行", 5000)
        self._sim_t = 0.0
        # 🐛 2026-08-06: sp_dt/sp_t_end 控件已删 (老倪: 没用), 用内部默认值
        self._sim_dt = getattr(self, "_sim_dt", 0.02)
        self._sim_t_end = getattr(self, "_sim_t_end", 10.0)
        self._sim_running = True
        # 重置所有节点状态为 idle
        for n in self.nodes:
            n["status"] = "idle"
            it = self._items.get(n["id"])
            if it:
                it.update()
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._log(f"▶ 仿真开始 · t∈[0, {self._sim_t_end}s] · dt={self._sim_dt}s · 节点数={len(self.nodes)}")
        self._timer.start(max(16, int(self._sim_dt * 1000 / 10)))  # 每步最多10x加速
        self._refresh_status()
        self._tutorial_on_action("run")

    def _canvas_stage_nodes(self):
        """画布上匹配 NODE_RUN_ACTIONS 的环节节点, 按拓扑(依赖)顺序.
        Scope 示波器是观察节点 → 排除 (训练完用户手动双击看波形, 不阻塞自动流程)"""
        order = self._topo_sort()
        out = []
        for nid in order:
            n = self._by_id(nid)
            if "Scope" in n.get("name", ""):
                continue  # 📊 Scope 手动双击观察
            if n.get("params", {}).get("video"):
                continue  # 🎥 视频显示节点: 观察类, 训练完手动双击播放 (2026-08-05 修复:
                #   "推理"关键字会误匹配 on_infer → 混进Model Zoo执行队列阻塞流程)
            if n.get("type") == "train_gate":
                continue  # ☑ 训练开关: 控制标志非执行环节 ("训练"关键字会误匹配 on_train,
                #   CICD 主控台 ▶运行 时被当环节执行 → 打乱流程语义; 开关状态由 on_train 内部检查)
            for kw, meth in self.NODE_RUN_ACTIONS:
                if kw in n.get("name", ""):
                    out.append((n, meth, kw))
                    break
        return out

    def _start_canvas_flow(self, stages):
        """▶ 运行: 环节节点按拓扑序真实执行 (复用 _flow_queue 自动流转)
        2026-08-05 优化: 多个训练节点按耗时升序排 (act→smolvla→smolvla_lew),
        让 3 条曲线尽快在 Scope 里齐 (老倪: 应该是3条曲线同时生成, 不是一个大点+一条)"""
        w = getattr(self, "_worker", None)
        if w is not None:
            # 🐛 2026-08-06: worker 终止竞态 → wait(300) 等正常收尾放行
            if w.isRunning() and not w.wait(300):
                self._log(self._busy_hint())
            return
        # 训练节点耗时升序 (act 最快 → smolvla → smolvla_lew → vla_touch → awe_zflow 最慢),
        # 其余环节保持拓扑序; 未知 policy 排最后
        # (2026-08-07: expert_mlp 蒸馏快, expert_policy 基准秒回 — 排最后不阻塞)
        _speed = {"act": 0, "smolvla": 1, "smolvla_lew": 2, "vla_touch": 3,
                  "awe_zflow": 4, "expert_mlp": 5, "expert_policy": 6}
        stages = sorted(stages, key=lambda s: _speed.get(s[0].get("params", {}).get("policy", ""), 9))
        names = " → ".join(f"「{n['name']}」" for n, _, _ in stages)
        self._log(f"▶ 真实全流程启动 ({len(stages)} 环节): {names}")
        # 2026-08-05 老倪: "打开就有个smolvla+lew" — 多训练节点(三Model Zoo)启动时清空
        # 全部曲线文件, 本轮从零开始 (Scope 只显示本轮三模型); 单训练节点不清 (保留历史)
        _train_stages = [s for s in stages if "训练" in s[2]]
        if len(_train_stages) >= 2:
            try:
                import glob as _g2
                root0 = self._repo_root()
                for _old in _g2.glob(os.path.join(root0, "reports", "train_curve_*.json")):
                    os.remove(_old)
                self._log(f"🧹 三Model Zoo: 已清空旧曲线, 本轮从零开始")
            except Exception:
                pass
        # (2026-08-06 老倪: 「运行已启动」小窗口不许弹 — 弹窗遮挡画布/训练进度,
        #  按钮状态(⏳运行中) + 日志区已足够反馈)
        # 🎛 运行中按钮状态 (2026-08-05 老倪: 停止按钮灰了) — 真实流程运行时 btn_stop 可用
        self.btn_run.setText("⏳ 运行中…")
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        # ⏱ 流程时钟 (2026-08-06 老倪: 点击运行 t 时间也不变 — 真实流程不走仿真 tick,
        #   底部状态栏 t 停在 0.00; 加独立 1s 时钟, 结束/停止时停)
        self._sim_t = 0.0
        if getattr(self, "_flow_clock", None) is None:
            self._flow_clock = QTimer(self)
            self._flow_clock.timeout.connect(self._flow_clock_tick)
        self._flow_clock.start(1000)
        for n in self.nodes:
            n["status"] = "idle"
            it = self._items.get(n["id"])
            if it:
                it.update()
        self.canvas._scene.update()
        self._flow_queue = [
            (lambda n=n, m=m, k=k: self._run_node_stage(n, getattr(self, m, None), k))
            for n, m, k in stages]
        # 🔎 2026-08-06 老倪: 队列任务名列表 (防重入提示显示剩余具体任务)
        self._flow_names = [n["name"] for n, m, k in stages]
        self._flow_next()
        self._tutorial_on_action("run")

    def step_sim(self):
        if not self.nodes:
            self._log("⚠️ 画布为空")
            return
        self._sim_t += self._sim_dt
        self._exec_topological()
        self._tutorial_on_action("step")
        if self._sim_t >= self._sim_t_end:
            self.stop_sim()

    def _exec_topological(self):
        order = self._topo_sort()
        self._log(f"⚡ 单步执行 [{len(order)} 节点] · " + " → ".join(
            [self._by_id(n)["name"] for n in order][:6]) + (" …" if len(order) > 6 else ""))
        for nid in order:
            n = self._by_id(nid)
            self._sim_node(n)

    def _sim_node(self, n):
        """本地模拟节点执行: 标记运行中→成功, 画布实时变色"""
        t = n["type"]
        p = n.get("params", {})
        # 状态: 运行中 (青色)
        n["status"] = "running"
        item = self._items.get(n["id"])
        if item:
            item.update()
        self.canvas._scene.update()
        # 模拟执行
        if t == "model":
            self._log(f"  🧠 {n['name']}: 推理完成 ({p.get('checkpoint', 'model')})")
        elif t == "action":
            self._log(f"  ➤ {n['name']}: 动作执行 {' | '.join(f'{k}={v}' for k, v in p.items())}")
        elif t == "hardware":
            self._log(f"  ▣ {n['name']}: 心跳 OK ({p.get('ip', '-')})")
        elif t == "condition":
            self._log(f"  ❖ {n['name']}: 条件评估 → 通过")
        else:
            self._log(f"  ◉ {n['name']}: 调度节点运行")
        # 状态: 成功 (绿)
        n["status"] = "success"
        if item:
            item.update()
        self.canvas._scene.update()
        self._refresh_status()

    def _refresh_status(self):
        """刷新底部实时状态栏 (节点计数/运行状态/时钟)"""
        total = len(self.nodes)
        ok = sum(1 for n in self.nodes if n.get("status") == "success")
        running = sum(1 for n in self.nodes if n.get("status") == "running")
        err = sum(1 for n in self.nodes if n.get("status") == "error")
        self.lbl_node_status.setText(f"节点: {total} | 成功: {ok} | 运行中: {running} | 失败: {err}")
        if self._sim_running:
            self.lbl_sys_state.setText("▶ 仿真运行中")
            self.lbl_sys_state.setStyleSheet("color:#00d4aa; font-size:11px; font-weight:700; background:transparent; border:none;")
        else:
            self.lbl_sys_state.setText("⏸ 待机")
            self.lbl_sys_state.setStyleSheet("color:#57606a; font-size:11px; font-weight:600; background:transparent; border:none;")
        self.lbl_rt.setText(f"t = {self._sim_t:.2f}s · dt = {self._sim_dt}s")

    def _topo_sort(self):
        """DAG 拓扑排序 (连线确定执行顺序)"""
        adj = {n["id"]: [] for n in self.nodes}
        indeg = {n["id"]: 0 for n in self.nodes}
        for l in self.links:
            if l["f"] in adj and l["t"] in adj:
                adj[l["f"]].append(l["t"])
                indeg[l["t"]] += 1
        q = [nid for nid, d in indeg.items() if d == 0]
        order = []
        while q:
            nid = q.pop(0)
            order.append(nid)
            for m in adj[nid]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
        # 剩余 (有环) 追加
        for n in self.nodes:
            if n["id"] not in order:
                order.append(n["id"])
        return order

    def _kill_train_processes(self):
        """⏹ 统一停止训练进程/容器 (2026-08-12 修复: 训练走 sudo docker run → 容器内
        python 是 root, 普通用户 pkill 无权限杀不掉 → sudo pkill + docker kill 双保险)"""
        import subprocess as _sp
        for pat in ("lerobot.scripts.lerobot_train", "train_awe_zflow",
                    "train_vla_touch", "train_yolo", "distill_expert",
                    "tools.cicd_pipeline"):
            try:
                _sp.run(["sudo", "-n", "pkill", "-9", "-f", pat],
                        capture_output=True, timeout=8)
            except Exception:
                pass
        # 🐳 docker kill: 容器内 python 进程是 root, pkill 只能杀 docker run 客户端,
        # 容器照样跑 → 直接 kill 容器 (daemon 执行, 无权限问题)
        try:
            out = _sp.run(["sudo", "-n", "docker", "ps", "-q",
                           "--filter", "ancestor=zmax-std:1.0"],
                          capture_output=True, text=True, timeout=10).stdout or ""
            for cid in out.split():
                _sp.run(["sudo", "-n", "docker", "kill", cid],
                        capture_output=True, timeout=10)
        except Exception:
            pass

    def on_stop(self):
        """studio 停止按钮 → simulink 停止 (2026-08-12: 原方法缺失, studio hasattr 静默失败)"""
        self.stop_sim()

    def stop_sim(self):
        self._sim_running = False
        self._timer.stop()
        # 2026-08-05 老倪: "运行点击之后停止按钮怎么变灰了" — 真实流程运行时 btn_stop
        # 应可用, 且点击后要真能终止训练 (原来只停仿真 timer 不碰 worker)
        w = getattr(self, "_worker", None)
        if w is not None and w.isRunning():
            self._kill_train_processes()
            try:
                # 2026-08-05 修复: 阻塞 wait 卡死 UI — 改 processEvents 轮询 (最大 10s,
                # 期间界面可拖动/日志刷新, 老倪: 怎么又卡死了)
                from PyQt5.QtWidgets import QApplication as _QA
                _app = _QA.instance()
                for _i in range(200):
                    if not w.isRunning():
                        break
                    if _app is not None:
                        _app.processEvents()
                    time.sleep(0.05)
            except Exception:
                pass
            self._flow_queue = []
            self._log("⏹ 已终止训练进程 (worker 已停止)")
        self.btn_run.setText("▶ 运行")
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        # 2026-08-06 老倪: 手动停止 → 停流程时钟
        fc = getattr(self, "_flow_clock", None)
        if fc is not None:
            fc.stop()
        self._log(f"⏹ 仿真停止 · t = {self._sim_t:.2f}s")
        self._refresh_status()
        self._tutorial_on_action("stop")

    def _by_id(self, nid):
        for n in self.nodes:
            if n["id"] == nid:
                return n
        return None

    # ── 导入/导出 (与 web 一致) ──
    def _dialog_ss(self):
        """🎨 对话框 QSS — 按当前主题动态生成 (2026-08-05 修复: 原 DIALOG_SS 是类常量
        硬编码浅色黑字 #1f2328, switch_theme 只替换 widget QSS 不更新常量 → 深色主题下
        消息框/文件框永远黑字看不清)"""
        pal = self._pal()
        bg, inp, bd, tx = pal["bg"], pal["input"], pal["border"], pal["text"]
        tx2 = pal["text2"]
        return f"""
        QFileDialog {{ background:{bg}; color:{tx}; }}
        QFileDialog QLabel {{ color:{tx}; font-size:12px; }}
        QFileDialog QLineEdit {{ background:{inp}; color:{tx}; border:1px solid {bd}; border-radius:4px; padding:4px 8px; }}
        QFileDialog QComboBox {{ background:{inp}; color:{tx}; border:1px solid {bd}; border-radius:4px; padding:4px; }}
        QFileDialog QComboBox QAbstractItemView {{ background:{bg}; color:{tx}; selection-background-color:#00d4aa44; }}
        QFileDialog QListView, QFileDialog QTreeView {{ background:{bg}; color:{tx}; border:1px solid {bd}; }}
        QFileDialog QListView::item:selected, QFileDialog QTreeView::item:selected {{ background:#00d4aa44; color:{tx}; }}
        QFileDialog QHeaderView {{ background:{bg}; color:{tx}; }}
        QFileDialog QHeaderView::section {{ background:{inp}; color:{tx}; border:none; border-right:1px solid {bd}; padding:4px 8px; font-weight:600; }}
        QFileDialog QPushButton {{ background:{inp}; color:{tx}; border:1px solid {bd}; border-radius:4px; padding:5px 14px; }}
        QFileDialog QPushButton:hover {{ border-color:#00d4aa; color:#00d4aa; }}
        QMessageBox {{ background:{bg}; color:{tx}; }}
        QMessageBox QLabel {{ color:{tx}; font-size:12px; }}
        QMessageBox QPushButton {{ background:{inp}; color:{tx}; border:1px solid {bd}; border-radius:4px; padding:6px 18px; font-size:12px; min-width:70px; }}
        QMessageBox QPushButton:hover {{ border-color:#00d4aa; color:#00d4aa; }}
        QMessageBox QPushButton:default {{ border-color:#00d4aa; }}
        """

    def _qmsg(self, title, text, kind="info", yes_no=False):
        """统一深色主题消息框 (QMessageBox 为 Qt 自绘, setStyleSheet 直接生效)"""
        mb = QMessageBox(self)
        mb.setWindowTitle(title)
        mb.setText(text)
        mb.setStyleSheet(self._dialog_ss())
        if yes_no:
            mb.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            mb.setDefaultButton(QMessageBox.No)
        else:
            mb.setStandardButtons(QMessageBox.Ok)
        if kind == "warning":
            mb.setIcon(QMessageBox.Warning)
        elif kind == "critical":
            mb.setIcon(QMessageBox.Critical)
        else:
            mb.setIcon(QMessageBox.Information)
        return mb.exec_()

    def _qmsg_yes(self, title, text):
        """深色主题 是/否 确认框 → True=是"""
        return self._qmsg(title, text, kind="info", yes_no=True) == QMessageBox.Yes

    def _qmsg_info(self, title, text):
        """深色主题 信息框"""
        self._qmsg(title, text, kind="info")

    def export_flow(self):
        flow = {"format": "zmax-simulink", "version": "1.0", "name": "untitled",
                "sim": {"dt": self._sim_dt, "t_end": self._sim_t_end, "solver": "fixed-step"},
                "nodes": self.nodes, "links": self.links}
        if not self.nodes:
            self._qmsg_info("💾 另存为", "画布为空, 没有可保存的内容")
            return
        from PyQt5.QtWidgets import QFileDialog
        # 默认保存到仓库 flows/ 目录 (与 cicd_workflow.json 同目录), 文件名含时间戳防覆盖
        flows_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "flows")
        os.makedirs(flows_dir, exist_ok=True)
        default_name = f"flow_{time.strftime('%Y%m%d_%H%M%S')}.json"
        dlg = QFileDialog(self, "💾 另存为工作流", os.path.join(flows_dir, default_name), "JSON (*.json)")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setStyleSheet(self._dialog_ss())
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)  # 强制用 Qt 对话框, 应用深色样式
        if dlg.exec_() == QFileDialog.Accepted:
            path = dlg.selectedFiles()[0]
            if not path.endswith(".json"):
                path += ".json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(flow, f, ensure_ascii=False, indent=2)
            self._log(f"💾 已另存为: {path} ({len(flow['nodes'])}节点 {len(flow['links'])}连线, 含位置坐标)")
            self._tutorial_on_action("save")
            # 🆕 保存成功气泡提示 (深色主题白字, 2026-08-05)
            try:
                gp = self.mapToGlobal(self.btn_save.rect().center())
                self._show_bubble(gp, f"✅ 已保存: {os.path.basename(path)}\n"
                                      f"{len(flow['nodes'])} 节点 · {len(flow['links'])} 连线 · 位置已记录\n"
                                      f"随时点「📂 加载」恢复此布局", ms=5000)
            except Exception:
                pass

    def import_flow(self):
        from PyQt5.QtWidgets import QFileDialog
        flows_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "flows")
        os.makedirs(flows_dir, exist_ok=True)
        dlg = QFileDialog(self, "📂 加载工作流", flows_dir, "JSON (*.json)")
        dlg.setAcceptMode(QFileDialog.AcceptOpen)
        dlg.setStyleSheet(self._dialog_ss())
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        if dlg.exec_() == QFileDialog.Accepted:
            path = dlg.selectedFiles()[0]
            try:
                flow = json.load(open(path, encoding="utf-8"))
                self.load_flow(flow)
                self._log(f"📂 已加载: {path} ({len(flow.get('nodes', []))}节点 {len(flow.get('links', []))}连线)")
                # 🆕 加载成功气泡提示 (深色主题白字)
                try:
                    gp = self.mapToGlobal(self.btn_load.rect().center())
                    self._show_bubble(gp, f"✅ 已加载: {os.path.basename(path)}\n"
                                          f"{len(flow.get('nodes', []))} 节点 · {len(flow.get('links', []))} 连线\n"
                                          f"节点位置与连线已恢复", ms=5000)
                except Exception:
                    pass
            except Exception as ex:
                self._qmsg_info("加载失败", str(ex))

    def load_flow(self, flow):
        self.clear()
        for n in flow.get("nodes", []):
            node = dict(n)
            node.setdefault("w", 150)
            node.setdefault("params", {})
            node.setdefault("inputs", [{"id": "in1", "label": "in", "dtype": "any"}])
            node.setdefault("outputs", [{"id": "out1", "label": "out", "dtype": "any"}])
            self.nodes.append(node)
            item = SimNodeItem(node, self)
            self._items[node["id"]] = item
            self.canvas._scene.addItem(item)
        for l in flow.get("links", []):
            self.links.append(dict(l))
        self._draw_links()
        self.canvas._scene.update()
        self._update_back_btn()

    def clear(self):
        self._clear_model_rows()          # 先清五模型背景条 (2026-08-05)
        self.canvas._scene.clear()
        self.nodes = []
        self.links = []
        self._items = {}
        self._link_items = []
        # ↩️ 新画布 = 旧撤销栈作废 (2026-08-07: 避免撤销到上一个模板的节点)
        self._undo_stack = []

    # ── 🎨 Model Zoo: 5 行彩色背景 node (row_bg) + 左侧大字模型名 (2026-08-05 老倪) ──
    def _clear_model_rows(self):
        """删除背景行 row_bg 节点 (真节点, 随 clear 一起清)"""
        for n in list(self.nodes):
            if n.get("type") == "row_bg":
                try:
                    it = self._items.get(n["id"])
                    if it is not None:
                        self.canvas._scene.removeItem(it)
                        self._items.pop(n["id"], None)
                    self.nodes.remove(n)
                except Exception:
                    pass
        self._model_row_items = []

    def _draw_model_rows(self, row_names, row_h=230, col_w=200,
                         base_x=120, base_y=80, n_cols=10):
        """在画布插入 N 个背景行 row_bg 节点 (真节点, 可右键编辑).
        row_names: 每行模型名 (大字) → 生成 name='🎨 {名}' bg=预设色 的 row_bg 节点,
        宽 = 整行跨度, 高 = 行高; 双击/右键参数框可改名改色
        ⚠️ 2026-08-07: 网格列距 260→200 (五模型布局补全后最右 x=1920),
        背景行 col_w/n_cols 必须与 layout 一致, 否则背景带与节点行错位/超宽"""
        self._clear_model_rows()
        # ↩️ 背景行批量添加不逐条入撤销栈 (整体布局操作)
        old_undo = getattr(self, "_suspend_undo", False)
        self._suspend_undo = True
        palette = {
            "YOLO 3D": "#3a5a7a", "ACT": "#26418f", "SmolVLA": "#8f6a26",
            "SmolVLA+LEW": "#1f7a4d", "VLA-Touch": "#6a2d8f", "AWE": "#8f2d4d",
            "MLP 蒸馏": "#2d6a8f", "官方专家": "#8f8a3d",  # 🏆 专家=金色(真值锚点)
        }
        x0 = base_x - 140          # 🎨 大字区让开节点列: 大字绝对右界 = x0+8+126 = -12
                                   #   < 节点 x=120, 零重叠 (2026-08-05 修复"叠字/重复"观感)
        w = (base_x + n_cols * col_w + 120) - x0
        for r, name in enumerate(row_names):
            y0 = base_y + r * row_h - 20
            bg = palette.get(name, "#26418f")
            n = self.add_node("row_bg", f"🎨 {name}", x0, y0,
                              {"bg": bg, "model": name, "desc": "背景行: 右键改名/改色"})
            n["w"] = int(w)
            n["h"] = row_h - 16
            it = self._items.get(n["id"])
            if it is not None:
                it.w = int(w)          # ⚠️ 必须同步 item 尺寸 (boundingRect 用 item.w/h,
                it.h = row_h - 16      #    不同步 → 只渲染 150×50 深色小块 = "黑色块" bug)
                it.setZValue(1)        # 背景低于节点(z=10): 点空白命中背景行, 点节点命中节点
                it.update()
        self._suspend_undo = old_undo
        self.canvas._scene.update()
        self._model_row_items = []   # 真节点由 nodes 持有, 无需单独引用

    def _sync(self):
        """节点变更 → 通知主窗口 (可用于推送 web /api/comfy/task)"""
        try:
            cb = getattr(self, "flow_synced", None) or getattr(self.window(), "on_flow_sync", None)
            if cb:
                cb({"format": "zmax-simulink", "nodes": self.nodes, "links": self.links})
        except Exception:
            pass

    def _log(self, msg):
        self.log_box.append(msg)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def _safe_log(self, msg):
        """🛡 后台线程安全日志 (2026-08-06: _auto_finalize_work 等 threading.Thread 直接
        _log → 跨线程操作 QTextEdit → GUI 崩溃! 用 QMetaObject 队列调用回主线程)"""
        try:
            from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(self.log_box, "append", Qt.QueuedConnection,
                                     Q_ARG(str, msg))
            QMetaObject.invokeMethod(self.log_box.verticalScrollBar(), "setValue",
                                     Qt.QueuedConnection,
                                     Q_ARG(int, self.log_box.verticalScrollBar().maximum()))
        except Exception:
            pass

    # ── 📺 外部训练日志监视 (2026-08-06 老倪: 命令行训练, GUI 终端也要有东西) ──
    def _start_ext_log_watch(self):
        """监视命令行训练日志文件 → 过滤关键行 → append 到 log_box"""
        self._ext_log_pos = {p: 0 for p in ("/home/xspace/zmax_train4.log",
                                            "/home/xspace/zmax_deliver_latest.log")}
        if getattr(self, "_ext_log_timer", None) is None:
            from PyQt5.QtCore import QTimer as _QT
            self._ext_log_timer = _QT(self)
            self._ext_log_timer.timeout.connect(self._poll_ext_log)
        self._ext_log_timer.start(2000)

    def _poll_ext_log(self):
        """每 2s: 读外部训练日志新行, 过滤关键行 (loss/进度/完成) 显示"""
        _keep = ("loss", "step=", "✅", "❌", "===", "完成", "📈", "训练",
                 "epoch", "it/s", "step/s", "curve")
        try:
            for p, pos in list(getattr(self, "_ext_log_pos", {}).items()):
                if not os.path.exists(p):
                    continue
                sz = os.path.getsize(p)
                if sz <= pos:
                    continue
                with open(p, encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                self._ext_log_pos[p] = sz
                for ln in chunk.splitlines():
                    if not ln.strip() or ln.startswith("+ "):
                        continue
                    if any(k in ln for k in _keep):
                        self.log_box.append(ln.rstrip()[:200])
            # 日志区自动滚底
            self.log_box.verticalScrollBar().setValue(
                self.log_box.verticalScrollBar().maximum())
            # ⚙ 2026-08-08 老倪: 训练中终端要看到状态 — 动态检测 lerobot_train 进程 + 进度 (去重)
            self._poll_train_state()
        except Exception:
            pass

    def _poll_train_state(self):
        """每 2s: 检测训练进程 → 日志框显示「训练中: 目录 · 步数」; 开始/结束各提示一次"""
        import subprocess as _sp
        try:
            _out = _sp.run(["pgrep", "-f", "lerobot_train"], capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return
        root = self._repo_root()
        _running = bool(_out.strip())
        _state = ""
        if _running:
            _dirs = sorted(glob.glob(os.path.join(root, "outputs", "train", "*", "checkpoints")),
                           key=os.path.getmtime)
            if _dirs:
                d = _dirs[-1]
                _steps = [int(b) for b in os.listdir(d) if b.isdigit()]
                _mx = max(_steps) if _steps else 0
                _name = os.path.basename(os.path.dirname(d))
                # 🐛 2026-08-08 老倪: 日志就一句话 — 加详细: 总步数(config)/百分比/loss
                _total = 0
                _cf = os.path.join(root, f"config_{_name}.yaml")
                if os.path.exists(_cf):
                    import re as _re
                    m = _re.search(r"^steps:\s*(\d+)", open(_cf, encoding="utf-8").read(), _re.M)
                    _total = int(m.group(1)) if m else 0
                _pct = f"{_mx / _total * 100:.0f}%" if _total else "?"
                _loss = ""
                _pol = _name.split("_")[0]  # smolvla_peg_long2 → smolvla
                _cvf = os.path.join(root, "reports", f"train_curve_{_pol}.json")
                try:
                    _cv = json.load(open(_cvf, encoding="utf-8")).get("curve") or []
                    if _cv and os.path.getmtime(_cvf) > os.path.getmtime(d):
                        _loss = f" · loss {_cv[-1][1]:.4f}"
                except Exception:
                    pass
                _state = f"⚙ 训练中: {_name} · 步 {_mx}/{_total or '?'} ({_pct}){_loss}"
        _prev = getattr(self, "_last_train_state", "")
        if _state and _state != _prev:
            self._safe_log(_state)
        elif not _state and _prev:
            self._safe_log("✅ 训练完成")
        self._last_train_state = _state

    def _toggle_log_box(self):
        """📋 底部日志区 折叠/展开 (2026-08-06 老倪: 下面的终端窗口也要能隐藏)"""
        if self.log_box.isVisible():
            self.log_box.setVisible(False)
            self.btn_log_toggle.setText("▶ 展开")
            self.btn_log_toggle.setToolTip("展开底部日志区")
        else:
            self.log_box.setVisible(True)
            self.btn_log_toggle.setText("◀ 收起")
            self.btn_log_toggle.setToolTip("隐藏底部日志区")

    # ── 📡 实时采集轮询 (后台线程, 不卡 UI) ──

    def _repo_root(self):
        """仓库根: tools/gui/simulink_module.py → lerobot-smolvla-lew/"""
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _run_cmd(self, cmd, cwd=None, collect=None, line_hook=None):
        """(后台线程内) 执行命令, 输出流式进日志; collect(list) 可选收集原始行; line_hook(ln) 每行回调
        🐛 2026-08-08 老倪: tqdm 用 \\r 刷新不换行 — for line 卡住 → 块读按 \\r/\\n 分行, 实时全量输出"""
        import subprocess
        try:
            p = subprocess.Popen(cmd, cwd=cwd or self._repo_root(),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            buf = b""
            while True:
                chunk = p.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf or b"\r" in buf:
                    if b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                    elif b"\r" in buf:
                        line, buf = buf.split(b"\r", 1)
                    txt = line.decode("utf-8", "replace").rstrip("\r").strip()
                    if not txt:
                        continue
                    self.log_signal.emit(txt[:600])  # 🐛 老倪: 不要简化 — 完整终端信息
                    if collect is not None:
                        collect.append(txt)
                    if line_hook is not None:
                        try:
                            line_hook(txt)
                        except Exception:
                            pass
            p.wait()
            return p.returncode
        except Exception as ex:
            self.log_signal.emit(f"❌ 执行失败: {ex}")
            return -1

    def _flow_dict(self):
        """当前画布 → flow JSON dict"""
        return {"format": "zmax-simulink", "version": "1.0", "name": "canvas",
                "sim": {"dt": self._sim_dt, "t_end": self._sim_t_end, "solver": "fixed-step"},
                "nodes": self.nodes, "links": self.links}

    @staticmethod
    def _parse_loss_curve(lines, prefer_action=False):
        """训练日志行 → [(step, loss), ...] (宽松解析: step在前或loss在前都认, 失败返回空)
        prefer_action=True (2026-08-05): 优先解析 action_loss:xxx 字段 (剔除 lew_loss,
        三模型 loss 口径统一可比); 无 action_loss 的行回退 loss:xxx"""
        import re
        dedup = {}
        for ln in lines:
            if "loss" not in ln.lower():
                continue
            m = None
            if prefer_action and "action_loss" in ln:
                # 新格式: "action_loss:1.2345 lew_loss:0.5678" (无 step → 用日志累积步数)
                ma = re.search(r"action_loss[:=\s]+([\d.eE+-]+)", ln)
                if ma:
                    loss = float(ma.group(1))
                    # 该行无 step; 用已有最大步数 + log_freq(5) 推断 (2026-08-05: log_freq 50→10→5,
                    # 12%训练时即可见曲线)
                    step = (max(dedup, default=0) + 5) if dedup else 5
                    dedup[step] = loss
                    continue
            pat1 = re.compile(r"step\s*[=:]?\s*(\d+).*?loss[=:\s]+([\d.eE+-]+)")
            pat2 = re.compile(r"loss[=:\s]+([\d.eE+-]+).*?step\s*[=:]?\s*(\d+)")
            m = pat1.search(ln)
            if m:
                step, loss = int(m.group(1)), float(m.group(2))
            else:
                m = pat2.search(ln)
                if not m:
                    continue
                step, loss = int(m.group(2)), float(m.group(1))
            dedup[step] = loss
        return sorted(dedup.items())

    # ── 启动器: 每个操作开一个后台线程, UI 不卡 ──
    def _start_worker(self, fn, busy_msg, stage=None):
        """开后台线程执行 fn, 期间防重入; stage 更新 CI/CD 面板状态"""
        w = getattr(self, "_worker", None)
        if w is not None:
            # 🐛 2026-08-06 修复: worker 终止竞态 — _done(主线程) 触发 _flow_next 时,
            #   worker 线程刚 emit 完还在收尾, isRunning() 短暂 True → 防重入误拦截
            #   后续任务 (Model Zoo VLA-Touch 卡住不启动!); wait(300) 等正常收尾放行
            if w.isRunning() and not w.wait(300):
                # 🔎 2026-08-06 老倪: "什么叫上一个任务还在跑? 要显示详细信息" — 详细提示
                self._log(self._busy_hint())
                return  # 任务未启动 → 引导不推进 (等上一个完成后用户再点)
        if stage:
            self._cicd_state[stage] = 1  # 运行中
            # 数据闭环引导: 任务真正启动才推进 (防重入 return 时不能推进)
            self._tutorial_on_action(stage)
            # 🧠 ACT-Meta 引导: 训练启动/完成时继续提示, 直到训练完成
            if stage == "train" and getattr(self, "_act_train_guided", False):
                self._log("🚀 训练已启动 (约40s, 4060 CUDA)… 完成后我会继续提示 👇")
        self._log(f"⏳ {busy_msg} (后台执行, UI 可继续操作)…")
        # 🐛 2026-08-12 老倪: ▶运行=left_right 自动训练时 ⏹停止一直灰 (start_sim 的
        # left_right 分支直接 on_train 就 return, 不设按钮状态) → 训练类 worker 启动
        # 时统一启用停止按钮 (stop_sim 会 sudo pkill + docker kill 容器训练)
        if stage == "train":
            try:
                self.btn_run.setText("⏳ 训练中…")
                self.btn_run.setEnabled(False)
                self.btn_stop.setEnabled(True)
            except Exception:
                pass

        def _emit_log(msg):
            self._log(msg)

        def _done(ok, summary):
            if stage:
                self._cicd_state[stage] = 2 if ok else 3  # 成功/失败
            if ok:
                self._log(f"✅ {summary}")
            else:
                self._log(f"❌ {summary}")
            # 🧠 ACT-Meta 引导: 训练完成 → 自动追加下游节点 + 高亮引导下一步
            if stage == "train" and getattr(self, "_act_train_guided", False):
                if ok:
                    self._log("🎉 训练完成! 全新 ACT-Meta 模型已就绪 ✓")
                    self._act_append_after_train()
                else:
                    self._log("❌ 训练失败, 请查看上方日志定位原因")
            # 🎬 双脑训练完成 → 自动后台生成插拔视频 (2026-08-12 老倪: 用户点节点秒开, 不等生成)
            if stage == "train" and ok and "left_right" in summary.lower():
                from PyQt5.QtCore import QTimer as _QT
                self._log("🎬 双脑训练完成, 自动生成插拔视频 (后台, 完成后可秒开)…")
                _QT.singleShot(800, lambda: self.on_insert_video(force=True))
            # ⚔️ 对比评估完成 → 自动弹出对比图表 (非模态, 2026-08-05 防卡死)
            if stage == "compare" and ok:
                try:
                    from simulink_scope import ModelCompareDialog
                    dlg = ModelCompareDialog(self)
                    self._show_nonmodal(dlg)
                except Exception as ex:
                    self._log(f"⚠️ 对比图表打开失败: {ex}")
            # 📤 PDF 报告完成 → 自动发飞书 dataworld 群 (2026-08-06 老倪:
            #   最后的 PDF 报告也要发到飞书 dataworld 群里; 后台线程发送不卡 UI)
            if stage == "report" and ok:
                self._log("📤 正在发送报告到飞书 dataworld 群…")
                self._send_report_to_feishu_async(summary)
            self._flow_next()  # 全流程流转钩子 (无队列时无操作)
            # 若有打开的全链路面板, 自动刷新
            if getattr(self, "_cicd_panel", None) and self._cicd_panel.isVisible():
                self._cicd_panel._refresh()

        worker = CICDWorker(fn)
        worker.log.connect(_emit_log)
        worker.finished_ok.connect(_done)
        # 2026-08-05 崩溃修复#10: 原 lambda setattr(self,"_worker",None) → finished 回调里
        # 置 None → worker 无引用被 GC, 而 QThread 底层线程未完全终止 → QThread destroyed
        # SIGABRT (PyQt 竞态, 实测 3404 行崩溃); 改: 不置 None, 引用保留到下次覆盖回收
        worker.finished.connect(lambda: None)
        self._worker = worker
        # 🔎 2026-08-06 老倪: 记录当前任务详情 (防重入提示用) — 任务名/开始时间/队列剩余
        import re as _re
        self._busy_info = {
            "name": (busy_msg or stage or "任务").split("(")[0].strip().lstrip("⏳ "),
            "start": time.time(),
            "queue_len": max(0, len(getattr(self, "_flow_queue", []) or []) - 1),
            "policy": None,
            "total_steps": None,
        }
        # policy 从 busy_msg 提取 (如 "正在准备 vla_touch 训练") → 训练实时进度读取用
        m = _re.search(r"(act|smolvla_?lew?|vla_touch|awe_zflow)", str(busy_msg))
        if m:
            self._busy_info["policy"] = m.group(1)
        worker.start()

    def open_cicd_panel(self):
        """打开 CI/CD 全链路面板:
        1) 若主画布为空 → 自动加载默认流水线 DAG (输入数据→ACT模型→输出action)
        2) 打开可视化流水线面板
        """
        # 画布空 → 加载 CICD 主控台模板 (2026-08-06: 旧「CI/CD 默认流水线」模板已删,
        # 改用 REFERENCE_APPS[0] CICD 主控台 — 全链路主要节点)
        if not self.nodes:
            self.load_reference_app(REFERENCE_APPS[0][0],
                                    REFERENCE_APPS[0][1], REFERENCE_APPS[0][2])
        if not getattr(self, "_cicd_panel", None):
            self._cicd_panel = CICDPanel(self)
        self._cicd_panel._refresh()
        self._cicd_panel.show()
        self._cicd_panel.raise_()
        self._cicd_panel.activateWindow()

    def open_pipeline_panel(self):
        """打开三阶段渐进式训练管线面板 (仿真→零样本测试→真机微调)"""
        if not getattr(self, "_pipeline_panel", None):
            self._pipeline_panel = PipelinePanel(self)
        self._pipeline_panel.show()
        self._pipeline_panel.raise_()
        self._pipeline_panel.activateWindow()
        self._tutorial_on_action("pipeline")

    # 🧠 ACT-Meta 逐步搭建引导: 从模块库逐模块搭建成最终模型 (2026-08-04 老倪)
    # 每步: 高亮模块库按钮 + 日志提示 → 用户点击添加 → 匹配推进 → 8步搭完自动连线
    # 🗑 2026-08-10 老倪: 视觉主干/VAE 子模块已删 (VEH.5.16/17) → 引导同步去 2 步 (变 7 步)
    ACT_BUILD_STEPS = [
        ("📦 metaworld_peg", "hardware", "第1/7步 数据源: 点击左侧模块库「📦 metaworld 数据」(4D/4D, sawyer 关节)"),
        ("🔤 Transformer Encoder", "model", "第2/7步 上下文编码: 点击「🔤 Transformer Encoder」(官方 ACT.encoder, 4层)"),
        ("🔡 Transformer Decoder", "model", "第3/7步 动作解码: 点击「🔡 Transformer Decoder」(官方 ACT.decoder, DETR queries)"),
        ("🎯 Action Head 4D", "action", "第4/7步 输出适配: 点击「🎯 Action Head 4D」(★适配 metaworld 4D, 真机6D)"),
        ("⏳ Temporal Ensemble", "condition", "第5/7步 动作平滑: 点击「⏳ Temporal Ensemble」(官方 ACTTemporalEnsembler)"),
        ("🚀 全新训练", "system", "第6/7步 训练入口: 点击「🚀 全新训练」(双击启动 metaworld 训练)"),
        ("📊 Scope 示波器", "action", "第7/7步 效果观察: 点击「📊 Scope 示波器」(训练完双击它看 loss 波形)"),
    ]

    def _open_float_workflow(self, title, setup_fn):
        """在独立浮动窗口打开一个新流程实例 (2026-08-05 老倪:
        "点击 ACT-Meta 引导后主屏幕没有切换, 你应该再打开一个独立窗口, 直接打开新流程,
         用户可以自主决定是否关掉这个独立窗口")
        新实例自带 模块库+画布+日志, 停掉采集轮询; 窗口可最大化, 关闭即丢弃新流程。
        """
        new_w = self.__class__()          # 独立实例 (不碰主画布)
        try:
            new_w._acq_timer.stop()        # 浮动实例不轮询采集
        except Exception:
            pass
        dlg = QDialog(self.window() or self)
        dlg.setWindowTitle(title)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint
                           | Qt.WindowMinimizeButtonHint)
        dlg.setStyleSheet("QDialog{background:#f6f8fa;}")
        dlg.resize(1360, 860)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        # 只放 主要操作窗口 (模块库 + 画布 MDI) + 底部日志 — 不是整套控制台
        # (2026-08-05 老倪: "actmeta按钮打开的是主要操作的子窗口, 不是又打开控制台")
        lay.addWidget(new_w._main_split, 1)
        lb = new_w.log_box
        lb.setMaximumHeight(96)
        lay.addWidget(lb)

        def _on_close(*_a):
            try:
                new_w._acq_timer.stop()
            except Exception:
                pass
            try:
                new_w._close_bubble(getattr(new_w, "_bubble", None))
            except Exception:
                pass
            new_w.deleteLater()

        dlg.finished.connect(_on_close)
        setup_fn(new_w)
        dlg.show()
        return dlg

    def open_act_meta_float(self):
        """🧠 ACT-Meta 引导 → 独立浮动窗口新流程 (主画布保留, 用户自主决定关闭)"""
        self._open_float_workflow("🧠 ACT-Meta 引导 · 新流程窗口 (可最大化, 关闭即弃)",
                                  lambda w: w.open_act_meta())

    def open_act_meta(self):
        """🧠 ACT-Meta 引导: 从模块库逐步搭建 metaworld 全新训练模型, 全程提示"""
        # 若画布已有内容, 确认清空 (重新搭建)
        if self.nodes:
            if not self._qmsg_yes("ACT-Meta 逐步搭建",
                                  "逐步搭建将清空当前画布，继续？\n(也可在左侧模块库点「🧠 ACT-Meta 完整模型」一键加载)"):
                return
        self.clear()
        self._act_build_step = -1
        self._act_build_active = True
        self._log("════ 🧠 ACT-Meta 逐步搭建引导 · 从模块库搭成完整模型 ════")
        self._log("🎯 目标: metaworld 数据 → ResNet18 → Encoder → Decoder → ActionHead(4D) → Ensemble → 训练(无VAE) → Scope")
        self._log("📋 每步请点击左侧模块库「🧠 ACT 模型·子模块」分类下的高亮模块, 共9步")
        self._act_build_next()

    def _act_build_next(self):
        """推进到下一步: 高亮模块库按钮 + 提示"""
        self._act_build_step += 1
        if self._act_build_step >= len(self.ACT_BUILD_STEPS):
            self._act_build_finish()
            return
        name, ntype, msg = self.ACT_BUILD_STEPS[self._act_build_step]
        # 高亮模块库对应按钮 (金框脉冲, 复用教程高亮工具)
        btn = getattr(self.library, "_lib_btns", {}).get(name)
        if btn is not None:
            self._tutorial_highlight(btn)
        self._log(f"👆 {msg}")

    def _act_build_on_add(self, name):
        """用户从模块库点击了模块 → 匹配则: 自动摆放理想位置 + 增量连线 + 推进"""
        if not getattr(self, "_act_build_active", False):
            return
        if self._act_build_step < 0:
            return
        cur_name, _, _ = self.ACT_BUILD_STEPS[self._act_build_step]
        if name != cur_name:
            # 点错模块: 明确提示 (不静默)
            self._log(f"❓ 不是这一步 — 请点击左侧模块库中金色高亮的「{cur_name}」")
            return
        # ✅ 匹配: 自动摆放 + 增量连线
        self._tutorial_cleanup_highlight()
        step = self._act_build_step
        node = self.nodes[-1]  # 刚添加的节点 (add_node 追加到末尾)
        it = self._items.get(node["id"])
        # 理想位置: 按步骤横排 (x=120+i*260, y=80), 与模板一致
        ideal_x, ideal_y = 120 + step * 260, 80
        node["x"], node["y"] = ideal_x, ideal_y
        if it is not None:
            it.setPos(ideal_x, ideal_y)
            it.update()
        self._log(f"✅ 已添加: {name} · 自动摆放到 {ideal_x},{ideal_y} · 画布 {len(self.nodes)}/{len(self.ACT_BUILD_STEPS)}")
        # 增量连线: 按 ACT-Meta 模板拓扑, 只连两端都已存在的连线 (不重复)
        self._act_build_link_existing()
        self.canvas._scene.update()
        self._act_build_next()

    def _act_build_link_existing(self):
        """按模板拓扑连线: 两端节点都已存在且未连过的才连 (引导中增量调用)"""
        tmpl = None
        for item in REFERENCE_APPS:
            nm = item[0]
            if nm == "🧠 ACT-Meta 全新训练":
                tmpl = (item[1], item[2])
                break
        if not tmpl:
            return
        tpl_nodes, tpl_links = tmpl
        existing = [n["id"] for n in self.nodes]
        linked_pairs = set()
        for lk in self.links:
            # links 元素是 dict: {"f": src_id, "t": dst_id}
            if isinstance(lk, dict):
                linked_pairs.add((lk.get("f"), lk.get("t")))
            else:
                try:
                    linked_pairs.add((lk[0], lk[1]))
                except Exception:
                    pass
        # 找当前节点与模板索引的对应
        idx_of = {}
        for i, (ntype, nm, _p) in enumerate(tpl_nodes):
            for n in self.nodes:
                if n.get("name") == nm:
                    idx_of[i] = n["id"]
                    break
        for fi, ti in tpl_links:
            sf, st = idx_of.get(fi), idx_of.get(ti)
            if sf and st and sf in existing and st in existing:
                if (sf, st) not in linked_pairs:
                    self.add_link(self._items.get(sf), self._items.get(st))
                    linked_pairs.add((sf, st))

    def _act_build_finish(self):
        """8步搭完: 确认连线完整 → 进入训练引导 (直到训练完成)"""
        self._act_build_active = False
        self._act_build_step = -1
        # 兜底: 补齐模板拓扑连线 (增量阶段可能因顺序漏连)
        self._act_build_link_existing()
        self.canvas._scene.update()
        tmpl = None
        for item in REFERENCE_APPS:
            nm = item[0]
            if nm == "🧠 ACT-Meta 全新训练":
                tmpl = (item[1], item[2])
                break
        if tmpl and len(self.nodes) >= 9:
            self._log("🎉 9/9 搭建完成! 已自动摆放 + 按官方 ACT 拓扑自动连线")
            self._log("👉 点「▶ 运行」启动全流程 (训练 ~40s), 或双击「🚀 全新训练」节点")
            self._log("📊 训练完成后双击「📊 Scope 示波器」→ 看 loss 下降波形 (Simulink Scope 对标)")
            self._log("💡 训练完成后我会继续提示下一步; 也可删除后重新搭建")
            # 开启训练引导: 训练启动/完成时自动提示
            self._act_train_guided = True
        else:
            self._log("⚠️ 搭建未完成, 请检查画布节点")

    def _highlight_node(self, node, ms=6000):
        """画布节点金框高亮 (paint 读 node['hl'] 画金色粗框), ms 后自动清除"""
        # 清掉其他节点的高亮, 保证只有一个金框
        for n in self.nodes:
            if n.get("hl"):
                n["hl"] = False
                it = self._items.get(n["id"])
                if it:
                    it.update()
        node["hl"] = True
        it = self._items.get(node["id"])
        if it is not None:
            it.update()
        self.canvas._scene.update()

        def _clear():
            if node.get("hl") and self._items.get(node["id"]) is it:
                node["hl"] = False
                if it is not None:
                    it.update()

        QTimer.singleShot(ms, _clear)

    def _act_append_after_train(self):
        """🧠 ACT-Meta 引导: 训练完成 → 自动追加「✅ 模型验证」+「📦 集成打包」
        节点并连线 (训练→验证→集成), 金框高亮集成节点 + 气泡引导双击推回 ECS。
        画布已有同名节点则跳过添加只补连线, 可重复训练不产生重复节点。
        """
        names = [n["name"] for n in self.nodes]
        n_verify = None
        n_pack = None
        if "✅ 模型验证" not in names:
            x = 120 + len(self.nodes) * 260
            n_verify = self.add_node("condition", "✅ 模型验证", x, 80,
                                     {"strict": True, "desc": "双击运行验证 (validate_flow)"})
        else:
            n_verify = next(n for n in self.nodes if n["name"] == "✅ 模型验证")
        if "📦 集成打包" not in names:
            x = 120 + len(self.nodes) * 260
            n_pack = self.add_node("action", "📦 集成打包", x, 80,
                                   {"target": "ECS", "desc": "双击上传 ECS (cicd_deploy push)"})
        else:
            n_pack = next(n for n in self.nodes if n["name"] == "📦 集成打包")
        # 连线: 训练 → 验证 → 集成 (add_link 自带防重复)
        train_nodes = [n for n in self.nodes if "训练" in n["name"]]
        if train_nodes:
            src = train_nodes[-1]
            have = {(lk["f"], lk["t"]) for lk in self.links}
            if (src["id"], n_verify["id"]) not in have:
                self.add_link(self._items[src["id"]], self._items[n_verify["id"]])
            if (n_verify["id"], n_pack["id"]) not in have:
                self.add_link(self._items[n_verify["id"]], self._items[n_pack["id"]])
        self._log("➕ 已自动追加「✅ 模型验证」「📦 集成打包」节点并连线 (训练→验证→集成)")
        self._log("👆 金色高亮 = 「📦 集成打包」— 双击它把新模型推回 ECS; 也可先双击「✅ 模型验证」检查合规")
        # 金框高亮 + 气泡指引
        self._highlight_node(n_pack)
        try:
            view = self.canvas
            it = self._items.get(n_pack["id"])
            if it is not None:
                gp = view.mapToGlobal(view.mapFromScene(it.sceneBoundingRect().center()))
                self._show_bubble(gp, "👆 双击金色高亮「📦 集成打包」→ 新模型推回 ECS", ms=6000)
        except Exception:
            pass

    def on_validate(self, strict=True, **kw):
        """① 验证: 后台执行 validate_flow.py (不卡 UI)

        strict: 节点逻辑可修改区 (True=全8项检查 / False=只查格式与连线)
        """
        self._log("════ ① 模型验证 (Model Advisor 对标) ════")

        def _work():
            import tempfile
            flow = self._flow_dict()
            tmp = os.path.join(tempfile.gettempdir(), "zmax_canvas_flow.json")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(flow, f, ensure_ascii=False, indent=2)
            root = self._repo_root()
            cmd = [sys.executable, os.path.join(root, "tools", "ci", "validate_flow.py"), tmp]
            if strict:
                cmd.append("--strict")
            rc = self._run_cmd(cmd)
            os.remove(tmp)
            return (rc == 0), ("模型合规, 可进入训练" if rc == 0 else "验证失败 · 修复后重试")

        self._start_worker(_work, "正在验证模型标准合规性", stage="validate")

    def _ensure_training_data(self, data_source=None):
        """(后台线程内) 确定训练数据源:
        1) 优先拉取 ECS 中转的 Orin 真实采集数据 (relay /latest)
        2) 无真实数据 → 回退 metaworld 占位数据集 (明确提示)
        data_source: 节点逻辑可修改区强制 (orin=只拉真实 / metaworld=只占位 / None=画布switch决策)
        返回 (dataset_root, source_label, real_data:bool)
        """
        import requests as _rq
        root = self._repo_root()
        real_dir = os.path.join(root, "data", "closed_loop")
        placeholder = os.path.join(root, "data", "metaworld_peg")

        # 0. 节点逻辑可修改区强制数据源 (node_logic.py ✏️) — 优先于画布 switch
        if data_source == "metaworld":
            if os.path.isdir(placeholder):
                self.log_signal.emit("📦 节点逻辑强制 [metaworld] → 使用占位集 (不拉 relay)")
                return placeholder, "metaworld 占位集 (节点逻辑)", False
            self.log_signal.emit("⚠️ 强制 metaworld 但 data/metaworld_peg 不存在 → 回退自动选择")
        elif data_source == "orin":
            self.log_signal.emit("📥 节点逻辑强制 [Orin] → 只拉 relay 真实数据")
            src = "orin"
        else:
            # 画布数据源选择: Switch 节点优先, 其次数据源激活节点 (CICD 主控台)
            sw = self._switch_state()
            if sw is not None:
                src = sw
            else:
                src = self._active_source()
            if src == "metaworld":
                if os.path.isdir(placeholder):
                    self.log_signal.emit("📦 数据源 [metaworld] → 使用 metaworld 占位集 (不拉 relay)")
                    return placeholder, "metaworld 占位集", False
                self.log_signal.emit("⚠️ 选了 metaworld, 但 data/metaworld_peg 不存在 → 回退自动选择")
            elif src == "orin":
                self.log_signal.emit("📥 数据源 [Orin] → 强制拉取 relay 真实数据")
            else:
                # 🐛 2026-08-09 老倪: 无 switch 时默认本地 metaworld (Orin 原始包未转 parquet 数据集,
                #   拉 relay 存档 closed_loop 会 FileNotFoundError — 不再默认拉)
                if os.path.isdir(placeholder):
                    self.log_signal.emit("📦 数据源默认 [metaworld] → 本地占位集训练 (Orin 未转数据集前不用 relay)")
                    return placeholder, "metaworld 占位集 (默认)", False

        # 1. 尝试拉真实数据
        try:
            r = _rq.get("https://datadrive.world/api/relay/latest", timeout=8)
            if r.status_code == 200:
                pkg = r.json()
                frames = pkg.get("frames", [])
                if frames:
                    # action 恒等修复 (采集端 bug: action==state → 关节速度差分)
                    try:
                        sys.path.insert(0, os.path.join(root, "tools"))
                        from fix_orin_action import fix_frames
                        n_fixed, fixed = fix_frames(frames)
                        if fixed:
                            self.log_signal.emit(f"🛠 检测到 action==state → 已修复为关节速度差分 ({n_fixed}帧)")
                    except Exception as ex:
                        self.log_signal.emit(f"⚠️ action修复跳过: {ex}")
                    os.makedirs(real_dir, exist_ok=True)
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    raw = os.path.join(real_dir, f"pkg_{ts}.json")
                    with open(raw, "w", encoding="utf-8") as f:
                        json.dump(pkg, f, ensure_ascii=False, indent=2)
                    import numpy as np
                    n = len(frames)
                    n_state = len(frames[0].get("observation.state") or frames[0].get("joint") or [7])
                    n_act = len(frames[0].get("action") or [6])
                    states = np.zeros((n, n_state), dtype=np.float32)
                    actions = np.zeros((n, n_act), dtype=np.float32)
                    for i, fr in enumerate(frames):
                        states[i] = (fr.get("observation.state") or fr.get("joint") or [0]*n_state)[:n_state]
                        actions[i] = (fr.get("action") or [0]*n_act)[:n_act]
                    npz = os.path.join(real_dir, f"orin_{ts}.npz")
                    np.savez_compressed(npz, states=states, actions=actions,
                                        task_name="zmax_orin", fps=30)
                    self.log_signal.emit(f"📡 拉取 Orin 真实数据: {n}帧 → {os.path.basename(npz)}")
                    return real_dir, f"Orin 真实数据 ({n}帧)", True
                else:
                    self.log_signal.emit("⚠️ relay 有响应但无帧数据")
            else:
                self.log_signal.emit(f"⚠️ relay 无新数据 (HTTP {r.status_code})")
        except Exception as ex:
            self.log_signal.emit(f"⚠️ 拉取真实数据失败: {ex}")

        # 2. 回退占位数据
        if os.path.isdir(placeholder):
            self.log_signal.emit("⚠️ 无真实数据 → 使用 metaworld 占位集训练 (验证管道用)")
            return placeholder, "metaworld 占位集", False
        self.log_signal.emit("❌ 无任何训练数据 (real 和 placeholder 都不存在)")
        return None, None, False

    def on_train(self, steps=None, batch_size=None, lr=None, data_source=None, policy="act", **kw):
        """🎛 模型训练入口 — 🐛 2026-08-08 老倪: 开头检查画布每模型训练开关 (关则跳过)
        ② 训练: 后台执行 (数据源智能选择 + lerobot_train)
        steps/batch_size/lr 来自节点逻辑可修改区 (node_logic.py) — None=配置模板默认。
        data_source: auto(画布switch决定) | orin(强制真实) | metaworld(占位集)
        policy: "act" | "smolvla_lew" (⚔️ 对比模板两训练节点各设一种, 默认 act)
        """
        # ☑ 画布训练开关检查: 总开关 + 该模型开关 (关 → 跳过)
        try:
            if not self._train_gate_state(policy=policy):
                self.log_signal.emit(f"⏭ 跳过 {policy} — 画布训练开关: 关 (双击开关节点可打开)")
                return True, f"{policy} 训练已跳过 (开关关)"
        except Exception:
            pass
        self._log("════ ② 训练 (lerobot_train) ════")

        def _work():
            root = self._repo_root()
            # ☑ 训练开关检查 (2026-08-05 老倪: checkbox 打勾=训练 / 不打=不训练 —
            #   开关节点放最前边, 关掉后整个训练环节跳过)
            if not self._train_gate_state():
                self.log_signal.emit("⏭ 训练开关未打勾 — 跳过训练 (双击 ☑ 训练开关节点可切换)")
                return True, "训练已跳过 (开关关闭)"
            data_root, source, real = self._ensure_training_data(data_source=data_source)
            if not data_root:
                return False, "无训练数据"
            self.log_signal.emit(f"📊 训练数据源: {source}" + (" · 真实产线数据" if real else ""))

            # 🔬 多策略: act=ACT / smolvla=SmolVLA 纯动作(无LEW) / smolvla_lew=SmolVLA+LeWorldModel
            #   / vla_touch=VLA-Touch 触觉增强控制器 (🖐 2026-08-05 老倪: 参考 VLA-Touch 项目,
            #   base VLA 冻结只训 Interpolant 控制器 — 4060 精简版)
            #   / left_right=双脑 (🧠 2026-08-10 老倪: left_right 工程标准训练, config_left_right.yaml)
            # 各用独立配置模板; ts_dir 前缀区分; 曲线落盘 reports/train_curve_<policy>.json
            if policy == "left_right":
                # 📁 2026-08-10 老倪: 配置规范位置 configs/policies/ (不再堆工程根, 根目录已有64个历史遗留)
                cfg_path = os.path.join(root, "configs", "policies", "config_left_right.yaml")
                ts_dir = "left_right_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "LeftRight"
            elif policy == "smolvla_lew":
                cfg_path = os.path.join(root, "config_smolvla_lew_metaworld.yaml")
                ts_dir = "smolvla_lew_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "SmolVLA+LEW"
            elif policy == "smolvla":
                cfg_path = os.path.join(root, "config_smolvla_metaworld.yaml")
                ts_dir = "smolvla_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "SmolVLA"
            elif policy == "vla_touch":
                # 🖐 VLA-Touch: 独立精简训练脚本 (Interpolant 触觉控制器, 不依赖 lerobot_train)
                cfg_path = None
                ts_dir = "vla_touch_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "VLA-Touch"
            elif policy == "awe_zflow":
                # 🧿 AWE-zFlow: 独立精简训练脚本 (场景原生 + zFlow 三层潜空间世界模型)
                cfg_path = None
                ts_dir = "awe_zflow_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "AWE-zFlow"
            else:
                cfg_path = os.path.join(root, "config_act_metaworld.yaml")
                ts_dir = "act_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "ACT"
            import re
            tmp_cfg = cfg_path
            if cfg_path is not None:
                try:
                    with open(cfg_path, encoding="utf-8") as f:
                        cfg_txt = f.read()
                    # 输出目录加时间戳, 避免重复训练时 FileExistsError
                    cfg_txt = re.sub(r"(output_dir:\s*).*", f"output_dir: outputs/train/{ts_dir}", cfg_txt, count=1)
                    cfg_txt = re.sub(r"(job_name:\s*).*", f"job_name: {ts_dir}", cfg_txt, count=1)
                    # 🐳 2026-08-08 容器训练: root 必须容器内路径 /app/data/... (挂载 -v root:/app)
                    cfg_txt = re.sub(r"(root:\s*).*", f"root: /app/{os.path.relpath(data_root, root)}", cfg_txt, count=1)
                    # 🆕 节点逻辑可修改区参数透传 (^ 行锚定防 n_obs_steps 误匹配)
                    if steps:
                        cfg_txt = re.sub(r"^steps:\s*.*", f"steps: {int(steps)}", cfg_txt, count=1, flags=re.M)
                    if batch_size:
                        cfg_txt = re.sub(r"^batch_size:\s*.*", f"batch_size: {int(batch_size)}", cfg_txt, count=1, flags=re.M)
                    if lr:
                        cfg_txt = re.sub(r"^\s*lr:\s*.*", f"  lr: {lr}", cfg_txt, count=1, flags=re.M)
                    over = f" · ✏️节点逻辑: steps={steps}" + (f" batch={batch_size}" if batch_size else "") + (f" lr={lr}" if lr else "")
                    self.log_signal.emit(f"⚙️ {pname} 训练配置已指向: {data_root} · 输出: outputs/train/{ts_dir}{over}")
                    tmp_cfg = os.path.join(root, f"config_{policy}_runtime.yaml")
                    with open(tmp_cfg, "w", encoding="utf-8") as f:
                        f.write(cfg_txt)
                except Exception as ex:
                    self.log_signal.emit(f"❌ 配置生成失败: {ex}")
                    tmp_cfg = cfg_path

            # 📊 Scope 曲线管理 (2026-08-05 调整): 只重置当前 policy 自己的旧曲线,
            #   保留其他模型已完成曲线 — 三Model Zoo时 ACT 训完波形保留, SmolVLA 训练中可见
            #   (老倪: 现在smolvla训练, 为什么之前的act波形没有了 — 原实现清空全部文件)
            try:
                _own = os.path.join(root, "reports", f"train_curve_{policy}.json")
                if os.path.exists(_own):
                    os.remove(_own)
            except Exception:
                pass

            self.log_signal.emit(f"🚀 启动 {pname} 训练 ({steps or 300}步, 4060 CUDA)…")
            # 🐳 2026-08-08 老倪: Model Engine 容器化 — 远程 GPU 已连接则提交 Docker (zmax-train 镜像)
            me = getattr(self, "_model_engine", None)
            if me and getattr(me, "gpu_mode", "local") == "remote" and getattr(me, "remote_engine", None):
                r = me.remote_engine
                import subprocess as _spr
                self.log_signal.emit(f"🐳 提交 {pname} 训练 → 远程容器 (Docker · {r['host']}) · Model Engine 容器化")
                try:
                    cfg_base = os.path.basename(cfg_path or "config_act_metaworld.yaml")
                    _odir = cfg_base.replace(".yaml", "") + "_$(date +%Y%m%d_%H%M%S)"
                    out = _spr.check_output(
                        f"sshpass -p '{r['pwd']}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o Port={r['port']} "
                        f"{r['user']}@{r['host']} "
                        f"'cd ~/lerobot-smolvla-lew && git pull -q 2>/dev/null; "
                        f"sed -i \"s|^  root: .*|  root: data/metaworld_peg|\" {cfg_base} 2>/dev/null; "
                        f"sed -i \"s|^output_dir: .*|output_dir: outputs/train/{_odir}|\" {cfg_base} 2>/dev/null; "
                        f"if ! docker images -q zmax-train:latest >/dev/null 2>&1; then "
                        f"nohup docker build -t zmax-train:latest . > /tmp/docker_build.log 2>&1 & echo BUILDING; "
                        f"else docker rm -f zmax_train 2>/dev/null; docker run -d --runtime nvidia --gpus all "
                        f"-v ~/lerobot-smolvla-lew:/app -w /app --name zmax_train "
                        f"zmax-train:latest python remote_train_entry.py --config_path {cfg_base} "
                        f"> /tmp/remote_train.log 2>&1; echo RUNNING; fi'",
                        shell=True, timeout=40).decode().strip()
                    if "BUILDING" in out:
                        self.log_signal.emit(f"🐳 远程镜像构建中 (首次容器化) · 日志 /tmp/docker_build.log · 完成后重跑")
                    else:
                        self.log_signal.emit(f"🐳 远程容器训练已启动 ({pname} · {cfg_base}) · 日志 docker logs zmax_train")
                        # 🐛 2026-08-09 老倪: 远程训练日志实时拉流 — 每5s docker logs 增量, 数据加载/epoch/loss 全显示
                        try:
                            import threading as _thr
                            _rlog_seen = [0]  # 已读行数

                            def _rstream():
                                import time as _rt, subprocess as _rsp
                                while True:
                                    try:
                                        _o = _rsp.check_output(
                                            f"sshpass -p '{r['pwd']}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 "
                                            f"-o Port={r['port']} {r['user']}@{r['host']} "
                                            f"'docker ps -q --filter name=zmax_train | head -1; echo ---; "
                                            f"docker logs zmax_train 2>&1 | tail -n +{_rlog_seen[0] + 1}'",
                                            shell=True, timeout=20).decode(errors="replace")
                                        _parts = _o.split("---", 1)
                                        _alive = bool(_parts[0].strip())
                                        _new = _parts[1].strip() if len(_parts) > 1 else ""
                                        if _new:
                                            for _ln in _new.splitlines():
                                                if _ln.strip():
                                                    self.log_signal.emit(f"   📡 {_ln.strip()[:150]}")
                                            _rlog_seen[0] += len(_new.splitlines())
                                        if not _alive:
                                            # 容器退出 → 再拉一次最终日志再停
                                            try:
                                                _fin = _rsp.check_output(
                                                    f"sshpass -p '{r['pwd']}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 "
                                                    f"-o Port={r['port']} {r['user']}@{r['host']} "
                                                    f"'docker logs zmax_train 2>&1 | tail -n +{_rlog_seen[0] + 1}'",
                                                    shell=True, timeout=20).decode(errors="replace")
                                                for _ln in _fin.strip().splitlines():
                                                    if _ln.strip():
                                                        self.log_signal.emit(f"   📡 {_ln.strip()[:150]}")
                                            except Exception:
                                                pass
                                            self.log_signal.emit("   └ 📡 远程训练容器已退出 — 日志流停止")
                                            return
                                    except Exception:
                                        pass
                                    _rt.sleep(5)

                            _thr.Thread(target=_rstream, daemon=True).start()
                            self.log_signal.emit("   └ 📡 远程日志流已开启 (每5秒 docker logs 增量拉取) …")
                        except Exception:
                            pass
                    return True, f"{pname} 容器化远程提交"
                except Exception as ex:
                    self.log_signal.emit(f"❌ 远程容器提交失败 {str(ex)[:50]} — 回退本地训练")
            # 📊 Scope: 训练中实时落盘 loss 曲线 (2026-08-05 老倪: "训练都开始了, 为什么scope没有波形"
            #   — 原来训练结束才落盘; 改流式: 每行 loss 增量写 reports/train_curve_<policy>.json,
            #   Scope 打开时即可见实时波形)
            out_lines = []
            cur_dict = {}
            cur_ts = time.strftime("%Y%m%d_%H%M%S")
            import json as _json  # 闭包用

            def _line_hook(ln):
                """训练中实时: 每行完整打印 (2026-08-08 老倪: 不要简化, 详细终端信息 — 在监控)
                同时解析 loss 行 → 增量更新曲线 → 写盘 (Scope 可见实时波形)"""
                try:
                    ln_s = ln.rstrip()[:240]  # 完整行 (防超长刷屏仅截 240)
                    pts = self._parse_loss_curve([ln], prefer_action=True)
                    if pts:
                        step, loss = pts[-1]
                        cur_dict[step] = loss
                        _flush_curve()
                        self.log_signal.emit(f"📈 {pname} {step}步 · loss {loss:.4f} · {ln_s}")
                    else:
                        self.log_signal.emit(ln_s)  # 非 loss 行也完整打印 (详细终端)
                except Exception:
                    self.log_signal.emit(ln.rstrip()[:160])

            def _flush_curve():
                try:
                    os.makedirs(os.path.join(root, "reports"), exist_ok=True)
                    with open(os.path.join(root, "reports", f"train_curve_{policy}.json"), "w", encoding="utf-8") as f:
                        _json.dump({"policy": policy, "name": pname, "ts": cur_ts,
                                    "curve": sorted(cur_dict.items()), "step_s": 0,
                                    "ckpt": f"outputs/train/{ts_dir}/checkpoints"}, f, ensure_ascii=False)
                except Exception:
                    pass

            if policy == "vla_touch":
                # 🖐 VLA-Touch: 独立精简训练脚本 (train_vla_touch.py) — 🐳 2026-08-08 强制容器
                cfg_in = None
                script_in = os.path.join("/app", "tools", "train_vla_touch.py")
                data_in = os.path.join("/app", os.path.relpath(data_root, root))
                cmd = ["sudo", "docker", "run", "--rm", "--gpus", "all",
                       "-v", f"{root}:/app", "-w", "/app",
                       "--entrypoint", "python", "zmax-std:1.0",
                       "-u", script_in,
                       "--steps", str(int(steps) if steps else 50),
                       "--data-root", data_in]
                if batch_size:
                    cmd += ["--batch", str(int(batch_size))]
                if lr:
                    cmd += ["--lr", str(lr)]
                rc = self._run_cmd(cmd, cwd=root, collect=out_lines,
                                   line_hook=lambda ln: _line_hook(ln))
            elif policy == "awe_zflow":
                # 🧿 AWE-zFlow: 独立精简训练脚本 (train_awe_zflow.py) — 🐳 2026-08-08 强制容器
                script_in = os.path.join("/app", "tools", "train_awe_zflow.py")
                data_in = os.path.join("/app", os.path.relpath(data_root, root))
                cmd = ["sudo", "docker", "run", "--rm", "--gpus", "all",
                       "-v", f"{root}:/app", "-w", "/app",
                       "--entrypoint", "python", "zmax-std:1.0",
                       "-u", script_in,
                       "--steps", str(int(steps) if steps else 50),
                       "--data-root", data_in]
                if batch_size:
                    cmd += ["--batch", str(int(batch_size))]
                if lr:
                    cmd += ["--lr", str(lr)]
                rc = self._run_cmd(cmd, cwd=root, collect=out_lines,
                                   line_hook=lambda ln: _line_hook(ln))
            else:
                # 🐳 2026-08-08 老倪: 训练强制容器 (zmax-std:1.0 — 与远程容器环境一致)
                # 删除旧代码: 不再用本地 .venv 直接训练
                # 容器属性信息 → 终端显示 (在哪/镜像/GPU/挂载)
                self.log_signal.emit("🐳 容器启动: 本地 (WSL2 docker) · 镜像 zmax-std:1.0 (28GB · torch 2.11.0+cu128 · transformers 5.5.4)")
                self.log_signal.emit("   ├ GPU: --gpus all (RTX 4060 · NVIDIA Container Toolkit)")
                self.log_signal.emit(f"   ├ 挂载: {root} → /app (工程/数据/输出)")
                self.log_signal.emit("   ├ PYTHONPATH: /app/src · 工作目录: /app")
                self.log_signal.emit(f"   └ 训练: {pname} · 容器内执行 (lerobot_train)")
                # WSL2 用 --gpus all (NVIDIA Container Toolkit); 远程 Linux 用 --device 透传
                cfg_in = os.path.join("/app", os.path.basename(tmp_cfg)) if tmp_cfg else None
                cmd = ["sudo", "docker", "run", "--rm",
                       "--gpus", "all",
                       "-v", f"{root}:/app", "-w", "/app",
                       "-e", "PYTHONPATH=/app/src",  # 🐛 lerobot 源码在 /app/src (镜像 COPY)
                       "--entrypoint", "python", "zmax-std:1.0",
                       "-u", "-m", "lerobot.scripts.lerobot_train",
                       "--config_path", cfg_in]
                rc = self._run_cmd(cmd, cwd=root, collect=out_lines,
                                   line_hook=lambda ln: _line_hook(ln))
            self._train_curve = self._parse_loss_curve(out_lines)
            step_s = self._parse_step_s(out_lines)
            # 最终落盘 (训练结束后覆盖实时文件: 补全 step_s + 最终曲线)
            try:
                import json as _json
                os.makedirs(os.path.join(root, "reports"), exist_ok=True)
                with open(os.path.join(root, "reports", f"train_curve_{policy}.json"), "w", encoding="utf-8") as f:
                    _json.dump({"policy": policy, "name": pname, "ts": time.strftime("%Y%m%d_%H%M%S"),
                                "curve": self._train_curve, "step_s": step_s,
                                "ckpt": f"outputs/train/{ts_dir}/checkpoints"}, f, ensure_ascii=False)
                self.log_signal.emit(f"📈 {pname} 曲线已存: reports/train_curve_{policy}.json · 速度 {step_s:.1f} step/s" if step_s else f"📈 {pname} 曲线已存: reports/train_curve_{policy}.json")
            except Exception:
                pass
            try:
                os.remove(tmp_cfg)
            except Exception:
                pass
            return (rc == 0), (f"{pname} 训练完成 · outputs/train/{ts_dir}/checkpoints/" if rc == 0
                               else f"{pname} 训练失败 (见上方日志)")

        self._start_worker(_work, f"正在准备 {policy} 训练 (拉取数据源 + 启动训练)", stage="train")

    @staticmethod
    def _parse_step_s(lines):
        """训练日志行 → 平均 step/s (tqdm 进度条 "12.68step/s" 或 "it/s" 格式)"""
        import re
        vals = []
        pat = re.compile(r"([\d.]+)\s*(?:step/s|it/s)")
        for ln in lines:
            for m in pat.finditer(ln):
                try:
                    vals.append(float(m.group(1)))
                except ValueError:
                    pass
        return sum(vals) / len(vals) if vals else 0.0

    def on_integrate(self, **kw):
        """③ 集成: 后台执行 (打包 checkpoint → 上传 ECS)"""
        self._log("════ ③ 集成 (checkpoint → ECS 中转) ════")

        def _work():
            root = self._repo_root()
            rc = self._run_cmd([sys.executable, os.path.join(root, "tools", "cicd_deploy.py"), "push"],
                               cwd=root)
            return (rc == 0), ("部署包已上传 ECS, 可进入部署" if rc == 0 else "集成失败 (见上方日志)")

        self._start_worker(_work, "正在打包并上传 ECS", stage="integrate")

    def on_deploy(self, **kw):
        """⑤ 部署: 后台执行 (ECS 状态检查)"""
        self._log("════ ⑤ 部署 (ECS 状态检查) ════")

        def _work():
            root = self._repo_root()
            rc = self._run_cmd([sys.executable, os.path.join(root, "tools", "cicd_deploy.py"), "status"],
                               cwd=root)
            return (rc == 0), ("部署状态已拉取 · 心跳正常" if rc == 0 else "部署状态检查失败")

        self._start_worker(_work, "正在查询部署状态", stage="deploy")

    def on_collect(self, timeout=8, fix_action=True, endpoint="https://datadrive.world/api/relay", **kw):
        """① 采集: 拉取 relay Orin 真实数据 → action 修复 → 落地

        timeout/fix_action/endpoint 来自节点逻辑可修改区 (node_logic.py)
        """
        self._log("════ ① 采集 (relay → 修复 action → 落地) ════")

        def _work():
            import requests as _rq
            import glob as _g
            root = self._repo_root()
            real_dir = os.path.join(root, "data", "closed_loop")
            # ── 全链路证据: 中转状态 + Orin 心跳 ──
            # nginx反代 → ECS:39053 zmax_relay.py
            try:
                r = _rq.get(f"{endpoint}/status", timeout=timeout)
                st = r.json() if r.status_code == 200 else {}
                pkgs = st.get("packages", 0)
                uptime = st.get("uptime", 0)
                self.log_signal.emit(f"📡 中转 {endpoint}/status → 在线{uptime}s · 队列包数: {pkgs}")
            except Exception as ex:
                pkgs = 0
                self.log_signal.emit(f"⚠️ 中转状态查询失败: {ex}")
            try:
                r = _rq.get(f"{endpoint}/orin/status", timeout=timeout)
                o = r.json() if r.status_code == 200 else {}
                if o.get("online"):
                    self.log_signal.emit(f"🤖 Orin 在线 · 模型{o.get('model')} · 心跳 {o.get('last_seen')} · 推理{o.get('infer_count')}次"
                                         + (f" · {o.get('last_infer_ms')}ms" if o.get("last_infer_ms") else ""))
                else:
                    self.log_signal.emit("🤖 Orin 未上报心跳 (离线)")
            except Exception as ex:
                self.log_signal.emit(f"⚠️ Orin 状态查询失败: {ex}")
            if pkgs <= 0:
                # 无新包: 给出最近落地包证据 (时间/来源/帧数), 说明队列已清空
                pkgs_files = sorted(_g.glob(os.path.join(real_dir, "*.json")), key=os.path.getmtime, reverse=True)
                if pkgs_files:
                    last = pkgs_files[0]
                    try:
                        ld = json.load(open(last, encoding="utf-8"))
                        lm = ld.get("meta", {})
                        nf = len(ld.get("frames", []))
                        self.log_signal.emit(f"📦 最近落地包: {os.path.basename(last)} · 来源{lm.get('source','?')} · {nf}帧"
                                             f" · {lm.get('n_joint','?')}D/{lm.get('n_action','?')}D" if nf else f"📦 最近落地包: {os.path.basename(last)}")
                    except Exception:
                        self.log_signal.emit(f"📦 最近落地包: {os.path.basename(last)}")
                else:
                    self.log_signal.emit("📦 本地无落地包 — 需小芳采集上传 (Orin→Mac:8769→ECS relay)")
                return True, "中转队列无新包 (已全部落地) · 证据见日志"
            r = _rq.get(f"{endpoint}/latest", timeout=timeout + 7)
            if r.status_code != 200:
                return False, "拉取失败"
            pkg = r.json()
            frames = pkg.get("frames", [])
            if not frames:
                return False, "包无 frames"
            meta = pkg.get("meta", {})
            self.log_signal.emit(f"📥 拉取 {endpoint}/latest → 来源{meta.get('source','?')} · {len(frames)}帧"
                                 f" · n_joint={meta.get('n_joint','?')} · n_action={meta.get('n_action','?')}"
                                 f" · fps={meta.get('fps','?')} · 收到于{time.strftime('%H:%M:%S', time.localtime(meta.get('received_at', time.time()))) }")
            sys.path.insert(0, os.path.join(root, "tools"))
            n_fixed, fixed = 0, False
            if fix_action:
                from fix_orin_action import fix_frames
                n_fixed, fixed = fix_frames(frames)
                if fixed:
                    self.log_signal.emit(f"🛠 action 恒等修复: {n_fixed}帧 (action==state → 关节速度差分)")
            else:
                self.log_signal.emit("⚙️ 已按节点逻辑关闭 action 修复 (fix_action=False)")
            os.makedirs(real_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            raw = os.path.join(real_dir, f"pkg_{ts}.json")
            with open(raw, "w", encoding="utf-8") as f:
                json.dump(pkg, f, ensure_ascii=False, indent=2)
            extra = f" · action恒等已修复({n_fixed}帧)" if fixed else ""
            return True, f"已落地 {len(frames)}帧 → {os.path.basename(raw)}{extra}"

        self._start_worker(_work, "正在拉取 Orin 真实数据", stage="collect")

    def on_infer_video(self, policy=None, **kw):
        """🎮 仿真推理对比 (2026-08-05 老倪): 多模型 rollout 视频 多窗口同步播放
        数据源: reports/rollout_<policy>/ (tools/rollout_video.py 生成, 无则自动生成)
        policy=None → 全模型 (模板: 3 模型三对比 / 5 模型Model Zoo自动探测);
        policy='act' → 单模型视频节点 (🎮 仿真视频 · ACT)
        auto=True (模板参数): 训练完自动触发 — 先后台生成 rollout, 完成后弹窗"""
        try:
            from simulink_scope import InferenceVideoDialog
        except ImportError as ex:
            self._log(f"❌ 缺少 simulink_scope.InferenceVideoDialog: {ex}")
            return
        # 单模型视频节点 → 自动升级为全Model Zoo (2026-08-06 老倪: 5 个要同时一起打开做对比,
        #   只开单个没意义); 画布有五模型 → 全开 5 个, 七模型(MLP/专家) → 全开 7 个
        names = " ".join(n.get("name", "") for n in self.nodes)
        if "MLP" in names or "专家" in names:
            policies = InferenceVideoDialog.POLICIES_7
        elif "VLA-Touch" in names or "AWE" in names:
            policies = InferenceVideoDialog.POLICIES_5
        else:
            policies = InferenceVideoDialog.POLICIES
        if policy:
            # 若单模型不在全模型列表 (异常), 退回单模型; 正常都在 → 全开对比
            if not any(p == policy for p, _, _ in policies):
                policies = [(policy, self._policy_display(policy), self._policy_color(policy))]
        root = self._repo_root()
        import glob as _glob
        # 多候选目录: rollout_final_<p> > rollout_peg_<p> > rollout_<p> (2026-08-06 同步昨晚产物)
        # (2026-08-07: expert_mlp/expert_policy 现成成功视频在 rollout_mlp/rollout_expert_full —
        #  触发前检查漏了映射 → 误判无帧 → 重新生成失败 → 视频没了!)
        _dm = {"expert_mlp": ("rollout_mlp", "rollout_final_expert_mlp", "rollout_expert_mlp"),
               "expert_policy": ("rollout_expert_full", "rollout_expert", "rollout_final_expert_policy")}
        have = all(any(_glob.glob(os.path.join(root, "reports", cand, "frame_*.png"))
                       for cand in (_dm.get(p, (f"rollout_final_{p}", f"rollout_peg_{p}", f"rollout_{p}"))))
                   for p, _, _ in policies)
        if not have:
            self._log(f"🎥 推理对比: 生成 {len(policies)} 模型 rollout 视频 (peg-insert, corner2↺90°, 各 60 帧)…")
            # 🐛 2026-08-06 老倪: "视频非得第二次双击才能打开" — 原 _qmsg_info 是
            # exec_ 模态, WSLg 下弹窗不可见 → 主线程阻塞 → 用户重复点击/按键才解除,
            # 看似第二次双击才打开; 改非模态: 对话框自身 lbl_note 会显示"生成中",
            # 不再阻塞主线程, 第一次双击立即出现窗口
            try:
                self._show_bubble(self.rect().center(),
                                  f"🎮 正在生成 {len(policies)} 模型仿真 rollout 对比视频 (metaworld 环境, 非 Orin 真机; 各 60 帧, 约 1-2 分钟)…\n"
                                  "生成完成自动播放对比", 5000)
            except Exception:
                pass
        dlg = InferenceVideoDialog(self, policies=policies)
        self._show_nonmodal(dlg)  # 非模态, 2026-08-05 防卡死

    @staticmethod
    def _policy_display(policy):
        """policy → 显示名 (act→ACT / smolvla→SmolVLA / smolvla_lew→SmolVLA+LEW / vla_touch→VLA-Touch / awe_zflow→AWE / expert_mlp→MLP蒸馏 / expert_policy→官方专家)"""
        return {"act": "ACT", "smolvla": "SmolVLA", "smolvla_lew": "SmolVLA+LEW",
                "vla_touch": "VLA-Touch", "awe_zflow": "AWE",
                "expert_mlp": "MLP 蒸馏", "expert_policy": "官方专家"}.get(policy, policy)

    @staticmethod
    def _policy_color(policy):
        """policy → 主题色"""
        return {"act": "#58a6ff", "smolvla": "#d29922", "smolvla_lew": "#a371f7",
                "vla_touch": "#6a2d8f", "awe_zflow": "#8f2d4d",
                "expert_mlp": "#2d6a8f", "expert_policy": "#8f8a3d"}.get(policy, "#58a6ff")

    def on_pdf_report(self, **kw):
        """📄 PDF 技术选型报告 (2026-08-05 老倪): Model Zoo实验 → 11 章专业报告
        数据: 画布 flow (系统全貌) + reports/train_curve_*.json (训练结果)
              + reports/rollout_*/ (推理视频帧) → tools/generate_report.py"""
        self._log("📄 正在生成Model Zoo技术选型报告 (概况/分系统/接口/参数/架构/功能/性价比/优劣势)…")

        def _work():
            try:
                import subprocess
                root = self._repo_root()
                # 保存当前画布 flow → 临时 JSON (报告第2章 系统全貌)
                flow_json = os.path.join(root, "reports", "_flow_snapshot.json")
                try:
                    with open(flow_json, "w", encoding="utf-8") as f:
                        json.dump({"format": "zmax-simulink", "name": "Model Zoo",
                                   "nodes": self.nodes, "links": self.links}, f,
                                  ensure_ascii=False, indent=1)
                except Exception:
                    flow_json = None
                cmd = ["sudo", "docker", "run", "--rm",
                       "-v", f"{root}:/app", "-w", "/app", "-e", "PYTHONPATH=/app/src",
                       "--entrypoint", "python", "zmax-std:1.0",
                       "/app/tools/generate_report.py"]
                if flow_json:
                    cmd += ["--flow", flow_json]
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=300, cwd=root)
                out = (r.stdout or "").strip().splitlines()
                last = out[-1] if out else "?"
                if r.returncode == 0 and os.path.exists(os.path.join(root, "reports")):
                    import glob as _g
                    # 🐛 2026-08-10 老倪: 文件名是 五模型对比技术选型报告_*.pdf (旧模式 Model Zoo 不匹配)
                    pdfs = sorted(_g.glob(os.path.join(root, "reports", "五模型对比技术选型报告_*.pdf")),
                                  key=os.path.getmtime)
                    if pdfs:
                        return True, f"📄 报告已生成: {os.path.basename(pdfs[-1])}"
                    return True, f"📄 报告已生成 (reports/ 下, 输出: {last})"
                return False, f"PDF 生成失败: {last}"
            except Exception as ex:
                return False, f"PDF 生成失败: {ex}"

        self._start_worker(_work, "正在生成 PDF 技术选型报告…", stage="report")

    def on_insert_video(self, force=False, **kw):
        """▶ 插拔演示视频 (2026-08-10 双脑+状态机): 后台跑 gen_insert_video.py
        → reports/insert_success_demo.mp4 → 自动发飞书 dataworld 群
        🐛 2026-08-10 老倪"视频早就生成好了怎么还要等" — 已存在直接打开, 不重新生成
        🐛 2026-08-12 老倪: force=True 强制重新生成 (训练完成自动触发, 用新模型覆盖旧视频)"""
        root = self._repo_root()
        mp4 = os.path.join(root, "reports", "insert_success_demo.mp4")
        if os.path.exists(mp4) and os.path.getsize(mp4) > 0 and not force:
            # 🐛 2026-08-12 老倪: 防重复弹出 — 双击重复触发/多次点击会弹好几个播放器
            import time as _t
            now = _t.time()
            if getattr(self, "_last_video_pop", 0) and now - self._last_video_pop < 15:
                self._log("🎬 视频已弹出 (15秒内防重复)")
                return
            self._last_video_pop = now
            self._log(f"🎬 视频已存在 ({os.path.getsize(mp4)//1024}KB, 直接打开, 不重新生成)")
            self._open_video_for_user(mp4)
            self._send_video_to_feishu_async(mp4)
            return
        self._log("▶ 正在生成双脑插拔演示视频 (seed1 完整插拔流程, 约1-2分钟)…")

        def _work():
            import subprocess as _sp
            root = self._repo_root()
            py = os.path.join(root, ".venv", "bin", "python")
            if not os.path.exists(py):
                return False, "缺少 .venv/bin/python (视频生成需本地 GPU 渲染环境)"
            r = _sp.run([py, os.path.join(root, "tools", "gen_insert_video.py")],
                        capture_output=True, text=True, timeout=600, cwd=root)
            out = (r.stdout or "").strip().splitlines()
            last = out[-1] if out else "?"
            mp4 = os.path.join(root, "reports", "insert_success_demo.mp4")
            if r.returncode == 0 and os.path.exists(mp4):
                self._send_video_to_feishu_async(mp4)
                # 🐛 2026-08-12 老倪: force 模式 (训练完自动生成) 不自动弹播放器 —
                # 用户在训练监控中, 弹窗打扰; 点节点时秒开即可
                if not force:
                    try:
                        self._open_video_for_user(mp4)
                    except Exception as _ex:
                        self._log(f"🎬 视频已生成: reports/insert_success_demo.mp4 (自动打开失败: {str(_ex)[:50]})")
                else:
                    self._log("🎬 视频已生成 (后台) — 双击 ▶ 生成插拔视频 节点即可秒开")
                return True, f"🎬 视频已生成: reports/insert_success_demo.mp4"
            return False, f"视频生成失败: {last}"

        self._start_worker(_work, "正在生成插拔演示视频…", stage="insert_video")

    def _open_video_for_user(self, mp4):
        """🎬 打开视频给老倪看: 复制到 Windows 可见 C 盘 → cmd start (cwd=/mnt/c/Windows)
        🐛 2026-08-12 老倪: explorer.exe 从 WSL 启动受 UNC cwd 影响静默失败 → 与项目其他
        文件打开一致走 cmd start + cwd 修正 (记忆: 文档/链接/文件全走 cmd start)"""
        import shutil as _sh, subprocess as _sp
        _pub = "/mnt/c/Users/Public/ZMAX_videos"
        os.makedirs(_pub, exist_ok=True)
        _dst = os.path.join(_pub, os.path.basename(mp4))
        _sh.copy2(mp4, _dst)
        _win = _dst.replace("/mnt/c/", "C:\\").replace("/", "\\")
        _sp.Popen(["cmd.exe", "/c", "start", "", _win], cwd="/mnt/c/Windows",
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        self._log(f"🎬 已打开: {_win} ({os.path.getsize(mp4)//1024}KB)")

    def on_insert_report(self, **kw):
        """📄 插拔方案PDF (2026-08-10 双脑+状态机): 视频帧 + 方案JSON → 6章报告 → 发飞书"""
        self._log("📄 正在生成双脑插拔方案PDF报告 (6章: 概况/架构/状态机/调优/对比/下一步)…")

        def _work():
            import subprocess as _sp
            root = self._repo_root()
            mp4 = os.path.join(root, "reports", "insert_success_demo.mp4")
            frame = os.path.join(root, "reports", "_insert_demo_frame.png")
            if os.path.exists(mp4):
                _sp.run(["ffmpeg", "-y", "-ss", "1.0", "-i", mp4, "-frames:v", "1", frame],
                        capture_output=True, text=True, timeout=60)
            # 🐛 2026-08-10: zmax-std 容器无 CJK 字体 → matplotlib 图中文方块;
            #   改用宿主 .venv (reportlab+matplotlib+Noto CJK 齐全, 与 rollout 视频同路径)
            py = os.path.join(root, ".venv", "bin", "python")
            if not os.path.exists(py):
                return False, "缺少 .venv/bin/python (报告生成需要本地环境)"
            r = _sp.run([py, os.path.join(root, "tools", "gen_insert_report.py"),
                         "--frame", frame],
                        capture_output=True, text=True, timeout=300, cwd=root)
            out = (r.stdout or "").strip().splitlines()
            last = out[-1] if out else "?"
            import glob as _g
            pdfs = sorted(_g.glob(os.path.join(root, "reports", "插拔方案报告_*.pdf")),
                          key=os.path.getmtime)
            if r.returncode == 0 and pdfs:
                self._send_pdf_to_feishu_async(pdfs[-1])
                return True, f"📄 报告已生成: {os.path.basename(pdfs[-1])}"
            return False, f"PDF 生成失败: {last}"

        self._start_worker(_work, "正在生成插拔方案PDF报告…", stage="insert_report")

    def on_infer(self, **kw):
        """⑥ 推理: 检查 Orin 推理状态 (infer_count / 延迟 / 心跳)"""
        self._log("════ ⑥ 推理 (Orin 状态检查) ════")
        def _work():
            import requests as _rq
            try:
                r = _rq.get("https://datadrive.world/api/relay/orin/status", timeout=6)
                if r.status_code != 200:
                    return False, "Orin 状态拉取失败"
                o = r.json()
                online = o.get("online", False)
                infer = o.get("infer_count", 0)
                ms = o.get("last_infer_ms")
                model = o.get("model", "?")
                msg = f"Orin {'●在线' if online else '○离线'} · 模型{model} · 推理{infer}次"
                if ms:
                    msg += f" · 最近{ms}ms"
                return online, msg
            except Exception as ex:
                return False, f"Orin 状态拉取失败: {ex}"

        self._start_worker(_work, "正在检查 Orin 推理状态", stage="infer")

    # ── 全流程自动流转 (CICD 面板 ▶ 按钮): 依次执行 6 环节 ──
    def _run_full_flow(self):
        """采集→训练→验证→集成→部署→推理 依次自动流转"""
        w = getattr(self, "_worker", None)
        if w is not None:
            # 🐛 2026-08-06: worker 终止竞态 → wait(300) 等正常收尾放行
            if w.isRunning() and not w.wait(300):
                self._log(self._busy_hint())
            return
        self._flow_queue = [self.on_collect, self.on_train, self.on_validate,
                            self.on_integrate, self.on_deploy, self.on_infer]
        self._flow_queue.pop(0)()

    def _busy_hint(self):
        """🔎 2026-08-06 老倪: 防重入详细提示 — 当前任务 + 已耗时 + 训练实时进度 + 剩余队列具体任务
        训练进度: 读 reports/train_curve_<policy>.json (训练中每 10 步落盘, curve 最后一条=最新 step/loss)"""
        bi = getattr(self, "_busy_info", None)
        if not bi:
            return "⏳ 上一个任务还在跑 (worker 运行中), 请稍候…"
        parts = [f"⏳ 正在运行「{bi['name']}」已 {int(time.time() - bi['start'])}s"]
        # 训练实时进度 (若当前任务带 policy)
        pol = bi.get("policy")
        if pol:
            try:
                import json as _j
                cf = os.path.join(self._repo_root(), "reports", f"train_curve_{pol}.json")
                if os.path.exists(cf):
                    d = _j.load(open(cf, encoding="utf-8"))
                    cur = d.get("curve") or []
                    if cur:
                        step, loss = cur[-1]
                        parts.append(f"训练 {step}/{bi.get('total_steps', '?')} 步 · loss {loss:.4f}")
            except Exception:
                pass
        # 剩余队列具体任务
        rem = list(getattr(self, "_flow_names", None) or [])[1:]
        if rem:
            parts.append("剩余: " + " → ".join(rem[:4]) + ("…" if len(rem) > 4 else ""))
        parts.append("(日志区可看到 📈 进度)")
        return " · ".join(parts)

    def _send_report_to_feishu_async(self, summary):
        """📤 PDF 报告自动发飞书 dataworld 群 (2026-08-06 老倪)
        后台线程: 找最新 PDF → 上传 → 发文件消息 → 发文本摘要; 失败仅日志, 不影响主流程"""
        import threading
        threading.Thread(target=self._send_report_to_feishu_work, args=(summary,),
                         daemon=True).start()

    def _send_report_to_feishu_work(self, summary):
        """(后台线程) 飞书上传 PDF + 发消息到 dataworld 群"""
        try:
            import json as _j, glob as _g, urllib.request as _ur, os as _os
            root = self._repo_root()
            # 🐛 2026-08-10 老倪: 文件名是 五模型对比技术选型报告_*.pdf (旧模式 Model Zoo 不匹配 → 未找到)
            pdfs = sorted(_g.glob(_os.path.join(root, "reports", "五模型对比技术选型报告_*.pdf")),
                          key=_os.path.getmtime)
            if not pdfs:
                self._safe_log("⚠️ 飞书发送: 未找到 PDF 报告文件")
                return
            pdf = pdfs[-1]
            # 凭据: ~/.hermes/.env (FEISHU_APP_ID/SECRET)
            env = {}
            env_path = _os.path.expanduser("~/.hermes/.env")
            if _os.path.exists(env_path):
                for line in open(env_path, encoding="utf-8"):
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k] = v
            app_id = env.get("FEISHU_APP_ID", "")
            app_secret = env.get("FEISHU_APP_SECRET", "")
            chat_id = env.get("FEISHU_REPORT_CHAT_ID", "oc_c0b4048546145c5c581ddd1a9e8f565d")
            if not app_id or not app_secret:
                self._safe_log("⚠️ 飞书发送: .env 无 FEISHU_APP_ID/SECRET")
                return

            def _post(url, data, headers=None):
                req = _ur.Request(url, data=_j.dumps(data).encode(),
                                  headers={"Content-Type": "application/json", **(headers or {})})
                return _j.loads(_ur.urlopen(req, timeout=15).read())

            r = _post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                      {"app_id": app_id, "app_secret": app_secret})
            tok = r.get("tenant_access_token")
            if not tok:
                self._safe_log("⚠️ 飞书发送: token 获取失败")
                return
            H = {"Authorization": "Bearer " + tok}
            # 上传 PDF
            boundary = "----zmaxreport"
            with open(pdf, "rb") as f:
                content = f.read()
            body = (("--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file_type\"\r\n\r\npdf\r\n" +
                     "--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file_name\"\r\n\r\n" +
                     _os.path.basename(pdf) + "\r\n" +
                     "--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file\"; filename=\"" +
                     _os.path.basename(pdf) + "\"\r\n"
                     "Content-Type: application/pdf\r\n\r\n").encode() + content + (
                     "\r\n--" + boundary + "--\r\n").encode())
            req = _ur.Request("https://open.feishu.cn/open-apis/im/v1/files", data=body,
                              headers={**H, "Content-Type": "multipart/form-data; boundary=" + boundary})
            r2 = _j.loads(_ur.urlopen(req, timeout=30).read())
            file_key = r2.get("data", {}).get("file_key")
            if not file_key:
                self._safe_log(f"⚠️ 飞书发送: 上传失败 {r2.get('msg', '')}")
                return
            # 发文件消息
            r3 = _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                       {"receive_id": chat_id, "msg_type": "file",
                        "content": _j.dumps({"file_key": file_key})}, H)
            # 发文本摘要 (报告标题 + 生成信息)
            title = _os.path.basename(pdf).replace("_", " ").replace(".pdf", "")
            txt = f"📄 Z-MAX 五模型技术选型报告已生成\n{title}\n{summary}"
            _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                  {"receive_id": chat_id, "msg_type": "text",
                   "content": _j.dumps({"text": txt})}, H)
            self._safe_log(f"✅ 报告已发送到飞书 dataworld 群 · {_os.path.basename(pdf)}")
        except Exception as ex:
            self._safe_log(f"⚠️ 飞书发送失败: {ex}")

    # ── 📤 通用飞书文件发送 (2026-08-10: 双脑插拔 视频/PDF 复用) ──
    def _feishu_send_file_work(self, path, ftype, txt):
        """后台线程: 飞书上传文件 (mp4/pdf) + 发文件消息 + 发文本摘要; 失败仅日志, 不影响主流程"""
        try:
            import json as _j, urllib.request as _ur, os as _os
            env = {}
            env_path = _os.path.expanduser("~/.hermes/.env")
            if _os.path.exists(env_path):
                for line in open(env_path, encoding="utf-8"):
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k] = v
            app_id = env.get("FEISHU_APP_ID", "")
            app_secret = env.get("FEISHU_APP_SECRET", "")
            chat_id = env.get("FEISHU_REPORT_CHAT_ID", "oc_c0b4048546145c5c581ddd1a9e8f565d")
            if not app_id or not app_secret:
                self._safe_log("⚠️ 飞书发送: .env 无 FEISHU_APP_ID/SECRET")
                return

            def _post(url, data, headers=None):
                req = _ur.Request(url, data=_j.dumps(data).encode(),
                                  headers={"Content-Type": "application/json", **(headers or {})})
                return _j.loads(_ur.urlopen(req, timeout=15).read())

            r = _post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                      {"app_id": app_id, "app_secret": app_secret})
            tok = r.get("tenant_access_token")
            if not tok:
                self._safe_log("⚠️ 飞书发送: token 获取失败")
                return
            H = {"Authorization": "Bearer " + tok}
            boundary = "----zmaxfile"
            with open(path, "rb") as f:
                content = f.read()
            body = (("--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file_type\"\r\n\r\n" + ftype + "\r\n" +
                     "--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file_name\"\r\n\r\n" +
                     _os.path.basename(path) + "\r\n" +
                     "--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file\"; filename=\"" +
                     _os.path.basename(path) + "\"\r\n"
                     "Content-Type: application/octet-stream\r\n\r\n").encode() + content + (
                     "\r\n--" + boundary + "--\r\n").encode())
            req = _ur.Request("https://open.feishu.cn/open-apis/im/v1/files", data=body,
                              headers={**H, "Content-Type": "multipart/form-data; boundary=" + boundary})
            r2 = _j.loads(_ur.urlopen(req, timeout=60).read())
            file_key = r2.get("data", {}).get("file_key")
            if not file_key:
                self._safe_log(f"⚠️ 飞书发送: 上传失败 {r2.get('msg', '')}")
                return
            _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                  {"receive_id": chat_id, "msg_type": "file",
                   "content": _j.dumps({"file_key": file_key})}, H)
            _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                  {"receive_id": chat_id, "msg_type": "text",
                   "content": _j.dumps({"text": txt})}, H)
            self._safe_log(f"✅ 已发送到飞书 dataworld 群 · {_os.path.basename(path)}")
        except Exception as ex:
            self._safe_log(f"⚠️ 飞书发送失败: {ex}")

    def _send_video_to_feishu_async(self, path):
        import threading
        threading.Thread(target=self._feishu_send_file_work,
                         args=(path, "mp4",
                               "🎬 Z-MAX 双脑+状态机插拔演示视频已生成\n" + os.path.basename(path)),
                         daemon=True).start()

    def _send_pdf_to_feishu_async(self, path):
        import threading
        threading.Thread(target=self._feishu_send_file_work,
                         args=(path, "pdf",
                               "📄 Z-MAX 双脑+状态机插拔方案报告已生成\n" + os.path.basename(path)),
                         daemon=True).start()

    # ── 🏁 自动最终交付: rollout 视频 + 拼接对比 + PDF + 发飞书 (2026-08-06 老倪) ──
    def _auto_finalize(self):
        """训练全流程完成后自动触发 (ZMAX_AUTO_RUN=1): 后台线程跑 rollout+PDF+飞书"""
        self._log("🏁 七模型训练完成! 自动生成 🎮 仿真 rollout 评估视频 (metaworld 环境) + PDF 报告 → 发飞书 dataworld 群…")
        import threading
        threading.Thread(target=self._auto_finalize_work, daemon=True).start()

    def _auto_finalize_work(self):
        """(后台线程) ① rollout 5 模型 → ② 每模型 mp4 → ③ 3+2 对比拼接 → ④ PDF → ⑤ 发飞书"""
        try:
            import subprocess as _sp
            root = self._repo_root()
            # 🐳 2026-08-08 老倪: 评估/rollout 强制容器 (zmax-std)
            venv = "docker"  # placeholder — 用容器命令
            pols = [("act", "ACT"), ("smolvla", "SmolVLA"), ("smolvla_lew", "SmolVLA+LEW"),
                    ("vla_touch", "VLA-Touch"), ("awe_zflow", "AWE")]
            # 🎛 2026-08-09 老倪: 按训练开关过滤 rollout 模型 (只出训过的, 不白跑全量)
            try:
                zoo_sw = getattr(self, "_zoo_sw", {})
                on_pols = [p for p, _ in pols if zoo_sw.get(p) is not None and zoo_sw[p].isChecked()]
                if on_pols:
                    pols = [p for p in pols if p[0] in on_pols]
                    self._safe_log(f"🎛 自动交付: 仅训过的模型 {[p for p, _ in pols]}")
            except Exception:
                pass
            # ① rollout 5 模型 (60 帧, 同视频规格)
            for pol, _nm in pols:
                try:
                    r = _sp.run(["sudo", "docker", "run", "--rm", "--gpus", "all",
                                 "-v", f"{root}:/app", "-w", "/app", "-e", "PYTHONPATH=/app/src",
                                 "--entrypoint", "python", "zmax-std:1.0",
                                 "/app/tools/rollout_video.py",
                                 "--policy", pol, "--steps", "60",
                                 "--task", "peg-insert-side-v3", "--camera", "corner2",
                                 "--rotate-ccw", "--out", os.path.join("/app", "reports", f"rollout_final_{pol}")],
                                capture_output=True, text=True, timeout=600, cwd=root)
                    self._safe_log(f"🎥 {pol} rollout {'✅' if r.returncode == 0 else '❌'}"
                              + (f" · {(r.stdout or '').strip().splitlines()[-1][:60]}" if r.returncode == 0 and r.stdout else ""))
                except Exception as ex:
                    self._safe_log(f"🎥 {pol} rollout ❌ {ex}")
            # ② 每模型帧 → mp4
            mp4s = []
            for pol, _nm in pols:
                d = os.path.join(root, "reports", f"rollout_final_{pol}")
                out_mp4 = os.path.join(root, "reports", f"rollout_final_{pol}.mp4")
                if not os.path.isdir(d):
                    continue
                try:
                    _sp.run(["ffmpeg", "-y", "-framerate", "20", "-i",
                             os.path.join(d, "frame_%04d.png"), "-c:v", "libx264",
                             "-pix_fmt", "yuv420p", "-loglevel", "error", out_mp4],
                            capture_output=True, timeout=120)
                    if os.path.exists(out_mp4):
                        mp4s.append((pol, out_mp4))
                        self._safe_log(f"🎞 {pol} mp4 已生成")
                except Exception:
                    pass
            # ③ 拼接对比 (xstack: 5模型=3+2 / 1模型=单视频直接用)
            cmp_mp4 = os.path.join(root, "reports", f"Model Zoo_rollout_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
            try:
                if len(mp4s) == 5:
                    fc = ("[0:v]scale=320:240[a0];[1:v]scale=320:240[a1];"
                          "[2:v]scale=320:240[a2];[3:v]scale=320:240[a3];"
                          "[4:v]scale=320:240[a4];"
                          "[a0][a1][a2]xstack=inputs=3:layout=0_0|w_0_0|w_0+w_1_0[v0];"
                          "[a3][a4]xstack=inputs=2:layout=0_0|w_0_0[v1];"
                          "[v0][v1]xstack=inputs=2:layout=0_0|0_h_0[v]")
                    _sp.run(["ffmpeg", "-y"] +
                            sum([["-i", m] for _, m in mp4s], []) +
                            ["-filter_complex", fc, "-map", "[v]", "-c:v", "libx264",
                             "-pix_fmt", "yuv420p", "-loglevel", "error", cmp_mp4],
                            capture_output=True, timeout=180)
                    if os.path.exists(cmp_mp4):
                        self._safe_log(f"🎬 Model Zoo视频: {os.path.basename(cmp_mp4)}")
                elif len(mp4s) == 1:
                    # 🎬 2026-08-09 老倪: 单模型 (只训一个开关) → 直接用该 mp4 当对比视频
                    import shutil
                    shutil.copy(mp4s[0][1], cmp_mp4)
                    self._safe_log(f"🎬 Model Zoo视频: {os.path.basename(cmp_mp4)} (单模型)")
                else:
                    cmp_mp4 = None
            except Exception:
                cmp_mp4 = None
            # ④ PDF 报告
            try:
                _sp.run([venv, os.path.join(root, "tools", "generate_report.py")],
                        capture_output=True, text=True, timeout=300, cwd=root)
                self._safe_log("📄 PDF 报告已生成")
            except Exception as ex:
                self._safe_log(f"📄 PDF 生成失败: {ex}")
            # ⑤ 发飞书: 对比视频 + PDF (先视频后报告, 用户群里看)
            if cmp_mp4 and os.path.exists(cmp_mp4):
                self._send_file_to_feishu(cmp_mp4, "🎬 Z-MAX 五模型 rollout 对比视频",
                                          file_type="mp4")
            for pol, _nm in pols:
                m = os.path.join(root, "reports", f"rollout_final_{pol}.mp4")
                if os.path.exists(m):
                    self._send_file_to_feishu(m, f"🎥 {_nm} rollout 视频", file_type="mp4")
            # PDF (复用既有发送逻辑)
            self._send_report_to_feishu_work("Model Zoo技术选型报告")
            self._safe_log("✅ 自动交付完成: 视频 + PDF 已发飞书 dataworld 群")
        except Exception as ex:
            self._safe_log(f"⚠️ 自动交付失败: {ex}")

    def _send_file_to_feishu(self, path, text_msg, file_type="mp4"):
        """📤 通用飞书发文件 (mp4/pdf 等): 上传 → 发 file 消息 + 文本说明 (后台线程)"""
        import threading
        threading.Thread(target=self._send_file_to_feishu_work, args=(path, text_msg, file_type),
                         daemon=True).start()

    def _send_file_to_feishu_work(self, path, text_msg, file_type="mp4"):
        """(后台线程) 上传任意文件到飞书并发送到 dataworld 群"""
        try:
            import json as _j, urllib.request as _ur, os as _os
            if not _os.path.exists(path):
                self._safe_log(f"⚠️ 飞书发送: 文件不存在 {path}")
                return
            env = {}
            env_path = _os.path.expanduser("~/.hermes/.env")
            if _os.path.exists(env_path):
                for line in open(env_path, encoding="utf-8"):
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k] = v
            app_id = env.get("FEISHU_APP_ID", "")
            app_secret = env.get("FEISHU_APP_SECRET", "")
            chat_id = env.get("FEISHU_REPORT_CHAT_ID", "oc_c0b4048546145c5c581ddd1a9e8f565d")
            if not app_id or not app_secret:
                self._safe_log("⚠️ 飞书发送: .env 无凭据")
                return

            def _post(url, data, headers=None):
                req = _ur.Request(url, data=_j.dumps(data).encode(),
                                  headers={"Content-Type": "application/json", **(headers or {})})
                return _j.loads(_ur.urlopen(req, timeout=15).read())

            r = _post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                      {"app_id": app_id, "app_secret": app_secret})
            tok = r.get("tenant_access_token")
            if not tok:
                self._safe_log("⚠️ 飞书发送: token 失败")
                return
            H = {"Authorization": "Bearer " + tok}
            boundary = "----zmaxfile"
            with open(path, "rb") as f:
                content = f.read()
            body = (("--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file_type\"\r\n\r\n" + file_type + "\r\n" +
                     "--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file_name\"\r\n\r\n" +
                     _os.path.basename(path) + "\r\n" +
                     "--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"file\"; filename=\"" +
                     _os.path.basename(path) + "\"\r\n"
                     "Content-Type: application/octet-stream\r\n\r\n").encode() + content + (
                     "\r\n--" + boundary + "--\r\n").encode())
            req = _ur.Request("https://open.feishu.cn/open-apis/im/v1/files", data=body,
                              headers={**H, "Content-Type": "multipart/form-data; boundary=" + boundary})
            r2 = _j.loads(_ur.urlopen(req, timeout=30).read())
            file_key = r2.get("data", {}).get("file_key")
            if not file_key:
                self._safe_log(f"⚠️ 飞书发送: 上传失败 {r2.get('msg', '')}")
                return
            _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                  {"receive_id": chat_id, "msg_type": "file",
                   "content": _j.dumps({"file_key": file_key})}, H)
            _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                  {"receive_id": chat_id, "msg_type": "text",
                   "content": _j.dumps({"text": text_msg + " · " + _os.path.basename(path)})}, H)
            self._safe_log(f"✅ 已发送到飞书 dataworld 群: {_os.path.basename(path)}")
        except Exception as ex:
            self._safe_log(f"⚠️ 飞书发送失败: {ex}")

    def _flow_next(self):
        """(worker 完成后) 执行下一个环节; 队列空 → 全流程结束, 恢复按钮"""
        if getattr(self, "_flow_queue", None):
            fn = self._flow_queue.pop(0)
            if getattr(self, "_flow_names", None):
                self._flow_names.pop(0)  # 🔎 同步队列名
            fn()
        else:
            # 2026-08-06 老倪: 流程结束 → 停流程时钟 (t 定格)
            fc = getattr(self, "_flow_clock", None)
            if fc is not None:
                fc.stop()
            # 2026-08-05 老倪: 全流程完成/终止后恢复运行按钮
            if getattr(self, "_worker", None) is None or not self._worker.isRunning():
                self.btn_run.setText("▶ 运行")
                self.btn_run.setEnabled(True)
                self.btn_stop.setEnabled(False)
            # 🏁 全流程完成 → 自动最终交付 (2026-08-06 老倪: 要能插拔的视频 + PDF,
            #   且视频也发 dataworld 群; 仅 ZMAX_AUTO_RUN=1 自动模式触发, 手动运行不打扰)
            if os.environ.get("ZMAX_AUTO_RUN") == "1" and \
                    not getattr(self, "_auto_finalize_done", False):
                self._auto_finalize_done = True
                self._auto_finalize()

    def _flow_clock_tick(self):
        """⏱ 流程时钟: 真实流程运行时 t 每秒 +1 (2026-08-06 老倪: 运行 t 不变)"""
        self._sim_t += 1.0
        try:
            self._refresh_status()  # 底部状态栏 lbl_rt 显示 t (右上角时钟已删)
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════
    # CICD 主控台: 节点双击 → 数据源切换 / 运行环节 (2026-08-02)
    # 老倪: "控制台是主控点, 在node上要有所有链路主要node, 要能运行;
    #        既要有metaworld数据, 又要有Orin, 又要有ACT模型, 可随意切换如何训练"
    # ════════════════════════════════════════════════════════════
    # 节点名 → 环节执行器 (双击运行)
    NODE_RUN_ACTIONS = [
        ("采集", "on_collect"),
        ("训练", "on_train"),
        ("基准", "on_train"),   # 📏 官方专家基准 (2026-08-07): 非训练, 执行一次基准演示
        ("验证", "on_validate"),
        ("集成", "on_integrate"),
        ("部署", "on_deploy"),
        ("推理", "on_infer"),
        ("对比评估", "on_compare_scope"),
        ("Scope", "on_scope"),
        ("PDF", "on_pdf_report"),   # 📄 技术选型报告 (2026-08-05 老倪)
    ]

    def on_compare_scope(self, **kw):
        """🔬 对比评估 Scope: 双击 → 自动跑已训练模型统一评估 → 弹出对比图表
        (兼容双/三/四模型: 至少一个模型有训练产物即可, compare_models.py 会跳过缺失的)"""
        root = self._repo_root()
        rc_act = os.path.join(root, "reports", "train_curve_act.json")
        rc_sml = os.path.join(root, "reports", "train_curve_smolvla.json")
        rc_lew = os.path.join(root, "reports", "train_curve_smolvla_lew.json")
        rc_vt = os.path.join(root, "reports", "train_curve_vla_touch.json")
        rc_aw = os.path.join(root, "reports", "train_curve_awe_zflow.json")
        rc_mlp = os.path.join(root, "reports", "train_curve_expert_mlp.json")
        rc_exp = os.path.join(root, "reports", "train_curve_expert_policy.json")
        have = [p for p, f in (("ACT", rc_act), ("SmolVLA", rc_sml),
                               ("SmolVLA+LEW", rc_lew), ("VLA-Touch", rc_vt),
                               ("AWE-zFlow", rc_aw), ("MLP 蒸馏", rc_mlp),
                               ("官方专家", rc_exp)) if os.path.exists(f)]
        if not have:
            self._log("⚠️ 对比评估: 还缺训练产物 — 先点「▶ 运行」(或分别双击训练节点) 训练模型")
            self._qmsg_info("🔬 对比评估",
                            "还缺训练产物!\n\n请先点「▶ 运行」依次训练模型\n"
                            "或分别双击「🚀 ACT 训练」「🚀 SmolVLA 训练」「🚀 SmolVLA+LEW 训练」「🚀 VLA-Touch 训练」「🚀 AWE 训练」「🎓 专家蒸馏训练」节点。")
            return
        self._log(f"⚔️ 对比评估: 统一 metaworld 测试集 (120帧) 评估 {len(have)} 个已训练模型 ({' / '.join(have)}) — 精确度/鲁棒性/延迟, 完成自动弹图表…")

        def _work():
            rc = self._run_cmd(["sudo", "docker", "run", "--rm", "--gpus", "all",
                                "-v", f"{root}:/app", "-w", "/app", "-e", "PYTHONPATH=/app/src",
                                "--entrypoint", "python", "zmax-std:1.0",
                                "/app/tools/compare_models.py",
                                "--frames", "120"], cwd=root)
            return (rc == 0), ("对比评估完成 · 弹窗展示图表" if rc == 0 else "对比评估失败 (见上方日志)")

        self._start_worker(_work, "正在评估已训练模型 (统一 metaworld)", stage="compare")

    def on_scope(self, **kw):
        """📊 Scope 示波器: 显示最近训练 loss 曲线 (Simulink Scope 对标)"""
        try:
            from simulink_scope import FlowScopeDialog
        except ImportError as ex:
            self._log(f"❌ 缺少 simulink_scope.py: {ex}")
            return
        dlg = FlowScopeDialog(self)
        self._show_nonmodal(dlg)  # 非模态, 2026-08-05 防卡死

    def on_node_activated(self, node):
        """双击节点: 数据源 → 切换; Switch → 切换路由; 子系统 → 展开; 视频 → 推理对比; 环节节点 → 运行; 其他 → 参数框"""
        params = node.get("params", {})
        # 0) 视频显示节点 (🎮 仿真推理对比 / 🎮 仿真视频 · <模型>, 2026-08-05 老倪):
        #    双击 → 同步播放; 单模型视频节点 (params.video_policy) → 只放该模型
        if params.get("video"):
            self.on_infer_video(policy=params.get("video_policy"))
            return
        # 0) 子系统节点 (Simulink Subsystem): 双击展开内部流程
        if params.get("subsystem"):
            self._open_subsystem(node)
            return
        # 1) 数据源节点: 切换激活 — 🐛 2026-08-12 老倪: 排除 insert_video/insert_report
        #   (▶视频/📄PDF 节点有 source 源码映射, 原被本分支抢先 → 双击变数据源切换)
        if params.get("source") and not params.get("insert_video") and not params.get("insert_report"):
            self._toggle_source(node)
            return
        # 1.5) Switch 节点 (仿 Simulink Switch 块): 切换数据源路由
        if params.get("switch") or node.get("type") == "switch":
            self._toggle_switch(node)
            return
        # 1.6) ☑ 训练开关节点 (2026-08-05 老倪: checkbox 打勾=训练 / 不打=不训练)
        if node.get("type") == "train_gate":
            self._toggle_train_gate(node)
            return
        # 1.7) 🧩 结构条件节点 (2026-08-09 老倪: ControlNet 思想 — 双击从原子技能库选条件编码注入)
        if node.get("type") == "coord_overlay":
            self._pick_atomic_condition(node)
            return
        # 1.8) 🧩 原子技能节点 (2026-08-09 老倪: W²-VLA Token — 双击导出该技能 action JSON)
        if node.get("type") == "skill":
            self._export_skill_action(node)
            return
        # 1.9) 🏭 场景节点 (2026-08-09 老倪: 双击 → 打开 ECS 链接 + 建场景节点链)
        if node.get("type") == "scene":
            self._open_scene(node)
            return
        # 1.10) ▶ 插拔演示视频 (2026-08-10 双脑+状态机: 双击 → 后台生成插拔 mp4 → 自动发飞书)
        if params.get("insert_video"):
            self.on_insert_video()
            return
        # 1.11) 📄 插拔方案PDF (2026-08-10 双脑+状态机: 双击 → 6章方案报告 → 自动发飞书)
        if params.get("insert_report"):
            self.on_insert_report()
            return
        # 1.12) 🌐 方案介绍节点 (2026-08-12 老倪: 画布节点双击 → 打开方案介绍分页)
        if params.get("solution_web"):
            self.open_solution_web()
            return
        # 2) 环节节点: 按名称匹配执行器
        for kw, meth in self.NODE_RUN_ACTIONS:
            if kw in node.get("name", ""):
                fn = getattr(self, meth, None)
                if fn:
                    # 2026-08-05 老倪: "增加训练步数调整功能, 双击打开配置" —
                    # 训练节点双击 → 训练配置对话框 (不直接运行)
                    if kw == "训练":
                        self.on_train_config(node)
                    else:
                        self._run_node_stage(node, fn, kw)
                return
        # 3) 其他节点: 打开参数框 (非模态, 2026-08-05 防卡死)
        dlg = BlockParamsDialog(node, None)
        self._show_nonmodal(dlg, on_accept=lambda: self._refresh_node(node))

    def on_train_config(self, node):
        """⚙️ 训练配置 (2026-08-05 老倪: 双击/右键训练节点 → 调整 steps/batch/lr)
        2026-08-05 修复#2: 模态 exec_ 在 WSLg 下弹窗不可见 → 界面'卡死'(按啥都不好使);
        改非模态 show + 自动居中置前, 主窗口永不被禁用"""
        dlg = TrainConfigDialog(node, self)
        try:
            dlg.move(self.mapToGlobal(self.rect().center()) - dlg.rect().center())
        except Exception:
            pass
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.raise_()
        dlg.activateWindow()

        def _on_done(result):
            if result == QDialog.Accepted:
                p = node.get("params", {})
                self._log(f"⚙️ [{node['name']}] 训练配置已更新: steps={p.get('steps')} · "
                          f"batch={p.get('batch_size')} · lr={p.get('lr')} (下次训练生效)")
                it = self._items.get(node["id"])
                if it:
                    it.update()
            dlg.deleteLater()

        dlg.finished.connect(_on_done)
        dlg.show()  # 非模态: 主窗口可继续操作, 对话框置顶显示

    # ── 📚 左侧模块库栏 折叠/展开 (2026-08-06 老倪: 太占地方可缩到左边) ──
    def _collapse_library(self):
        """隐藏模块库左侧栏 → 画布占满; 左缘留 16px ▶ 展开条"""
        self.library.setVisible(False)
        self._lib_expand_bar.setVisible(True)
        self._log("📚 模块库已收起 (点左缘 ▶ 展开)")

    def _expand_library(self):
        """恢复模块库左侧栏"""
        self.library.setVisible(True)
        self._lib_expand_bar.setVisible(False)
        self._log("📚 模块库已展开")

    def _show_nonmodal(self, dlg, on_accept=None):
        """🖥 通用非模态对话框 (2026-08-05 根治: exec_ 模态在 WSLg 下弹窗不可见 →
        主窗口被禁用'卡死'; 统一 show() + 置顶 + finished 回调, 主窗口永不被禁)"""
        try:
            dlg.move(self.mapToGlobal(self.rect().center()) - dlg.rect().center())
        except Exception:
            pass
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.raise_()
        dlg.activateWindow()

        def _done(result):
            if result == QDialog.Accepted and on_accept is not None:
                try:
                    on_accept()
                except Exception:
                    pass
            # 🐛 2026-08-06 老倪: 视频对比只能打开一次 — _done 闭包捕获 dlg 形成
            # 循环引用 (dlg.finished → _done → dlg), deleteLater 后 Python wrapper
            # 不释放 → 旧 dialog 幽灵残留 (timer 继续跑), 二次打开出现两个窗口
            try:
                dlg.finished.disconnect(_done)  # 断开循环引用, 允许真正释放
            except Exception:
                pass
            dlg.deleteLater()

        dlg.finished.connect(_done)
        dlg.show()

    def on_show_node_logic(self, node):
        """右键 → 查看/编辑节点逻辑 (node_logic.py ✏️ 可修改区, 保存即生效)"""
        dlg = NodeLogicDialog(node.get("name", ""), node.get("type", ""), self)
        self._show_nonmodal(dlg)

    def on_node_params(self, node):
        """右键 → 节点参数框"""
        dlg = BlockParamsDialog(node, None)
        self._show_nonmodal(dlg, on_accept=lambda: self._refresh_node(node))

    def _refresh_node(self, node):
        it = self._items.get(node["id"])
        if it:
            it.update()

    def _toggle_switch(self, node):
        """双击 Switch 节点: orin ↔ metaworld 切换 (Simulink Switch 块语义)"""
        p = node.setdefault("params", {})
        p["switch"] = "metaworld" if p.get("switch", "orin") == "orin" else "orin"
        it = self._items.get(node["id"])
        if it:
            it.update()
        self.canvas._scene.update()
        sel = p["switch"]
        label = "Orin 真实数据 (relay/latest)" if sel == "orin" else "metaworld 占位集"
        self._log(f"🔀 Switch 切换到 → {label} · 训练将使用该数据源 (双击可再切换)")
        self._sync()

    def _toggle_train_gate(self, node):
        """双击 ☑ 训练开关节点: 打勾=训练 / 不打=不训练 (checkbox 语义, 2026-08-05 老倪)"""
        p = node.setdefault("params", {})
        p["train_enabled"] = not p.get("train_enabled", True)
        it = self._items.get(node["id"])
        if it:
            it.update()
        self.canvas._scene.update()
        en = p["train_enabled"]
        self._log(f"☑ 训练开关: {'打勾 → 训练启用' if en else '不打勾 → 训练跳过'} (双击可再切换)")
        self._sync()

    def _export_skill_action(self, node):
        """🧩 原子技能 → action JSON (2026-08-09 老倪: W²-VLA Token 落地)
        单技能: 双击技能节点 → 生成该技能的 action 定义 JSON"""
        import json as _j, os as _os, time as _t
        p = node.get("params", {})
        act = {
            "format": "zmax-skill-action",
            "generated": _t.strftime("%Y%m%d_%H%M%S"),
            "skill_id": p.get("skill_id", ""),
            "name": node.get("name", "").replace("🧩 ", ""),
            "tokens": p.get("tokens", {}),
            "action": p.get("action", "operate"),
            "modalities": p.get("modalities", []),
            "encoding": p.get("encoding", {}),
            "gate": p.get("gate", 0.5),
            "input": {"topic": "/dds/cond/" + (p.get("skill_id", "skill").lower())},
            "output": {"topic": "/dds/action/" + (p.get("skill_id", "skill").lower())},
        }
        repo = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        out = _os.path.join(repo, "flows", f"action_{p.get('skill_id', 'skill')}.json")
        _j.dump(act, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        self._log(f"🧩 技能 action 已导出: {out}")
        return out

    def export_all_skill_actions(self):
        """🧩 导出画布上全部原子技能 → action JSON (汇总文件, 画板可加载)"""
        import json as _j, os as _os, time as _t
        skills = [n for n in self.nodes if n.get("type") == "skill"]
        if not skills:
            self._log("⚠️ 画布上没有原子技能节点")
            return
        acts = []
        for n in skills:
            p = n.get("params", {})
            acts.append({
                "skill_id": p.get("skill_id", ""),
                "name": n.get("name", "").replace("🧩 ", ""),
                "tokens": p.get("tokens", {}),
                "action": p.get("action", "operate"),
                "modalities": p.get("modalities", []),
                "encoding": p.get("encoding", {}),
                "gate": p.get("gate", 0.5),
            })
        flow = {
            "format": "zmax-actions",
            "generated": _t.strftime("%Y%m%d_%H%M%S"),
            "count": len(acts),
            "actions": acts,
        }
        repo = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        out = _os.path.join(repo, "flows", f"actions_{_t.strftime('%Y%m%d_%H%M%S')}.json")
        _j.dump(flow, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        self._log(f"🧩 已导出 {len(acts)} 个技能 action → {out} (画板可加载)")
        return out

    def open_atomic_skill_flow(self, btn_name="🧩 原子"):
        """🧩 原子按钮 (2026-08-09 老倪 v4): SCN-01/02/03 三场景全链, 共用 1 个 SYS1
        每场景: 场景node → 原子技能序列 → 结构条件
        三场景结构条件 → 汇聚 1 个 SYS1 动作系统 → action 输出节点"""
        import os as _os, json as _j, time as _t
        repo = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        sp = _os.path.join(repo, "flows", "scene_skills_3scenarios.json")
        try:
            scenes = _j.load(open(sp, encoding="utf-8")).get("scenes", [])
        except Exception as e:
            self._log(f"❌ 场景库读取失败: {e}")
            return
        if not scenes:
            self._log("❌ 场景库为空")
            return
        if self.nodes:
            if not self._qmsg_yes("🧩 原子技能全场景", "将清空当前画布, 重建 SCN-01/02/03 三场景全链?"):
                return
        self.clear()
        old_sync = self._sync
        self._sync = lambda: None
        old_undo = getattr(self, "_suspend_undo", False)
        self._suspend_undo = True
        try:
            _ICON = {"SCN-01": "🔌", "SCN-02": "🤖", "SCN-03": "🔍"}
            _co_nodes = []  # 三场景结构条件节点 (汇聚到同一 SYS1)
            for _si, scene in enumerate(scenes):
                _sid = scene.get("id", f"SCN-{_si+1:02d}")
                _row_y = 60 + _si * 680  # 🐛 2026-08-09: 行距 680 (技能 7×90=630 不重叠)
                # ① 场景节点 (左)
                sn = self.add_node("scene", f"{_ICON.get(_sid,'🏭')} {_sid} {scene.get('name','')[:12]}",
                                   80, _row_y, {"scene_id": _sid,
                                                "desc": scene.get("description", "")[:70]})
                # ② 原子技能序列 (atoms 去重, 中列竖排)
                atoms = []
                for st in scene.get("process_steps", []):
                    for a in st.get("atoms", []):
                        if a not in atoms:
                            atoms.append(a)
                _px, _py = 320, _row_y - 40
                _prev = sn
                for _ai, atom in enumerate(atoms):
                    _aid = atom.split(" ")[0]
                    _anm = atom[len(_aid):].strip() or _aid
                    an = self.add_node("skill", f"🧩 {_aid} {_anm[:10]}", _px, _py + _ai * 90, {  # 🐛 间距 90 不重叠
                        "skill_id": _aid, "scene": _sid, "step": _ai + 1,
                        "action": "operate", "gate": 0.5,
                        "desc": f"{_sid} 第{_ai+1}步: {_anm}"})
                    _fi = self._items.get(_prev["id"]); _ti = self._items.get(an["id"])
                    if _fi and _ti:
                        self.add_link(_fi, _ti, "next")
                    _prev = an
                # ③ 结构条件 (每场景一个)
                _perf = scene.get("performance", {})
                cn = self.add_node("coord_overlay",
                                   f"🧩 结构条件 · {_sid}", _px + 260, _row_y + 200, {  # 🐛 对齐技能列中部
                                       "cond_ref": _sid, "skill": scene.get("name", ""),
                                       "scene": _sid, "gate": 0.5,
                                       "desc": f"🏭 {scene.get('name','')[:14]} 条件编码 (成功率{_perf.get('operation_success_rate','')}, 节拍{_perf.get('cycle_time','')})"})
                _fi = self._items.get(_prev["id"]); _ti = self._items.get(cn["id"])
                if _fi and _ti:
                    self.add_link(_fi, _ti, "cond")
                _co_nodes.append(cn)
                self._log(f"🏭 {_sid} 场景链已建: 场景→{len(atoms)}技能→结构条件")
            # ④ 共用 1 个 SYS1 动作系统 (三场景结构条件汇聚)
            s1 = self.add_node("system", "🧠 SYS1 动作系统", 950, 300, {
                "layer": "sys1", "shared": True,
                "desc": "三场景共用: 接收 SCN-01/02/03 结构条件编码, 执行动作序列"})
            for cn in _co_nodes:
                _ci = self._items.get(cn["id"]); _s1i = self._items.get(s1["id"])
                if _ci and _s1i:
                    self.add_link(_ci, _s1i, "action")
            # ⑤ action 输出节点群 (2026-08-09 老倪: A00~A10 全是 SYS1 的输出)
            #   A001 精密对准 ~ A010 锡焊/钎焊 (操作动作系列, 每动作一个输出节点)
            _A_NAMES = {"A000": "动作库", "A001": "精密对准", "A002": "插入/拔出",
                        "A003": "压装/扣合", "A004": "旋拧/锁付", "A005": "扭矩/角度控制",
                        "A006": "轨迹跟踪加工", "A007": "点胶/涂布/喷涂", "A008": "贴标/贴装",
                        "A009": "撕膜/贴膜", "A010": "锡焊/钎焊"}
            _s1i = self._items.get(s1["id"])
            _act_prev = None
            for _ai in range(1, 11):
                _aid = f"A{_ai:03d}"
                _ax = 1250 + (_ai - 1) % 5 * 190
                _ay = 180 + (_ai - 1) // 5 * 120
                act = self.add_node("action", f"🎯 {_aid} {_A_NAMES.get(_aid, '')[:8]}", _ax, _ay, {
                    "action_out": f"/dds/action/{_aid.lower()}",
                    "scene": "SCN-01/02/03", "gate": 0.5,
                    "desc": f"{_aid} {_A_NAMES.get(_aid, '')} — SYS1 动作输出"})
                _ai2 = self._items.get(act["id"])
                if _s1i and _ai2:
                    self.add_link(_s1i, _ai2, "action")
                _act_prev = act
            # action 汇聚输出
            act_all = self.add_node("action", "📤 Action 汇总", 1250 + 5 * 190 - 100, 180 + 2 * 120, {
                "action_out": "/dds/action/scn_all",
                "scene": "SCN-01/02/03", "gate": 0.5,
                "desc": "A001~A010 动作汇总输出: /dds/action/scn_all (画板可加载)"})
            _ai2 = self._items.get(act_all["id"])
            if _s1i and _ai2:
                self.add_link(_s1i, _ai2, "action")
        finally:
            self._sync = old_sync
            self._suspend_undo = old_undo
            self._sync()
            self.canvas._scene.update()
        self._log(f"🧩 原子技能全场景已建: {len(scenes)} 场景 → 共用 SYS1 → action 输出")

    def open_scene(self, scene_id, node=None):
        """🏭 场景: 打开 ECS 链接 (传场景 JSON) + 建场景节点链 (2026-08-09 老倪)
        数据源: flows/scenes.json — 光模块工厂三大场景 (插拔/搬运/光学检测)
        ECS 链接: https://datadrive.world/scene.html?scene=<scene_id>&json=<base64>"""
        import os as _os, json as _j, base64 as _b64, urllib.parse as _up
        repo = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        p = _os.path.join(repo, "flows", "scene_skills_3scenarios.json")
        if not _os.path.exists(p):
            self._log(f"❌ 场景库不存在: {p}")
            return
        try:
            data = _j.load(open(p, encoding="utf-8"))
            scene = next((s for s in data.get("scenes", []) if s.get("id") == scene_id), None)
            if scene is None:
                scene = next((s for s in data.get("scenes", []) if s.get("scene_id") == scene_id), None)
        except Exception as e:
            self._log(f"❌ 场景库解析失败: {e}")
            return
        if not scene:
            self._log(f"❌ 场景不存在: {scene_id}")
            return
        # 1) 打开 ECS 3D 场景链接 (2026-08-09 老倪+web: scene-3d.html 3D 机器人场景)
        try:
            from PyQt5.QtCore import QUrl
            from PyQt5.QtGui import QDesktopServices
            _SCENE3D = {"SCN-01": "insert", "SCN-02": "handle", "SCN-03": "aoi"}
            _k = _SCENE3D.get(scene_id, scene_id.lower())
            url = f"https://datadrive.world/scene-3d.html?scene={_k}"
            QDesktopServices.openUrl(QUrl(url))
            self._log(f"🏭 已打开 3D 场景: {scene_id} → {url}")
        except Exception as e:
            self._log(f"⚠️ 打开链接失败: {e}")
        # 2) 建场景节点链 (画布: 场景节点 + 技能节点序列 → 结构条件 → SYS1)
        self._build_scene_flow(scene, node)

    def _build_scene_flow(self, scene, scene_node=None):
        """🏭 场景节点链: 场景 → 技能序列 (skill) → 结构条件 (coord_overlay) → SYS1"""
        import os as _os, json as _j, time as _t
        repo = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        tk_p = _os.path.join(repo, "flows", "atomic_skill_tokens.json")
        try:
            tks = {s["skill_id"]: s for s in _j.load(open(tk_p, encoding="utf-8")).get("skills", [])}
        except Exception:
            tks = {}
        if scene_node:
            sx, sy = scene_node.get("x", 200), scene_node.get("y", 150)
        else:
            sx, sy = 120, 150
        prev = None
        # 🐛 兼容用户场景库: process_steps (用户) / process (旧)
        _steps = scene.get("process_steps") or scene.get("process") or []
        _perf = scene.get("performance") or scene.get("metrics") or {}
        for i, step in enumerate(_steps):
            sid = step.get("skill_id", "")
            tk = tks.get(sid, {})
            # 技能节点
            _sid = scene.get("scene_id") or scene.get("id") or ""
            sn = self.add_node("skill", f"🧩 {sid} {step.get('name','')[:14]}", sx, sy + i * 90, {
                "skill_id": sid, "tokens": tk.get("tokens", {}),
                "action": step.get("action", "operate"), "gate": 0.5,
                "scene": _sid, "step": step.get("step", i + 1),
                "desc": step.get("desc", "")[:60]})
            if prev:
                fi = self._items.get(prev["id"]); ti = self._items.get(sn["id"])
                if fi and ti:
                    self.add_link(fi, ti, "next")
            prev = sn
        # 结构条件节点 (场景级)
        cn = self.add_node("coord_overlay", f"🧩 结构条件 · {_sid}", sx + 260, sy, {
            "cond_ref": _sid, "skill": scene.get("name", ""),
            "tokens": {"scene": _sid}, "gate": 0.5,
            "desc": f"🏭 {str(scene.get('name', ''))[:20]} 条件编码 (成功率{_perf.get('operation_success_rate', '')}, 节拍{_perf.get('cycle_time', '')})"})
        # 技能 → 结构条件
        if prev:
            fi = self._items.get(prev["id"]); ti = self._items.get(cn["id"])
            if fi and ti:
                self.add_link(fi, ti, "cond")
        # SYS1 动作系统
        s1 = self.add_node("system", "🧠 SYS1 动作系统", sx + 260, sy + 120, {
            "layer": "sys1", "desc": f"执行 {str(scene.get('name', ''))[:16]} — 原子技能序列落地"})
        si = self._items.get(cn["id"]); s1i = self._items.get(s1["id"])
        if si and s1i:
            self.add_link(si, s1i, "action")
        self._log(f"🏭 场景 {_sid} 节点链已建: 场景→{len(_steps)}技能→结构条件→SYS1")
        self._sync()

    def open_scene_link(self, scene_id):
        """🏭 场景 → ① POST 场景 JSON 到 ECS scene-api.php ② 打开 3D 链接 (2026-08-09 老倪+web)
        POST: https://datadrive.world/scene-api.php/<insert|handle|aoi> (web 格式 name/skills/specs/kpi)
        URL: scene-3d.html?scene=<k>&json=<base64> — 页面渲染场景工艺指标/结构尺寸/工序
        🐛 WSL 无 xdg-open → QDesktopServices 找不到浏览器 → 用 cmd.exe start (Windows 默认浏览器)"""
        import os as _os, json as _j, base64 as _b64, urllib.parse as _up, subprocess as _sp
        import urllib.request as _rq
        _SCENE3D = {"SCN-01": "insert", "SCN-02": "handle", "SCN-03": "aoi"}
        _k = _SCENE3D.get(scene_id, scene_id.lower())
        url = f"https://datadrive.world/scene-3d.html?scene={_k}"
        _scene = None
        try:
            _repo = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
            _sp2 = _os.path.join(_repo, "flows", "scene_skills_3scenarios.json")
            _data = _j.load(open(_sp2, encoding="utf-8"))
            _scene = next((s for s in _data.get("scenes", []) if s.get("id") == scene_id), None)
            if _scene:
                _b = _b64.b64encode(_j.dumps(_scene, ensure_ascii=False).encode()).decode()
                url += f"&json={_up.quote(_b)}"
        except Exception:
            pass
        # ① POST 场景 JSON 到 ECS (web 格式: name/skills/specs/kpi)
        try:
            if _scene:
                import re as _re
                def _num(v):
                    # 提取首个数字 (≥99.5% → 99.5; ≤3.5s/颗 → 3.5)
                    m = _re.search(r"\d+(\.\d+)?", str(v))
                    try:
                        return float(m.group(0)) if m else 0.0
                    except Exception:
                        return 0.0
                _steps = _scene.get("process_steps", [])
                _sr = _num(_scene.get("performance", {}).get("operation_success_rate", ""))
                _payload = {
                    "name": _scene.get("name", scene_id),
                    "skills": [f"{st.get('step', i+1)}.{st.get('name', '')}" for i, st in enumerate(_steps)],
                    "specs": {
                        # web 格式: success_rate 为小数 (99.5% → 0.995)
                        "success_rate": round(_sr / 100.0, 4) if _sr > 1 else _sr,
                        "cycle_time": _num(_scene.get("performance", {}).get("cycle_time", "")),
                    },
                    "kpi": _scene.get("performance", {}),
                }
                _req = _rq.Request(
                    f"https://datadrive.world/scene-api.php/{_k}",
                    data=_j.dumps(_payload, ensure_ascii=False).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
                with _rq.urlopen(_req, timeout=8) as _resp:
                    _resp.read()
                self._log(f"🏭 场景 JSON 已 POST → scene-api.php/{_k} (ECS 保存 scenes/scene_{_k}.json)")
        except Exception as _e:
            self._log(f"⚠️ 场景 JSON POST 失败: {_e}")
        # ② 打开 3D 链接
        try:
            _sp.Popen(["cmd.exe", "/c", "start", "", url],
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, cwd="/mnt/c/Windows")
            self._log(f"🏭 打开 3D 场景: {scene_id} → Windows 浏览器")
        except Exception as e:
            self._log(f"⚠️ 打开链接失败: {e}")

    def _open_scene(self, node):
        """双击场景节点 (2026-08-09 老倪 v2): 打开 场景JSON上传窗口
        UI: JSON 预览 + 上传链接 + 📤 上传按钮 + 上传结果 (窗口设计)"""
        import os as _os, json as _j, base64 as _b64, urllib.parse as _up, urllib.request as _rq, re as _re, subprocess as _sp
        sid = node.get("params", {}).get("scene_id", "")
        # 读场景 JSON
        _repo = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        _sp2 = _os.path.join(_repo, "flows", "scene_skills_3scenarios.json")
        _scene = None
        try:
            _data = _j.load(open(_sp2, encoding="utf-8"))
            _scene = next((s for s in _data.get("scenes", []) if s.get("id") == sid), None)
        except Exception as e:
            self._log(f"❌ 场景库读取失败: {e}")
            return
        if not _scene:
            self._log(f"❌ 场景不存在: {sid}")
            return
        # 转换 web 格式 payload
        def _num(v):
            m = _re.search(r"\d+(\.\d+)?", str(v))
            try:
                return float(m.group(0)) if m else 0.0
            except Exception:
                return 0.0
        _sr = _num(_scene.get("performance", {}).get("operation_success_rate", ""))
        _payload = {
            "name": _scene.get("name", sid),
            "skills": [f"{st.get('step', i+1)}.{st.get('name', '')}" for i, st in enumerate(_scene.get("process_steps", []))],
            "specs": {
                "success_rate": round(_sr / 100.0, 4) if _sr > 1 else _sr,
                "cycle_time": _num(_scene.get("performance", {}).get("cycle_time", "")),
            },
            "kpi": _scene.get("performance", {}),
        }
        _json_str = _j.dumps(_payload, ensure_ascii=False, indent=2)
        _SCENE3D = {"SCN-01": "insert", "SCN-02": "handle", "SCN-03": "aoi"}
        _k = _SCENE3D.get(sid, sid.lower())
        _api_url = f"https://datadrive.world/scene-api.php/{_k}"
        _view_url = f"https://datadrive.world/scene-3d.html?scene={_k}"
        # ── UI ──
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                     QPlainTextEdit, QPushButton, QLineEdit)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"🏭 场景 JSON 上传 · {sid} ({_scene.get('name', '')[:20]})")
        dlg.setMinimumSize(640, 560)
        dlg.setStyleSheet("""
            QDialog { background:#0d1117; }
            QLabel { color:#e6edf3; font-size:12px; }
            QPlainTextEdit { background:#161b22; color:#c9d1d9; border:1px solid #30363d; border-radius:6px; font-family:'Consolas','Menlo',monospace; font-size:11px; padding:6px; }
            QLineEdit { background:#161b22; color:#00d4aa; border:1px solid #30363d; border-radius:4px; padding:5px 8px; font-size:11px; }
            QPushButton { background:#21262d; color:#e6edf3; border:1px solid #30363d; border-radius:4px; padding:7px 14px; font-weight:600; }
            QPushButton:hover { border-color:#00d4aa; color:#00d4aa; }
        """)
        lay = QVBoxLayout(dlg)
        # 头部信息
        _perf = _scene.get("performance", {})
        hdr = QLabel(f"📋 {_scene.get('name', '')}  ({sid} · {_scene.get('category', '')})\n"
                     f"📊 成功率 {_perf.get('operation_success_rate', '')} · 节拍 {_perf.get('cycle_time', '')}")
        hdr.setWordWrap(True)
        hdr.setStyleSheet("color:#00d4aa; font-weight:700; font-size:13px;")
        lay.addWidget(hdr)
        # JSON 预览
        lay.addWidget(QLabel("📄 场景描述 JSON (可编辑):"))
        editor = QPlainTextEdit(_json_str)
        editor.setMinimumHeight(240)
        lay.addWidget(editor)
        # 上传链接
        lay.addWidget(QLabel("🔗 上传链接 (ECS 接收端点):"))
        url_row = QHBoxLayout()
        url_edit = QLineEdit(_api_url)
        url_edit.setReadOnly(True)
        url_row.addWidget(url_edit, 1)
        btn_copy = QPushButton("📋 复制")
        url_row.addWidget(btn_copy)
        lay.addLayout(url_row)
        # 结果状态
        status = QLabel("")
        status.setWordWrap(True)
        status.setStyleSheet("color:#8b949e; font-size:11px;")
        lay.addWidget(status)
        # 操作按钮
        btn_row = QHBoxLayout()
        btn_up = QPushButton("📤 上传到 ECS")
        btn_up.setStyleSheet("QPushButton{background:#0d3b33; color:#fff; border:1px solid #00d4aa; border-radius:4px; padding:8px 16px; font-weight:700;}")
        btn_3d = QPushButton("🌐 打开 3D 场景")
        btn_close = QPushButton("✖ 关闭")
        btn_row.addWidget(btn_up, 2)
        btn_row.addWidget(btn_3d, 1)
        btn_row.addWidget(btn_close, 1)
        lay.addLayout(btn_row)
        # 交互
        def _copy():
            from PyQt5.QtWidgets import QApplication as _QA
            _QA.clipboard().setText(url_edit.text())
            status.setText("✅ 链接已复制到剪贴板")
        btn_copy.clicked.connect(_copy)
        def _upload():
            try:
                _p = _j.loads(editor.toPlainText())
            except Exception as e:
                status.setText(f"❌ JSON 格式错误: {e}")
                return
            btn_up.setText("⏳ 上传中…")
            btn_up.setEnabled(False)
            try:
                _req = _rq.Request(_api_url, data=_j.dumps(_p, ensure_ascii=False).encode(),
                                   headers={"Content-Type": "application/json"}, method="POST")
                with _rq.urlopen(_req, timeout=10) as _resp:
                    _rb = _j.loads(_resp.read().decode("utf-8", "replace"))
                if _rb.get("ok"):
                    _saved = _rb.get("url", "")
                    status.setText(f"✅ 上传成功!\n💾 保存: {_saved}\n(name={_rb.get('name', '')})")
                    status.setStyleSheet("color:#3fb950; font-size:11px;")
                else:
                    status.setText(f"⚠️ 上传返回: {_rb.get('error', '未知')}")
            except Exception as e:
                status.setText(f"❌ 上传失败: {e}")
            btn_up.setText("📤 上传到 ECS")
            btn_up.setEnabled(True)
        btn_up.clicked.connect(_upload)
        def _open3d():
            dlg.accept()
            self.open_scene_link(sid)
        btn_3d.clicked.connect(_open3d)
        btn_close.clicked.connect(dlg.reject)
        dlg.exec_()

    def _pick_atomic_condition(self, node):
        """🧩 ControlNet 思想: 双击结构条件节点 → 从 atomic_skills_conditions.json 选原子技能条件 → 注入节点
        条件编码 (多模态 one-hot) 作为控制信号, latent += proj(cond)×gate (图像是背景, 条件是主线)"""
        import os as _os, json as _j
        path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "flows", "atomic_skills_conditions.json")
        if not _os.path.exists(path):
            self._log(f"❌ 条件库不存在: {path} (先运行 flows/gen_atomic_conditions.py)")
            return
        try:
            conds = _j.load(open(path, encoding="utf-8"))
        except Exception as e:
            self._log(f"❌ 条件库解析失败: {e}")
            return
        # 弹选择框: 分类 → 技能 → 条件
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QComboBox, QPushButton, QLabel
        dlg = QDialog(self)
        dlg.setWindowTitle("🧩 结构条件 · 原子技能库 (ControlNet)")
        dlg.setMinimumWidth(480)
        lay = QVBoxLayout(dlg)
        from collections import OrderedDict
        by_cat = OrderedDict()
        for c in conds:
            by_cat.setdefault(c["category"], []).append(c)
        cat_cb = QComboBox()
        cat_cb.addItems(list(by_cat.keys()))
        skill_cb = QComboBox()
        def fill_skills(_):
            skill_cb.clear()
            for c in by_cat.get(cat_cb.currentText(), []):
                skill_cb.addItem(f"{c['cond_id']} {c['skill_name'][:22]} · {c['action']}", c)
        cat_cb.currentIndexChanged.connect(fill_skills)
        fill_skills(0)
        lay.addWidget(QLabel("① 技能大类:"))
        lay.addWidget(cat_cb)
        lay.addWidget(QLabel("② 原子技能 → 条件编码:"))
        lay.addWidget(skill_cb)
        info = QLabel("")
        info.setWordWrap(True)
        info.setStyleSheet("color:#8b949e; font-size:10px;")
        lay.addWidget(info)
        def show_info(_):
            c = skill_cb.currentData()
            if c:
                enc = c.get("encoding", {})
                on = [k for k, v in enc.items() if v]
                info.setText(f"Topic: {c['topic']}\n模态: {', '.join(c.get('modalities', []))} · 编码位: {on}\n动作: {c['action']} · gate={c.get('gate', 0.5)}")
        skill_cb.currentIndexChanged.connect(show_info)
        show_info(0)
        btn_ok = QPushButton("✅ 注入此条件")
        btn_ok.setStyleSheet("QPushButton{background:#0d3b33; color:#fff; border-radius:4px; padding:8px; font-weight:bold;}")
        def apply():
            c = skill_cb.currentData()
            if not c:
                return
            p = node.setdefault("params", {})
            p["cond_ref"] = c["cond_id"]
            p["skill"] = c["skill_name"]
            p["topic"] = c["topic"]
            p["action"] = c["action"]
            p["modalities"] = c.get("modalities", [])
            p["encoding"] = c.get("encoding", {})
            p["gate"] = c.get("gate", 0.5)
            p["desc"] = f"🧩 {c['skill_name'][:24]} 条件编码 (ControlNet: latent += proj(cond)×{p['gate']})"
            it = self._items.get(node["id"])
            if it:
                it.update()
            self.canvas._scene.update()
            self._log(f"🧩 结构条件 ← {c['cond_id']} {c['skill_name']} (模态 {c.get('modalities')} · gate {p['gate']})")
            dlg.accept()
            self._sync()
        btn_ok.clicked.connect(apply)
        lay.addWidget(btn_ok)
        dlg.exec_()

    def _toggle_train_gate_ctx(self, name, train_enabled):
        """node_logic 框架动作: 按节点名找到画布开关节点并切换 (兼容右键逻辑执行)"""
        for n in self.nodes:
            if n.get("name") == name:
                self._toggle_train_gate(n)
                return (True, f"训练开关: {'打勾 → 训练' if n.get('params', {}).get('train_enabled', True) else '不打勾 → 跳过'}")
        return (True, f"训练开关: 状态 {train_enabled}")

    def _train_gate_state(self, policy=None):
        """画布上 ☑ 训练开关节点状态: 总开关(无policy) + 模型开关(policy匹配) — 🐛 2026-08-08 老倪 每模型独立"""
        gates = [n for n in self.nodes if n.get("type") == "train_gate"]
        if not gates:
            return True
        # 总开关 (无 policy): 任一关 → 跳过
        master = [n for n in gates if not n.get("params", {}).get("policy")]
        if master and not all(n.get("params", {}).get("train_enabled", True) for n in master):
            return False
        # 模型开关 (policy 匹配): 匹配的开关关 → 跳过该模型
        if policy:
            pol_gates = [n for n in gates if n.get("params", {}).get("policy") == policy]
            if pol_gates and not all(n.get("params", {}).get("train_enabled", True) for n in pol_gates):
                return False
        return True

    def _switch_state(self):
        """画布上 Switch 节点当前路由 → 'orin' | 'metaworld' | None"""
        for n in self.nodes:
            p = n.get("params", {})
            if p.get("switch"):
                return p["switch"] if p["switch"] in ("orin", "metaworld") else "orin"
        return None

    def _toggle_source(self, node):
        """切换训练数据源: 当前数据源节点激活, 其他数据源节点取消"""
        node["params"]["active"] = True
        for n in self.nodes:
            if n["id"] != node["id"] and n.get("params", {}).get("source"):
                n["params"]["active"] = False
                it = self._items.get(n["id"])
                if it:
                    it.update()
        it = self._items.get(node["id"])
        if it:
            it.update()
        self.canvas._scene.update()
        src = node["params"].get("source", "?")
        label = "Orin 真实数据 (relay/latest)" if src == "orin" else "metaworld 占位集"
        self._log(f"🔄 训练数据源切换 → {label} · 双击任意数据源节点可再切换")
        self._sync()

    def _probe_dataset(self, dp):
        """探测数据集属性 (2026-08-07 老倪: 双击数据源看实际路径+属性)"""
        import glob as _g
        info = {}
        try:
            ij = os.path.join(dp, "info.json")
            if os.path.exists(ij):
                with open(ij, encoding="utf-8") as f:
                    d = json.load(f)
                info["总帧数"] = d.get("total_frames", "—")
                info["episodes"] = d.get("total_episodes", "—")
                ft = d.get("features", {})
                if isinstance(ft, dict):
                    for k, v in ft.items():
                        info[f"特征 {k}"] = (v.get("dtype", "—") if isinstance(v, dict) else str(v))
                info["fps"] = d.get("fps", "—")
            ep = os.path.join(dp, "episodes")
            if os.path.isdir(ep):
                n = len(_g.glob(os.path.join(ep, "*")))
                if "episodes" not in info or info["episodes"] == "—":
                    info["episodes"] = n
            nf = len(_g.glob(os.path.join(dp, "**", "*.mp4"), recursive=True))
            nf2 = len(_g.glob(os.path.join(dp, "**", "*.npz"), recursive=True))
            info["视频文件"] = nf
            info["npz 文件"] = nf2
            sz = sum(os.path.getsize(os.path.join(r, f))
                     for r, _, fs in os.walk(dp) for f in fs) / 1e6
            info["大小"] = f"{sz:.0f} MB"
        except Exception as ex:
            info["探测错误"] = str(ex)
        return info

    def _show_source_info(self, node):
        """📦 数据源双击 → 非模态属性框: 实际数据路径 + 属性详情 + 切换激活 (2026-08-07 老倪)"""
        src = node["params"].get("source", "metaworld")
        root = self._repo_root()
        cands = {
            "metaworld": ["data/metaworld_peg"],
            # 2026-08-07 老倪: orin/closed_loop 数据已删 — orin 候选移除
        }.get(src, ["data/metaworld_peg"])
        dlg = QDialog(self.window() or self)
        dlg.setWindowTitle(f"📦 数据源: {node['name']}")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.setStyleSheet("QDialog{background:#f6f8fa;} QLabel{font-size:12px;}")
        lay = QVBoxLayout(dlg)
        act = "✓ 激活" if node["params"].get("active") else "○ 未激活"
        lay.addWidget(QLabel(f"来源: {src} · {act} · {node['params'].get('desc', '')}"))
        found = False
        for p in cands:
            dp = os.path.join(root, p)
            if not os.path.isdir(dp):
                continue
            found = True
            info = self._probe_dataset(dp)
            box = QFrame()
            box.setStyleSheet("QFrame{background:#ffffff;border:1px solid #d0d7de;border-radius:6px;}")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 8, 10, 8)
            tl = QLabel(f"📂 实际路径: {p}  ({dp})")
            tl.setStyleSheet("font-weight:bold;color:#1f6feb;")
            bl.addWidget(tl)
            for k, v in info.items():
                bl.addWidget(QLabel(f"    {k}: {v}"))
            lay.addWidget(box)
        if not found:
            lay.addWidget(QLabel(f"⚠️ 未找到数据目录: {cands}"))
        # 切换激活按钮 (保留原双击切换能力)
        if not node["params"].get("active"):
            btn = QPushButton(f"🔀 切换为激活数据源")
            btn.setStyleSheet("background:#1f6feb;color:#fff;padding:6px 12px;border-radius:4px;")
            btn.clicked.connect(lambda: (self._toggle_source(node), dlg.close()))
            lay.addWidget(btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.close)
        lay.addWidget(close_btn)
        dlg.setMinimumWidth(520)
        self._show_nonmodal(dlg)

    def _active_source(self):
        """画布上激活的数据源节点 → 'orin' | 'metaworld' | None"""
        for n in self.nodes:
            p = n.get("params", {})
            if p.get("source") and p.get("active"):
                return p["source"]
        return None

    def _run_node_stage(self, node, fn, label):
        """双击环节节点 → 后台执行, 节点状态 running→success/error (复用 _start_worker 防重入)"""
        # 🆕 节点逻辑优先: node_logic.py ✏️ 可修改区 (用户改的参数/逻辑真生效)
        logic_res = node_logic.execute_node_logic(self, node, label)
        if logic_res is not None:
            fn = (lambda _r=logic_res: _r)
        cur = getattr(self, "_worker", None)
        if cur is not None:
            # 🐛 2026-08-06: worker 终止竞态 → wait(300) 等正常收尾放行
            if cur.isRunning() and not cur.wait(300):
                # 🔎 2026-08-06 老倪: 防重入提示显示详细信息
                self._log(self._busy_hint())
                return
        node["status"] = "running"
        it = self._items.get(node["id"])
        if it:
            it.update()
        self.canvas._scene.update()
        self._log(f"⏳ 双击运行 [{node['name']}] ({label}) — 后台执行, UI 可继续操作…")

        def _done(ok, summary):
            node["status"] = "success" if ok else "error"
            it2 = self._items.get(node["id"])
            if it2:
                it2.update()
            self.canvas._scene.update()
            if ok:
                self._log(f"✅ [{node['name']}] {summary}")
            else:
                self._log(f"❌ [{node['name']}] {summary}")
            # 2026-08-05 修复: finished_ok emit 时线程未完全结束 → 下一个环节被
            # _worker.isRunning() 误拦 (ACT完成后SmolVLA启动被拦截); wait(100) 等线程
            # 真正结束再置 None — 线程已死 GC 安全 (崩溃修复#10 保留引用不冲突)
            cur = getattr(self, "_worker", None)
            if cur is not None:
                try:
                    cur.wait(100)
                except Exception:
                    pass
                self._worker = None
            if getattr(self, "_cicd_panel", None) and self._cicd_panel.isVisible():
                self._cicd_panel._refresh()
            self._flow_next()  # 全流程流转

        worker = CICDWorker(fn)
        worker.log.connect(self._log)
        worker.finished_ok.connect(_done)
        worker.finished.connect(lambda: None)
        self._worker = worker
        worker.start()


# ── 独立运行入口 (调试) ──
def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = SimulinkModule()
    w.resize(1200, 760)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
