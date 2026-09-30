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
       "ssz700": (470, 140),   # 🖥 Z700 真机信号 → 数据源行(左上=源头); 图深度重排曾把它顶到 x=5750, 使"真机帧→板检测"变成右→左
       "n_intent_direct": (8390, 1764),   # 紧贴上上游 ssintact_dec(8060) 右侧 → 边为正向, 且不孤立
 "n_skill_dict": (6410, 1076), "ssllm_in": (9050, 952),
       "ssinnov": (5750, 4076),   # 🧪 状态校正器 (原位; 断头已修 —— 出边在 RESTORE 里)
       #   → 「状态校正器→动作调制器(u_fb)」不再是右→左线, 不会被剔除 (2026-09-23 修断头)
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
    #   ⚠️ 这几条是「语义关键边」: 剔除后节点会变断头 → 下面**剔除之后**再补回 (顺序不能反)
    RESTORE = [("ssinnov", "sssched", "↩ 反馈 · contact+残差 → 动作调制 (u_fb)", "in8"),
               ("ssintact_dec", "n_intent_direct", "Δz → 意图直读", "in1"),
               ("ssz700", "n_board_frame", "真机帧 → 板检测 (20 圆点)", "in1")]
    back = [l for l in d["links"] if l["f"] in nd and l["t"] in nd
            and nd[l["f"]].get("type") != "row_bg" and nd[l["t"]].get("type") != "row_bg"
            and nd[l["f"]]["x"] >= nd[l["t"]]["x"]]
    if back:
        p = os.path.join(REPO, "docs", "design", "feedback-edges-v510.json")
        json.dump(back, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    keep = [l for l in d["links"] if not any(l is b for b in back)]
    d["links"] = keep
    # ⚠️ RESTORE 必须在**剔除之后**跑 —— 否则被剔除的语义关键边下次重跑不会再回来
    #   (2026-09-23 实证: 原顺序"先 RESTORE 后 purge" → 「状态校正器→动作调制器」被删后
    #    再也补不回来 → 节点成断头; 重排后关键反馈边可重复复跑)
    for _f, _t, _lab, _tp in RESTORE:
        if _f in nd and _t in nd and (_f, _t) not in {(l["f"], l["t"]) for l in d["links"]}:
            d["links"].append({"id": "lkrs_%s_%s" % (_f, _t), "f": _f, "t": _t,
                               "f_port": "out1", "t_port": _tp, "label": _lab})
            print("   ↩ 复跑保边: %s → %s (%s)" % (_f, _t, _lab))
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("节点 %d → %d (移除停用带 %d)" % (before_n, len(d["nodes"]), before_n - len(d["nodes"])))
    print("连线 %d → %d (剔除右→左 %d · 存 docs/design/feedback-edges-v510.json)" % (before_l, len(keep), len(back)))
    print("🧿 n_dsvl 位置:", nd["n_dsvl"]["x"], nd["n_dsvl"]["y"], "· 👁 n_vlm_llm:", nd["n_vlm_llm"]["x"], nd["n_vlm_llm"]["y"])


if __name__ == "__main__":
    main()
