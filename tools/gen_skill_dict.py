#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2 技能词典离线生成 — data/muscle_memory.json → models/skill_dict.json

词典 = L4 动作基: {skill → Δz / 帧长 / 练习次数 / 桶(种子) / io 契约}
用途: L4 预测意图 Δz 后在此词典上 kNN 直读技能 (无需连续动作空间搜索)
       L3 编排按 io 契约做段间接力 (入口/出口状态对齐)
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from lerobot.memory import memory_graph as mg  # noqa: E402


def build():
    skills = {}
    for sk, v in mg.skill_dict().items():
        io = mg.skill_io(sk)
        skills[sk] = {"stage": v.get("stage"), "dz": v.get("dz"),
                      "n_ok": v.get("n_ok"), "frames": v.get("frames"),
                      "seeds": sorted({b.get("seed") for b in (io.get("buckets") or [])
                                       if b.get("seed") is not None}),
                      "n_buckets": len(io.get("buckets") or []),
                      "io": io.get("io"), "io_reason": io.get("io_reason")}
    return {"format": "zmax-skill-dict", "version": "1.0",
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "data/muscle_memory.json (L2 标杆库)",
            "note": "L4 动作基 — Δz 由标杆 champ_x 首末差算出; io 契约 S2 采集(旧数据可能为空)",
            "n_skills": len(skills), "skills": skills}


if __name__ == "__main__":
    d = build()
    out = os.path.join(ROOT, "models", "skill_dict.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"🧬 技能词典已生成: {out}")
    print(f"   {d['n_skills']} 技能 · 来源 {d['source']}")
    for sk, v in sorted(d["skills"].items()):
        io = "有" if v.get("io") else "无(S2待采)"
        print(f"   {sk} {v['stage']}: Δz={v['dz']} frames={v['frames']} n_ok={v['n_ok']} "
              f"桶={v['n_buckets']} io={io}")
