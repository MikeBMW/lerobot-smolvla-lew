#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_add_l5_node.py — 加「🧿 L5 · 视觉语言自动标注 → L2/L3/L4 监督 → 自动训练」节点

老倪需求 (2026-09-28): 「能力档位节点增加 L5 档位, 选 L5 + 点运行 → 大模型视觉语言能力
自动标注, 为 L2 L3 L4 提供监督标注数据, 同时自动启动训练流程」

本脚本只做**画布真源**的机械改动 (不含运行逻辑):
  1) 加 1 个节点 ss_l5 (type=model, 注册表合法值) 落在大模型层行帯 (y 554..972)
  2) 把 能力档位节点 sscap 的 desc 更新为四档 (L2/L3/L4/L5)
  3) 接线: 📦 metaworld 数据源 → L5 标注 (帧输入)
           L5 → 🎛 L4 LoRA / 🎛 L3 LoRA / 🎯 YOLO  (监督标注 → 训练)
  全部: 六断言 (id 唯一 / int 坐标 / 零重叠[排除 bg,row_bg] / 落正确行帯 / 端口存在且前向 / 无重复)
        + 连线后孤立节点=0 + 写盘前备份到 flows/_archive/ 并打印还原命令

用法: ./gui-venv311/bin/python tools/canvas_add_l5_node.py [--dry]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

R = "/home/ubuntu/zmax_rel"
FLOW = os.path.join(R, "flows/state_space_obs.json")
ARCHIVE = os.path.join(R, "flows/_archive")

NID = "ss_l5"
NAME = "🧿 L5 · 视觉语言自动标注 → L2/L3/L4 监督 → 自动训练"
DESC = ("[L5 档] ▶运行(档位=L5) → 后台异步跑 tools/auto_annotate.py: 6 路实拍 → DeepSeek-V4-Flash "
        "视觉语言理解 → 场景描述+边界框+标注图 (每帧约 120s, 异步不阻塞 GUI); 产物按监督口径落盘: "
        "L2 = YOLO 格式数据集(images/labels+data.yaml, 供全量训练) · L3/L4 = 监督标注 manifest (jsonl); "
        "标注完成 → 自动接力训练: L2 YOLO 全量 (yolo_annot_train --base none) · L3 SmolVLA LoRA · "
        "L4 INTACT LoRA (tools/joint_train_all.py + lora_inject.py, 训完必 merge_lora_ckpt.py)。"
        "双击本节点 = 看闭环状态/产物; 状态徽章实时显示 标注pid/批次/训练阶段")
PARAMS = {
    "state_space": True,
    "l5_loop": True,
    "l5_capability_level": True,
    "orchestrator": "tools/l5_annotate_train_loop.py",
    "annotator": "tools/auto_annotate.py",
    "trainer": "tools/joint_train_all.py",
    "lora_inject": "tools/lora_inject.py",
    "lora_merge": "tools/merge_lora_ckpt.py",
    "x": 300, "y": 554, "w": 430, "h": 68,
    "inputs": ["in1"], "outputs": ["out1", "out2", "out3"],
}

# (源, 目标, 源端口, 目标端口, 标签)
ADD = [
    ("ssdata", NID, "out1", "in1", "6 路实拍/环境帧 → 视觉语言自动标注"),
    (NID, "ss_lora_l4", "out1", "in1", "L5 监督标注数据 → L4 INTACT LoRA 微调"),
    (NID, "ss_lora_l3", "out2", "in1", "L5 监督标注数据 → L3 SmolVLA LoRA 微调"),
    (NID, "ssyolo", "out3", "in1", "L5 监督标注数据 → L2 YOLO 检测 (全量训练)"),
]


def _p0(n, key, dflt):
    v = n.get(key) or [dflt]
    x = v[0]
    return x if isinstance(x, str) else str(x.get("id", dflt))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    by = {n["id"]: n for n in nodes}

    # ── 断言 1: id 唯一 ────────────────────────────────────────────────
    assert NID not in by, "节点已存在 (幂等: 无需重复加)"
    for nid in ("ssdata", "ss_lora_l4", "ss_lora_l3", "ssyolo", "sscap"):
        assert nid in by, "缺少引用节点 %s" % nid
    # 注册表合法 type 白名单 (致命坑: 非法 type → add_node KeyError → 加载循环中断 → 连线全丢)
    LEGAL = {"model", "data", "hardware", "condition", "bg", "row_bg"}
    assert "model" in LEGAL

    box = {"x": int(PARAMS["x"]), "y": int(PARAMS["y"]),
           "w": int(PARAMS["w"]), "h": int(PARAMS["h"])}
    # ── 断言 2: 坐标为 int ─────────────────────────────────────────────
    for k, v in box.items():
        assert isinstance(v, int), "%s 必须 int" % k
    # ── 断言 3: 零重叠 (排除 bg/row_bg 整行矩形) ───────────────────────
    for n in nodes:
        if n.get("type") in ("bg", "row_bg"):
            continue
        if not (box["x"] + box["w"] + 8 <= n["x"] or n["x"] + n["w"] + 8 <= box["x"] or
                box["y"] + box["h"] + 8 <= n["y"] or n["y"] + n["h"] + 8 <= box["y"]):
            raise AssertionError("与 %s (%s) 重叠" % (n["id"], n["name"][:24]))
    # ── 断言 4: 落在正确行帯 (大模型层) ────────────────────────────────
    band = [b for b in nodes if b.get("type") == "row_bg"
            and b["y"] <= box["y"] < b["y"] + b["h"]]
    assert band, "未落在任何行帯"
    b = band[0]
    assert box["y"] + box["h"] <= b["y"] + b["h"], "超出行帯下沿"
    assert "大模型层" in b["name"], "应落在大模型层行帯, 实际 %s" % b["name"]

    node = {"id": NID, "type": "model", "name": NAME, "icon": "🧿", "color": "#a371f7",
            "x": box["x"], "y": box["y"], "w": box["w"], "h": box["h"],
            "inputs": list(PARAMS["inputs"]), "outputs": list(PARAMS["outputs"]),
            "actions": [], "params": dict(PARAMS)}
    node["params"].pop("x"), node["params"].pop("y")
    node["params"].pop("w"), node["params"].pop("h")
    node["params"].pop("inputs"), node["params"].pop("outputs")

    nodes.append(node)
    by[NID] = node

    # ── 断言 5: 端口存在 + 前向 + 断言 6: 无重复连线 ──────────────────
    have = {(l["f"], l["t"]) for l in links}
    add = []
    for (f, t, fp, tp, lab) in ADD:
        ins = [x if isinstance(x, str) else str(x.get("id")) for x in (by[t].get("inputs") or [])]
        outs = [x if isinstance(x, str) else str(x.get("id")) for x in (by[f].get("outputs") or [])]
        assert tp in ins, "%s 无入端口 %s (有 %s)" % (t, tp, ins)
        assert fp in outs, "%s 无出端口 %s (有 %s)" % (f, fp, outs)
        assert (f, t) not in have, "重复连线 %s→%s" % (f, t)
        assert by[f]["x"] + by[f]["w"] <= by[t]["x"] + 1, \
            "反向线 %s→%s (%d > %d)" % (f, t, by[f]["x"] + by[f]["w"], by[t]["x"])
        add.append({"id": "lkl5_%02d" % (len(add) + 1), "f": f, "t": t,
                    "f_port": fp, "t_port": tp, "label": lab})

    # 更新能力档位节点 desc (四档) — sscap
    old_desc = by["sscap"]["params"].get("desc", "")
    by["sscap"]["params"]["desc"] = (
        "[数据源层·能力档位] 单击圆钮直选 / 双击循环: L2 基础(插装成功) → L3 +smolvla(插→拔→AOI→放回全链) "
        "→ L4 +流形预测世界模型(失败自主恢复直到完成) → L5 大模型视觉语言自动标注(L2/L3/L4 监督数据) "
        "+ 标注完成自动启动训练(L2 YOLO 全量 / L3 SmolVLA LoRA / L4 INTACT LoRA→merge)。档位驱动 ▶运行 任务链。")

    if a.dry:
        print("(--dry) 将加节点 %s @(%d,%d) %dx%d · %d 条连线"
              % (NID, box["x"], box["y"], box["w"], box["h"], len(add)))
        for l in add:
            print("   ", l["label"])
        return 0

    # ── 备份 (写盘前) ──────────────────────────────────────────────────
    os.makedirs(ARCHIVE, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(ARCHIVE, "state_space_obs_before_l5_%s.json" % ts)
    shutil.copy2(FLOW, bak)
    links.extend(add)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ── 连通性: 孤立节点必须为 0 ──────────────────────────────────────
    real = [n for n in nodes if n.get("type") not in ("bg", "row_bg")]
    deg = {n["id"]: [0, 0] for n in real}
    for l in links:
        if l["f"] in deg:
            deg[l["f"]][1] += 1
        if l["t"] in deg:
            deg[l["t"]][0] += 1
    orph = [k for k, v in deg.items() if v[0] == 0 and v[1] == 0]
    assert not orph, "出现孤立节点: %s" % orph
    assert deg[NID][0] >= 1 and deg[NID][1] >= 3, "新节点度数异常 %s" % deg[NID]

    print("✅ 节点 %s @ (%d,%d) %dx%d 入1出3 · 落在行帯 [%s]"
          % (NID, box["x"], box["y"], box["w"], box["h"], b["name"][:20]))
    print("   画布: %d 节点(%d 真) / %d 连线 · 孤立 %d · 新节点度数(in,out)=%s"
          % (len(nodes), len(real), len(links), len(orph), deg[NID]))
    print("   能力档位 desc: %s → %s" % (old_desc[:34] + "…", by["sscap"]["params"]["desc"][:34] + "…"))
    print("   备份: %s" % os.path.relpath(bak, R))
    print("   ↩️ 还原: cp %s %s" % (os.path.relpath(bak, R), os.path.relpath(FLOW, R)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
