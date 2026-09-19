#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""perception_chain_real.py — 真实链路: YOLO(L2感知) + 板坐标系(3D) + DeepSeek VL(L3理解)"""
import json
import os
import sys
import time

R = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(R, "tools"))
sys.path.insert(0, os.path.join(R, "src"))
import board_frame_module as B

FR = os.path.expanduser("~/zmax_ss_remote/cam_rs.png")


def run(with_vlm=True):
    """跑一次真实链路: YOLO 检出模块 → 板坐标系 3D → (可选)VL 场景理解 → 写 scene_state + 记忆"""
    r = B.run(FR)
    out = {"t": time.time(), "frame": FR,
           "frame_age_s": round(time.time() - os.path.getmtime(FR), 2),
           "l2_board_frame": r}
    if with_vlm:
        try:
            from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM
            v = SceneVLM.get().describe(FR, {"instruction": "感知链场景理解"}) or {}
            out["l3_vlm"] = {"src": v.get("src"), "json": v.get("json") or v}
        except Exception as e:                                                   # noqa: BLE001
            out["l3_vlm"] = {"error": str(e)}
    return out


def write_out(out):
    """写单一真源 data/scene_state.json (合并语义) + 追加式记录 (可回放)"""
    p = os.path.join(R, "data", "scene_state.json")
    d = {}
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                                        # noqa: BLE001
            d = {}
    d["perception_chain"] = out
    d["updated_at"] = out["t"]
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 多层记忆: 感知/场景理解 → L4 宏观记忆 (追加式, 其它键原样保留)
    mp = os.path.join(R, "data", "macro_memory.json")
    try:
        md = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {}
        md.setdefault("perception", []).append({
            "t": out["t"],
            "l2": out.get("l2_board_frame"),
            "l3": ((out.get("l3_vlm") or {}).get("json") or {})})
        md["perception"] = md["perception"][-200:]
        json.dump(md, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:                                                            # noqa: BLE001
        pass
    lp = os.path.expanduser("~/zmax_data/perception_chain.jsonl")
    with open(lp, "a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    return p, lp


if __name__ == "__main__":
    o = run(with_vlm="--no-vlm" not in sys.argv)
    p, lp = write_out(o)
    print(json.dumps(o, ensure_ascii=False)[:900])
    print("→ 真源:", p, "| 记录:", lp)
