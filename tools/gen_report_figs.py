#!/usr/bin/env python3
"""生成报告用架构图: 5 模型架构图 + Simulink pipeline 图 → PNG (供 PDF 嵌入)
2026-08-06 老倪要求: PDF 要有模型架构图 + pipeline
2026-08-07 老倪: 图片中文乱码 → 加 Noto CJK 中文字体 (matplotlib 默认 DejaVu 无中文)
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager

# 🀄 中文字体 (2026-08-07: 之前无字体配置 → 全图中文乱码; 与 generate_report._cfg_cjk 同款)
for _cand in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"):
    if os.path.exists(_cand):
        try:
            font_manager.fontManager.addfont(_cand)
        except Exception:
            pass
matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Noto Serif CJK SC", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "figs")
os.makedirs(OUT, exist_ok=True)

C = {
    "bg": "#0d1117", "card": "#161b22", "border": "#30363d",
    "blue": "#58a6ff", "purple": "#a371f7", "green": "#3fb950",
    "cyan": "#00d4aa", "orange": "#f7a90b", "red": "#f85149",
    "gray": "#8b949e", "text": "#e6edf3", "yellow": "#d4a800",
}

MODELS = [
    ("ACT", "动作分块 Transformer\n(VAE 解码器)", C["blue"],
     ["观测: 图像+状态", "编码器 4层", "VAE 潜空间 32d", "动作分块解码(7步)"]),
    ("SmolVLA", "VLM 视觉语言动作\n(扩散策略)", C["purple"],
     ["观测: 图像+文本", "SmolVLM2-500M", "扩散去噪迭代", "动作(连续)"]),
    ("SmolVLA+LEW", "VLM + 世界模型\n(LeWorldModel)", C["cyan"],
     ["观测: 图像+文本", "SmolVLM2-500M", "GRU 世界模型 6层", "未来状态预测→动作"]),
    ("VLA-Touch", "触觉增强插值\n(Interpolant)", C["orange"],
     ["观测: 状态+触觉", "触觉编码器", "Interpolant 采样", "小步精炼动作"]),
    ("AWE-zFlow", "场景原生 + 世界模型\n(zFlow 三层潜空间)", C["yellow"],
     ["观测: 状态+视触觉", "三层潜空间(几何/物体/语义)", "GRU 世界模型预测未来", "潜空间推演→动作"]),
    ("MLP 蒸馏", "行为克隆 MLP\n(蒸馏自官方专家)", "#2d6a8f",
     ["观测: 39D 完整观测", "全连接 512×1", "专家 BC 蒸馏 300eps", "直接输出动作"]),
    ("官方专家", "规则策略 (真值基准)\n(PD 控制律+夹爪状态机)", "#8f8a3d",
     ["观测: 状态+目标", "PD 位置控制律", "夹爪状态机", "规则直算动作"]),
]

def draw_model_arch():
    """7 模型架构图 (纵排卡片, 每卡片: 名称+架构+组件流) — 2026-08-07 七模型 + 字体调大"""
    fig, axes = plt.subplots(7, 1, figsize=(11, 17.5))
    fig.patch.set_facecolor(C["bg"])
    for ax, (name, arch, color, comps) in zip(axes, MODELS):
        ax.set_facecolor(C["bg"])
        ax.set_xlim(0, 10); ax.set_ylim(0, 2)
        ax.axis("off")
        # 卡片底
        card = FancyBboxPatch((0.05, 0.08), 9.9, 1.85, boxstyle="round,pad=0.05",
                              fc=C["card"], ec=color, lw=1.8)
        ax.add_patch(card)
        # 模型名
        ax.text(0.3, 1.45, name, fontsize=17, fontweight="bold", color=color, va="center")
        ax.text(0.3, 0.9, arch, fontsize=12.5, color=C["text"], va="center")
        # 组件流 (右向)
        x = 3.7
        for i, ctext in enumerate(comps):
            box = FancyBboxPatch((x, 0.55), 1.55, 0.95, boxstyle="round,pad=0.03",
                                 fc="#21262d", ec=C["border"], lw=0.9)
            ax.add_patch(box)
            ax.text(x + 0.78, 1.02, ctext.split("\n")[0], fontsize=9.5,
                    color=C["text"], ha="center", va="center")
            if ctext != comps[-1]:
                ax.annotate("", xy=(x + 1.63, 1.02), xytext=(x + 1.53, 1.02),
                            arrowprops=dict(arrowstyle="->", color=color, lw=1.6))
            x += 1.68
    fig.suptitle("Z-MAX 七模型架构对比", fontsize=19, color=C["text"], fontweight="bold", y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = os.path.join(OUT, "model_arch.png")
    fig.savefig(out, dpi=110, facecolor=C["bg"])
    plt.close(fig)
    print("✅ 架构图:", out)

PIPELINE_STAGES = [
    ("采集", "Orin 真机\n相机+关节", C["green"]),
    ("上传", "ECS 中转\nrelay 队列", C["blue"]),
    ("训练", "4060 GPU\nACT/VLA 训练", C["purple"]),
    ("集成", "checkpoint\n→ 静态 URL", C["cyan"]),
    ("部署", "Orin 推理\n模型加载", C["orange"]),
    ("推理", "动作输出\n实时执行", C["red"]),
]

def draw_pipeline():
    """Simulink 数据闭环 pipeline 图 (6 环节环形+箭头)"""
    fig, ax = plt.subplots(figsize=(11, 3.2))
    fig.patch.set_facecolor(C["bg"])
    ax.set_facecolor(C["bg"])
    ax.set_xlim(0, 12); ax.set_ylim(0, 2)
    ax.axis("off")
    x = 0.3
    for i, (name, desc, color) in enumerate(PIPELINE_STAGES):
        box = FancyBboxPatch((x, 0.4), 1.7, 1.3, boxstyle="round,pad=0.04",
                             fc=C["card"], ec=color, lw=1.8)
        ax.add_patch(box)
        ax.text(x + 0.85, 1.32, name, fontsize=12, fontweight="bold", color=color,
                ha="center", va="center")
        ax.text(x + 0.85, 0.82, desc, fontsize=6.8, color=C["text"], ha="center", va="center")
        if i < len(PIPELINE_STAGES) - 1:
            ax.annotate("", xy=(x + 1.78, 1.05), xytext=(x + 1.66, 1.05),
                        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.8))
        x += 1.95
    # 闭环回线
    ax.annotate("", xy=(0.55, 0.32), xytext=(11.3, 0.32),
                arrowprops=dict(arrowstyle="-|>", color=C["cyan"], lw=1.2, linestyle="--"))
    ax.text(5.8, 0.12, "数据闭环 (自动迭代: 推理→采集→训练)", fontsize=8,
            color=C["cyan"], ha="center", va="center")
    fig.suptitle("Z-MAX 数据闭环 Simulink Pipeline (CICD)", fontsize=14,
                 color=C["text"], fontweight="bold", y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(OUT, "pipeline.png")
    fig.savefig(out, dpi=110, facecolor=C["bg"])
    plt.close(fig)
    print("✅ pipeline 图:", out)

def draw_training_flow():
    """三阶段渐进训练 + 五模型对比评估流程"""
    fig, ax = plt.subplots(figsize=(11, 3.0))
    fig.patch.set_facecolor(C["bg"])
    ax.set_facecolor(C["bg"])
    ax.set_xlim(0, 12); ax.set_ylim(0, 2)
    ax.axis("off")
    stages = [
        ("S1 仿真预训练", "metaworld\nbackbone 冻结", C["blue"]),
        ("S2 零样本测试", "Sim→Real\nRealityGap 评估", C["cyan"]),
        ("S3 真机微调", "Orin 数据\n低 lr + ensemble", C["orange"]),
    ]
    x = 0.6
    for i, (name, desc, color) in enumerate(stages):
        box = FancyBboxPatch((x, 0.5), 3.2, 1.2, boxstyle="round,pad=0.04",
                             fc=C["card"], ec=color, lw=1.8)
        ax.add_patch(box)
        ax.text(x + 1.6, 1.32, name, fontsize=11, fontweight="bold", color=color, ha="center")
        ax.text(x + 1.6, 0.82, desc, fontsize=7.5, color=C["text"], ha="center")
        if i < 2:
            ax.annotate("", xy=(x + 3.32, 1.1), xytext=(x + 3.18, 1.1),
                        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.8))
        x += 3.7
    fig.suptitle("三阶段渐进式训练 (Sim-to-Real)", fontsize=14,
                 color=C["text"], fontweight="bold", y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(OUT, "training_flow.png")
    fig.savefig(out, dpi=110, facecolor=C["bg"])
    plt.close(fig)
    print("✅ 训练流程:", out)

if __name__ == "__main__":
    draw_model_arch()
    draw_pipeline()
    draw_training_flow()
    print("全部图表完成 →", OUT)
