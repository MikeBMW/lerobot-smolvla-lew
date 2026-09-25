#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_add_web_agent_node.py — 在 L5 大模型层「DeepSeek 节点左侧」加「🌐 Web 智能体桥」节点

老倪 (2026-09-25): 「开通一个状态空间 L5 的新节点, 用于与 web 的 agent 交换信息 … 位置就在 L5 大模型层,
在 deepseek 节点左侧就行; 你来构图」+「保持画布简洁清晰」→ 只加 **1 节点 2 连线** (入: 工程记忆能力清单;
出: 提示词意图 → L5 场景理解), 回执走 ECS 中转(画布外副作用, 不再画线)。

硬断言 (照 tools/canvas_add_manifold_engine.py 的纪律):
  ① 节点 id 唯一 · ② 坐标 int · ③ 与全图零重叠 · ④ 落在 L5 行带内
  ⑤ 只在 n_dsvl 左侧 (x + w < n_dsvl.x) · ⑥ 与 n_dsvl 同行 (y 相同)
  ⑦ 连线前向 (f.x < t.x) · 端口存在 · 不与既有连线重复
用法: ./gui-venv311/bin/python tools/canvas_add_web_agent_node.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")

NODE_ID = "n_web_agent"
W, H = 230, 68
NODE = {
    "id": NODE_ID,
    "type": "model",
    "name": "🌐 Web 智能体桥 · 远程提示词",
    "icon": "🌐",
    "color": "#a371f7",
    "inputs": ["in1"],
    "outputs": ["out1"],
    "params": {
        "state_space": True,
        "web_agent": True,
        "readonly": True,
        "transport": "ECS 中转 /api/relay/agent/{prompt,reply,status} (游标式 append-only jsonl, 只读幂等)",
        "poll_s": 5,
        "endpoints": {
            "web→本机": "POST /api/relay/agent/prompt {text} → 本机 5s 轮询 GET /api/relay/agent/prompt?after=N",
            "本机→web": "POST /api/relay/agent/reply → web GET /api/relay/agent/reply?after=N",
        },
        "funcs": ["help", "status", "canvas", "reports", "memory", "skills", "sim", "net",
                  "aoi", "robot_read", "feishu"],
        "redline": "只读白名单: 提示词命中动作类关键词(插入/抓取/夹爪/移动/拍照/示教…) → 拒答+记审计, 不转发",
        "desc": ("[L5 人机在环] web 上的 agent 用**自然语言提示词**远程调用状态空间的**只读功能**"
                 "(状态/画布/报告/记忆/技能/仿真自检/网络/AOI 只读判决/真机只读信号/飞书通知), 并把执行结果"
                 "回执到 web; 动作类提示词一律拒答 (老倪红线: 不动真机)。画布侧: 入=工程记忆能力清单, "
                 "出=提示词意图 → L5 场景理解(DeepSeek); 回执不经画布(中转副作用)。"),
        "source": "src/lerobot/policies/left_right/state_space/web_agent_bridge.py",
        "source_symbol": "class WebAgentBridge (dispatch/poll_once/watch)",
    },
}
LINKS = [
    {"id": "lkwa_mem", "f": "n_eng_mem", "t": NODE_ID, "f_port": "out1", "t_port": "in1",
     "label": "能力清单/工程记忆 → 远程可调功能面"},
    {"id": "lkwa_dsvl", "f": NODE_ID, "t": "n_dsvl", "f_port": "out1", "t_port": "in3",
     "label": "远程提示词意图 → L5 场景理解"},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    d = json.load(open(FLOW, encoding="utf-8"))
    ns, ls = d["nodes"], d["links"]
    by_id = {n["id"]: n for n in ns}
    assert NODE_ID not in by_id, f"{NODE_ID} 已存在 (幂等: 不必重复加)"
    for need in ("n_dsvl", "n_eng_mem"):
        assert need in by_id, f"缺参考节点 {need}"

    dsvl, mem = by_id["n_dsvl"], by_id["n_eng_mem"]
    # ① 位置: deepseek 左侧, 同行, 落在 [mem 右沿, dsvl 左沿] 空档正中
    gap_l, gap_r = mem["x"] + mem["w"], dsvl["x"]
    assert gap_r - gap_l >= W + 40, f"空档不足: {gap_l}~{gap_r} ({gap_r-gap_l}px < {W+40})"
    X = int(gap_l + (gap_r - gap_l - W) // 2)
    Y = int(dsvl["y"])
    print(f"① 位置: 空档 {gap_l}~{gap_r} → x={X} (左空 {X-gap_l}px · 右空 {gap_r-(X+W)}px) · y={Y}")
    assert X + W < dsvl["x"], "必须在 DeepSeek 左侧"
    assert Y == dsvl["y"], "必须与 DeepSeek 同行带"

    node = dict(NODE, x=X, y=Y, w=W, h=H)
    # ② 零重叠 + int 坐标 (⚠️ 行带背景节点 bg/row_bg 是整行矩形, 不能算重叠 — 否则永远报"与 ssbg5 重叠")
    for n in ns:
        if n.get("params", {}).get("bg") or n.get("params", {}).get("row_bg"):
            continue
        assert not (X < n["x"] + n["w"] and n["x"] < X + W and Y < n["y"] + n["h"] and n["y"] < Y + H), \
            f"与 {n['id']} 重叠"
    for k in ("x", "y", "w", "h"):
        assert isinstance(node[k], int), f"非 int 坐标 {k}"
    real = [n for n in ns if not (n.get("params", {}).get("bg") or n.get("params", {}).get("row_bg"))]
    print(f"② 与全图 {len(real)} 个实节点零重叠 · 坐标全 int ✅")

    # ③ 行带核验 (L5 = 大模型层行背景)
    band = [n for n in ns if n.get("params", {}).get("bg") and "大模型层" in str(n.get("name", ""))]
    assert band, "找不到 L5 行带背景节点"
    b = band[0]
    assert b["y"] <= Y <= b["y"] + b["h"], f"不在 L5 行带 ({b['name'][:20]}) 内"
    print(f"③ 落在行带 [{b['name'][:24]}] ✅")

    # ④ 连线: 端口/方向/重复
    ids = set(by_id) | {NODE_ID}
    xy = {n["id"]: n["x"] for n in ns}
    xy[NODE_ID] = X
    for L in LINKS:
        assert L["f"] in ids and L["t"] in ids, f"端口节点不存在: {L}"
        fp = by_id.get(L["f"], node).get("outputs", [])
        tp = by_id.get(L["t"], node).get("inputs", [])
        assert L["f_port"] in fp, f"{L['f']} 无 {L['f_port']}"
        assert L["t_port"] in tp, f"{L['t']} 无 {L['t_port']}"
        assert xy[L["f"]] < xy[L["t"]], f"非前向连线 {L['f']}→{L['t']}"
        assert not any(x["f"] == L["f"] and x["t"] == L["t"] for x in ls), f"重复连线 {L}"
        assert not any(x["id"] == L["id"] for x in ls), f"重复连线 id {L['id']}"
    print(f"④ 连线 {len(LINKS)} 条: 端口存在 · 全前向 · 无重复 ✅")

    if a.dry_run:
        print("(dry-run: 未写盘)")
        return 0
    bak = FLOW + f".bak_pre_webagent_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(FLOW, bak)
    d["nodes"].append(node)
    d["links"].extend(LINKS)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"⑤ 已写入 {FLOW}\n   节点 {len(ns)}→{len(d['nodes'])} · 连线 {len(ls)}→{len(d['links'])} · 备份 {os.path.basename(bak)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
