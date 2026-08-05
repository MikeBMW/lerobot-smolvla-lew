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
        ("hardware", "📥 Orin 数据源", {"ip": "192.168.23.10", "fps": 30, "source": "orin",
                                        "desc": "真实产线数据"}),
        ("hardware", "📦 metaworld 数据", {"steps": 150, "source": "metaworld",
                                           "desc": "占位集·管道验证"}),
        ("switch", "🔀 Switch 数据源", {"switch": "orin", "desc": "双击切换 Orin/metaworld"}),
        ("model", "🧠 ACT 训练", {"steps": 150, "chunk_size": 7, "dim_model": 256,
                                  "desc": "双击运行训练 (lerobot_train)"}),
        ("condition", "✅ 模型验证", {"strict": True, "desc": "双击运行验证 (validate_flow)"}),
        ("action", "📦 集成打包", {"target": "ECS", "desc": "双击上传 ECS (cicd_deploy push)"}),
        ("hardware", "🚚 部署 Orin", {"target": "192.168.23.10", "desc": "双击查部署状态"}),
    ], [(0, 2), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6)]),
    ("⚙️ CI/CD 默认流水线", [
        ("hardware", "📥 输入数据", {"ip": "Orin", "fps": 30, "desc": "采集数据源"}),
        ("model", "🧠 ACT 模型", {"chunk_size": 7, "dim_model": 256, "desc": "训练/推理"}),
        ("action", "🎯 输出 action", {"pos": [0.1, 0.2, 0.3], "desc": "末端动作"}),
    ], [(0, 1), (1, 2)]),
    ("📦 取料·100G 闭环", [
        ("hardware", "Orin Nano", {"ip": "192.168.23.10", "fps": 30}),
        ("model", "ACT", {"chunk_size": 7, "dim_model": 256}),
        ("action", "A01 取料·100G", {"pos": [0.1, 0.2, 0.3]}),
        ("condition", "C03 力控达标", {"max_force": 5.0}),
    ], [(0, 1), (1, 2), (2, 3)]),
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
        ("system", "🚀 全新训练", {"steps": 150, "desc": "双击 → on_train (metaworld 占位集, 全新不续训)"}),
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
        ("system", "🚀 ACT 训练", {"policy": "act", "steps": 150,
                                  "desc": "双击 → on_train(policy=act) · metaworld 训练"}),
        # ── SmolVLA 纯动作分支 (4, 无 LEW) ──
        ("model", "🧠 SmolVLM2-500M", {"freeze": True,
                                       "smolvlm": "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
                                       "desc": "SmolVLA 视觉语言主干 (冻结, 多模态编码)"}),
        ("model", "🌀 DiT-B 动作解码", {"hidden": 256, "layers": 1, "timesteps": 2,
                                       "desc": "SmolVLA action_model DiT-B → 动作去噪生成 (无世界模型)"}),
        ("model", "🎯 Action Head 4D · SmolVLA", {"action_dim": 4, "chunk_size": 7,
                                                  "desc": "SmolVLA 纯动作版: 输出 (B,7,4) · 无 LEW"}),
        ("system", "🚀 SmolVLA 训练", {"policy": "smolvla", "steps": 150,
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
        ("system", "🚀 SmolVLA+LEW 训练", {"policy": "smolvla_lew", "steps": 150,
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
    # 🎥 推理对比 (2026-08-05 老倪: "训练完后继续推理, 对比3个模型的推理效果,
    #   要有视频显示的node, 3个视频display窗口")
    # 数据 → 3 训练 → 3 视频显示 (双击任意视频节点 → 3 窗口同步播放推理效果)
    ("🎥 推理效果对比", [
        ("hardware", "📦 metaworld 数据", {"source": "metaworld", "frames": 696, "active": True,
                                           "dims": "4D/4D", "shared": True,
                                           "desc": "统一 metaworld 数据集 (训练 + 推理共用)"}),
        ("system", "🚀 ACT 训练", {"policy": "act", "steps": 150,
                                    "desc": "训练 ACT (metaworld, 150步)"}),
        ("system", "🚀 SmolVLA 训练", {"policy": "smolvla", "steps": 150,
                                        "desc": "训练 SmolVLA 纯动作 (metaworld, 150步)"}),
        ("system", "🚀 SmolVLA+LEW 训练", {"policy": "smolvla_lew", "steps": 150,
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
        {"name": "🚀 全新训练", "params": {"steps": 150,
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
    ("system", "系统 (7)", [
        {"name": "S00 任务调度", "params": {"policy": "fifo"}},
        {"name": "S01 工作流",   "params": {"file": "flow.json"}},
        {"name": "S02 数据闭环", "params": {"mode": "auto"}},
        {"name": "S03 日志",     "params": {"level": "info"}},
        {"name": "S04 W&B监控",  "params": {}},
        {"name": "S05 心跳",     "params": {"interval": 5}},
        {"name": "S06 Switch 数据源", "params": {"switch": "orin"}},
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
]


def gen_id():
    """节点 id: n + 时间戳 + 3位随机 (与 web 同规则)"""
    return "n%d%s" % (int(time.time() * 1000), ''.join(
        random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(3)))


def link_id():
    return "l%d%s" % (int(time.time() * 1000), ''.join(
        random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(2)))


# ════════════════════════════════════════════════════════════════
# 参数面板 (Block Parameters — 对标 Simulink 双击弹窗)
# ════════════════════════════════════════════════════════════════
class BlockParamsDialog(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node = node
        self.setWindowTitle(f"Block Parameters: {node['name']}")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)

        head = QLabel(f"{NODE_TYPES.get(node['type'], {}).get('cn', node['type'])} · {node['name']}")
        head.setStyleSheet("font-size:14px; font-weight:700; color:#1f2328; padding:4px;")
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
            lab.setStyleSheet("color:#888; font-size:11px;")
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
                le = QLineEdit(str(v))
                self._edits[k] = le
            form.addRow(k, self._edits[k])

        lay.addLayout(form)

        # 端口说明
        info = QLabel(f"输入: {len(node.get('inputs', []))} · 输出: {len(node.get('outputs', []))}")
        info.setStyleSheet("color:#57606a; font-size:10px;")
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
        self.setStyleSheet("QDialog { background:#f6f8fa; }")
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
        self._view.setStyleSheet("background:#f6f8fa; border:1px solid #d0d7de; border-radius:8px;")
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
        self._stage_log.setStyleSheet("color:#57606a; font-size:11px; font-family:Consolas; background:#e9edf2; border:1px solid #d0d7de; border-radius:6px; padding:8px;")
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
            QPushButton { background:#e9edf2; color:#24292f; border:1px solid #d0d7de;
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
        self.setStyleSheet("QDialog { background:#f6f8fa; }")
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
        card.setStyleSheet("QFrame#stage%d { background:#e9edf2; border:1px solid #d0d7de; border-radius:10px; }" % sid)
        card.setFixedWidth(250)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        h = QHBoxLayout()
        t = QLabel(f"{num}  {title}")
        t.setStyleSheet("color:#1f2328; font-size:13px; font-weight:700; background:transparent; border:none;")
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
            sp.setStyleSheet("background:#f6f8fa; color:#1f2328; border:1px solid #d0d7de; border-radius:4px; padding:2px 6px;")
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
        bar.setStyleSheet("QFrame { background:#e9edf2; border:1px solid #d0d7de; border-radius:8px; }")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(14)
        self.lbl_data = QLabel("📥 数据: —")
        self.lbl_model = QLabel("🧠 模型: —")
        self.lbl_url = QLabel("🔗 URL: —")
        self.lbl_orin = QLabel("🤖 Orin: —")
        self.lbl_infer = QLabel("⚡ 推理: —")
        for lb in (self.lbl_data, self.lbl_model, self.lbl_url, self.lbl_orin, self.lbl_infer):
            lb.setStyleSheet("color:#24292f; font-size:11px; font-family:Consolas; background:transparent; border:none;")
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
            b.setStyleSheet("QPushButton { background:#e9edf2; color:#57606a; border:1px solid #d0d7de; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:600; }"
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
                b.setStyleSheet("QPushButton { background:#e9edf2; color:#57606a; border:1px solid #d0d7de; border-radius:6px; padding:6px 10px; font-size:11px; font-weight:600; }"
                                "QPushButton:hover { border-color:#00d4aa; color:#00d4aa; }")
        for sid, (card, st_lbl, info) in self._cards.items():
            sid_st = stages.get(str(sid), {}).get("state", "pending")
            st_lbl.setText(self._STATUS_ICON.get(sid_st, "○"))
            st_lbl.setStyleSheet(f"color:{self._STATUS_COLOR.get(sid_st,'#57606a')}; font-size:13px; font-weight:700; background:transparent; border:none;")
            card.setStyleSheet("QFrame#stage%d { background:#e9edf2; border:2px solid %s; border-radius:10px; }"
                               % (sid, self._STATUS_COLOR.get(sid_st, "#d0d7de")))
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
        worker.finished.connect(lambda: setattr(self, "_worker", None))
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
        worker.finished.connect(lambda: setattr(self, "_remote_worker", None))
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
        self.h = DH
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
        bx, by = b.x(), b.y() + self.dst.h / 2
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
        if not active:
            color = QColor(pal["inactive"])
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
        # 箭头 (指向输入)
        b = self.dst.scenePos()
        bx, by = b.x(), b.y() + self.dst.h / 2
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
        # NoDrag: 让 ItemIsMovable 的节点可自由拖动 (RubberBandDrag 会拦截节点移动)
        self.setDragMode(QGraphicsView.NoDrag)
        # 空格键临时平移 (Simulink 习惯: 按住空格拖动画布)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self._drag_from = None       # 连线起点 (SimNodeItem)
        self._tmp_line = None        # 临时连线
        self._drag_node = None       # 手动拖动的节点 (只移动它, 绕开scene多选)
        self._drag_offset = QPointF()  # 按下点与节点原点的偏移
        self._panning = False
        self._pan_start = None
        self._scale = 1.0

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
                if not (e.modifiers() & Qt.ControlModifier):
                    for it in self._scene.selectedItems():
                        if it is not item:
                            it.setSelected(False)
                    item.setSelected(True)
                self._drag_node = item
                self._drag_offset = p - rp
                return
        super().mousePressEvent(e)
        # 点击空白处 (非Ctrl): 清除所有选中
        if e.button() == Qt.LeftButton and not (e.modifiers() & Qt.ControlModifier):
            item = self.itemAt(e.pos())
            if not isinstance(item, (SimNodeItem, SimLinkItem)):
                self._scene.clearSelection()

    def _show_node_menu(self, item, view_pos):
        """右键节点菜单 (viewport 全局坐标, WSLg 可靠; 深色QSS防黑字)"""
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background:#ffffff; color:#1f2328; border:1px solid #b6bdc7; border-radius:6px; }"
            "QMenu::item { padding:6px 28px 6px 14px; color:#1f2328; font-size:12px; }"
            "QMenu::item:selected { background:#1f6feb; color:#ffffff; }")
        a_logic = menu.addAction("📖 查看/编辑节点逻辑")
        a_param = menu.addAction("⚙️ 节点参数")
        a_run = menu.addAction("▶ 运行节点")
        chosen = menu.exec_(self.viewport().mapToGlobal(view_pos))
        if chosen == a_logic:
            self.module.on_show_node_logic(item.node)
        elif chosen == a_param:
            self.module.on_node_params(item.node)
        elif chosen == a_run:
            self.module.on_node_activated(item.node)

    def mouseMoveEvent(self, e):
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
            self._drag_node = None
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
    def __init__(self, module):
        super().__init__()
        self.module = module
        self.setFixedWidth(220)
        self.setStyleSheet("background:#f6f8fa; border-right:1px solid #d0d7de;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        title = QLabel("📚 模块库")
        title.setStyleSheet("color:#1f2328; font-size:13px; font-weight:700; padding:4px;")
        lay.addWidget(title)

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

        hint = QLabel("点击添加 · 双击改参 · 输出→输入连线\n点线删除 · Ctrl+滚轮缩放 · 顶部工作流过滤")
        hint.setStyleSheet("color:#57606a; font-size:9px; padding:4px;")
        lay.addWidget(hint)

    def _rebuild(self):
        """重建模块库列表 (按工作流过滤)"""
        # 清空
        while self.v.count():
            item = self.v.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._lib_btns = {}  # 模块名 → 按钮 (引导高亮用)
        for ntype, gname, items in LIBRARY:
            # 工作流过滤: 按节点类型匹配
            wf_of = {t: wf for wf, t in WORKFLOW_TYPES.items()}
            if self._current_wf and wf_of.get(ntype) != self._current_wf:
                continue
            lab = QLabel(f"{gname}")
            lab.setStyleSheet(f"color:{COLORS[ntype]}; font-size:11px; font-weight:700; padding:6px 2px 2px;")
            self.v.addWidget(lab)
            for it in items:
                btn = QToolButton()
                btn.setText(f"⬡  {it['name']}")
                btn.setStyleSheet(f"""
                    QToolButton {{ background:#e9edf2; color:#24292f; border:1px solid #d0d7de;
                    border-radius:4px; padding:4px 8px; font-size:11px; text-align:left; }}
                    QToolButton:hover {{ border-color:{COLORS[ntype]}; color:#1f2328; }}
                """)
                if it.get("template"):
                    # 完整模型条目: 点击加载模板
                    btn.clicked.connect(lambda _, tpl=it["template"]: self.module.load_reference_app_by_name(tpl))
                else:
                    btn.clicked.connect(lambda _, t=ntype, nm=it["name"], ps=it["params"]:
                                        self.module.add_node_at_center(t, nm, ps))
                self._lib_btns[it["name"]] = btn
                self.v.addWidget(btn)
        self.v.addStretch()

    def set_filter(self, wf_key):
        """按工作流过滤模块库 (None=全部)"""
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
                    w.wait(3000)  # 最多等 3s, 避免退出时线程未结束
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
        hero = QFrame()
        hero.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #f6f8fa, stop:0.6 #0f1a24, stop:1 #f6f8fa); border-bottom:1px solid #d0d7de;")
        hero.setFixedHeight(64)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(16, 8, 16, 8)
        hl.setSpacing(14)
        hero_title = QLabel("Z-MAX 具身智能 · Simulink 模式")
        hero_title.setStyleSheet("color:#1f2328; font-size:19px; font-weight:800; background:transparent; border:none;")
        hl.addWidget(hero_title)
        hero_sub = QLabel("使用 XSpace Studio 实现产线机器人的感知、规划与控制 · 模块库拖拽 · 连线仿真 · 数据闭环")
        hero_sub.setStyleSheet("color:#57606a; font-size:11px; background:transparent; border:none;")
        hl.addWidget(hero_sub)
        hl.addStretch()
        ver = QLabel("v1.0 · zmax-simulink")
        ver.setStyleSheet("color:#00d4aa; font-size:10px; font-family:Consolas; background:transparent; border:none;")
        hl.addWidget(ver)
        outer.addWidget(hero)

        # ── 工作流导航条 (对标 MathWorks 6 大功能分区) ──
        wf = QFrame()
        wf.setStyleSheet("background:#eef1f5; border-bottom:1px solid #d0d7de;")
        wf.setFixedHeight(40)
        wfl = QHBoxLayout(wf)
        wfl.setContentsMargins(10, 4, 10, 4)
        wfl.setSpacing(4)
        self._wf_btns = {}
        for key, label in [("data", "① 访问·标注数据"), ("scene", "② 仿真场景"),
                           ("plan", "③ 规划·控制"), ("percept", "④ 感知算法"),
                           ("deploy", "⑤ 部署"), ("test", "⑥ 集成·测试")]:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setStyleSheet("""
                QPushButton { background:transparent; color:#57606a; border:1px solid transparent;
                border-radius:5px; padding:4px 12px; font-size:11px; font-weight:600; }
                QPushButton:hover { color:#1f2328; background:#e9edf2; }
                QPushButton:checked { color:#00d4aa; background:#00d4aa1a; border-color:#00d4aa44; }
            """)
            b.clicked.connect(lambda _, k=key: self._filter_library(k))
            self._wf_btns[key] = b
            wfl.addWidget(b)
        wfl.addStretch()
        outer.addWidget(wf)

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
        self.btn_scope = mk_btn("🖥 Scope", "示波器: 新老模型动作曲线对比", self.show_scope, "#d4a800")
        tl.addWidget(self.btn_run)
        tl.addWidget(self.btn_step)
        tl.addWidget(self.btn_stop)
        tl.addSpacing(8)
        tl.addWidget(self.btn_tutorial)
        tl.addWidget(self.btn_scope)
        self.btn_float = mk_btn("⛶ 浮动", "画布独立成浮动窗口, 鼠标拖边/最大化扩大视野 (关闭自动还原)", self.toggle_float_canvas, "#58a6ff")
        tl.addWidget(self.btn_float)
        self.btn_win = mk_btn("🪟 画布窗口", "恢复画布子窗口 (MDI: 最小化/关闭后点此找回)", self.show_canvas_win, "#57606a")
        tl.addWidget(self.btn_win)

        tl.addSpacing(16)
        tl.addWidget(QLabel("时间"))
        self.sp_t_end = QDoubleSpinBox(); self.sp_t_end.setRange(0.1, 3600)
        self.sp_t_end.setValue(self._sim_t_end); self.sp_t_end.setSuffix(" s")
        self.sp_t_end.setMaximumWidth(70)
        self.sp_t_end.setStyleSheet("background:#e9edf2; color:#1f2328; border:1px solid #d0d7de; border-radius:4px; padding:2px 6px;")
        tl.addWidget(self.sp_t_end)
        tl.addWidget(QLabel("dt"))
        self.sp_dt = QDoubleSpinBox(); self.sp_dt.setRange(0.001, 1.0)
        self.sp_dt.setValue(self._sim_dt); self.sp_dt.setDecimals(3)
        self.sp_dt.setMaximumWidth(62)
        self.sp_dt.setStyleSheet("background:#e9edf2; color:#1f2328; border:1px solid #d0d7de; border-radius:4px; padding:2px 6px;")
        tl.addWidget(self.sp_dt)

        tl.addStretch()
        self.lbl_clock = QLabel("t = 0.00s")
        self.lbl_clock.setStyleSheet("color:#00d4aa; font-size:13px; font-weight:700; font-family:Consolas;")
        tl.addWidget(self.lbl_clock)

        btn_save = mk_btn("💾 另存为", "保存当前画布 (含节点位置/连线) 为 JSON 文件, 可下次加载回来", self.export_flow, "#3fb950")
        btn_load = mk_btn("📂 加载", "从 JSON 文件加载工作流 (恢复节点位置与连线)", self.import_flow, "#58a6ff")
        self.btn_save = btn_save
        self.btn_load = btn_load
        tl.addWidget(btn_save)
        tl.addWidget(btn_load)

        # ── 真实操作按钮 (CI/CD 闭环: 验证→训练→集成→部署) — 独立第二行, 完整显示 ──
        tb2 = QFrame()
        tb2.setStyleSheet("background:#f6f8fa; border-bottom:1px solid #d0d7de;")
        tb2.setFixedHeight(44)
        tl2 = QHBoxLayout(tb2)
        tl2.setContentsMargins(10, 4, 10, 4)
        tl2.setSpacing(8)
        # 全链路入口 (最醒目, 打开 CI/CD 全景面板)
        # 数据闭环控制台 = 唯一 CICD 入口 (6环节流水线 + 三阶段训练合并)
        self.btn_pipeline = mk_btn("🎯 数据闭环控制台", "数据闭环 CICD 控制台: 6环节流水线 + 三阶段训练 + 闭环状态 (自动流转, steps可配)",
                                   self.open_pipeline_panel, "#00d4aa")
        tl2.addWidget(self.btn_pipeline)
        # 🧠 ACT-Meta 引导: 一键打开 metaworld 全新训练模型 (2026-08-04 老倪)
        self.btn_actmeta = mk_btn("🧠 ACT-Meta 引导", "打开 metaworld 数据全新训练 ACT 模型: 7个子模块搭建, Action Head 适配 4D 输出, 双击「🚀 全新训练」即可开始 (嵌入式窗口引导)",
                                  self.open_act_meta, "#58a6ff")
        tl2.addWidget(self.btn_actmeta)
        # 🔬 三模型对比: 与⚔️对比同族 (2026-08-05 老倪) — 放第二行, 第一行按钮太多会被挤掉
        self.btn_compare3 = mk_btn("🔬 三模型对比", "ACT vs SmolVLA(纯动作) vs SmolVLA+LeWorldModel 三模型对比: 无LEW/有LEW 同骨干差异直观可见 · ▶运行出对比图表", self.open_compare3, "#d4a800")
        tl2.addWidget(self.btn_compare3)
        # 🎛 顶层总系统 (2026-08-05 老倪: "顶层总系统没有啊" — 参考应用滚动条里不易发现, 加显眼工具栏入口)
        self.btn_topsys = mk_btn("🎛 总系统", "顶层系统: 数据→总系统块→评估Scope · 双击总系统块展开 ACT/SmolVLA/SmolVLA+LEW 三条训练线 (Simulink Subsystem)", self.open_topsys, "#a371f7")
        tl2.addWidget(self.btn_topsys)
        # 🎛 子系统返回 (2026-08-05 老倪: 顶层总系统双击展开内部三线, 返回恢复顶层)
        self.btn_back = mk_btn("⬅ 返回总系统", "从子系统内部返回上一层 (Simulink Subsystem 语义)", self.back_to_subsystem, "#3fb950")
        self.btn_back.setVisible(False)
        tl2.addWidget(self.btn_back)
        # 💾 保存模型 (2026-08-05 老倪: "当前训练的模型可以保存, 下次直接应用")
        self.btn_save_model = mk_btn("💾 保存模型", "把当前已训练的模型 checkpoint 固化为「已保存模型」, 推理服务下次可直接选择加载 (复制到 models/saved/)", self.save_trained_model, "#3fb950")
        tl2.addWidget(self.btn_save_model)
        # 🎥 录屏 (2026-08-05 老倪: 整个训练→推理→部署过程录制成视频, 可加速, 总长<1分钟, 含终端输出+模型结果)
        self.btn_record = mk_btn("🔴 录制", "开始录屏: 定时截取本窗口 (画布+终端输出+模型结果), 训练→推理→部署全程记录", self.start_recording, "#ff4444")
        tl2.addWidget(self.btn_record)
        self.btn_stop_rec = mk_btn("⏹ 停止", "停止录屏: ffmpeg 合成 MP4 (2fps采集, 可加速, 总长<1分钟)", self.stop_recording, "#f0883e")
        self.btn_stop_rec.setEnabled(False)
        tl2.addWidget(self.btn_stop_rec)
        tl2.addStretch()
        lbl_op = QLabel("双击节点即运行 · Switch 选数据源 · 3阶段自动流转")
        lbl_op.setStyleSheet("color:#57606a; font-size:10px; background:transparent; border:none;")
        tl2.addWidget(lbl_op)

        outer.addWidget(tb)

        # CI/CD 操作行 (第二行工具栏, 在仿真工具栏之下)
        outer.addWidget(tb2)

        # 参考应用条 (对标 MathWorks 参考应用列表) — 横向滚动, 模板多不挤压 (2026-08-05 修复:
        # 9 个模板单行 QHBoxLayout 后面的总系统/三模型被挤没, 改 QScrollArea 横向滚动)
        ra = QFrame()
        ra.setStyleSheet("background:#eef1f5; border-bottom:1px solid #d0d7de;")
        ra.setFixedHeight(44)
        ral = QHBoxLayout(ra)
        ral.setContentsMargins(10, 4, 10, 4)
        ral.setSpacing(6)
        ra_lab = QLabel("🗂 参考应用:")
        ra_lab.setStyleSheet("color:#57606a; font-size:11px; font-weight:600; background:transparent; border:none;")
        ral.addWidget(ra_lab)
        ra_scroll = QScrollArea()
        ra_scroll.setWidgetResizable(True)
        ra_scroll.setFixedHeight(32)
        ra_scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }"
                                "QScrollArea > QWidget > QWidget { background:transparent; }"
                                "QScrollBar:horizontal { height:6px; background:#eef1f5; }"
                                "QScrollBar::handle:horizontal { background:#b6bdc7; border-radius:3px; }")
        ra_inner = QWidget()
        ra_inner_lay = QHBoxLayout(ra_inner)
        ra_inner_lay.setContentsMargins(0, 0, 0, 0)
        ra_inner_lay.setSpacing(6)
        self._ref_btns = {}
        for item in REFERENCE_APPS:
            name = item[0]
            nodes, links = item[1], item[2]
            layout = item[3] if len(item) > 3 else None
            b = QPushButton(name)
            b.setStyleSheet("""
                QPushButton { background:#e9edf2; color:#24292f; border:1px solid #d0d7de;
                border-radius:4px; padding:3px 10px; font-size:10px; }
                QPushButton:hover { border-color:#00d4aa; color:#00d4aa; }
            """)
            b.clicked.connect(lambda _, nm=name, nd=nodes, lk=links, lo=layout: self.load_reference_app(nm, nd, lk, layout=lo))
            self._ref_btns[name] = b
            ra_inner_lay.addWidget(b)
        ra_inner_lay.addStretch()
        ra_scroll.setWidget(ra_inner)
        ral.addWidget(ra_scroll, 1)
        outer.addWidget(ra)

        # ── 📡 实时采集状态条 (轮询 ECS relay: Orin/MAC 采集数据实时可见) ──
        acq = QFrame()
        acq.setStyleSheet("background:#eef1f5; border-bottom:1px solid #d0d7de;")
        acq.setFixedHeight(34)
        acl = QHBoxLayout(acq)
        acl.setContentsMargins(12, 4, 12, 4)
        acl.setSpacing(10)
        acq_lab = QLabel("📡 实时采集")
        acq_lab.setStyleSheet("color:#58a6ff; font-size:11px; font-weight:700; background:transparent; border:none;")
        acl.addWidget(acq_lab)
        self.lbl_acq_state = QLabel("⏳ 查询 ECS 中转…")
        self.lbl_acq_state.setStyleSheet("color:#57606a; font-size:11px; font-family:Consolas; background:transparent; border:none;")
        acl.addWidget(self.lbl_acq_state)
        acl.addStretch()
        self.lbl_acq_pkgs = QLabel("数据包: 0")
        self.lbl_acq_pkgs.setStyleSheet("color:#57606a; font-size:11px; font-family:Consolas; background:transparent; border:none;")
        acl.addWidget(self.lbl_acq_pkgs)
        self.lbl_acq_latest = QLabel("最新: —")
        self.lbl_acq_latest.setStyleSheet("color:#00d4aa; font-size:11px; font-family:Consolas; background:transparent; border:none;")
        acl.addWidget(self.lbl_acq_latest)
        outer.addWidget(acq)
        # 轮询定时器 (每 5s, 轻量)
        self._acq_timer = QTimer(self)
        self._theme = _CUR_THEME  # 🎨 当前风格 (light/dark)
        self._acq_timer.timeout.connect(self._poll_acquisition)
        self._acq_timer.start(5000)

        # 主体: 库 + MDI 画布子窗口 (2026-08-05 老倪: 对标 MATLAB Simulink / CANoe —
        # 主要操作窗口首次打开嵌在主窗口内部, 子窗口带 最小化/最大化/关闭)
        split = QSplitter(Qt.Horizontal)
        self._main_split = split
        self.canvas = SimCanvas(self)
        self.canvas.flow_changed.connect(lambda: self._sync())
        self.canvas.log.connect(self._log)
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
        self._canvas_win.setWindowTitle("🖥 画布 · Simulink 模型 (可最小化/最大化/关闭)")
        self._canvas_win.resize(920, 620)
        self._canvas_win.setAttribute(Qt.WA_DeleteOnClose, False)  # 关闭=隐藏, 可恢复
        self._mdi.addSubWindow(self._canvas_win)
        # 首次打开铺满 MDI 操作区 (老倪: 窗口应充满嵌入的原来空间, 不露背景; 可还原/缩放)
        self._canvas_win.showMaximized()
        self.library = LibraryPanel(self)
        split.addWidget(self.library)
        split.addWidget(self._mdi)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
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

        # 底部日志 (对标 Simulink 诊断)
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
        pairs = list(seen.items()) + [("#dbe9ff", "#1a2230")]  # 按钮 hover
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
    def _filter_library(self, wf_key):
        for k, b in self._wf_btns.items():
            b.setChecked(k == wf_key)
        self.library.set_filter(wf_key)
        self._log(f"🗂 工作流: {dict(data='① 访问·标注', scene='② 仿真场景', plan='③ 规划·控制', percept='④ 感知', deploy='⑤ 部署', test='⑥ 集成·测试').get(wf_key, wf_key)} · 模块库已过滤")

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

    def load_reference_app(self, name, node_specs, link_specs, layout=None):
        if self.nodes:
            if not self._qmsg_yes("加载参考应用", f"加载「{name}」将清空当前画布，继续？"):
                return
        self.clear()
        # ⚠️ 批量加载性能 (2026-08-05 实测): add_node 每次 _sync() 会 POST web 同步,
        # 13 节点模板 = 13 次串行网络请求 (web comfy mock 常挂 → 每个超时数秒) → 按钮卡死。
        # 加载期间禁用 _sync, 末尾统一同步一次。
        old_sync = self._sync
        self._sync = lambda: None
        try:
            ids = []
            base_x, base_y = 120, 80
            # 🗂 多行展开布局 (2026-08-05): layout 是 [[节点名...]每行] 网格 —
            # 行 = 模型分支, 列 = 功能角色, 同名节点多行出现→垂直对齐(如 Action Head 共第5列);
            # 空串 = 占位跳过。无 layout → 传统单行横排 (兼容旧模板)。
            if layout:
                pos = {}
                for r, row in enumerate(layout):
                    for c, nm in enumerate(row):
                        if not nm:
                            continue  # 占位空串, 跳过
                        pos.setdefault(nm, []).append((base_x + c * 260, base_y + r * 230))
                used = set()
                for i, (ntype, nm, params) in enumerate(node_specs):
                    cands = pos.get(nm, [])
                    xy = next((p for p in cands if p not in used), None)
                    if xy is None:
                        xy = (base_x + i * 260, base_y)  # 兜底单行
                    used.add(xy)
                    n = self.add_node(ntype, nm, xy[0], xy[1], params)
                    ids.append(n["id"])
            else:
                for i, (ntype, nm, params) in enumerate(node_specs):
                    n = self.add_node(ntype, nm, base_x + i * 260, base_y, params)
                    ids.append(n["id"])
            for fi, ti, *label in link_specs:
                if fi < len(ids) and ti < len(ids):
                    self.add_link(self._items[ids[fi]], self._items[ids[ti]],
                                  label=label[0] if label else None)
        finally:
            self._sync = old_sync
        self._sync()  # 一次同步到位
        self.canvas._scene.update()
        self._log(f"🗂 已加载参考应用: {name} ({len(ids)}节点 {len(link_specs)}连线) · 双击节点改参数")
        self._tutorial_on_action("ref")

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
                     "system": "◉", "hardware": "▣", "switch": "🔀"}[ntype],
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
        self._sync()

    def delete_link(self, link):
        if link in self.links:
            self.links.remove(link)
            self._draw_links()
            self._log("🗑 连线已删除")
            self._sync()

    def delete_selected(self):
        sel = [it for it in self._items.values() if it.isSelected()]
        if not sel:
            return
        ids = {it.node["id"] for it in sel}
        for it in sel:
            self.canvas._scene.removeItem(it)
        self.nodes = [n for n in self.nodes if n["id"] not in ids]
        self.links = [l for l in self.links if l["f"] not in ids and l["t"] not in ids]
        self._items = {k: v for k, v in self._items.items() if k not in ids}
        self._draw_links()
        self._log(f"🗑 删除 {len(sel)} 个节点")
        self._sync()

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
        for lk in self.links:
            s, d = self._items.get(lk["f"]), self._items.get(lk["t"])
            if s and d:
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
                    self._show_bubble(gp, "👆 双击金色高亮「📊 对比评估 Scope」→ 查看两模型对比图表\n"
                                         "(先点「▶ 运行」训练 ACT + SmolVLA)", ms=6000)
        except Exception:
            pass

    def open_compare3(self):
        """🔬 三模型对比: ACT vs SmolVLA(纯动作) vs SmolVLA+LeWorldModel
        加载「🔬 三模型对比」模板 — LeWorldModel 串行在 DiT-B 之后 (官方 forward 顺序),
        SmolVLA 纯动作 = freeze_smolvlm:true (LEW 强制关), SmolVLA+LEW = freeze:false + enable_lew:true
        """
        if self.nodes:
            if not self._qmsg_yes("🔬 三模型对比",
                                  "将清空当前画布, 加载 三模型对比?\n\n"
                                  "模块划分: ♻共用2 (metaworld数据 / 对比评估Scope)\n"
                                  "          ACT 分支 7 + SmolVLA 纯动作 4 + SmolVLA+LEW 5\n"
                                  "🔬 三模型: ACT / SmolVLA(无LEW) / SmolVLA+LeWorldModel 串行\n"
                                  "▶ 点「▶ 运行」→ 依次训练三模型 → 双击 Scope 看对比图表"):
                return
        self.clear()
        if not self.load_reference_app_by_name("🔬 三模型对比"):
            self._qmsg_info("🔬 三模型对比", "模板加载失败")
            return
        self._log("════ 🔬 三模型对比 (统一 metaworld 数据集) ════")
        self._log("📦 模块划分: ♻共用 2 (metaworld数据 / 对比评估Scope) + ACT 7 + SmolVLA纯 4 + SmolVLA+LEW 5")
        self._log("🔬 三模型: ① ACT ② SmolVLA 纯动作 (freeze_smolvlm:true → LEW 强制关) ③ SmolVLA+LeWorldModel 串行 (freeze:false + enable_lew:true)")
        self._log("🌐 LeWorldModel 串行在 DiT-B 之后 — 官方 forward 顺序: SmolVLM2 编码 → DiT 动作 → LEW 世界预测")
        self._log("▶ 点「▶ 运行」→ 依次训练三模型, 各 300 步 metaworld")
        self._log("📈 训练完双击「📊 对比评估 Scope」→ 三模型对比: 训练速度 · 精确度(MSE/成功率) · 鲁棒性 · 延迟")
        QTimer.singleShot(300, lambda: self._compare_load_hint())

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
        if not self.load_reference_app_by_name("🎛 总系统·三模型对比"):
            self._qmsg_info("🎛 顶层总系统", "模板加载失败")
            return
        self._log("════ 🎛 顶层总系统 (Simulink Subsystem) ════")
        self._log("顶层: 📦metaworld数据 → 🔬总系统块 → 📊对比评估Scope")
        self._log("双击「🔬 总系统·三模型对比」块 → 展开内部三条训练线 (ACT / SmolVLA / SmolVLA+LEW)")
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
                    self._show_bubble(gp, "👆 双击金色高亮「🔬 总系统·三模型对比」\n"
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
        self._canvas_win.setWindowTitle("🖥 画布 · Simulink 模型 (可最小化/最大化/关闭)")
        self._canvas_win.resize(920, 620)
        self._canvas_win.setAttribute(Qt.WA_DeleteOnClose, False)
        self._mdi.addSubWindow(self._canvas_win)
        self._canvas_win.show()
        self._mdi.setActiveSubWindow(self._canvas_win)
        self._log("⛶ 画布已还原回主窗口")
        self._float_dlg = None

    def show_canvas_win(self):
        """🪟 恢复画布子窗口: MDI 最小化/关闭(隐藏)后找回"""
        mdi = getattr(self, "_mdi", None)
        win = getattr(self, "_canvas_win", None)
        if mdi is None or win is None:
            return
        if win.isMinimized():
            win.showNormal()
        elif win.isHidden():
            win.show()
        mdi.setActiveSubWindow(win)
        self._log("🪟 画布子窗口已恢复")

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
        # 加载子系统内部模板 (三模型对比: 三条并行训练线)
        if not self.load_reference_app_by_name(sub_name):
            self._subsystem_stack.pop()
            self._qmsg_info("🎛 子系统", f"找不到子系统模板: {sub_name}")
            return
        self._subsystem_active = True
        self._update_back_btn()
        self._log(f"🎛 已进入子系统「{sub_name}」— ACT / SmolVLA / SmolVLA+LEW 三条并行训练线")
        self._log("   ▶ 点「▶ 运行」依次训练三模型 → 双击「📊 对比评估 Scope」出对比图表")
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
        self._rec_timer.start(500)  # 2fps 采集 → 2x 加速
        # 🎬 录制中视觉指示: 按钮变红字 + 呼吸闪烁 (500ms 交替样式)
        self.btn_record.setText("⏺ 录制中…")
        self.btn_record.setEnabled(True)   # 保持可点? 不, 录制中禁点(防重复), 用样式表强调
        self.btn_record.setEnabled(False)
        self._rec_blink = QTimer(self)
        self._rec_blink.timeout.connect(self._rec_blink_tick)
        self._rec_blink.start(500)
        self._rec_blink_on = True
        self._rec_style_normal = self.btn_record.styleSheet()
        self.btn_stop_rec.setEnabled(True)
        self._log(f"🔴 录屏开始 → {os.path.relpath(self._rec_dir, root)} (2fps 采集, 停止后合成 MP4)")

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
        PNG 压缩大图慢 → UI 卡顿停止按钮无响应; JPEG q85 快 ~10x)"""
        try:
            pm = self.grab()
            if not pm.isNull():
                pm.save(os.path.join(self._rec_dir, f"frame_{self._rec_idx:04d}.jpg"), "JPG", 85)
                self._rec_idx += 1
                # 状态提示: 每 30 帧 (15s) 更新一次
                if self._rec_idx % 30 == 0:
                    self._log(f"⏺ 录屏中: {self._rec_idx} 帧 · {time.time() - self._rec_start:.0f}s")
        except Exception:
            pass

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
        fps = 2.0
        out_mp4 = os.path.join(rec_dir, "screen_rec.mp4")
        self._log(f"⏳ 正在合成视频 ({n} 帧, ffmpeg 后台)…")
        import threading
        t = threading.Thread(target=self._ffmpeg_compose, args=(rec_dir, out_mp4, fps, n, dur), daemon=True)
        t.start()

    def _ffmpeg_compose(self, rec_dir, out_mp4, fps, n, dur):
        """(后台线程) ffmpeg 合成 MP4 — 帧是 JPG 序列, 输出 2fps 视频 (总长 = 录制/2)"""
        import subprocess
        cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i",
               os.path.join(rec_dir, "frame_%04d.jpg"), "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-r", str(fps), out_mp4]
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
        dlg.exec_()

    def show_scope(self):
        """打开 Scope 示波器对比 (新老模型动作曲线)"""
        try:
            from simulink_scope import ScopeCompareDialog
        except ImportError:
            self._qmsg_info("Scope", "缺少 simulink_scope.py 模块")
            return
        dlg = ScopeCompareDialog(self)
        dlg.exec_()

    def start_sim(self):
        if not self.nodes:
            self._log("⚠️ 画布为空 — 点击上方「🗂 参考应用」一键加载模板, 或从左侧模块库添加节点")
            if self._tutorial_active:
                self._tutorial_hint_mismatch("run", "pipeline")
            return
        # 🆕 ▶ 运行 = 画布真实全流程: 画布上有环节节点(采集/训练/验证/集成/部署/推理)
        #   就按拓扑顺序真实执行 (老倪: "运行按钮应该启动整个流程"), 没有环节节点才走拓扑仿真
        stages = self._canvas_stage_nodes()
        if stages:
            self._start_canvas_flow(stages)
            return
        self._sim_t = 0.0
        self._sim_dt = self.sp_dt.value()
        self._sim_t_end = self.sp_t_end.value()
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
        if w is not None and w.isRunning():
            self._log("⏳ 上一个任务还在跑, 请稍候…")
            return
        # 训练节点耗时升序 (act 最快 → smolvla → smolvla_lew 最慢), 其余环节保持拓扑序
        _speed = {"act": 0, "smolvla": 1, "smolvla_lew": 2}
        stages = sorted(stages, key=lambda s: _speed.get(s[0].get("params", {}).get("policy", ""), 9))
        names = " → ".join(f"「{n['name']}」" for n, _, _ in stages)
        self._log(f"▶ 真实全流程启动 ({len(stages)} 环节): {names}")
        for n in self.nodes:
            n["status"] = "idle"
            it = self._items.get(n["id"])
            if it:
                it.update()
        self.canvas._scene.update()
        self._flow_queue = [
            (lambda n=n, m=m, k=k: self._run_node_stage(n, getattr(self, m, None), k))
            for n, m, k in stages]
        self._flow_next()
        self._tutorial_on_action("run")

    def step_sim(self):
        if not self.nodes:
            self._log("⚠️ 画布为空")
            return
        self._sim_t += self._sim_dt
        self._exec_topological()
        self.lbl_clock.setText(f"t = {self._sim_t:.2f}s")
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
        self.lbl_clock.setText(f"t = {self._sim_t:.2f}s")

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

    def stop_sim(self):
        self._sim_running = False
        self._timer.stop()
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
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
        self.canvas._scene.clear()
        self.nodes = []
        self.links = []
        self._items = {}
        self._link_items = []

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

    # ── 📡 实时采集轮询 (后台线程, 不卡 UI) ──
    def _poll_acquisition(self):
        """每 5s 轮询 ECS relay /status + /packages, 更新采集状态条"""
        if getattr(self, "_acq_worker", None) and self._acq_worker.isRunning():
            return  # 上次还在查, 跳过

        def _work():
            import requests as _rq
            try:
                r = _rq.get("https://datadrive.world/api/relay/status", timeout=6)
                if r.status_code != 200:
                    return False, f"⚠️ relay HTTP {r.status_code}"
                st = r.json()
                uptime = st.get("uptime", 0)
                npkg = st.get("packages", 0)
                meta = st.get("latest_meta") or {}
                frames = meta.get("frames", "?")
                src = meta.get("source", "?")
                ts = meta.get("ts") or meta.get("time") or "?"
                # 打包成 JSON 字符串传递 (信号只支持 str)
                import json as _json
                return True, _json.dumps({"uptime": uptime, "npkg": npkg, "frames": frames,
                                          "src": src, "ts": str(ts)})
            except Exception as ex:
                return False, f"⚠️ 采集查询失败: {ex}"

        def _done(ok, info):
            if not ok:
                self.lbl_acq_state.setText(info)
                self.lbl_acq_state.setStyleSheet("color:#ff4444; font-size:11px; font-family:Consolas; background:transparent; border:none;")
                return
            import json as _json
            try:
                d = _json.loads(info)
            except Exception:
                self.lbl_acq_state.setText("⚠️ 采集状态解析失败")
                return
            uptime, npkg, frames, src, ts = d.get("uptime", 0), d.get("npkg", 0), d.get("frames", "?"), d.get("src", "?"), d.get("ts", "?")
            if npkg > 0:
                self.lbl_acq_state.setText(f"● 采集中 · 中转在线 {int(uptime)}s · 来源 {src}")
                self.lbl_acq_state.setStyleSheet("color:#3fb950; font-size:11px; font-family:Consolas; background:transparent; border:none;")
                self.lbl_acq_pkgs.setText(f"数据包: {npkg}")
                self.lbl_acq_latest.setText(f"最新: {frames}帧 @ {ts}")
                # 采集进行中 → 画布 hardware 节点标记运行
                for n in self.nodes:
                    if n.get("type") == "hardware":
                        n["status"] = "running"
                        it = self._items.get(n["id"])
                        if it:
                            it.update()
                self.canvas._scene.update()
            else:
                self.lbl_acq_state.setText("○ 等待采集数据…")
                self.lbl_acq_state.setStyleSheet("color:#57606a; font-size:11px; font-family:Consolas; background:transparent; border:none;")
                self.lbl_acq_pkgs.setText("数据包: 0")
                self.lbl_acq_latest.setText("最新: —")

        worker = CICDWorker(_work)
        worker.finished_ok.connect(_done)
        worker.finished.connect(lambda: setattr(self, "_acq_worker", None))
        self._acq_worker = worker
        worker.start()

    # ════════════════════════════════════════════════════════════
    # CI/CD 闭环: 验证 → 训练 → 集成 → 部署 (后台线程执行)
    # ════════════════════════════════════════════════════════════
    def _repo_root(self):
        """仓库根: tools/gui/simulink_module.py → lerobot-smolvla-lew/"""
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _run_cmd(self, cmd, cwd=None, collect=None, line_hook=None):
        """(后台线程内) 执行命令, 输出流式进日志; collect(list) 可选收集原始行; line_hook(ln) 每行回调"""
        import subprocess
        try:
            p = subprocess.Popen(cmd, cwd=cwd or self._repo_root(),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 bufsize=1, encoding="utf-8", errors="replace")
            for line in p.stdout:
                txt = line.rstrip()
                self.log_signal.emit(txt[:200])
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
                    # 该行无 step; 用已有最大步数 + log_freq 推断
                    step = (max(dedup, default=0) + 50) if dedup else 50
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
        if w is not None and w.isRunning():
            self._log("⏳ 上一个任务还在跑, 请稍候…")
            return  # 任务未启动 → 引导不推进 (等上一个完成后用户再点)
        if stage:
            self._cicd_state[stage] = 1  # 运行中
            # 数据闭环引导: 任务真正启动才推进 (防重入 return 时不能推进)
            self._tutorial_on_action(stage)
            # 🧠 ACT-Meta 引导: 训练启动/完成时继续提示, 直到训练完成
            if stage == "train" and getattr(self, "_act_train_guided", False):
                self._log("🚀 训练已启动 (约40s, 4060 CUDA)… 完成后我会继续提示 👇")
        self._log(f"⏳ {busy_msg} (后台执行, UI 可继续操作)…")

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
            # ⚔️ 对比评估完成 → 自动弹出对比图表
            if stage == "compare" and ok:
                try:
                    from simulink_scope import ModelCompareDialog
                    dlg = ModelCompareDialog(self)
                    dlg.exec_()
                except Exception as ex:
                    self._log(f"⚠️ 对比图表打开失败: {ex}")
            self._flow_next()  # 全流程流转钩子 (无队列时无操作)
            # 若有打开的全链路面板, 自动刷新
            if getattr(self, "_cicd_panel", None) and self._cicd_panel.isVisible():
                self._cicd_panel._refresh()

        worker = CICDWorker(fn)
        worker.log.connect(_emit_log)
        worker.finished_ok.connect(_done)
        worker.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker = worker
        worker.start()

    def open_cicd_panel(self):
        """打开 CI/CD 全链路面板:
        1) 若主画布为空 → 自动加载默认流水线 DAG (输入数据→ACT模型→输出action)
        2) 打开可视化流水线面板
        """
        # 画布空 → 加载默认 CI/CD 工作流 (可保存 JSON)
        if not self.nodes:
            self.load_reference_app("⚙️ CI/CD 默认流水线",
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
    ACT_BUILD_STEPS = [
        ("📦 metaworld 数据", "hardware", "第1/9步 数据源: 点击左侧模块库「📦 metaworld 数据」(4D/4D, sawyer 关节)"),
        ("🖼 视觉主干 ResNet18", "model", "第2/9步 视觉编码: 点击「🖼 视觉主干 ResNet18」(官方 ACT.backbone, 图像→特征图)"),
        ("🧬 VAE 编码器 CVAE", "model", "第3/9步 变分编码: 点击「🧬 VAE 编码器 CVAE」(官方 vae_encoder, 动作序列→潜变量)"),
        ("🔤 Transformer Encoder", "model", "第4/9步 上下文编码: 点击「🔤 Transformer Encoder」(官方 ACT.encoder, 4层)"),
        ("🔡 Transformer Decoder", "model", "第5/9步 动作解码: 点击「🔡 Transformer Decoder」(官方 ACT.decoder, DETR queries)"),
        ("🎯 Action Head 4D", "action", "第6/9步 输出适配: 点击「🎯 Action Head 4D」(★适配 metaworld 4D, 真机6D)"),
        ("⏳ Temporal Ensemble", "condition", "第7/9步 动作平滑: 点击「⏳ Temporal Ensemble」(官方 ACTTemporalEnsembler)"),
        ("🚀 全新训练", "system", "第8/9步 训练入口: 点击「🚀 全新训练」(双击启动 metaworld 训练)"),
        ("📊 Scope 示波器", "action", "第9/9步 效果观察: 点击「📊 Scope 示波器」(训练完双击它看 loss 波形)"),
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
        self._log("🎯 目标: metaworld 数据 → ResNet18 → CVAE → Encoder → Decoder → ActionHead(4D) → Ensemble → 训练 → Scope")
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
        placeholder = os.path.join(root, "data", "metaworld_act")

        # 0. 节点逻辑可修改区强制数据源 (node_logic.py ✏️) — 优先于画布 switch
        if data_source == "metaworld":
            if os.path.isdir(placeholder):
                self.log_signal.emit("📦 节点逻辑强制 [metaworld] → 使用占位集 (不拉 relay)")
                return placeholder, "metaworld 占位集 (节点逻辑)", False
            self.log_signal.emit("⚠️ 强制 metaworld 但 data/metaworld_act 不存在 → 回退自动选择")
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
                self.log_signal.emit("⚠️ 选了 metaworld, 但 data/metaworld_act 不存在 → 回退自动选择")
            elif src == "orin":
                self.log_signal.emit("📥 数据源 [Orin] → 强制拉取 relay 真实数据")

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
        """② 训练: 后台执行 (数据源智能选择 + lerobot_train)

        steps/batch_size/lr 来自节点逻辑可修改区 (node_logic.py) — None=配置模板默认。
        data_source: auto(画布switch决定) | orin(强制真实) | metaworld(占位集)
        policy: "act" | "smolvla_lew" (⚔️ 对比模板两训练节点各设一种, 默认 act)
        """
        self._log("════ ② 训练 (lerobot_train) ════")

        def _work():
            root = self._repo_root()
            data_root, source, real = self._ensure_training_data(data_source=data_source)
            if not data_root:
                return False, "无训练数据"
            self.log_signal.emit(f"📊 训练数据源: {source}" + (" · 真实产线数据" if real else ""))

            # 🔬 三策略: act=ACT / smolvla=SmolVLA 纯动作(无LEW) / smolvla_lew=SmolVLA+LeWorldModel
            # 各用独立配置模板; ts_dir 前缀区分; 曲线落盘 reports/train_curve_<policy>.json
            if policy == "smolvla_lew":
                cfg_path = os.path.join(root, "config_smolvla_lew_metaworld.yaml")
                ts_dir = "smolvla_lew_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "SmolVLA+LEW"
            elif policy == "smolvla":
                cfg_path = os.path.join(root, "config_smolvla_metaworld.yaml")
                ts_dir = "smolvla_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "SmolVLA"
            else:
                cfg_path = os.path.join(root, "config_act_metaworld.yaml")
                ts_dir = "act_" + time.strftime("%Y%m%d_%H%M%S")
                pname = "ACT"
            import re
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg_txt = f.read()
                # 输出目录加时间戳, 避免重复训练时 FileExistsError
                cfg_txt = re.sub(r"(output_dir:\s*).*", f"output_dir: outputs/train/{ts_dir}", cfg_txt, count=1)
                cfg_txt = re.sub(r"(job_name:\s*).*", f"job_name: {ts_dir}", cfg_txt, count=1)
                cfg_txt = re.sub(r"(root:\s*).*", f"root: {data_root}", cfg_txt, count=1)
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

            self.log_signal.emit(f"🚀 启动 {pname} 训练 ({steps or 300}步, 4060 CUDA)…")
            # 📊 Scope: 训练中实时落盘 loss 曲线 (2026-08-05 老倪: "训练都开始了, 为什么scope没有波形"
            #   — 原来训练结束才落盘; 改流式: 每行 loss 增量写 reports/train_curve_<policy>.json,
            #   Scope 打开时即可见实时波形)
            out_lines = []
            cur_dict = {}
            cur_ts = time.strftime("%Y%m%d_%H%M%S")
            import json as _json  # 闭包用

            def _line_hook(ln):
                """训练中实时: 解析 loss 行 → 增量更新曲线 → 写盘 (Scope 可见实时波形)
                2026-08-05 口径统一: 优先解析 action_loss:xxx (剔除 lew_loss, 三模型可比);
                无 action_loss 的行回退解析 loss:xxx"""
                try:
                    pts = self._parse_loss_curve([ln], prefer_action=True)
                    if not pts:
                        return
                    step, loss = pts[-1]
                    cur_dict[step] = loss
                    _flush_curve()
                except Exception:
                    pass

            def _flush_curve():
                try:
                    os.makedirs(os.path.join(root, "reports"), exist_ok=True)
                    with open(os.path.join(root, "reports", f"train_curve_{policy}.json"), "w", encoding="utf-8") as f:
                        _json.dump({"policy": policy, "name": pname, "ts": cur_ts,
                                    "curve": sorted(cur_dict.items()), "step_s": 0,
                                    "ckpt": f"outputs/train/{ts_dir}/checkpoints"}, f, ensure_ascii=False)
                except Exception:
                    pass

            rc = self._run_cmd([os.path.join(root, ".venv", "bin", "python"),
                                "-m", "lerobot.scripts.lerobot_train",
                                "--config_path", tmp_cfg], cwd=root, collect=out_lines,
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

    def on_infer_video(self, **kw):
        """🎥 推理效果对比 (2026-08-05 老倪): 3 模型 rollout 视频 3 窗口同步播放
        数据源: reports/rollout_<policy>/ (tools/rollout_video.py 生成, 无则自动生成)
        auto=True (模板参数): 训练完自动触发 — 先后台生成 3 模型 rollout, 完成后弹窗"""
        try:
            from simulink_scope import InferenceVideoDialog
        except ImportError as ex:
            self._log(f"❌ 缺少 simulink_scope.InferenceVideoDialog: {ex}")
            return
        # 检查是否已有 rollout 帧
        root = self._repo_root()
        import glob as _glob
        have = all(_glob.glob(os.path.join(root, "reports", f"rollout_{p}", "frame_*.png"))
                   for p in ("act", "smolvla", "smolvla_lew"))
        if not have:
            self._log("🎥 推理对比: 生成 3 模型 rollout 视频 (metaworld push-v3, 各 120 帧)…")
            self._qmsg_info("🎥 推理效果对比",
                            "3 模型推理视频将自动生成 (metaworld rollout, 各 120 帧)\n"
                            "生成完成自动弹出 3 窗口同步播放对比。")
        dlg = InferenceVideoDialog(self)
        dlg.exec_()

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
        if w is not None and w.isRunning():
            self._log("⏳ 上一个任务还在跑, 请稍候…")
            return
        self._flow_queue = [self.on_collect, self.on_train, self.on_validate,
                            self.on_integrate, self.on_deploy, self.on_infer]
        self._flow_queue.pop(0)()

    def _flow_next(self):
        """(worker 完成后) 执行下一个环节"""
        if getattr(self, "_flow_queue", None):
            fn = self._flow_queue.pop(0)
            fn()

    # ════════════════════════════════════════════════════════════
    # CICD 主控台: 节点双击 → 数据源切换 / 运行环节 (2026-08-02)
    # 老倪: "控制台是主控点, 在node上要有所有链路主要node, 要能运行;
    #        既要有metaworld数据, 又要有Orin, 又要有ACT模型, 可随意切换如何训练"
    # ════════════════════════════════════════════════════════════
    # 节点名 → 环节执行器 (双击运行)
    NODE_RUN_ACTIONS = [
        ("采集", "on_collect"),
        ("训练", "on_train"),
        ("验证", "on_validate"),
        ("集成", "on_integrate"),
        ("部署", "on_deploy"),
        ("推理", "on_infer"),
        ("对比评估", "on_compare_scope"),
        ("Scope", "on_scope"),
    ]

    def on_compare_scope(self, **kw):
        """🔬 对比评估 Scope: 双击 → 自动跑已训练模型统一评估 → 弹出对比图表
        (兼容双/三模型: 至少一个模型有训练产物即可, compare_models.py 会跳过缺失的)"""
        root = self._repo_root()
        rc_act = os.path.join(root, "reports", "train_curve_act.json")
        rc_sml = os.path.join(root, "reports", "train_curve_smolvla.json")
        rc_lew = os.path.join(root, "reports", "train_curve_smolvla_lew.json")
        have = [p for p, f in (("ACT", rc_act), ("SmolVLA", rc_sml), ("SmolVLA+LEW", rc_lew)) if os.path.exists(f)]
        if not have:
            self._log("⚠️ 对比评估: 还缺训练产物 — 先点「▶ 运行」(或分别双击训练节点) 训练模型")
            self._qmsg_info("🔬 对比评估",
                            "还缺训练产物!\n\n请先点「▶ 运行」依次训练模型\n"
                            "或分别双击「🚀 ACT 训练」「🚀 SmolVLA 训练」「🚀 SmolVLA+LEW 训练」节点。")
            return
        self._log(f"⚔️ 对比评估: 统一 metaworld 测试集 (120帧) 评估 {len(have)} 个已训练模型 ({' / '.join(have)}) — 精确度/鲁棒性/延迟, 完成自动弹图表…")

        def _work():
            rc = self._run_cmd([os.path.join(root, ".venv", "bin", "python"),
                                os.path.join(root, "tools", "compare_models.py"),
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
        dlg.exec_()

    def on_node_activated(self, node):
        """双击节点: 数据源 → 切换; Switch → 切换路由; 子系统 → 展开; 视频 → 推理对比; 环节节点 → 运行; 其他 → 参数框"""
        params = node.get("params", {})
        # 0) 视频显示节点 (🎥 推理效果对比, 2026-08-05 老倪): 双击 → 3 窗口同步播放
        if params.get("video"):
            self.on_infer_video()
            return
        # 0) 子系统节点 (Simulink Subsystem): 双击展开内部流程
        if params.get("subsystem"):
            self._open_subsystem(node)
            return
        # 1) 数据源节点: 切换激活
        if params.get("source"):
            self._toggle_source(node)
            return
        # 1.5) Switch 节点 (仿 Simulink Switch 块): 切换数据源路由
        if params.get("switch") or node.get("type") == "switch":
            self._toggle_switch(node)
            return
        # 2) 环节节点: 按名称匹配执行器
        for kw, meth in self.NODE_RUN_ACTIONS:
            if kw in node.get("name", ""):
                fn = getattr(self, meth, None)
                if fn:
                    self._run_node_stage(node, fn, kw)
                return
        # 3) 其他节点: 打开参数框
        dlg = BlockParamsDialog(node, None)
        if dlg.exec_() == QDialog.Accepted:
            it = self._items.get(node["id"])
            if it:
                it.update()

    def on_show_node_logic(self, node):
        """右键 → 查看/编辑节点逻辑 (node_logic.py ✏️ 可修改区, 保存即生效)"""
        dlg = NodeLogicDialog(node.get("name", ""), node.get("type", ""), self)
        dlg.exec_()

    def on_node_params(self, node):
        """右键 → 节点参数框"""
        dlg = BlockParamsDialog(node, None)
        if dlg.exec_() == QDialog.Accepted:
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
        if cur is not None and cur.isRunning():
            self._log("⏳ 上一个任务还在跑, 请稍候…")
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
            if getattr(self, "_cicd_panel", None) and self._cicd_panel.isVisible():
                self._cicd_panel._refresh()

        worker = CICDWorker(fn)
        worker.log.connect(self._log)
        worker.finished_ok.connect(_done)
        worker.finished.connect(lambda: setattr(self, "_worker", None))
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
