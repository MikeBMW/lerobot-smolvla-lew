#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""post_layout_fix.py — 布局后处理 (老倪 2026-09-19 三条要求)

① 画布左上角不能留 "L4专家自主功能" 残字 → 停用带 ssbg6 直接移除
② 🧿 DeepSeek-VL 节点必须留在原位置可见 → 大模型层锚定坐标 (图深度重排会把它顶到 x=7400)
③ 画布不能出现 "右侧输出连左侧输入" → 右→左边从画布剔除, 语义存 docs/design/feedback-edges-v510.json
"""
import json
import os

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FLOW = os.path.join(REPO, "flows", "state_space_obs.json")
DEAD = ["ssbg6"]
PIN = {"n_dsvl": (470, 952), "n_vlm_llm": (800, 952), "ss_mem_share": (1130, 952),
       "n_eng_mem": (140, 952), "ssllm": (1460, 952), "n_mem_links": (1790, 952),
       "n_intent_bundle": (1790, 1076), "ssreason": (2780, 952), "ssskill": (6080, 952),
       "n_intent_direct": (8390, 1764),   # 紧贴上上游 ssintact_dec(8060) 右侧 → 边为正向, 且不孤立
 "n_skill_dict": (6410, 1076), "ssllm_in": (9050, 952),
}


def main():
    d = json.load(open(FLOW, encoding="utf-8"))
    before_n, before_l = len(d["nodes"]), len(d["links"])
    d["nodes"] = [n for n in d["nodes"] if n["id"] not in DEAD]
    nd = {n["id"]: n for n in d["nodes"]}
    for k, (x, y) in PIN.items():
        if k in nd:
            nd[k]["x"], nd[k]["y"] = x, y
    # 右→左被剔除后变成孤立的真能力节点: **移到消费者左侧 + 正向重建边** (老倪: 不许孤立, 更不许有右→左线)
    RESTORE = [("ssintact_dec", "n_intent_direct", "Δz → 意图直读")]
    have = {(l["f"], l["t"]) for l in d["links"]}
    for _f, _t, _lab in RESTORE:
        if _f in nd and _t in nd and (_f, _t) not in have:
            d["links"].append({"id": "lkrs_%s_%s" % (_f, _t), "f": _f, "t": _t,
                               "f_port": "out1", "t_port": "in1", "label": _lab})
    back = [l for l in d["links"] if l["f"] in nd and l["t"] in nd
            and nd[l["f"]].get("type") != "row_bg" and nd[l["t"]].get("type") != "row_bg"
            and nd[l["f"]]["x"] >= nd[l["t"]]["x"]]
    if back:
        p = os.path.join(REPO, "docs", "design", "feedback-edges-v510.json")
        json.dump(back, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    keep = [l for l in d["links"] if not any(l is b for b in back)]
    d["links"] = keep
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("节点 %d → %d (移除停用带 %d)" % (before_n, len(d["nodes"]), before_n - len(d["nodes"])))
    print("连线 %d → %d (剔除右→左 %d · 存 docs/design/feedback-edges-v510.json)" % (before_l, len(keep), len(back)))
    print("🧿 n_dsvl 位置:", nd["n_dsvl"]["x"], nd["n_dsvl"]["y"], "· 👁 n_vlm_llm:", nd["n_vlm_llm"]["x"], nd["n_vlm_llm"]["y"])


if __name__ == "__main__":
    main()
