#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_add_hil_node.py — 在状态空间画布 L5 层加「🙋 HIL 人机在环」节点 (2026-09-26 老倪)

需求: "在状态空间工程增加 HIL Human in the loop 节点, 向 ECS web 发送状态空间状态;
      我在 ECS 的浏览器上能给出要求; 就用 hermes 的标准浏览器的形式"
职责: ① 把状态空间工程的状态(分层/阶段/事件预测/资源/取证) 发 ECS web  ② 收人在浏览器给的指示 → 回灌工程
位置: L5 大模型层行, DeepSeek 右侧空位 (2136..2436 宽 300 → 230 宽居中 = x 2171), 保持画布简洁
硬断言: id 唯一 / int 坐标 / 零重叠(排除行背景) / 在 L5 行带 / 连线全前向 / 端口存在 / 备份
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")

NID = "n_hil"
W, H = 230, 68
ANCHOR = "n_dsvl"           # 以 DeepSeek 为锚: 放它右侧空位
Y = 554                     # L5 行带
X = 2171                    # 2136(DeepSeek右) + (300-230)/2


def main() -> int:
    d = json.load(open(FLOW, encoding="utf-8"))
    ns = d["nodes"]
    dry = "--dry-run" in sys.argv
    by = {n["id"]: n for n in ns}

    # ① id 唯一
    assert NID not in by, "id 已存在: %s" % NID
    # ② 锚点同行带 + 位置关系 (HIL 在 DeepSeek 右侧)
    a = by[ANCHOR]
    assert a["y"] == Y, "锚点 %s 不在 L5 行带 y=%d (实为 %d)" % (ANCHOR, Y, a["y"])
    assert X >= a["x"] + a["w"], "HIL 必须落在 %s 右侧 (x=%d >= %d)" % (ANCHOR, X, a["x"] + a["w"])
    # ③ 零重叠 (排除行背景 bg/row_bg) + int 坐标
    for n in ns:
        p = n.get("params") or {}
        if p.get("bg") or p.get("row_bg"):
            continue
        assert not (X < n["x"] + n["w"] and n["x"] < X + W and Y < n["y"] + n["h"] and n["y"] < Y + H), \
            "与 %s 重叠" % n["id"]
    for k, v in (("x", X), ("y", Y), ("w", W), ("h", H)):
        assert isinstance(v, int), "%s 必须是 int" % k

    node = {
        "id": NID, "type": "node", "name": "🙋 HIL 人机在环 · 状态↔指示",
        "x": X, "y": Y, "w": W, "h": H, "icon": "🙋", "color": "#39d353",
        "inputs": [{"id": "in1", "name": "L5 判读/建议"}, {"id": "in2", "name": "工程状态"}],
        "outputs": [{"id": "out1", "name": "人工指示 → 规划"}],
        "params": {
            "state_space": True, "hil": True, "web": True,
            "transport": "ECS 中转 /api/relay/{hil/state, agent/prompt, agent/reply}",
            "push_s": 5, "readonly": True,
            "web_page": "https://datadrive.world/hil.html",
            "source": "src/lerobot/policies/left_right/state_space/hil_bridge.py",
            "source_symbol": "class HilBridge",
            "desc": "状态空间状态→ECS web(浏览器, hermes 形式)展示核心思想; 人的指示经浏览器回灌工程; 红线: 不下发真机动作",
        },
    }
    links = [
        {"id": "lkhil_dsvl", "f": ANCHOR, "t": NID, "f_port": "out1", "t_port": "in1",
         "label": "L5 判读/建议 → 人机在环展示"},
        {"id": "lkhil_ssllm", "f": NID, "t": "ssllm", "f_port": "out1", "t_port": "in1",
         "label": "人工指示 → L3 规划/编排"},
    ]

    # ④ 连线: 端口存在 + 全前向 + 不重复
    ids = set(by) | {NID}
    seen = {l["id"] for l in d["links"]}
    for l in links:
        assert l["id"] not in seen, "连线 id 重复: %s" % l["id"]
        assert l["f"] in ids and l["t"] in ids, "连线端点不存在"
        for side, nid, port in (("f", l["f"], l["f_port"]), ("t", l["t"], l["t_port"])):
            n = node if nid == NID else by[nid]
            key = "outputs" if side == "f" else "inputs"
            ports = [p["id"] if isinstance(p, dict) else p for p in (n.get(key) or [])]
            assert port in ports or not ports, "%s 无端口 %s" % (nid, port)
        fx = X if l["f"] == NID else by[l["f"]]["x"]
        tx = X if l["t"] == NID else by[l["t"]]["x"]
        assert fx < tx, "连线非前向: %s" % l["id"]

    print("✅ 六条硬断言全过 (id/坐标/零重叠/L5 行带/前向/端口)")
    print("   节点 %s @ (%d,%d) %dx%d · 入线 %d 出线 %d" %
          (NID, X, Y, W, H, sum(1 for l in links if l["t"] == NID), sum(1 for l in links if l["f"] == NID)))
    if dry:
        print("   --dry-run: 未写盘")
        return 0

    bak = FLOW + ".bak_hil_%d" % int(time.time())
    shutil.copy2(FLOW, bak)
    ns.append(node)
    d["links"].extend(links)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("   已写入 %s (节点 %d / 连线 %d) · 备份 %s" %
          (os.path.basename(FLOW), len(ns), len(d["links"]), os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
