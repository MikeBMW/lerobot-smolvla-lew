# -*- coding: utf-8 -*-
"""🎨 状态空间画布摆位整理 (老倪: "L4专家自主功能这层的节点都变三层了, 不好看, 变成一层;
下游的节点要依次向右挪动一些, 连线要整齐")

画布自身的排版规则 (源码实证, 必须按它反推坐标, JSON 只是输入):
  1. 角色: tools/gui/simulink_module.py:5146  普通节点 w>=DW(280) / h>=DH(110) 强制放大
  2. 586-604 行: `_relayout_row_gaps(min_gap=56)` 加载时按 round(y/60) 分桶, 桶内按 x 排序后
     把后一个节点推到 "前一个右缘 + 56"; 所以同桶内刻意留 ==56 的间隙 → 不会被再推
  3. 3289 行 SimLinkItem._path: 连线端口按"该节点第 i 条出/入线 / 总线数"垂直均分:
       ay = src.y + src.h*(fo+1)/(no+1);  by = dst.y + dst.h*(ti+1)/(mi+1)
     → 端口几何只取决于 **link 在 JSON 数组里的先后**, 与 in1/in2 命名无关
     → 出线口在源右缘 (ax = src.x+w), 入线口在目标左缘 (bx = dst.x)
     → ax > bx 就是"右出线连左入线" = 视觉回退 (老倪红线)
  所以本脚本做两件事: ①按 grid 重排坐标 ②把 link 数组按 (源y,源x,目标y,目标x) 全局排序 →
  每个节点的入线 slot 单调于来向 (高→低 / 左→右), 连线不再互相交叉。
"""
import json
import os
import shutil
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")

# ── 坐标表: id -> (x, y, w, h)  None = 不动 ──
POS = {
    # 🏆 L4 专家自主功能 —— 一层 (5 个节点同一 y, 同一 round(y/60) 桶)
    "ssintact":     (40,   -830, 300, 110),
    "ssintact_dec": (396,  -830, 300, 110),
    "ssmani_exp":   (752,  -830, 280, 110),
    "ssmani_c":     (1088, -830, 280, 110),
    "ssmani_p":     (1424, -830, 280, 110),
    "ssbg7":        (-20,  -850, 1780, 170),   # L4 行带 (原 360 高 3 行 → 170 高 1 行)
    # 🚀 L3 —— VLM 右移让 YOLO/L3记忆 的入线变前向; DiT 右移到 L4 行右侧
    "ssvlm":        (396,  -325, 280, 110),
    "ssdec":        (1810, -300, 280, 110),
    # 🔧 L2 分段控制小模型 —— 整组依次右移, 让 DiT→前馈 变前向
    "ssff":         (2160,  365, 280, 110),
    "ssest":        (2496,  365, 280, 110),
    "sspred":       (2832,  365, 280, 110),
    "ssinnov":      (3168,  365, 280, 110),
    # 🔧 L2 状态机决策 —— 跟随右移 (消除 状态校正器→动作调制器 回退)
    "sssched":      (3520,  625, 280, 110),
    "sslimit":      (3856,  625, 280, 110),
    # 🔧 L2 原子技能库 —— 通用算子 A/B/C + SK01-08 整行右移 185px
    #   (原因: 流形专家预测器右缘 1032 → A 必须在 1032 右侧, 否则 L4→L2 动态参数变成反向线;
    #    这一行 11 节点 3640px 顺序平移, 行内相对几何不变 → A→B→C→SK01 仍全前向)
    "ssa":          (1090,  845, 280, 110),
    "ssb":          (1426,  845, 280, 110),
    "ssc":          (1762,  845, 280, 110),
    "sssk1":        (2098,  845, 280, 110),
    "sssk2":        (2434,  845, 280, 110),
    "sssk3":        (2770,  845, 280, 110),
    "sssk4":        (3106,  845, 280, 110),
    "sssk5":        (3442,  845, 280, 110),
    "sssk6":        (3778,  845, 280, 110),
    "sssk7":        (4114,  845, 280, 110),
    "sssk8":        (4450,  845, 280, 110),
    # 🔧 L2 执行层 + 验证/可视化 —— SK01-08 那行 11 节点 3640px 太长, 执行器挪到行尾右侧
    "ssact":        (4800, 1045, 280, 110),
    "ssworld":      (5140, 1045, 280, 110),
    "ssfeat":       (5500, 1215, 280, 110),
    "sstest":       (5860, 1215, 280, 110),
    "ssbg8":        (-20,  1190, 6180, 140),  # 验证层行带 (原宽 1150 盖不住自己的节点)
    "ssvideo":      (5500, 1365, 280, 110),
    "ss3d_view":    (5860, 1365, 280, 110),
    "ssvideo2":     (6220, 1365, 280, 110),
    "ssbg9":        (-20,  1345, 6900, 170),  # 可视化行带 (原 y=1325 与验证层行带贴死)
    # 🧩 43D 状态向量 —— 右移让 触觉感知→obs 变前向
    "ssobs":        (1048,  175, 280, 110),
}

# ── 端口声明 (只影响详情面板文字, 几何由 link 顺序决定) ──
PORTS = {
    "ssdec": (["in1", "in2", "in3", "in4"], ["out1"]),
    "ssff":  (["in1", "in2", "in3"], ["out1"]),
    "sssched": (["in1", "in2", "in3", "in4", "in5", "in6", "in7", "in8"], ["out1"]),
}
# 端口语义名 (老倪看详情面板要自解释)
PORT_LABEL = {
    "ssdec": {"in1": "潜空间 z (VLM)", "in2": "L4 条件 (INTACT 解码器)",
              "in3": "接触流形坐标", "in4": "性能流形代价"},
    "ssff": {"in1": "DiT action", "in2": "标杆 u_ff", "in3": "obs 43D (前馈主输入)"},
    "sssched": {"in1": "任务Token序列 (LLM)", "in2": "恢复建议 (异常推理)",
                "in3": "工作空间势场 (总装记忆)", "in4": "流程势场 (L3记忆)",
                "in5": "标杆直通建议 (L2记忆)", "in6": "质量门 (AOI)",
                "in7": "u_ff 前馈建议", "in8": "contact+残差 (状态校正器)"},
}


def main():
    src = open(FLOW, encoding="utf-8").read()
    j = json.loads(src)
    bak = f"{FLOW}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(FLOW, bak)
    print(f"备份 → {bak}")

    nodes = {n["id"]: n for n in j["nodes"]}
    moved = []
    for nid, (x, y, w, h) in POS.items():
        n = nodes.get(nid)
        if n is None:
            raise SystemExit(f"❌ 找不到节点 {nid}")
        old = (n.get("x"), n.get("y"), n.get("w"), n.get("h"))
        if (x, y, w, h) != old:
            moved.append((nid, n.get("name", "")[:22], old, (x, y, w, h)))
        n["x"], n["y"], n["w"], n["h"] = x, y, w, h
        if n.get("type") != "row_bg":
            n["h"] = max(h, 110)

    for nid, (ins, outs) in PORTS.items():
        n = nodes[nid]
        n["inputs"] = [{"id": p, "label": PORT_LABEL.get(nid, {}).get(p, p), "dtype": "any"} for p in ins]
        n["outputs"] = [{"id": p, "label": p, "dtype": "any"} for p in outs]

    # 连线全局排序: 出线口/入线口 slot 单调于来向 → 不交叉
    def key(lk):
        s, d = nodes.get(lk["f"]), nodes.get(lk["t"])
        if not (s and d):
            return (9e9, 9e9, 9e9, 9e9)
        return (s["y"], s["x"], d["y"], d["x"])

    before = [lk["id"] for lk in j["links"]]
    j["links"].sort(key=key)
    after = [lk["id"] for lk in j["links"]]
    reorder = sum(1 for a, b in zip(before, after) if a != b)

    out = json.dumps(j, indent=1, ensure_ascii=False) + "\n"
    assert len(json.loads(out)["nodes"]) == len(j["nodes"])
    open(FLOW, "w", encoding="utf-8").write(out)

    print(f"\n移动节点 {len(moved)} 个:")
    for nid, nm, old, new in moved:
        print(f"  {nid:<14}{nm:<24} ({old[0]},{old[1]},{old[2]}x{old[3]}) → ({new[0]},{new[1]},{new[2]}x{new[3]})")
    print(f"\n连线顺序调整: {reorder}/{len(after)} 位不同 (按 源y→源x→目标y→目标x 排序)")
    print(f"节点 {len(j['nodes'])} · 连线 {len(j['links'])}")


if __name__ == "__main__":
    main()
