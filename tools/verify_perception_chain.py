#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_perception_chain.py — 感知链功能验证 (YOLO + 板坐标系 + DeepSeek VL, 真实产物)

--check yolo_live     : 最新感知记录里 YOLO 检出模块 conf ≥0.5 且框有效
--check board_frame   : 板点 =20 且输出"模块在板坐标(x,y)mm" 且 |离板面| ≤2mm
--check vlm_scene     : 最新记录里 VL 结构化判读含 目标/画面质量/背景线索
--check single_source : data/scene_state.json 含感知链段; 追加记录可回放(行数>0)
--check canvas_wired  : 画布 n_board_frame 入≥3出≥3, 且功能节点孤立=0
"""
import json
import os
import sys

R = "/home/ubuntu/lerobot-smolvla-lew"
LP = os.path.expanduser("~/zmax_data/perception_chain.jsonl")


def _last():
    if not os.path.exists(LP):
        return None
    lines = [x for x in open(LP, encoding="utf-8") if x.strip()]
    return json.loads(lines[-1]) if lines else None


def c_yolo():
    r = _last()
    if not r:
        return False, "无感知记录"
    bf = r.get("l2_board_frame") or {}
    c = bf.get("conf")
    return (bool(bf.get("框")) and c is not None and float(c) >= 0.5,
            "conf=%s 框=%s" % (c, bf.get("框")))


def c_board():
    r = _last()
    if not r:
        return False, "无感知记录"
    bf = r.get("l2_board_frame") or {}
    xy = bf.get("模块在板坐标 (x,y,mm)")
    dz = bf.get("离板面mm")
    ok = int(bf.get("板点", 0)) == 20 and bool(xy) and dz is not None and abs(float(dz)) <= 2.0
    return ok, "板点=%s xy=%s 离板面=%s" % (bf.get("板点"), xy, dz)


def c_vlm():
    """回溯最近 20 条记录找带 VL 结构化判读的那条 (单次 --no-vlm 运行不该判失败)"""
    j = {}
    if os.path.exists(LP):
        for line in [x for x in open(LP, encoding="utf-8") if x.strip()][-20:]:
            try:
                j = ((json.loads(line).get("l3_vlm") or {}).get("json")) or {}
            except Exception:                                                    # noqa: BLE001
                j = {}
            if j:
                break
    if not j:
        return False, "近 20 条记录里无 VL 判读"
    need = ["目标可见", "画面质量", "背景线索"]
    miss = [k for k in need if k not in j]
    return (not miss, "字段=%d 缺=%s 目标=%s" % (len(j), miss or "无", str(j.get("目标是什么"))[:24]))


def c_single():
    p = os.path.join(R, "data", "scene_state.json")
    if not os.path.exists(p):
        return False, "无 scene_state"
    d = json.load(open(p, encoding="utf-8"))
    n = 0
    if os.path.exists(LP):
        n = sum(1 for _ in open(LP, encoding="utf-8"))
    return ("perception_chain" in d and bool(d.get("updated_at")) and n > 0,
            "真源段=%s 记录=%d 行" % ("有" if "perception_chain" in d else "无", n))


def c_canvas():
    p = os.path.join(R, "flows", "state_space_obs.json")
    d = json.load(open(p, encoding="utf-8"))
    ids = {x["id"] for x in d["nodes"]}
    if "n_board_frame" not in ids:
        return False, "板坐标系节点不存在"
    nin = len([l for l in d["links"] if l["t"] == "n_board_frame"])
    nout = len([l for l in d["links"] if l["f"] == "n_board_frame"])
    linked = set()
    for l in d["links"]:
        linked.add(l["f"]); linked.add(l["t"])
    iso = [i for i in ids if i not in linked]
    bands = [i for i in iso if i.startswith(("ssbg", "row_", "swbg"))]
    return (nin >= 3 and nout >= 3 and len(iso) == len(bands),
            "入%d 出%d 孤立%d(全为背景带 %d)" % (nin, nout, len(iso), len(bands)))


CHECKS = {"yolo_live": c_yolo, "board_frame": c_board, "vlm_scene": c_vlm,
          "single_source": c_single, "canvas_wired": c_canvas}

if __name__ == "__main__":
    which = os.environ.get("PC_CHECK")
    for a in sys.argv[1:]:
        if a in CHECKS:
            which = a
        if a.startswith("--check="):
            which = a.split("=", 1)[1]
        elif a == "--check" and len(sys.argv) > 2:
            which = sys.argv[2]
    if not which:
        ok = True
        for k, f in CHECKS.items():
            o, d = f()
            print(("✅" if o else "❌"), k, d)
            ok = ok and o
        sys.exit(0 if ok else 1)
    f = CHECKS.get(which)
    if not f:
        print("❌ 未知检查:", which); sys.exit(2)
    o, d = f()
    print(("✅ " if o else "❌ ") + which + " · " + d)
    sys.exit(0 if o else 1)
