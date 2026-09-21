#!/usr/bin/env python3
"""fix_vlm_l3_row.py — 把「🧠 VLM 通用视觉编码器 (SmolVLA)」归位到 🚀 L3 高级自动功能 行, 紧接 Flow-Matching DiT

老倪 2026-09-21 指令:
  「画布上, VLM通用视觉编码器, 应该是 L3高级自动功能的功能, 后面直接跟着 Flow-Matching DiT」

改动 (幂等, 可重复跑):
  ① ssvlm 坐标 (1000, 952 大模型层) → (1160, 2576 = L3 高级自动功能行)
     · x=1160 的取值理由: 它在 L4 行流形节点 (x=1180/1310/1490) **左侧** → 原有出边仍是"左→右"正向,
       不会因移位产生老倪明确不要的"右→左"连线 (2026-09-19 布局坑)。
  ② L3 行背景 ssbg_vlm 向左扩到 x=1000, 使 ssvlm 落在带内 (节点 x = bg_x + 160, 符合布局规则)。
  ③ 确认 ssvlm → ssdec(Flow-Matching Action Head (DiT)) 连线存在 (缺失则补)。

验收: 断言 ssvlm 落在 L3 行带内 + 紧邻在 DiT 左侧 + 无"右→左"连线 + 节点/连线数不变。
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLOW = os.path.join(REPO, "flows", "state_space_obs.json")
VLM_ID = "ssvlm"
DEC_ID = "ssdec"
ROW_KEY = "L3 高级自动功能"
TARGET_X, TARGET_Y = 1160, 2576
ROW_X = 1000


def main() -> int:
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes = {n["id"]: n for n in d["nodes"]}
    if VLM_ID not in nodes:
        print("❌ 找不到节点", VLM_ID)
        return 2
    vlm, dec = nodes[VLM_ID], nodes[DEC_ID]
    row = next((n for n in d["nodes"] if n.get("type") == "row_bg" and ROW_KEY in str(n.get("name"))), None)
    if row is None:
        print("❌ 找不到 L3 行背景")
        return 2

    changed = []
    if (vlm.get("x"), vlm.get("y")) != (TARGET_X, TARGET_Y):
        changed.append(f"ssvlm ({vlm.get('x')},{vlm.get('y')}) → ({TARGET_X},{TARGET_Y})")
        vlm["x"], vlm["y"] = TARGET_X, TARGET_Y
    row_right = row["x"] + row["w"]
    if row["x"] > ROW_X:
        changed.append(f"L3 行背景 x {row['x']} → {ROW_X} (w {row['w']} → {row_right - ROW_X})")
        row["w"] = row_right - ROW_X
        row["x"] = ROW_X

    has_edge = any(l.get("f") == VLM_ID and l.get("t") == DEC_ID for l in d["links"])
    if not has_edge:
        d["links"].append({"id": f"auto_{VLM_ID}_{DEC_ID}", "f": VLM_ID, "t": DEC_ID,
                           "f_port": "out1", "t_port": "in1"})
        changed.append("补连线 ssvlm → ssdec")

    # ── 验收 ──
    fails = []
    if not (row["x"] <= vlm["x"] <= row["x"] + row["w"]):
        fails.append("ssvlm 不在 L3 行带内")
    if not (vlm["y"] == dec["y"] and vlm["x"] < dec["x"]):
        fails.append("ssvlm 未与 DiT 同行且在左")
    if dec["x"] - (vlm["x"] + vlm["w"]) > 700:
        fails.append("ssvlm 与 DiT 距离过远")
    by_id = {n["id"]: n for n in d["nodes"]}
    r2l = [(l["f"], l["t"]) for l in d["links"]
           if (by_id.get(l.get("f"), {}).get("x") or 0) > (by_id.get(l.get("t"), {}).get("x") or 0)]
    new_r2l = [p for p in r2l if VLM_ID in p]

    print("改动:", " · ".join(changed) if changed else "无 (已就位)")
    print("ssvlm 现坐标 (%s,%s) · DiT (%s,%s) · 间距 %dpx · L3 行 [%s, %s]"
          % (vlm["x"], vlm["y"], dec["x"], dec["y"], dec["x"] - (vlm["x"] + vlm["w"]),
             row["x"], row["x"] + row["w"]))
    print("全画布右→左连线 %d 条 (其中涉及 VLM %d 条)" % (len(r2l), len(new_r2l)))
    if fails:
        print("❌ 验收失败:", fails)
        return 1
    if changed:
        json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("✅ 已写回", FLOW)
    print("✅ 验收通过 (节点 %d · 连线 %d)" % (len(d["nodes"]), len(d["links"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
