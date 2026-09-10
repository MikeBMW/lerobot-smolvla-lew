#!/usr/bin/env python3
"""子系统功能框图生成器 — 输入→[子系统]→输出 方框流 + 文字解释
2026-08-06 老倪要求: 报告以结构化图形方案为主, 每个子系统画功能框图
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "figs", "subsystems")
os.makedirs(OUT, exist_ok=True)

C = {"bg": "#0d1117", "card": "#161b22", "border": "#30363d",
     "blue": "#58a6ff", "purple": "#a371f7", "green": "#3fb950",
     "cyan": "#00d4aa", "orange": "#f7a90b", "gray": "#8b949e", "text": "#e6edf3",
     "red": "#f85149"}

# 每个子系统: 名称/功能/输入/输出/文字解释/颜色
SUBS = [
    ("vis", "视觉感知子系统", "相机图像 → 视觉特征", "图像(480×480)", "SigLIP 视觉特征(512d)",
     "用 SigLIP-base 编码器把相机图像变成特征向量, 供世界模型/动作头使用。冻结训练, 只当特征提取器。",
     C["blue"]),
    ("wm", "世界模型子系统 (可选)", "特征+状态+动作 → 未来预测", "视觉特征+状态+动作历史", "未来潜状态预测",
     "LEW/AWE 用 GRU 预测下一时刻潜状态, 提供'预见性'。ACT/SmolVLA 无此模块, 纯反应式。",
     C["cyan"]),
    ("touch", "触觉/力觉子系统", "力反馈 → 触觉特征", "关节差分力(3d)+力幅(1d)", "触觉特征",
     "用状态差分模拟接触力(与训练同管道), VLA-Touch/AWE 原生融合, 面向插拔力控。",
     C["orange"]),
    ("act", "动作生成子系统", "特征 → 动作块", "编码特征", "动作块 (B,7,4)",
     "ACT 用 CVAE 解码器确定性回归; SmolVLA 系扩散迭代去噪; VLA-Touch 插值采样; AWE 潜空间解码。",
     C["purple"]),
    ("ensemble", "时序集成子系统", "动作块序列 → 平滑动作", "多步动作块", "时间平滑动作",
     "Temporal Ensemble 对相邻动作块取时间加权平均, 消除抖动, 输出平滑执行轨迹。",
     C["green"]),
    ("eval", "对比评估子系统", "模型曲线+rollout → 结论", "训练曲线/推理视频", "对比表+PDF报告",
     "Scope 归一化横比各模型收敛, rollout 视频看实际效果, 触觉中断实验测鲁棒性。",
     C["red"]),
]

def draw(sub):
    key, title, fn, inp, outp, explain, color = sub
    fig, ax = plt.subplots(figsize=(10.5, 2.6))
    fig.patch.set_facecolor(C["bg"])
    ax.set_facecolor(C["bg"])
    ax.set_xlim(0, 10.5); ax.set_ylim(0, 2.4)
    ax.axis("off")

    # 输入框 (左)
    ib = FancyBboxPatch((0.1, 0.8), 2.2, 0.9, boxstyle="round,pad=0.04",
                        fc="#21262d", ec=C["blue"], lw=1.5)
    ax.add_patch(ib)
    ax.text(1.2, 1.45, "输入", fontsize=8, color=C["blue"], ha="center", fontweight="bold")
    ax.text(1.2, 1.05, inp, fontsize=8, color=C["text"], ha="center")

    # 功能框 (中)
    fb = FancyBboxPatch((3.2, 0.55), 3.6, 1.4, boxstyle="round,pad=0.05",
                        fc=C["card"], ec=color, lw=2)
    ax.add_patch(fb)
    ax.text(5.0, 1.62, title, fontsize=11.5, color=color, ha="center", fontweight="bold")
    ax.text(5.0, 1.2, fn, fontsize=8.5, color=C["text"], ha="center")

    # 输出框 (右)
    ob = FancyBboxPatch((7.6, 0.8), 2.2, 0.9, boxstyle="round,pad=0.04",
                        fc="#21262d", ec=C["green"], lw=1.5)
    ax.add_patch(ob)
    ax.text(8.7, 1.45, "输出", fontsize=8, color=C["green"], ha="center", fontweight="bold")
    ax.text(8.7, 1.05, outp, fontsize=8, color=C["text"], ha="center")

    # 箭头
    for x1, x2 in [(2.32, 3.18), (6.82, 7.58)]:
        ax.annotate("", xy=(x2, 1.25), xytext=(x1, 1.25),
                    arrowprops=dict(arrowstyle="-|>", color=C["gray"], lw=1.6))

    # 文字解释 (底部)
    ax.text(5.25, 0.25, explain, fontsize=8.8, color="#9ecbff", ha="center", va="center",
            wrap=True)

    out = os.path.join(OUT, f"sub_{key}.png")
    fig.savefig(out, dpi=130, facecolor=C["bg"], bbox_inches="tight")
    plt.close(fig)
    print(f"✅ {key}: {out}")

if __name__ == "__main__":
    for s in SUBS:
        draw(s)
    print("全部子系统框图完成")
