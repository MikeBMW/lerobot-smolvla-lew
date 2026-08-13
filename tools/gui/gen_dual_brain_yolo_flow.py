#!/usr/bin/env python3
"""生成 flows/dual_brain_peg_yolo.json — 双脑+状态机 + YOLO 3D 感知链 (2026-08-12 老倪)

基于 flows/dual_brain_peg.json, 在顶部插入 YOLO 感知行:
  🎯 YOLO 3D → 📐 2D→3D 解算 → 🔌 State Adapter → 📊 39D obs 输入
感知链源码: src/lerobot/policies/yolo_3d/ (train_yolo / yolo_state_aligner / gen_yolo_data)

幂等可重跑; 产物 flows/dual_brain_peg_yolo.json
"""
import json, os, sys

FLOW = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "flows", "dual_brain_peg.json"))
OUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "flows", "dual_brain_peg_yolo.json"))

# YOLO 感知链节点 (与 LIBRARY 🎯 YOLO 3D (感知) 组同参)
# 2026-08-12 老倪: metaworld 数据源在最前端 → 喂 YOLO 感知 (数据流源头)
YOLO_SRC = "src/lerobot/policies/yolo_3d"
YOLO_ROW = [
    {"id": "dbt0", "type": "hardware", "name": "📦 metaworld_peg", "x": 140, "y": -150,
     "w": 200, "icon": "📦", "color": "#3fb950",
     "params": {"source": "metaworld", "frames": 4800, "active": True,
                "dims": "4D/4D", "desc": "states 4D · actions 4D (sawyer 关节) · 24集4800帧 · 图像喂 YOLO 感知"}},
    {"id": "yol1", "type": "model", "name": "🎯 YOLO 3D", "x": 380, "y": -150,
     "w": 200, "icon": "🎯", "color": "#3fb950",
     "params": {"source": YOLO_SRC,
                "model": "yolov8s", "classes": "peg/hole/hand",
                "yolo_enabled": True, "state_dim": 39,
                "desc": "相机图像 → YOLO 检测销钉/插孔/末端 → 2D→3D解算 → 39D state (源码 src/lerobot/policies/yolo_3d/)"}},
    {"id": "yol2", "type": "model", "name": "📐 2D→3D 解算", "x": 620, "y": -150,
     "w": 200, "icon": "📐", "color": "#58a6ff",
     "params": {"source": YOLO_SRC,
                "intrinsics": "camera_K", "method": "depth|hand-eye",
                "desc": "YOLO 2D框中心 + 深度/标定 → 目标 3D 坐标 → 拼入 state (yolo_state_aligner.py)"}},
    {"id": "yol3", "type": "model", "name": "🔌 State Adapter", "x": 860, "y": -150,
     "w": 200, "icon": "🔌", "color": "#d4a800",
     "params": {"source": YOLO_SRC,
                "in_dim": 43, "out_dim": 43, "normalize": True,
                "desc": "视觉39D + 触觉4D = 43D 统一 state, 接入双脑输入 (2026-08-12 触觉并入)"}},
    {"id": "yol4", "type": "model", "name": "📍 Marker 触觉跟踪", "x": 1100, "y": -150,
     "w": 200, "icon": "📍", "color": "#f0883e",
     "params": {"source": YOLO_SRC,
                "grid": "7x9", "dim": 4,
                "desc": "GelSight 标记位移 → 低维力信号 4D (数据来自 metaworld_peg 改造, gen_tactile.py)"}},
]


def main():
    with open(FLOW, encoding="utf-8") as f:
        d = json.load(f)

    # 1) 顶部加 YOLO 感知行 (bg 在最上, 与行高 230 对齐; w=1790 与状态机行同宽, 2026-08-12)
    d["nodes"] = [
        {"id": "yolbg", "type": "row_bg", "name": "🎨 YOLO 感知", "x": -20, "y": -170,
         "w": 1790, "icon": "🎨", "color": "#2d6a8f",
         "params": {"bg": "#0f2438", "model": "yolo_3d", "desc": "YOLO 3D 感知链 (src/lerobot/policies/yolo_3d/)"},
         "h": 214, "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
         "outputs": [{"id": "out1", "label": "out", "dtype": "any"}]},
    ] + [dict(n, inputs=[{"id": "in1", "label": "in", "dtype": "any"}],
              outputs=[{"id": "out1", "label": "out", "dtype": "any"}]) for n in YOLO_ROW] + d["nodes"]

    # 2) 感知链连线: 📦 metaworld_peg → 🎯 YOLO 3D → 📐 2D→3D → 🔌 State Adapter ← 📍 Marker 触觉跟踪 (4D)
    #    数据源同时喂 Marker 触觉跟踪 (2026-08-12 老倪: 触觉输入也要有数据)
    #    State Adapter (43D) → obs 输入
    obs_id = next(n["id"] for n in d["nodes"] if n["name"] == "📊 39D obs 输入")
    new_links = [
        {"id": "lyol0", "f": "dbt0", "f_port": "out1", "t": "yol1", "t_port": "in1"},  # 数据源 → YOLO 感知
        {"id": "lyol5", "f": "dbt0", "f_port": "out1", "t": "yol4", "t_port": "in1"},  # 数据源 → Marker 触觉跟踪
        {"id": "lyol1", "f": "yol1", "f_port": "out1", "t": "yol2", "t_port": "in1"},
        {"id": "lyol2", "f": "yol2", "f_port": "out1", "t": "yol3", "t_port": "in1"},
        {"id": "lyol4", "f": "yol4", "f_port": "out1", "t": "yol3", "t_port": "in1"},  # 触觉4D 并入
        {"id": "lyol3", "f": "yol3", "f_port": "out1", "t": obs_id, "t_port": "in1"},
    ]
    d["links"] = new_links + d["links"]
    # 触觉并入后 obs 输入 39D → 43D (2026-08-12)
    for n in d["nodes"]:
        if n["name"] == "📊 39D obs 输入":
            n["name"] = "📊 43D obs 输入"
            n["params"]["desc"] = "视觉39D + 触觉4D = 43D 统一 state 输入"
    # 双脑/策略节点 → 源码映射 (右键打开, 2026-08-12 老倪)
    for n in d["nodes"]:
        if n["name"] in ("🧠 左脑 LeftBrainMLP", "🧠 右脑 RightBrainWM", "◉ LeftRightPolicy"):
            n["params"]["source"] = "src/lerobot/policies/left_right"
    # 3) 🎨 训练行: 🚀 训练 (数据源复用前端 📦 metaworld_peg, 2026-08-12 老倪)
    d["nodes"] += [
        {"id": "dbtbg", "type": "row_bg", "name": "🎨 训练", "x": -20, "y": 750,
         "w": 1070, "icon": "🎨", "color": "#3fb950",
         "params": {"bg": "#10281c", "model": "train", "desc": "训练行: metaworld_peg 数据源 → left_right 训练"},
         "h": 214, "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
         "outputs": [{"id": "out1", "label": "out", "dtype": "any"}]},
        {"id": "dbt1", "type": "system", "name": "🚀 训练", "x": 140, "y": 770,
         "w": 200, "icon": "🚀", "color": "#00d4aa",
         "params": {"steps": 3000, "policy": "left_right",
                    "desc": "双击 → 配置/启动 left_right 训练 (metaworld_peg 数据, 39D, 3000步)"},
         "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
         "outputs": [{"id": "out1", "label": "out", "dtype": "any"}]},
    ]
    lr_id = next(n["id"] for n in d["nodes"] if n["name"] == "◉ LeftRightPolicy")
    d["links"] += [
        {"id": "ltr0", "f": "dbt0", "f_port": "out1", "t": "dbt1", "t_port": "in1"},  # 数据源 → 训练 (跨行)
        {"id": "ltr1", "f": "dbt1", "f_port": "out1", "t": lr_id, "t_port": "in1"},
    ]
    # 4) 🌐 方案介绍节点 → 交付行 (2026-08-12 老倪: 画布节点双击打开方案分页, 替代工具栏按钮)
    d["nodes"] += [{
        "id": "dbso", "type": "system", "name": "🌐 方案介绍", "x": 620, "y": 540,
        "w": 200, "icon": "🌐", "color": "#1f6feb",
        "params": {"solution_web": True,
                   "desc": "双击 → 打开 Z-MAX 方案介绍分页 (datadrive.world/solution.html, 光模块工厂5大场景, 含PDF下载)"},
        "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
        "outputs": [{"id": "out1", "label": "out", "dtype": "any"}]},
    ]
    d["name"] = "🧠 left_right 双脑+状态机 + 🎯 YOLO感知链 + 📍触觉 + 📦训练"

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成 {OUT}")
    print(f"   节点 {len(d['nodes'])} (原16 + YOLO行3 + bg1) · 连线 {len(d['links'])} (原15 + 3)")


if __name__ == "__main__":
    main()
