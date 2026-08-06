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
                         QPolygonF, QLinearGradient, QRadialGradient)
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
    "model":     {"cn": "模型", "color": "#58a6ff"},
    "action":    {"cn": "动作", "color": "#00d4aa"},
    "system":    {"cn": "系统", "color": "#d4a800"},
    "hardware":  {"cn": "硬件", "color": "#ff4444"},
    "switch":    {"cn": "路由", "color": "#f0a030"},  # Simulink Switch 块: 数据源选择
    "train_gate": {"cn": "训练开关", "color": "#3fb950"},  # ☑ 训练使能开关 (2026-08-05 老倪: checkbox 打勾=训练)
    "yolo_gate":  {"cn": "YOLO开关", "color": "#d4a800"},  # 🎯 YOLO 感知开关 (2026-08-06 老倪: state 输入 switch, 默认开=39D)
    "row_bg":    {"cn": "背景行", "color": "#3a3f4b"},   # 🎨 五模型对比: 整行彩色背景 + 左侧大字模型名 (可编辑/改名/改色)
    "pdf_report": {"cn": "PDF报告", "color": "#1f6feb"}, # 📄 五模型对比技术选型报告生成 (2026-08-05 老倪)
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
        ("hardware", "📥 Orin 数据源", {"ip": "192.168.23.10", "fps": 30, "source": "orin",
                                        "desc": "真实产线数据"}),
        ("hardware", "📦 metaworld 数据", {"steps": 1000, "source": "metaworld",
                                           "desc": "占位集·管道验证"}),
        ("switch", "🔀 Switch 数据源", {"switch": "orin", "desc": "双击切换 Orin/metaworld"}),
        ("model", "🧠 ACT 训练", {"steps": 1000, "chunk_size": 7, "dim_model": 256,
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
        ("hardware", "📦 metaworld 数据", {"source": "metaworld", "frames": 696, "active": True,
                                           "dims": "4D/4D", "desc": "states 4D · actions 4D (sawyer 关节)"}),
        ("model", "🖼 视觉主干 ResNet18", {"backbone": "resnet18", "pretrained": True,
                                          "desc": "官方 ACT.backbone → layer4 特征图 (B,C,H,W)"}),
        ("model", "🧬 VAE 编码器 CVAE", {"use_vae": True, "latent_dim": 32,
                                        "desc": "官方 ACT.vae_encoder → 潜变量分布 (μ,logσ²)"}),
        ("model", "🔤 Transformer Encoder", {"n_layers": 4, "dim_model": 256, "n_heads": 8,
                                            "desc": "官方 ACT.encoder → 上下文 tokens (latent+state+图像)"}),
        ("model", "🔡 Transformer Decoder", {"n_layers": 4, "chunk_size": 7, "n_heads": 8,
                                            "desc": "官方 ACT.decoder → DETR queries 解码动作块"}),
        ("action", "🎯 Action Head 4D", {"action_dim": 4, "chunk_size": 7,
                                        "desc": "★适配 metaworld: 输出 (B,7,4) · 真机 Orin 为 6D"}),
        ("condition", "⏳ Temporal Ensemble", {"coeff": 0.01,
                                              "desc": "官方 ACTTemporalEnsembler → 动作块时间平滑"}),
        ("system", "🚀 全新训练", {"steps": 1000, "desc": "双击 → on_train (metaworld 占位集, 全新不续训)"}),
        ("action", "📊 Scope 示波器", {"desc": "双击 → 示波器: 训练 loss 曲线/执行效果 (Simulink Scope 对标)"}),
    ], [(0, 1), (1, 3), (0, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8)]),
    # 🎛 顶层总系统 (2026-08-05 老倪: "参考 Simulink, 用一个模块表示总系统; 双击打开后,
    #   可以看到 ACT, SmolVLA, SmolVLA+LEW 三条线" — Simulink Subsystem 语义)
    # 顶层: 数据 → 总系统块 (双击展开内部三线) → 评估 Scope
    ("🎛 总系统·三模型对比", [
        ("hardware", "📦 metaworld 数据", {"source": "metaworld", "frames": 696, "active": True,
                                           "dims": "4D/4D", "shared": True,
                                           "desc": "顶层输入: 统一 metaworld 数据集 (696帧, states/actions 4D)"}),
        ("system", "🔬 总系统·三模型对比", {"subsystem": "🔬 三模型对比", "type_label": "Subsystem",
                                            "desc": "Simulink 子系统: 双击展开 → ACT / SmolVLA / SmolVLA+LEW 三条并行训练线"}),
        ("system", "📊 对比评估 Scope", {"shared": True,
                                        "desc": "顶层输出: 双击 → 三模型 训练速度/精确度/鲁棒性 对比图表"}),
    ], [
        (0, 1, "数据"), (1, 2, "评估"),
    ],
    # 顶层布局: 单行三节点 (数据 → 总系统 → Scope)
    [
        ["📦 metaworld 数据", "🔬 总系统·三模型对比", "📊 对比评估 Scope"],
    ]),
    # 🔬 三模型对比 (2026-08-05 老倪: "增加一个没有leworldmodel的流程, 三个模型对比,
    #   即 ACT, SmolVLA, SmolVLA+LeWorldModel 串行")
    # 模块划分: ♻ 2 共用 (metaworld数据 / 对比评估 Scope)
    #           ACT 分支 7 (ResNet18→CVAE→Encoder→Decoder→ActionHead→Ensemble→训练)
    #           SmolVLA 纯动作分支 4 (SmolVLM2→DiT-B→ActionHead→训练, 无 LEW)
    #           SmolVLA+LEW 分支 5 (SmolVLM2→DiT-B→LeWorldModel→ActionHead→训练)
    # 配置区分: smolvla 用 config_smolvla_metaworld.yaml (freeze_smolvlm:true → LEW 强制关)
    #           smolvla_lew 用 config_smolvla_lew_metaworld.yaml (freeze:false + enable_lew:true)
    ("🔬 三模型对比", [
        ("hardware", "📦 metaworld 数据", {"source": "metaworld", "frames": 696, "active": True,
                                           "dims": "4D/4D", "shared": True,
                                           "desc": "♻ 三模型共用: 统一 metaworld 数据集 (696帧, states/actions 4D)"}),
        # ── ACT 分支 (7) ──
        ("model", "🖼 视觉主干 ResNet18", {"backbone": "resnet18", "pretrained": True,
                                          "desc": "ACT.backbone → layer4 特征图 (B,C,H,W)"}),
        ("model", "🧬 VAE 编码器 CVAE", {"use_vae": True, "latent_dim": 32,
                                        "desc": "ACT.vae_encoder → 潜变量分布 (μ,logσ²)"}),
        ("model", "🔤 Transformer Encoder", {"n_layers": 4, "dim_model": 256, "n_heads": 8,
                                            "desc": "ACT.encoder → 上下文 tokens (latent+state+图像)"}),
        ("model", "🔡 Transformer Decoder", {"n_layers": 4, "chunk_size": 7, "n_heads": 8,
                                            "desc": "ACT.decoder → DETR queries 解码动作块"}),
        ("model", "🎯 Action Head 4D · ACT", {"action_dim": 4, "chunk_size": 7,
                                              "desc": "ACT 专用: 输出 (B,7,4)"}),
        ("condition", "⏳ Temporal Ensemble", {"coeff": 0.01,
                                              "desc": "ACTTemporalEnsembler → 动作块时间平滑 (仅 ACT 用)"}),
        ("system", "🚀 ACT 训练", {"policy": "act", "steps": 1000,
                                  "desc": "双击 → on_train(policy=act) · metaworld 训练"}),
        # ── SmolVLA 纯动作分支 (4, 无 LEW) ──
        ("model", "🧠 SmolVLM2-500M", {"freeze": True,
                                       "smolvlm": "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
                                       "desc": "SmolVLA 视觉语言主干 (冻结, 多模态编码)"}),
        ("model", "🌀 DiT-B 动作解码", {"hidden": 256, "layers": 1, "timesteps": 2,
                                       "desc": "SmolVLA action_model DiT-B → 动作去噪生成 (无世界模型)"}),
        ("model", "🎯 Action Head 4D · SmolVLA", {"action_dim": 4, "chunk_size": 7,
                                                  "desc": "SmolVLA 纯动作版: 输出 (B,7,4) · 无 LEW"}),
        ("system", "🚀 SmolVLA 训练", {"policy": "smolvla", "steps": 1000,
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
        ("system", "🚀 SmolVLA+LEW 训练", {"policy": "smolvla_lew", "steps": 1000,
                                          "desc": "双击 → on_train(policy=smolvla_lew) · 冻结关 + 世界模型开"}),
        ("system", "📊 对比评估 Scope", {"shared": True,
                                        "desc": "♻ 共用: 双击 → 三模型 训练速度/精确度/鲁棒性 对比图表"}),
        ("system", "🎥 推理效果对比", {"video": "all", "auto": True,
                                          "desc": "训练完自动触发: 3 模型 metaworld rollout 生成视频 → 3 窗口同步播放对比 (推理效果)"}),
    ], [
        # ACT 路 (9): 数据→ResNet18(+CVAE)→Encoder→Decoder→ActionHead·ACT→Ensemble→训练
        # 🏷 数据节点三路输出 (官方 modeling_act.py): (0,1)=图像→ResNet18 · (0,2)=动作→CVAE(训练时编码真值动作)
        #   · (0,3)=状态→Encoder (encoder 拼接 latent+图像特征+state); (2,3)=CVAE 潜变量→Encoder
        (0, 1, "图像"), (0, 2, "动作"), (0, 3, "状态"), (1, 3, "图像特征"), (2, 3, "潜变量"), (3, 4), (4, 5), (5, 6), (6, 7),
        # SmolVLA 纯动作路 (4): 数据→SmolVLM2→DiT-B→ActionHead→训练
        (0, 8, "图像+状态"), (8, 9, "多模态embeds"), (9, 10), (10, 11),
        # SmolVLA+LEW 路 (6): 数据→SmolVLM2·LEW→DiT-B·LEW→ActionHead·LEW→训练 (主策略链路)
        #   + LeWorldModel 旁路: 数据→LEW (视频帧+动作) — 官方 world_model_le.py forward(videos, actions):
        #   SigLIP 编码视频帧 + action_encoder 编码动作 → ARPredictor(AdaLN-zero 条件调制) 预测下一帧,
        #   与 DiT-B 输出无关 (训练时用真值动作); 主链路与 LEW 并列, 非串行
        (0, 12, "图像+状态"), (12, 13, "多模态embeds"), (13, 15, "动作块"), (15, 16),
        (0, 14, "视频+动作"), (14, 16, "世界预测"),
        # 评估: 三训练 → 对比 Scope
        (7, 17), (11, 17), (16, 17),
        # 🎥 推理对比 (2026-08-05 老倪: 训练完继续推理): 三训练 → 推理对比节点
        (7, 18), (11, 18), (16, 18),
    ],
    # 🗂 多行展开布局 (2026-08-05 老倪: "不要排成一条直线, 要展开; 类似功能如 Action Head 垂直对齐")
    # 每行 = 一个模型分支; 每列 = 一个功能角色; 空串占位列保持 Action Head 对齐到第5列
    [
        ["📦 metaworld 数据", "🖼 视觉主干 ResNet18", "🧬 VAE 编码器 CVAE", "🔤 Transformer Encoder", "🔡 Transformer Decoder", "🎯 Action Head 4D · ACT", "⏳ Temporal Ensemble", "🚀 ACT 训练"],
        ["📦 metaworld 数据", "🧠 SmolVLM2-500M", "🌀 DiT-B 动作解码", "", "", "🎯 Action Head 4D · SmolVLA", "", "🚀 SmolVLA 训练"],
        ["📦 metaworld 数据", "🧠 SmolVLM2-500M · LEW", "🌀 DiT-B 动作解码 · LEW", "🌐 LeWorldModel", "", "🎯 Action Head 4D · SmolVLA+LEW", "", "🚀 SmolVLA+LEW 训练"],
        ["📊 对比评估 Scope", "", "", "", "", "", "", "🎥 推理效果对比"],
    ]),
    # 🔬 五模型对比 (2026-08-05 老倪: "把 ACT SmolVLA smolvla+lew VLA-Touch AWE 5个模型
    #   放到一起, 纵向对比" — 技术选型终极画布)
    # 模块划分: ♻ 2 共用 (metaworld数据 / 对比评估 Scope / 推理效果对比) + 五模型分支
    #   ACT 7 (ResNet18→CVAE→Encoder→Decoder→ActionHead→Ensemble→训练)
    #   SmolVLA 4 (SmolVLM2→DiT-B→ActionHead→训练, 无 LEW)
    #   SmolVLA+LEW 5 (SmolVLM2→DiT-B→LeWorldModel→ActionHead→训练)
    #   VLA-Touch 6 (DINOv2→Marker→DiT-B base VLA→ActionHead→Interpolant→训练)
    #   AWE 6 (SigLIP视触觉→H-JEPA三层潜空间→zFlow世界引擎→未来决策交叉注意力→ActionHead→训练)
    # 布局: 每行一个模型; 同构模块同列垂直对齐 (视觉编码列/动作生成列/附加列/Action Head列/训练列)
    ("🔬 五模型对比", [
        ("hardware", "📦 metaworld 数据", {"source": "metaworld", "frames": 696, "active": True,
                                           "dims": "39D/4D", "shared": True,
                                           "desc": "♻ 七模型共用: 统一 metaworld 数据集 (peg-v6, state 39D 完整观测, action 4D)"}),
        # ── YOLO 感知前端 (2026-08-06 老倪: YOLO 加所有模型最前端, 自动标注+真机感知) ──
        ("train_gate", "🎯 YOLO 感知开关", {"yolo_enabled": True, "state_dim": 39,
                                          "desc": "state 输入 switch: 开=39D(YOLO检测产出, 含销钉/孔坐标) / 关=3D(仅末端) · 默认开"}),
        ("model", "🎯 YOLO 目标检测", {"model": "yolov8s", "classes": "peg/hole/hand", "shared": True,
                                     "desc": "♻ 感知前端 (真机必需): 相机图像 → YOLO 检测销钉/插孔/末端 2D框 → 3D坐标。仿真=模拟器直给39D(等价完美YOLO)"}),
        ("condition", "📐 2D→3D 解算", {"intrinsics": "camera_K", "method": "depth|hand-eye",
                                      "desc": "♻ 坐标解算: YOLO 2D框中心 + 深度/单目标定 → 目标 3D 坐标 → 拼入 39D state"}),
        # ── ACT 分支 (7) ──
        ("model", "🖼 视觉主干 ResNet18", {"backbone": "resnet18", "pretrained": True,
                                          "desc": "ACT.backbone → layer4 特征图 (B,C,H,W)"}),
        ("model", "🧬 VAE 编码器 CVAE", {"use_vae": True, "latent_dim": 32,
                                        "desc": "ACT.vae_encoder → 潜变量分布 (μ,logσ²)"}),
        ("model", "🔤 Transformer Encoder", {"n_layers": 4, "dim_model": 256, "n_heads": 8,
                                            "desc": "ACT.encoder → 上下文 tokens (latent+state+图像)"}),
        ("model", "🔡 Transformer Decoder", {"n_layers": 4, "chunk_size": 7, "n_heads": 8,
                                            "desc": "ACT.decoder → DETR queries 解码动作块"}),
        ("model", "🎯 Action Head 4D · ACT", {"action_dim": 4, "chunk_size": 7,
                                              "desc": "ACT 专用: 输出 (B,7,4)"}),
        ("condition", "⏳ Temporal Ensemble", {"coeff": 0.01,
                                              "desc": "ACTTemporalEnsembler → 动作块时间平滑 (仅 ACT 用)"}),
        ("system", "🚀 ACT 训练", {"policy": "act", "steps": 1000,
                                  "desc": "双击 → on_train(policy=act) · metaworld 训练"}),
        # ── SmolVLA 纯动作分支 (4, 无 LEW) ──
        ("model", "🧠 SmolVLM2-500M", {"freeze": True,
                                       "smolvlm": "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
                                       "desc": "SmolVLA 视觉语言主干 (冻结, 多模态编码)"}),
        ("model", "🌀 DiT-B 动作解码", {"hidden": 256, "layers": 1, "timesteps": 2,
                                       "desc": "SmolVLA action_model DiT-B → 动作去噪生成 (无世界模型)"}),
        ("model", "🎯 Action Head 4D · SmolVLA", {"action_dim": 4, "chunk_size": 7,
                                                  "desc": "SmolVLA 纯动作版: 输出 (B,7,4) · 无 LEW"}),
        ("system", "🚀 SmolVLA 训练", {"policy": "smolvla", "steps": 1000,
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
        ("system", "🚀 SmolVLA+LEW 训练", {"policy": "smolvla_lew", "steps": 1000,
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
        ("system", "🚀 VLA-Touch 训练", {"policy": "vla_touch", "steps": 1000,
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
        ("system", "🚀 AWE 训练", {"policy": "awe_zflow", "steps": 1000,
                                  "desc": "双击 → on_train(policy=awe_zflow) · 场景原生+zFlow 世界模型"}),
        # ── 蒸馏 MLP 分支 (4, 2026-08-06 老倪: 加入五模型对比) ──
        ("model", "🎯 YOLO 目标检测", {"model": "yolov8s", "classes": "peg/hole/hand",
                                     "desc": "感知前端 (真机必需): 相机图像 → YOLO 检测销钉/插孔 2D框 → 深度/标定 → 3D坐标。仿真里 39D 由模拟器直接给(等价完美检测), 真机必须 YOLO 产出"}),
        ("model", "📥 全观测编码 39D", {"obs_dim": 39, "normalize": True,
                                         "desc": "MLP 输入: 完整 39 维观测 (hand/peg/hole 位置+速度) — 由 YOLO+标定产出 (仿真=模拟器直给)"}),
        ("model", "🔗 全连接层 512·1", {"hidden": 512, "layer": 1,
                                       "desc": "MLP.net.0 → ReLU: 39→512 特征提取"}),
        ("model", "🔗 全连接层 512·2", {"hidden": 512, "layer": 2,
                                       "desc": "MLP.net.3 → ReLU: 512→512"}),
        ("model", "🔗 全连接层 512·3", {"hidden": 512, "layer": 3,
                                       "desc": "MLP.net.6 → ReLU: 512→512"}),
        ("model", "🎯 Action Head 4D · MLP", {"action_dim": 4, "chunk_size": 1,
                                              "desc": "MLP.net.8: 512→4 (3D速度+夹爪) · 无状态无时序"}),
        ("system", "🎓 专家蒸馏训练", {"policy": "expert_mlp", "steps": 300,
                                     "desc": "双击 → distill_expert.py: 300 episodes 官方专家数据 BC 蒸馏 · 抓起18/20 插入11/20"}),
        # ── 官方专家基准分支 (规则状态机, 2026-08-06 老倪: 官方基准入画布) ──
        ("condition", "🧭 位置控制律", {"p_gain": 25, "control": "position",
                                      "desc": "官方 _desired_pos: 接近peg(水平)→下降抓取→移向hole→插入 (位置控制 p=25)"}),
        ("condition", "🤏 夹爪状态机", {"grab_effort": 0.6, "threshold": "0.04m/0.15m",
                                      "desc": "官方 _grab_effort: 末端距peg xy<0.04 且 z差<0.15 → 夹爪闭合 0.6"}),
        ("condition", "🎯 Action Head 4D · 专家", {"action_dim": 4, "chunk_size": 1,
                                                   "desc": "专家动作 = delta_pos(p=25) + grab_effort · 反馈控制非学习"}),
        ("system", "📏 官方专家基准", {"policy": "expert_policy", "success": "19/20 抓起 17/20 插入(85%)",
                                     "desc": "metaworld 官方 SawyerPegInsertionSideV3Policy · 非神经网络, 规则+位置反馈 · 基准线"}),
        # ── 评估 ──
        ("system", "📊 对比评估 Scope", {"shared": True,
                                        "desc": "♻ 共用: 双击 → 五模型 训练速度/精确度/鲁棒性 对比图表"}),
        ("system", "🎥 推理效果对比", {"video": "all", "auto": True,
                                          "desc": "训练完自动触发: 5 模型 rollout 视频同步播放对比"}),
        # ── 5 个视频对比 node (2026-08-05 老倪: 推理效果对比之后, 每模型一个视频) ──
        ("system", "🎥 视频对比 · ACT", {"video": True, "video_policy": "act",
                                          "desc": "ACT rollout 视频 (reports/rollout_act/), 双击播放"}),
        ("system", "🎥 视频对比 · SmolVLA", {"video": True, "video_policy": "smolvla",
                                              "desc": "SmolVLA rollout 视频, 双击播放"}),
        ("system", "🎥 视频对比 · SmolVLA+LEW", {"video": True, "video_policy": "smolvla_lew",
                                                  "desc": "SmolVLA+LEW rollout 视频, 双击播放"}),
        ("system", "🎥 视频对比 · VLA-Touch", {"video": True, "video_policy": "vla_touch",
                                                "desc": "VLA-Touch rollout 视频, 双击播放"}),
        ("system", "🎥 视频对比 · AWE", {"video": True, "video_policy": "awe_zflow",
                                          "desc": "AWE rollout 视频, 双击播放"}),
        # ── 📄 PDF 技术选型报告 (2026-08-05 老倪: 报告含概况/分系统/接口/参数/架构/功能/性价比/优劣势) ──
        ("pdf_report", "📄 PDF 技术选型报告", {"auto": True,
                                             "desc": "双击生成 11 章技术选型 PDF: 实验概况·系统全貌·分系统功能·接口说明·参数对比·架构区别·功能分析·性价比·优势劣势·视频对比·结论"}),
    ], [
        # ACT 路 (9): 数据→ResNet18(+CVAE)→Encoder→Decoder→ActionHead·ACT→Ensemble→训练
        (0, 1, "图像"), (0, 2, "动作"), (0, 3, "状态"), (1, 3, "图像特征"), (2, 3, "潜变量"), (3, 4), (4, 5), (5, 6), (6, 7),
        # SmolVLA 纯动作路 (4)
        (0, 8, "图像+状态"), (8, 9, "多模态embeds"), (9, 10), (10, 11),
        # SmolVLA+LEW 路 (6): 主策略链路 + LeWorldModel 旁路
        (0, 12, "图像+状态"), (12, 13, "多模态embeds"), (13, 15, "动作块"), (15, 16),
        (0, 14, "视频+动作"), (14, 16, "世界预测"),
        # VLA-Touch 路 (9): 数据→DINOv2/Marker/DiT-B→ActionHead→Interpolant→训练
        (0, 17, "图像"), (0, 18, "触觉图"), (0, 19, "状态+指令"),
        (17, 21, "视觉嵌入"), (18, 21, "触觉信号m"), (19, 20, "动作块"), (20, 21, "VLA动作a"),
        (21, 22, "精炼动作"),
        # AWE 路 (8): 数据→SigLIP视触觉编码→三层潜空间→zFlow世界引擎→未来决策交叉注意力→ActionHead→训练
        (0, 23, "图像+力觉"), (0, 24, "状态+力觉"), (23, 24, "视触觉特征"), (24, 25, "三层潜状态"),
        (25, 26, "未来潜状态"), (26, 27, "注入动作"), (27, 28, "动作"),
        # 评估: 五训练 → 对比 Scope
        (7, 29), (11, 29), (16, 29), (22, 29), (28, 29),
        # 推理对比: 五训练 → 推理对比节点
        (7, 30), (11, 30), (16, 30), (22, 30), (28, 30),
        # 视频对比: 五训练 → 各自视频节点 + 推理对比 → 5 视频节点 (2026-08-05 老倪)
        (7, 31, "rollout"), (11, 32, "rollout"), (16, 33, "rollout"),
        (22, 34, "rollout"), (28, 35, "rollout"),
        (30, 31), (30, 32), (30, 33), (30, 34), (30, 35),
        # PDF 报告: 5 视频节点 + Scope + 推理对比 → PDF (数据支撑: 曲线+视频+评估)
        (29, 36, "评估结果"), (30, 36, "推理对比"),
        (31, 36, "ACT视频"), (32, 36, "SmolVLA视频"), (33, 36, "SmolVLA+LEW视频"),
        (34, 36, "VLA-Touch视频"), (35, 36, "AWE视频"),
    ],
    # 🗂 多行展开布局 (每行一个模型; 同构模块同列垂直对齐)
    # 列: 数据 | 视觉编码 | 动作生成 | 附加模块 | 附加模块 | Action Head | (空) | 训练
    [
        ["📦 metaworld 数据", "🖼 视觉主干 ResNet18", "🧬 VAE 编码器 CVAE", "🔤 Transformer Encoder", "🔡 Transformer Decoder", "🎯 Action Head 4D · ACT", "⏳ Temporal Ensemble", "🚀 ACT 训练"],
        ["📦 metaworld 数据", "🧠 SmolVLM2-500M", "🌀 DiT-B 动作解码", "", "", "🎯 Action Head 4D · SmolVLA", "", "🚀 SmolVLA 训练"],
        ["📦 metaworld 数据", "🧠 SmolVLM2-500M · LEW", "🌀 DiT-B 动作解码 · LEW", "🌐 LeWorldModel", "", "🎯 Action Head 4D · SmolVLA+LEW", "", "🚀 SmolVLA+LEW 训练"],
        ["📦 metaworld 数据", "🖼 DINOv2 视觉编码", "🌀 DiT-B base VLA", "📍 Marker 触觉跟踪", "🌉 Interpolant 控制器", "🎯 Action Head · VLA", "", "🚀 VLA-Touch 训练"],
        ["📦 metaworld 数据", "🖐 SigLIP 视触觉编码", "🧠 H-JEPA 三层潜空间", "🌊 zFlow 世界引擎", "🔀 未来决策交叉注意力", "🎯 Action Head · AWE", "", "🚀 AWE 训练"],
        ["📦 metaworld 数据", "🎯 YOLO 目标检测", "📥 全观测编码 39D", "🔗 全连接层 512·1", "🔗 全连接层 512·2", "🎯 Action Head 4D · MLP", "", "🎓 专家蒸馏训练"],
        ["📦 metaworld 数据", "🧭 位置控制律", "🤏 夹爪状态机", "", "", "🎯 Action Head 4D · 专家", "", "📏 官方专家基准"],
        ["📊 对比评估 Scope", "", "", "", "", "", "", "🎥 推理效果对比"],
        # 🎥 视频对比行 (2026-08-05 老倪: 推理效果对比之后 5 个视频节点)
        ["", "🎥 视频对比 · ACT", "🎥 视频对比 · SmolVLA", "🎥 视频对比 · SmolVLA+LEW",
         "🎥 视频对比 · VLA-Touch", "🎥 视频对比 · AWE", "", ""],
        # 📄 PDF 报告行 (2026-08-05 老倪: 最后生成技术选型报告)
        ["", "", "", "", "", "", "", "📄 PDF 技术选型报告"],
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
    #   ⑥🚀 训练 (只训控制器) ⑦📊 对比评估 Scope (共用)
    ("🖐 VLA-Touch 触觉对比", [
        ("hardware", "📦 metaworld 数据", {"source": "metaworld", "frames": 696, "active": True,
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
        ("system", "🚀 VLA-Touch 训练", {"policy": "vla_touch", "steps": 1000,
                                        "desc": "双击 → on_train(policy=vla_touch) · 冻结 VLA 只训 Interpolant (4060 精简)"}),
        ("system", "📊 对比评估 Scope", {"shared": True,
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
        ["📦 metaworld 数据", "🖼 DINOv2 视觉编码", "🌉 Interpolant 控制器", "🚀 VLA-Touch 训练", "📊 对比评估 Scope"],
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
    #   ⑥🚀 训练 (同列) ⑦📊 对比评估 Scope (共用)
    ("🧿 AWE 场景原生对比", [
        ("hardware", "📦 metaworld 数据", {"source": "metaworld", "frames": 696, "active": True,
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
        ("system", "🚀 AWE 训练", {"policy": "awe_zflow", "steps": 1000,
                                  "desc": "双击 → on_train(policy=awe_zflow) · 场景原生+zFlow 世界模型 (4060 精简)"}),
        ("system", "📊 对比评估 Scope", {"shared": True,
                                        "desc": "♻ 共用: 双击 → 多模型 训练速度/精确度/鲁棒性 对比图表"}),
    ], [
        # 官方数据流 (场景原生视触觉: 数据 → 视触觉编码/潜空间/世界引擎/注入/动作头 → 训练 → Scope)
        (0, 1, "图像+力觉"), (0, 2, "状态+力觉"), (1, 2, "视触觉特征"), (2, 3, "三层潜状态"),
        (3, 4, "未来潜状态"), (4, 5, "注入动作"), (5, 6, "动作"), (6, 7, "评估"),
    ],
    # 🗂 单行展开布局 (与 VLA-Touch 同构: 数据 → 视触觉编码 → 世界模型 → ActionHead → 训练 → 评估)
    [
        ["📦 metaworld 数据", "🖐 SigLIP 视触觉编码", "🧠 H-JEPA 三层潜空间", "🌊 zFlow 世界引擎", "🔀 未来决策交叉注意力", "🎯 Action Head · AWE", "🚀 AWE 训练", "📊 对比评估 Scope"],
    ]),
    # 🎥 推理对比 (2026-08-05 老倪: "训练完后继续推理, 对比3个模型的推理效果,
    #   要有视频显示的node, 3个视频display窗口")
    # 数据 → 3 训练 → 3 视频显示 (双击任意视频节点 → 3 窗口同步播放推理效果)
    ("🎥 推理效果对比", [
        ("hardware", "📦 metaworld 数据", {"source": "metaworld", "frames": 696, "active": True,
                                           "dims": "4D/4D", "shared": True,
                                           "desc": "统一 metaworld 数据集 (训练 + 推理共用)"}),
        ("system", "🚀 ACT 训练", {"policy": "act", "steps": 1000,
                                    "desc": "训练 ACT (metaworld, 150步)"}),
        ("system", "🚀 SmolVLA 训练", {"policy": "smolvla", "steps": 1000,
                                        "desc": "训练 SmolVLA 纯动作 (metaworld, 150步)"}),
        ("system", "🚀 SmolVLA+LEW 训练", {"policy": "smolvla_lew", "steps": 1000,
                                            "desc": "训练 SmolVLA+LeWorldModel (metaworld, 150步)"}),
        ("system", "🎥 视频显示 · ACT", {"video": "act", "desc": "双击 → 3 窗口同步播放: ACT 推理效果 (metaworld push-v3 rollout)"}),
        ("system", "🎥 视频显示 · SmolVLA", {"video": "smolvla", "desc": "双击 → 3 窗口同步播放: SmolVLA 推理效果"}),
        ("system", "🎥 视频显示 · SmolVLA+LEW", {"video": "smolvla_lew", "desc": "双击 → 3 窗口同步播放: SmolVLA+LEW 推理效果"}),
    ], [
        (0, 1), (0, 2), (0, 3), (1, 4), (2, 5), (3, 6),
    ],
    [
        ["📦 metaworld 数据", "🚀 ACT 训练", "🎥 视频显示 · ACT"],
        ["", "🚀 SmolVLA 训练", "🎥 视频显示 · SmolVLA"],
        ["", "🚀 SmolVLA+LEW 训练", "🎥 视频显示 · SmolVLA+LEW"],
    ]),
]

# 模块库 (左侧拖拽面板) — 与 web comfyui.html 的模块组一致
LIBRARY = [
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
        {"name": "M01 ACT",     "params": {"chunk_size": 7, "dim_model": 256}},
        {"name": "M02 VLA-T",   "params": {"remote": "4090:50054"}},
        {"name": "M03 GR00T",   "params": {"remote": "4090:50056"}},
        {"name": "M04 LEW",     "params": {"horizon": 16}},
        {"name": "M05 H-JEPA",  "params": {"remote": "4090"}},
    ]),
    # 🧠 ACT 模型·官方子模块 (2026-08-04 老倪: "在左侧模块库里分个类, 将ACT-meta保存到模块库里;
    #  引导从最基础的模块库搭建成最终模型, 全程提示")
    # 对应 modeling_act.py: backbone → vae_encoder → encoder → decoder → action_head → ACTTemporalEnsembler
    ("model", "🧠 ACT 模型·子模块", [
        {"name": "📦 metaworld 数据", "params": {"source": "metaworld", "frames": 696, "active": True,
                                                "dims": "4D/4D", "desc": "states 4D · actions 4D (sawyer 关节)"}},
        {"name": "🖼 视觉主干 ResNet18", "params": {"backbone": "resnet18", "pretrained": True,
                                                   "desc": "官方 ACT.backbone → layer4 特征图 (B,C,H,W)"}},
        {"name": "🧬 VAE 编码器 CVAE", "params": {"use_vae": True, "latent_dim": 32,
                                                 "desc": "官方 ACT.vae_encoder → 潜变量分布 (μ,logσ²)"}},
        {"name": "🔤 Transformer Encoder", "params": {"n_layers": 4, "dim_model": 256, "n_heads": 8,
                                                      "desc": "官方 ACT.encoder → 上下文 tokens"}},
        {"name": "🔡 Transformer Decoder", "params": {"n_layers": 4, "chunk_size": 7, "n_heads": 8,
                                                      "desc": "官方 ACT.decoder → DETR queries 动作块"}},
        {"name": "🎯 Action Head 4D", "params": {"action_dim": 4, "chunk_size": 7,
                                                "desc": "★适配 metaworld: 输出 (B,7,4) · 真机 6D"}},
        {"name": "⏳ Temporal Ensemble", "params": {"coeff": 0.01,
                                                   "desc": "官方 ACTTemporalEnsembler → 动作平滑"}},
        {"name": "🚀 全新训练", "params": {"steps": 1000,
                                          "desc": "双击 → on_train (metaworld 占位集, 全新不续训)"}},
        {"name": "📊 Scope 示波器", "params": {"desc": "双击 → 示波器: 训练 loss 曲线/执行效果"}},
        {"name": "🧠 ACT-Meta 完整模型", "params": {}, "template": "🧠 ACT-Meta 全新训练",
         "desc": "一键搭建完整模型 (8节点8连线) · 或按上方子模块逐步搭建"},
        {"name": "🔬 三模型对比", "params": {}, "template": "🔬 三模型对比",
         "desc": "一键搭建三模型对比 (18节点: 2共用♻ + ACT 7 + SmolVLA纯 4 + SmolVLA+LEW 5, Action Head 各一个) · 点▶运行出对比图表"},
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
        {"name": "🖐 VLA-Touch 完整模型", "params": {}, "template": "🖐 VLA-Touch 触觉对比",
         "desc": "一键搭建 VLA-Touch 对比管道 (8节点9连线: 数据→DINOv2/Marker/DiT-B→ActionHead→Interpolant→训练→Scope)"},
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
        {"name": "🧿 AWE 完整模型", "params": {}, "template": "🧿 AWE 场景原生对比",
         "desc": "一键搭建 AWE 场景原生对比管道 (8节点8连线: 数据→SigLIP视触觉编码→三层潜空间→zFlow世界引擎→注入→ActionHead→训练→Scope)"},
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
         "desc": "五模型对比实验 → 11 章技术选型 PDF (概况/系统全貌/分系统功能/接口/参数/架构/功能/性价比/优劣势/视频对比/结论)"},
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
    ]),
    # 📊 评估分组 (2026-08-06 老倪: Scope 放到左侧 node 库, 直接拖到主窗口)
    ("system", "📊 评估 (3)", [
        {"name": "📊 Scope 示波器", "params": {"scope": True},
         "desc": "双击 → 示波器: 训练 loss 曲线/执行效果 (Simulink Scope 对标)"},
        {"name": "📊 对比评估 Scope", "params": {"shared": True},
         "desc": "♻ 共用: 双击 → 多模型 训练速度/精确度/鲁棒性 对比图表"},
        {"name": "🎥 推理效果对比", "params": {"video": "all", "auto": True},
         "desc": "多模型 metaworld rollout 视频 → 窗口同步播放对比 (推理效果)"},
    ]),
]


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
                _sp.run(["pkill", "-f", "lerobot.scripts.lerobot_train"],
                        capture_output=True, timeout=5)
                _sp.run(["pkill", "-f", "tools.cicd_pipeline"],
                        capture_output=True, timeout=5)
                _sp.run(["pkill", "-9", "-f", "lerobot.scripts.lerobot_train"],
                        capture_output=True, timeout=5)
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
        import glob as _g
        for jf in _g.glob(os.path.join(root, "data", "closed_loop", "*.json")):
            try:
                d = json.load(open(jf, encoding="utf-8"))
                n_pkgs += len(d.get("frames", []))
            except Exception:
                pass
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
        self.setZValue(10)

    def boundingRect(self):
        return QRectF(0, 0, self.w, self.h).adjusted(-12, -12, 12, 12)

    def paint(self, painter, opt, widget=None):
        t = self.node["type"]
        # 🎨 背景行节点 (五模型对比): 整行彩色半透明色带 + 左侧大字模型名
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
        # 标题
        painter.setPen(QColor(pal["title"]))
        f = QFont("Arial", 9, QFont.Bold)
        painter.setFont(f)
        name = self.node["name"]
        if len(name) > 16:
            name = name[:15] + "…"
        painter.drawText(QRectF(12, 4, self.w - 16, 20), Qt.AlignVCenter | Qt.AlignLeft, name)
        # 类型标签 (Switch 显示当前选择: SEL: orin/metaworld) — 浅色主题下用深灰文字
        painter.setPen(QColor(pal["label"]))
        painter.setFont(QFont("Arial", 7))
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
            painter.setBrush(color)
            painter.setPen(QPen(QColor(pal["port_edge"]), 1))
            painter.drawEllipse(QPointF(0, self.h / 2), 5, 5)
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
        ax, ay = a.x() + self.src.w, a.y() + self.src.h / 2