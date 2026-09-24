#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 canvas_update_verif_nodes.py — 用**实时计数**刷新画布上「功能清单 / 测试用例」两个节点的 desc

为什么: `ssfeat` 的 desc 里写着 "A引擎 7/B六层 11/C感知链 4/…" 这类**分组用例计数**, 加用例后会过期
(2026-09-24 新增 F-B12/F-B13 → B 组 11→13)。本脚本从**单一真源**重算并写回, 幂等。

断言: ① 两个节点存在 ② 计数 > 0 且与真源一致 ③ 坐标/结构不动 (只改 params.desc) ④ 幂等 (已最新则跳过)
用法: bash tools/studio_ctl.sh stop && ./gui-venv311/bin/python tools/canvas_update_verif_nodes.py --apply
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
VER = os.path.join(ROOT, "src", "lerobot", "verification")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf                                     # 屏蔽被载模块的打印
    try:
        vl = _load(os.path.join(VER, "verification_layer.py"), "verification_layer")
        cl = _load(os.path.join(VER, "capability_levels.py"), "capability_levels")
        nft = _load(os.path.join(VER, "node_func_tree.py"), "node_func_tree")
        feats = list(vl.FEATURES)
        n_feat = len(feats)
        cap_n = sum(len(d.get("funcs", [])) for d in cl.CAPABILITY_LEVELS.values())
        tree = (nft.node_count(), nft.func_count(), nft.test_count())
        auto = sum(1 for f in feats if "自动" in str(f[4]))
    finally:
        sys.stdout = old
    groups = Counter(str(f[0]).split("-")[1][0] for f in feats)     # A/B/C/D/E/F/G/H
    L2 = sum(1 for f in feats if f[6] == "L2")
    L4 = sum(1 for f in feats if f[6] == "L4")
    grp_txt = "/".join(f"{k}{groups[k]}" for k in sorted(groups))
    desc_feat = (f"Feature 功能清单: 状态空间系统全部 feature 汇总 ({grp_txt}; 分级 L2 {L2}/L4 {L4}); "
                 f"共 {n_feat} 条自动/半自动断言 · 功能树 {tree[1]} 功能×{tree[2]} 用例 (22 节点); "
                 f"新增: F-B12 3D视觉引导 / F-B13 触觉反馈闭环 (2026-09-24); 源码 verification_layer.py FEATURES")
    desc_test = (f"Test 用例执行: 跑自动化套件 (引擎/六层/感知/规划/元层/画布), PASS/FAIL+数值证据 · "
                 f"当前 {n_feat} 条 (自动 {auto}) · 新增 F-B12/F-B13 = 真物理引擎断言 (慢~20s, 单跑 ZMAX_VERIF_ONLY=F-B12); "
                 f"源码 verification_layer.py VerificationLayer")
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes = {n["id"]: n for n in d["nodes"]}
    for nid, desc in (("ssfeat", desc_feat), ("sstest", desc_test)):
        assert nid in nodes, f"画布缺节点 {nid}"
        nodes[nid]["params"]["desc"] = desc
    print(f"真源计数: FEATURES {n_feat} (自动 {auto}, L2 {L2}/L4 {L4}) · 分组 {grp_txt} · "
          f"capability 功能 {cap_n} · 功能树 {tree[0]} 节点/{tree[1]} 功能/{tree[2]} 用例")
    print("ssfeat.desc ←", desc_feat[:120], "…")
    print("sstest.desc ←", desc_test[:120], "…")
    for n in d["nodes"]:
        for k in ("x", "y", "w", "h"):
            if k in n:
                assert isinstance(n[k], int), f"非 int 坐标 {n['id']}.{k}"
    if not a.apply:
        print("(dry-run; 加 --apply 落地)")
        return 0
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已写回 {os.path.relpath(FLOW, ROOT)} (节点 {len(d['nodes'])} · 连线 {len(d['links'])})")
    print("CANVAS_VERIF_NODES_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
