#!/usr/bin/env python3
"""Model Zoo 7 模型对比报告 — 每模型优缺点 (2026-08-10)"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

font_path = None
for p in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
          "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"]:
    import os
    if os.path.exists(p):
        font_path = p; break
if font_path:
    font_manager.fontManager.addfont(font_path)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=font_path).get_name()
plt.rcParams["axes.unicode_minus"] = False

# 评估数据 (metaworld peg-insertion, 5000步容器训练)
models = ["ACT", "SmolVLA", "SmolVLA\n+LEW", "VLA\n-Touch", "AWE", "MLP\n蒸馏", "官方\n专家"]
lifts = [0, 0, 0, 0, 0, 6, 19]      # 抓起成功数
ins = [0, 0, 0, 0, 0, 3, 17]        # 插入成功数
total = [8, 8, 8, 8, 8, 10, 20]     # 尝试次数
dist = [0.361, 0.365, 0.367, 0.365, 0.365, None, None]  # 距孔距离 m
params = [30, 500, 500, 500, 250, 0.64, 0]  # M 参数 (视觉BC为VLM主干规模)

fig, axes = plt.subplots(1, 3, figsize=(16, 5.5))
fig.suptitle("Model Zoo 7 模型对比 — 光模块插拔任务 (metaworld, 5000步训练)", fontsize=15, fontweight="bold")

# 1. 抓起/插入成功率
ax = axes[0]
x = np.arange(len(models))
w = 0.35
b1 = ax.bar(x-w/2, [l/t*100 for l, t in zip(lifts, total)], w, label="抓起成功率", color="#2ecc71")
b2 = ax.bar(x+w/2, [i/t*100 for i, t in zip(ins, total)], w, label="插入成功率", color="#e67e22")
ax.set_xticks(x); ax.set_xticklabels(models, fontsize=8)
ax.set_ylabel("成功率 (%)"); ax.set_ylim(0, 105)
ax.legend(fontsize=8)
for b in list(b1)+list(b2):
    h = b.get_height()
    if h > 0:
        ax.text(b.get_x()+b.get_width()/2, h+1, f"{h:.0f}%", ha="center", fontsize=8)
ax.set_title("成功率对比 (抓起/插入)", fontsize=12)
ax.axhline(85, color="#ffd700", ls="--", lw=1)
ax.text(6.4, 86, "专家85%", fontsize=8, color="#ffd700")

# 2. 距孔距离
ax = axes[1]
valid = [(m, d) for m, d in zip(models, dist) if d]
ms = [v[0] for v in valid]; ds = [v[1] for v in valid]
bars = ax.bar(ms, [d*100 for d in ds], color="#58a6ff", width=0.5)
ax.set_ylabel("平均距孔距离 (cm)")
for b, d in zip(bars, ds):
    ax.text(b.get_x()+b.get_width()/2, d*100+1, f"{d*100:.1f}cm", ha="center", fontsize=9)
ax.set_title("接近能力 (越小越好)", fontsize=12)
ax.text(0.3, 38, "全部视觉BC模型停在 36cm 外\n(只会接近, 不会抓取)", fontsize=9, color="#e74c3c")

# 3. 参数量 (对数)
ax = axes[2]
bars = ax.bar(models, params, color=["#58a6ff"]*5+["#bc8cff", "#ffd700"], width=0.5)
ax.set_yscale("log")
ax.set_ylabel("参数量 (M, 对数)")
for b, v in zip(bars, params):
    ax.text(b.get_x()+b.get_width()/2, v*1.3, f"{v:.2f}M" if v < 100 else f"{v:.0f}M", ha="center", fontsize=8)
ax.set_title("模型规模 (对数)", fontsize=12)
ax.text(5.3, 3, "MLP蒸馏 0.64M\n(轻量)", fontsize=9, color="#bc8cff")

plt.tight_layout(rect=[0, 0.04, 1, 0.92])
out = "reports/ModelZoo_7模型优缺点对比_20260813.pdf"
plt.savefig(out, dpi=150, bbox_inches="tight")
print("✅ PDF:", out)
