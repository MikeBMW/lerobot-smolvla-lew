#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_cleanup.py — 大清理行动: 删"不相关节点" (有文档依据 + 可回滚 + 安全判据)

判据 (任一不满足则该节点**不删**, 只报告):
  ① 依据: 节点属于**已关闭任务线**
       - sstest  = 🧪 Test 用例执行 (测试脚手架, 终端节点 出0)
       - ssa/ssb/ssc = 🅰️🅱️🅾️ 通用算子 A/B/C (参数写入/微调/校验) → 参数寻优线**已关闭** (10/10 同 seed 配对无差异)
  ② 安全: 删掉该节点与其连线后, **其所有邻居仍有 ≥1 入且 ≥1 出** (不许产生新的孤立/断链)
  ③ 回滚: 原文件备份到 flows/_archive/ + 写出 manifest(删了哪些/怎么还原)
  ④ 复核: 删后重跑 渲染取证 + 孤立点统计 + 档位级审计 (无执行注册 0 / 真缺口 0)

用法: gui-venv311/bin/python tools/canvas_cleanup.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax_rel"
FLOW = os.path.join(ROOT, "flows/state_space_obs.json")
ARCH = os.path.join(ROOT, "flows/_archive")
PY = os.path.join(ROOT, "gui-venv311/bin/python")

# id → (名称, 依据)
CAND = {
    "sstest": ("🧪 Test 用例执行", "测试脚手架 (终端节点, 出度 0); 自检改由 tools/verify_*.py 承担"),
    "ssa": ("🅰️ 通用算子 A · 参数写入", "参数寻优线**已关闭** (20X: 10/10 同 seed 配对无差异)"),
    "ssb": ("🅱️ 通用算子 B · 参数微调", "参数寻优线**已关闭**"),
    "ssc": ("🅾️ 通用算子 C · 参数校验", "参数寻优线**已关闭**"),
}


def deg_of(nodes, links, skip=()):
    deg = {n["id"]: [0, 0] for n in nodes if n["id"] not in skip}
    for l in links:
        if l["f"] in deg:
            deg[l["f"]][1] += 1
        if l["t"] in deg:
            deg[l["t"]][0] += 1
    return deg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写盘 (缺省=只检查)")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    by = {n["id"]: n for n in nodes}

    print("═" * 78)
    print("🧹 状态空间画布 · 大清理 (候选 %d 个)" % len(CAND))
    print("═" * 78)
    to_del, verdicts = [], []
    for cid, (nm, why) in CAND.items():
        if cid not in by:
            verdicts.append((cid, nm, "不存在(已清)", why, False))
            continue
        nb = set()
        for l in links:
            if l["f"] == cid:
                nb.add(l["t"])
            if l["t"] == cid:
                nb.add(l["f"])
        after = deg_of(nodes, links, skip={cid})
        broken = [x for x in nb if x in after and (after[x][0] == 0 or after[x][1] == 0)]
        ok = not broken
        verdicts.append((cid, nm, "可删" if ok else "拒绝: 会让 %s 断链" % broken, why, ok))
        if ok:
            to_del.append(cid)
    for cid, nm, st, why, ok in verdicts:
        print("  %s %-24s id=%-8s %s\n        依据: %s" % ("🗑" if ok else "⛔", nm[:24], cid, st, why))

    if not to_del:
        print("\n无可删节点 (全部被安全判据拒绝)")
        return 0
    print("\n→ 将删除 %d 个: %s" % (len(to_del), to_del))
    if not a.apply:
        print("(未加 --apply, 只检查; 未写盘)")
        return 0

    os.makedirs(ARCH, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(ARCH, "state_space_obs_before_cleanup_%s.json" % ts)
    shutil.copy2(FLOW, bak)
    keep_nodes = [n for n in nodes if n["id"] not in to_del]
    keep_links = [l for l in links if l["f"] not in to_del and l["t"] not in to_del]
    d["nodes"], d["links"] = keep_nodes, keep_links
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    manifest = {"ts": ts, "backup": os.path.relpath(bak, ROOT), "deleted": {c: CAND[c][0] for c in to_del},
                "reason": {c: CAND[c][1] for c in to_del},
                "restore": "cp %s %s" % (os.path.relpath(bak, ROOT), os.path.relpath(FLOW, ROOT)),
                "before": {"nodes": len(nodes), "links": len(links)},
                "after": {"nodes": len(keep_nodes), "links": len(keep_links)}}
    json.dump(manifest, open(os.path.join(ARCH, "cleanup_manifest_%s.json" % ts), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n✅ 已删除 %d 节点: %d 节点 / %d 连线 → %d 节点 / %d 连线" %
          (len(to_del), len(nodes), len(links), len(keep_nodes), len(keep_links)))
    print("   备份: %s\n   还原: %s" % (manifest["backup"], manifest["restore"]))

    # ④ 复核
    print("\n── 复核 ──")
    for tag, cmd in (("渲染取证", [PY, "tools/verify_canvas_render.py"]),
                     ("档位级审计", [PY, "tools/canvas_level_audit.py"])):
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=400)
        tail = [x for x in (r.stdout or "").strip().splitlines() if x.strip()][-3:]
        print("  [%s] rc=%s\n     %s" % (tag, r.returncode, "\n     ".join(x[:120] for x in tail)))
    nd = deg_of(keep_nodes, keep_links)
    orph = [k for k, v in nd.items() if v[0] == 0 and v[1] == 0]
    print("  [连通性] 孤立节点 %d 个 %s" % (len(orph), orph[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
