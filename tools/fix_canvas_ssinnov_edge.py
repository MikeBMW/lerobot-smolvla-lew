#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_canvas_ssinnov_edge.py — 修「🧪 状态校正器」断头 (老倪 2026-09-23 三问之一)

根因 (实证):
  commit 13632919 (2026-09-19) 的 tools/gui/post_layout_fix.py 为满足老倪要求③
  「画布不能出现右侧输出连左侧输入」, 把 **所有 f.x >= t.x 的连线**从画布剔除并存
  docs/design/feedback-edges-v510.json。当时 🧪状态校正器 在 x=5750、🧭动作调制器 在
  x=3520 → 「状态校正器 → 动作调制器」被判为右→左 → **删除**; 后续重跑又把 feedback
  存档覆盖成只剩 3 条 → 这条语义记录整体丢失 ⇒ 节点变成"有入无出"(断头)。
  铁证: 🧭动作调制器 的 in8 端口标签至今仍是「contact+残差 (状态校正器)」—— 端口在等这条线。

修法 (最小 + 可复跑):
  ① 把 🧪状态校正器 移回 动作调制器 左侧 (x=2456, y=4076 同一行, 与 估计/预测 同带)
  ② 恢复连线 状态校正器 →(out1→in8) 动作调制器
  ③ 同步写 tools/gui/post_layout_fix.py 的 PIN/RESTORE, 避免下次重跑又被剔除
用法: gui-venv311/bin/python tools/fix_canvas_ssinnov_edge.py [--dry]
"""
import json
import os
import shutil
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
LAYOUT = os.path.join(ROOT, "tools", "gui", "post_layout_fix.py")
NEW_X, NEW_Y = 2456, 4076
EDGE = {"id": "lkfix_ssinnov_sssched", "f": "ssinnov", "t": "sssched",
        "f_port": "out1", "t_port": "in8", "label": "contact+残差 → 动作调制 (u_fb)"}


def main():
    dry = "--dry" in sys.argv
    j = json.load(open(FLOW, encoding="utf-8"))
    nodes = {n["id"]: n for n in j["nodes"]}
    if "ssinnov" not in nodes or "sssched" not in nodes:
        print("❌ 缺节点 ssinnov/sssched"); return 1
    n = nodes["ssinnov"]
    old = (n.get("x"), n.get("y"))
    have = {(l["f"], l["t"]) for l in j["links"]}
    print("现状: 状态校正器 (x=%s,y=%s) → 动作调制器 连线存在=%s" % (old[0], old[1], ("ssinnov", "sssched") in have))
    if dry:
        print("--dry: 不改动"); return 0
    shutil.copy2(FLOW, FLOW + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
    n["x"], n["y"] = NEW_X, NEW_Y
    added = False
    if ("ssinnov", "sssched") not in have:
        j["links"].append(dict(EDGE)); added = True
    # 端口语义对齐 (in8 label 已存在则不动)
    for nd in j["nodes"]:
        if nd["id"] == "sssched" and isinstance(nd.get("inputs"), list):
            for p in nd["inputs"]:
                if isinstance(p, dict) and p.get("id") == "in8":
                    p["label"] = p.get("label") or "contact+残差 (状态校正器)"
    json.dump(j, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 状态校正器 移 (%s,%s) → (%d,%d) · 连线%s" % (old[0], old[1], NEW_X, NEW_Y,
                                                          "已补" if added else "已存在"))
    # ③ 让布局脚本同源 (下次重跑不会又删掉)
    try:
        s = open(LAYOUT, encoding="utf-8").read()
        if '"ssinnov": (2456, 4076)' not in s:
            s = s.replace('"ssn_anchor": (0, 0),', '')  # no-op 保护
            s = s.replace(' "n_skill_dict": (6410, 1076), "ssllm_in": (9050, 952),',
                          ' "n_skill_dict": (6410, 1076), "ssllm_in": (9050, 952),\n'
                          '       "ssinnov": (2456, 4076),   # 🧪 状态校正器回到 动作调制器(3520) 左侧\n'
                          '       #   → 「状态校正器→动作调制器(u_fb)」不再是右→左线, 不会被剔除 (2026-09-23 修断头)')
            s = s.replace('    RESTORE = [("ssintact_dec", "n_intent_direct", "Δz → 意图直读"),',
                          '    RESTORE = [("ssinnov", "sssched", "contact+残差 → 动作调制 (u_fb)"),\n'
                          '               ("ssintact_dec", "n_intent_direct", "Δz → 意图直读"),')
            open(LAYOUT, "w", encoding="utf-8").write(s)
        print("✅ 布局脚本 post_layout_fix.py 已同步 (PIN + RESTORE)")
    except Exception as e:                                        # noqa: BLE001
        print("⚠️ 布局脚本同步失败(不影响本次修复): %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
