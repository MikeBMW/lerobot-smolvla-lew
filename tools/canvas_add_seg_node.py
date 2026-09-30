#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 canvas_add_seg_node.py — 把「开放词汇分割 (SAM3 分割anything)」节点接入状态空间画布 (L2 感知面)

架构口径 (2026-09-29 老倪: 状态空间缺分割能力):
  · 分割是**感知原语**(图像+概念提示词 → 该概念的所有实例掩膜), 与 🎯 YOLO 目标检测**同一层同一排**:
    都落在 L2「分段感知 (检测/触觉/2D→3D/质量)」行带里 ⇒ 所以放在 ssyolo 右侧, 同一水平线 (y 与 ssyolo 齐)。
  · 概念提示词来自 **L5**(意图), 帧来自**数据源**; 掩膜送去 2D→3D 解算与 VLM 视觉编码 ⇒ 入 2 出 2, 不孤岛不断头。

硬断言 (照 canvas_add_manifold_engine.py 的模板):
  ① 幂等 (已存在则跳过) ② 落在 L2 分段感知行带内, y 与 ssyolo 对齐
  ③ 与既有节点零重叠 ④ x 落在 ssyolo 右侧那块空档内且留边
  ⑤ 连线全前向 (源 x < 目标 x) 且不重复 ⑥ 坐标全 int ⑦ 写盘用备份 + 原子替换, 写后**回读核验**

用法 (改画布前先看 studio 是否在跑 —— GUI 内存版可能把磁盘版盖回去):
    ./gui-venv311/bin/python tools/canvas_add_seg_node.py            # dry-run
    ./gui-venv311/bin/python tools/canvas_add_seg_node.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW_LINK = os.path.join(ROOT, "flows", "state_space_obs.json")
# 🐛 2026-09-29 踩过: 仓库根这份是**软链**, 真源在包里 (src/lerobot/engineering/flows/...)。
#    直接用 os.replace 写软链路径会把软链替换成普通文件 (git 里 T 类型变更, 真源反而没改) ⇒
#    一律按 realpath 写**真源**, 软链保持不动。
FLOW = os.path.realpath(FLOW_LINK)

NID = "ss_seg"
NAME = "🧩 开放词汇分割 (SAM3 分割anything)"
W, H = 200, 68
ANCHOR = "ssyolo"                      # 同排锚点: 分割紧邻检测 (同一感知面)
Y_TOL = 6                              # 与锚点 y 对齐容差
GAP_MIN = 20                           # 与锚点最小间隙(px)

INPUTS = [("ssdata", "帧 (真机/仿真图像源)"),
          ("ss_l5", "概念提示词 (L5 给的意图: 文本/框/点)")]
OUTPUTS = [("ss2d3d", "实例掩膜 → 2D→3D 解算 (掩膜内中位深度)"),
           ("ssvlm", "掩膜/轮廓特征 → VLM 视觉编码")]

PARAMS = {
    "state_space": True,
    "segmentation": True,
    "open_vocabulary": True,
    "kind": "real",
    "layer": "L2",
    "role": "L2 感知原语 — 一帧 + 概念提示词(文本/框/点) → 该概念的**所有实例掩膜**(像素级); 与 L2-A01 YOLO 同级(框→轮廓, 固定类→开放词汇)",
    "intent_from": "L5 (VLM/人/工单给概念; 本节点不自造概念)",
    "model": "facebook/sam3 (848M: 共享视觉编码 + DETR 检测器 + SAM2 式跟踪器)",
    "engine": "transformers Sam3Model / Sam3Processor (本机 transformers 5.16.1) + 权重=HF 逐文件镜像(官方 gated, 用镜像)",
    "weights_dir": "/home/ubuntu/zmax_data/models/sam3_hf (model.safetensors 3.44GB fp32 → bf16 载入)",
    "api": "POST http://127.0.0.1:8796/seg {cam|image_path|image_b64, texts[], three_d, write_spec} · GET /health",
    "source": "tools/sam3_seg.py",
    "source_symbol": "def segment(img_bgr",
    "run": "python tools/sam3_seg.py --serve --port 8796   (显存独占 ≈2GB, 按需调用, 不逐帧常开)",
    "overlay": "写 data/scene/overlay_spec.json 的 origin='seg' / kind='mask' (品红轮廓 + 半透明填充; 与 sim/vlm/det 按 origin 合并)",
    "license": "SAM License (允许商用; 禁军事/ITAR 用途; 再分发须带许可)",
    "modes": "PCS 图像(文本→所有实例掩膜) · PCS 视频(文本→跨帧跟踪) · PVS(点/框/mask → 单实例精修, SAM2 兼容接口)",
    "caveat": "1008px 输入 + 848M 参数 ⇒ 4060(8GB) 上不能与别的模型同刻常驻; 定位=关键帧/触发式(按钮/画布节点/标注批次), 不是 30fps 逐帧",
    "desc": "状态空间的分割能力: 把'检测框'升级成'像素掩膜', 并把概念从固定类别升级成开放词汇(分割anything)",
}


def band_of(n, bands):
    for b in bands:
        if b["y"] <= n["y"] <= b["y"] + b.get("h", 0):
            return b
    return None


def next_port(links, node, side):
    used = set()
    for L in links:
        if side == "out" and L["f"] == node:
            used.add(str(L.get("f_port")))
        if side == "in" and L["t"] == node:
            used.add(str(L.get("t_port")))
    for k in range(1, 40):
        p = "%s%d" % ("out" if side == "out" else "in", k)
        if p not in used:
            return p
    return "in1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    byid = {n["id"]: n for n in nodes}

    if NID in byid:
        print("⏭ %s 已存在 → 幂等跳过 (若要改参数请先手工移除该节点)" % NID)
        return 0
    for sid, _ in INPUTS + OUTPUTS:
        assert sid in byid, "引用了不存在的节点 %s" % sid

    anchor = byid[ANCHOR]
    bands = [n for n in nodes if n.get("type") == "row_bg"]
    band = band_of(anchor, bands)
    assert band is not None and "L2" in str(band.get("name", "")), "锚点 %s 不在 L2 行带" % ANCHOR
    Y = anchor["y"]

    # ③ 在「锚点右侧 → 行带右界」这一段里找最靠左的可放位置 (整块 W×H 不与任何节点相交)
    def collides(x, y):
        for n in nodes:
            if n.get("type") == "row_bg":
                continue
            if x < n["x"] + n.get("w", 0) and n["x"] < x + W and y < n["y"] + n.get("h", 0) and n["y"] < y + H:
                return n
        return None

    x0 = anchor["x"] + anchor.get("w", 0) + GAP_MIN
    x = x0
    hit = None
    while x + W <= band["x"] + band["w"]:
        hit = collides(x, Y)
        if hit is None:
            break
        x += 10
    assert hit is None, "锚点 %s 右侧行带内放不下 %dx%d (先被 %s 挡住)" % (ANCHOR, W, H, hit["id"])
    assert abs(Y - anchor["y"]) <= Y_TOL, "y 与锚点未对齐"
    assert band["y"] <= Y <= band["y"] + band["h"] - H, "新节点超出行带: y=%d 带=%s..%s" % (
        Y, band["y"], band["y"] + band["h"])
    print("②③ 位置核验: y=%d 与锚点 %s(%d) 对齐 ✓ · 整块 %dx%d 与 %d 个节点零重叠 ✓ · 落在行带 [%s] ✓"
          % (Y, ANCHOR, anchor["y"], W, H, len(nodes), band["name"][:26]))
    print("   横向: 锚点右缘 %d → 新节点 x=%d..%d (间隙 %d)" % (
        anchor["x"] + anchor.get("w", 0), x, x + W, x - (anchor["x"] + anchor.get("w", 0))))

    node = {"id": NID, "type": "model", "name": NAME, "x": int(x), "y": int(Y),
            "w": int(W), "h": int(H), "icon": "🧩", "color": "#ff5cc8",
            "params": PARAMS, "inputs": ["in%d" % (i + 1) for i in range(len(INPUTS))],
            "outputs": ["out%d" % (i + 1) for i in range(len(OUTPUTS))], "actions": []}
    nodes.append(node)

    new_links = []
    for sid, lab in INPUTS:
        new_links.append({"id": "lk0929_%s_%s" % (sid, NID), "f": sid, "t": NID,
                          "f_port": next_port(links + new_links, sid, "out"),
                          "t_port": next_port(links + new_links, NID, "in"), "label": lab})
    for tid, lab in OUTPUTS:
        new_links.append({"id": "lk0929_%s_%s" % (NID, tid), "f": NID, "t": tid,
                          "f_port": next_port(links + new_links, NID, "out"),
                          "t_port": next_port(links + new_links, tid, "in"), "label": lab})

    # ⑤ 全前向 + 不重复 ⑥ int 坐标
    xof = {n["id"]: n["x"] for n in nodes}
    for L in new_links:
        assert xof[L["f"]] < xof[L["t"]], "非前向连线 %s→%s" % (L["f"], L["t"])
        assert not any(t["f"] == L["f"] and t["t"] == L["t"] for t in links), "重复连线 %s" % L
    for n in nodes:
        for k in ("x", "y", "w", "h"):
            if k in n:
                assert isinstance(n[k], int), "非 int 坐标 %s.%s" % (n["id"], k)
    links.extend(new_links)
    print("⑤ 接线: 入 %d + 出 %d = %d 条 (全前向, 无重复) ✓" % (len(INPUTS), len(OUTPUTS), len(new_links)))
    for L in new_links:
        print("   %-10s(%s) → %-10s" % (L["f"], L["label"][:34], L["t"]))

    if not a.apply:
        print("(dry-run; 加 --apply 落地)")
        return 0

    # ⑦ 备份 + 原子写 + 回读核验
    d["nodes"], d["links"] = nodes, links
    bdir = os.path.join(ROOT, "backups")
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, "state_space_obs_%s_pre_seg.json" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(FLOW, bak)
    tmp = FLOW + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FLOW)
    back = json.load(open(FLOW, encoding="utf-8"))
    ids = {n["id"] for n in back["nodes"]}
    assert NID in ids, "回读核验失败: 节点没落盘"
    n2 = [n for n in back["nodes"] if n["id"] == NID][0]
    assert (n2["x"], n2["y"], n2["w"], n2["h"]) == (x, Y, W, H), "回读坐标不符"
    got = [l for l in back["links"] if l["f"] == NID or l["t"] == NID]
    assert len(got) == len(new_links), "回读连线数不符: %d != %d" % (len(got), len(new_links))
    print("⑦ 回读核验 ✓ 备份=%s" % os.path.relpath(bak, ROOT))
    print("✅ 已写入 %s: 节点 %d · 连线 %d" % (os.path.relpath(FLOW, ROOT), len(back["nodes"]), len(back["links"])))
    print("CANVAS_SEG_NODE_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
