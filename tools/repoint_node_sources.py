#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔧 把"source 指向 GUI 文件、真实现其实在 src/"的画布节点重指向真源码

依据 (不是猜): `src/lerobot/policies/left_right/state_space/skills/atomic_skills.py` 自己的文档写着
"本文件 = 原子技能模板的**权威定义源** (SK01-08); 画布 SK01-08 节点右键源码指向本文件的技能类",
而画布上 sssk1-8 的 `params.source` 写的是 `tools/gui/node_logic.py node_ss_skill` (壳, 只有展示逻辑);
同理 ssyolo/ss2d3d/sstactile 指向 `tools/gui/yolo_perception.py` (150 行, 里面**没有**对应实现),
真实现分别在 src/lerobot/policies/yolo_3d/{yolo_state_aligner.py, gen_tactile.py} (registry 里已核对过符号)。

规则 (宁缺勿错): 目标文件存在 且 符号在该文件里真实存在 才重指向; 否则跳过并打印原因。

用法: python3 tools/repoint_node_sources.py [--apply]
"""
import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")

MAP = {
    "sssk1": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", "class SK01Approach"),
    "sssk2": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", "class SK02Align"),
    "sssk3": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", "class SK03Descend"),
    "sssk4": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", "class SK04Grasp"),
    "sssk5": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", "class SK05Lift"),
    "sssk6": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", "class SK06Transfer"),
    "sssk7": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", "class SK07Insert"),
    "sssk8": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", "class SK08Complete"),
    "ssyolo": ("src/lerobot/policies/yolo_3d/yolo_state_aligner.py", "class YoloStateAligner"),
    "ss2d3d": ("src/lerobot/policies/yolo_3d/yolo_state_aligner.py", "def detect_3d"),
    "sstactile": ("src/lerobot/policies/yolo_3d/gen_tactile.py", "def synth_tactile"),
}


def sym_at(path, sym):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for i, ln in enumerate(f, 1):
                if ln.lstrip().startswith(sym):
                    return i
    except OSError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    todo, skip = [], []
    for n in d["nodes"]:
        if n["id"] not in MAP:
            continue
        rel, sym = MAP[n["id"]]
        full = os.path.join(ROOT, rel)
        ln = sym_at(full, sym) if os.path.isfile(full) else None
        cur = str((n.get("params") or {}).get("source") or "")
        if ln is None:
            skip.append((n["id"], f"目标文件/符号不可用: {rel} :: {sym}"))
            continue
        if cur == rel and (n.get("params") or {}).get("source_symbol") == sym:
            skip.append((n["id"], "已指向该处"))
            continue
        todo.append((n, rel, sym, ln, cur))

    print(f"将重指向: {len(todo)} 个 · 跳过 {len(skip)} 个")
    for n, rel, sym, ln, cur in todo:
        print(f"  🔧 {n['id']:11s} {(n.get('name') or '')[:34]:36s} {cur[:38]:40s} → {rel}:{ln} :: {sym}")
    for i, why in skip:
        print(f"  · 跳过 {i}: {why}")
    if not a.apply:
        print("\n(dry-run; 加 --apply 才写入)")
        return 0
    bak = FLOW + time.strftime(".bak_%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    for n, rel, sym, ln, cur in todo:
        n["params"]["source"] = rel
        n["params"]["source_symbol"] = sym
    with open(FLOW, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已重指向 {len(todo)} 个节点 · 备份 {os.path.relpath(bak, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
