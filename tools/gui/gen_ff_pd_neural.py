#!/usr/bin/env python3
"""gen_ff_pd_neural.py — ff_pd_top.json 加「🧠 神经同构 (脑↔控制)」模块行

2026-08-16 老倪: 左脑MLP≈小脑(前馈逆动力学) / 右脑GRU≈非线性卡尔曼(预测-更新) /
状态机≈皮层(认知决策)。把三脑映射落地成可标定模块, 与上方 Z700 内部行对应连线。

幂等: 已有神经同构行则跳过。产物: flows/ff_pd_top.json (仓库根, 非 tools/flows)
"""
import json
import os
import sys

FLOW = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "flows", "ff_pd_top.json"))

NEURAL_ROW_Y = 290   # 新区块行 y (row_bg)
NEURAL_NODE_Y = 330  # 节点 y (row_bg y + 40)

# 神经同构行节点: (id, type, name, x, params, inputs, outputs)
NEURAL_NODES = [
    ("ffkal", "model", "🔮 右脑 · 非线性卡尔曼", 150,
     {"neural_kalman": True, "z700_internal": True,
      "desc": "世界模型: 预测(状态转移A≈GRU循环权重) + 更新(门控≈卡尔曼增益K) — 输出状态预测+contact概率",
      "A": 0.95, "K": 0.5, "limit": [-1.0, 1.0]},
     ["in1", "in2"], ["out1", "out2"]),
    ("ffkal2", "model", "⚖️ α 融合层 (置信度旋钮)", 360,
     {"neural_alpha": True, "z700_internal": True,
      "desc": "fused = (1−α)·预测 + α·观测 — α≈等效卡尔曼增益: 0=纯模型 1=纯传感器, 按阶段调度",
      "alpha": 0.5, "alpha_approach": 0.3, "alpha_insert": 0.9,
      "limit": [0.0, 1.0]},
     ["in1", "in2", "in3"], ["out1"]),
    ("ffcer", "model", "🧠 左脑 · 小脑 (前馈)", 570,
     {"neural_cerebellum": True, "z700_internal": True,
      "desc": "小脑=学习过的逆动力学模型: obs→action 直接映射, 无递归无延迟, 偏差产生前给力",
      "K_ff": 0.2, "act_gain": 0.3, "err_gain": 2.0, "gate": 1.0,
      "x_mean": 0.0, "x_std": 1.0, "limit": [-1.0, 1.0]},
     ["in1"], ["out1"]),
    ("ffclim", "system", "🧬 攀缘纤维 · 误差警戒", 730,
     {"neural_climbing": True, "z700_internal": True,
      "desc": "生物标定: 力传感器 vs 右脑预测 → 大误差=复杂脉冲 → 触发 gate 抑制 (LTD)",
      "gate_th": 2.0, "gate_min": 0.1},
     ["in1", "in2"], ["out1"]),
    ("ffltd", "model", "🛡 gate · 突触抑制 (LTD)", 890,
     {"neural_ltd": True, "z700_internal": True,
      "desc": "长时程抑制: 左脑不准 → 瞬间降 gate (1.0→0.1) 压制 MLP, 控制权移交传感器; 恢复期切阶段 gate 复原",
      "gate": 1.0, "gate_off": 0.1, "gate_off2": 0.01},
     ["in1", "in2"], ["out1"]),
    ("ffctx", "system", "🧭 皮层 · 状态机", 1050,
     {"neural_cortex": True, "z700_internal": True,
      "desc": "认知决策: 接收右脑contact概率+几何误差 → 决定阶段切换 (接近→抓取→…→完成)",
      "contact_th": 0.6, "Kp": 2.0, "thresh": 0.06},
     ["in1", "in2"], ["out1"]),
    ("ffcal", "system", "🔧 左脑标定实验", 1230,
     {"neural_calib": True, "z700_internal": True,
      "desc": "三件套标定: ①感知零偏(归一化x_mean) ②执行力(act_gain/err_gain) ③现场微调 — 左脑标定靠数据不靠权重",
      "n_static": 500, "fine_tune_steps": 3000},
     ["in1"], ["out1"]),
]

# 神经同构行 row_bg (分区背景, 与内部行对齐语义: 前馈=右脑预测区)
NEURAL_BG = {
    "id": "ffnbg", "type": "row_bg", "name": "🧠 神经同构 (脑↔控制)",
    "x": -20, "y": NEURAL_ROW_Y, "w": 1530,
    "params": {"bg": "#1a1030", "model": "z700",
               "desc": "神经同构: 右脑=非线性卡尔曼(预测-更新) · α融合层=置信度旋钮 · 左脑=小脑(前馈) · 攀缘纤维=误差警戒 · gate=LTD抑制 · 皮层=状态机(决策)"},
}

# 连线: 神经行 ↔ 上方 Z700 内部行 (f/t 是节点 id, 端口 in1/out1…)
NEURAL_LINKS = [
    # 感知链(ffy1) → 右脑卡尔曼 in1 (观测进世界模型)
    ("ffy1", "ffkal", "out1", "in1"),
    # 双脑(ffb1) → 右脑卡尔曼 in2 (动作进世界模型: 动作如何改变状态)
    ("ffb1", "ffkal", "out1", "in2"),
    # 右脑预测 out1 → α融合层 in1 (预测值)
    ("ffkal", "ffkal2", "out1", "in1"),
    # 感知链(ffy1) → α融合层 in2 (传感器观测值)
    ("ffy1", "ffkal2", "out1", "in2"),
    # 感知链(ffy1) → 左脑小脑 in1 (状态进小脑: 逆动力学映射)
    ("ffy1", "ffcer", "out1", "in1"),
    # 左脑小脑 → 攀缘纤维 in1 (平行纤维 = MLP 输出)
    ("ffcer", "ffclim", "out1", "in1"),
    # 感知链(ffy1) → 攀缘纤维 in2 (力传感器实测)
    ("ffy1", "ffclim", "out1", "in2"),
    # 攀缘纤维 → gate in1 (误差信号 → LTD 抑制)
    ("ffclim", "ffltd", "out1", "in1"),
    # 左脑 → gate in2 (被抑制的 MLP 输出)
    ("ffcer", "ffltd", "out1", "in2"),
    # gate 抑制后输出 → 动作(ffact) in2 (安全边界内执行)
    ("ffltd", "ffact", "out1", "in2"),
    # 右脑卡尔曼 out2(contact概率) → 皮层状态机 in1 (认知决策输入)
    ("ffkal", "ffctx", "out2", "in1"),
    # 状态机(ffsm) → 皮层 in2 (几何误差进认知层)
    ("ffsm", "ffctx", "out1", "in2"),
    # 皮层 → 动作(ffact) in3 (决策输出叠加到动作)
    ("ffctx", "ffact", "out1", "in3"),
    # 标定实验 → 左脑 (标定结果注入 act_gain/err_gain/x_mean)
    ("ffcal", "ffcer", "out1", "in2"),
]


def main():
    d = json.load(open(FLOW, encoding="utf-8"))
    nids = {n["id"] for n in d["nodes"]}
    if "ffkal" in nids:
        print("✅ 神经同构行已存在, 幂等跳过")
        return 0
    # 1) 加 row_bg
    d["nodes"].append(NEURAL_BG)
    # 2) 加节点
    for nid, ntype, name, x, params, inputs, outputs in NEURAL_NODES:
        d["nodes"].append({
            "id": nid, "type": ntype, "name": name, "x": x, "y": NEURAL_NODE_Y,
            "w": 190, "icon": "", "color": "", "params": params,
            "inputs": inputs, "outputs": outputs, "actions": [],
        })
    # 3) 加连线
    for f, t, fp, tp in NEURAL_LINKS:
        d["links"].append({
            "id": f"{f}->{t}", "f": f, "t": t, "f_port": fp, "t_port": tp, "label": "",
        })
    # 4) 动作节点 ffact 输入扩 in2/in3 (gate 抑制 + 皮层决策输出叠加);
    #    左脑节点 ffcer 输入扩 in2 (标定实验注入)
    for n in d["nodes"]:
        if n["id"] == "ffact":
            for _p in ("in2", "in3"):
                if _p not in n.get("inputs", []):
                    n["inputs"] = n.get("inputs", []) + [_p]
        if n["id"] == "ffcer" and "in2" not in n.get("inputs", []):
            n["inputs"] = n.get("inputs", []) + ["in2"]
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ ff_pd_top.json 已加神经同构行: +1 row_bg +{len(NEURAL_NODES)} 节点 +{len(NEURAL_LINKS)} 连线 (ffact 输入扩 in2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
