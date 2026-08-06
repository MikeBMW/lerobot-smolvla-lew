#!/usr/bin/env python3
"""重做理论公式图 v2 — 每个模型: 公式 + 中文解释 + 形象比喻 + 证明分步说明
2026-08-06 老倪要求: 公式要解释, 证明要形象说明, 不能有乱码
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "figs", "theory")
os.makedirs(OUT, exist_ok=True)

# 每个模型: 公式(mathtext) + 中文解释 + 形象比喻 + 证明
CARDS = {
    "act": {
        "title": "ACT — 确定性动作分块 (条件VAE)",
        "formula": r"$\mathcal{L}_{ACT} = \mathbb{E}[-\log p_\theta(a|x,z)] + \beta\,D_{KL}(q_\phi(z|x,a)\|p(z))$",
        "explain": "含义: 编码器把「看到什么(x)+要做什么(a)」压缩成潜变量z, 解码器再从z还原动作a。第一项=动作重建误差, 第二项=潜变量不跑偏的约束。",
        "analogy": "比喻: 像「抄作业」——先记住要点(z), 再凭要点默写动作。训练越久, 默写越准。",
        "proof": "证明(形象): β越大→越强迫z只记关键信息→模型退化成「直接回归」: 看到x就输出最可能的动作(平均值)。所以 ACT 最优解=条件期望 E[a|x], 速度最快但只会一种答案。",
    },
    "smolvla": {
        "title": "SmolVLA — VLM 扩散策略 (DDPM)",
        "formula": r"$\mathcal{L} = \mathbb{E}_{t,\epsilon}\|\epsilon - \epsilon_\theta(x_t, \mathrm{VLM}(x), t)\|^2$",
        "explain": "含义: 把动作当「照片」, 训练时往照片加噪变雪花, 再教模型从雪花还原照片。x_t=加噪到第t步的图, ε=噪声, 模型学的是「去噪方向」。",
        "analogy": "比喻: 像「雾里看花」——先学会从浓雾(纯噪声)里一步步看清花(动作)。每次去噪都是小步修正。",
        "proof": "证明(形象): 每步去噪=在「动作分布」上走一步, 走很多步(约10步)后到达的终点=按真实概率采样。所以 SmolVLA 能输出「多种正确答案」(多模态), 但每步都慢(延迟高)。",
    },
    "lew": {
        "title": "SmolVLA+LEW — 世界模型 (LeWorldModel)",
        "formula": r"$z_{t+1}=f_{WM}(z_t,a_t),\quad |J(\pi)-J^*| \leq \frac{2\gamma\epsilon}{1-\gamma}$",
        "explain": "含义: 世界模型学习「世界怎么变」——给定当前状态z_t和动作a_t, 预测下一状态z_{t+1}。上界公式说: 世界模型预测误差ε, 经过折扣γ累积后, 策略性能损失有上限。",
        "analogy": "比喻: 像「下棋想三步」——先在大脑里模拟走法后果, 再选最好的走。想得越准(ε小), 棋下得越好。",
        "proof": "证明(形象): 每步预测误差ε像「滚雪球」, 但折扣γ让雪球越滚越小(γ<1), 无穷级数求和=ε/(1-γ)。模型内模拟代替真机试错→省大量真机数据(样本效率高)。",
    },
    "vla_touch": {
        "title": "VLA-Touch — 触觉增强 Interpolant",
        "formula": r"$x_t=(1-t)x_0+tx_1+\gamma\mathcal{N}(0,1),\quad \mathrm{Var}(a|x,\tau)<\mathrm{Var}(a|x)$",
        "explain": "含义: 在「纯噪声x0」和「目标动作x1」之间插值采样, 逐步逼近目标。下面的方差不等式: 加了触觉τ后, 动作的不确定性变小(知道用力大小→插得更准)。",
        "analogy": "比喻: 像「摸黑插插头」——手摸到插座位置(触觉τ)后, 就不用瞎猜了, 一插一个准。",
        "proof": "证明(形象): 方差分解: 总不确定性 = 知道触觉后的残余 + 触觉带来的信息量。触觉给的信息越多(互信息大), 残余不确定性越小。所以 触觉越准 → 动作误差越小。",
    },
    "awe": {
        "title": "AWE-zFlow — 场景原生 + 潜空间世界模型",
        "formula": r"$z_{t+1}=f_{GRU}(z^{(1)}_t,z^{(2)}_t,z^{(3)}_t,a_t),\quad \mathrm{Regret}\leq\frac{2\gamma^N R_{max}}{1-\gamma}+\frac{2\gamma\,\epsilon_{WM}}{1-\gamma}$",
        "explain": "含义: 三层潜空间各管一事(几何/物体/语义), GRU世界模型预测未来; 遗憾上界=预测N步后, 未来折扣奖励被覆盖(第一项→0), 只剩世界模型误差(第二项)。",
        "analogy": "比喻: 像「老司机开车」——不只盯眼前(反应式), 而是预判前方路况(世界模型预测), 提前打方向。触觉坏了也不慌, 凭预判继续开。",
        "proof": "证明(形象): ①分层=把世界拆成3个抽屉各放一类信息, 互不干扰→预测更准(条件熵下降) ②预测N步=把未来N步的奖励提前算清, N越大越接近完美 ③触觉中断实验实测: VLA-Touch原地停, AWE靠预测继续接近——理论与实验互相印证。",
    },
}

def render(key, data):
    fig = plt.figure(figsize=(10.5, 4.6))
    fig.patch.set_facecolor("#0d1117")
    ax = fig.add_axes([0.03, 0.03, 0.94, 0.94])
    ax.set_facecolor("#0d1117")
    ax.axis("off")
    y = 0.93
    ax.text(0.01, y, data["title"], fontsize=14, color="#58a6ff", fontweight="bold",
            transform=ax.transAxes, va="top")
    y -= 0.10
    # 公式 (浅色大字, 清晰无乱码)
    ax.text(0.01, y, data["formula"], fontsize=12.5, color="#e6edf3",
            transform=ax.transAxes, va="top")
    y -= 0.13
    # 解释
    ax.text(0.01, y, "【含义】" + data["explain"], fontsize=9.5, color="#9ecbff",
            transform=ax.transAxes, va="top", wrap=True)
    y -= 0.14
    # 比喻
    ax.text(0.01, y, "【比喻】" + data["analogy"], fontsize=9.5, color="#7ee787",
            transform=ax.transAxes, va="top", wrap=True)
    y -= 0.14
    # 证明
    ax.text(0.01, y, "【证明】" + data["proof"], fontsize=9.5, color="#f7a90b",
            transform=ax.transAxes, va="top", wrap=True)
    out = os.path.join(OUT, f"theory_{key}.png")
    fig.savefig(out, dpi=130, facecolor="#0d1117")
    plt.close(fig)
    print(f"✅ {key}")

if __name__ == "__main__":
    for k, v in CARDS.items():
        render(k, v)
    print("全部公式解释图完成")
