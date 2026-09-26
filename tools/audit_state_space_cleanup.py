#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_state_space_cleanup.py — 状态空间工程全局复盘 (只读盘点, 为大清理提供依据)

产出 (不写任何文件):
  ① 画布总览: 节点/连线/行带分布
  ② 每个真节点的**连通度** (入/出), 标出**孤儿**(0 入 0 出 / 只有单边)
  ③ **可疑节点**分类: 背景行(bg/row_bg) · 疑似旧版/测试/占位/重复(名字含 v1/v2/旧/test/demo/占位/TODO)
  ④ 每行(层)的节点清单 (便于确认主线)
  ⑤ 台账/服务/cron 里的任务清单 (活跃 vs 停滞)
用法: gui-venv311/bin/python tools/audit_state_space_cleanup.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = "/home/ubuntu/zmax_rel"
FLOW = os.path.join(ROOT, "flows/state_space_obs.json")


def sh(cmd, timeout=12):
    try:
        r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return (r.stdout or "").strip()
    except Exception:                                                          # noqa: BLE001
        return ""


def main() -> int:
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    by = {n["id"]: n for n in nodes}
    deg = {n["id"]: [0, 0] for n in nodes}          # [in, out]
    for l in links:
        if l["f"] in deg:
            deg[l["f"]][1] += 1
        if l["t"] in deg:
            deg[l["t"]][0] += 1

    print("═" * 78)
    print("① 画布总览: %d 节点 / %d 连线" % (len(nodes), len(links)))
    bg = [n for n in nodes if n.get("type") in ("bg", "row_bg")]
    real = [n for n in nodes if n not in bg]
    print("   背景/行条 %d · 真节点 %d" % (len(bg), len(real)))

    # 行带
    rows = {}
    for n in real:
        rows.setdefault(n["y"], []).append(n)
    print("\n④ 行带(层)分布 (y → 节点数):")
    for y in sorted(rows):
        print("   y=%-5s %2d 个: %s" % (y, len(rows[y]), " · ".join(x["name"][:18] for x in sorted(rows[y], key=lambda z: z["x"]))))

    print("\n② 连通度 / 孤儿:")
    orph = [n for n in real if deg[n["id"]][0] == 0 and deg[n["id"]][1] == 0]
    no_in = [n for n in real if deg[n["id"]][0] == 0 and deg[n["id"]][1] > 0]
    no_out = [n for n in real if deg[n["id"]][1] == 0 and deg[n["id"]][0] > 0]
    print("   完全孤立(0入0出) %d 个:" % len(orph))
    for n in orph:
        print("      - %-30s id=%s  (%.0f,%.0f)" % (n["name"][:30], n["id"], n["x"], n["y"]))
    print("   无输入(入口) %d 个: %s" % (len(no_in), ", ".join(n["name"][:14] for n in no_in[:12])))
    print("   无输出(终点) %d 个: %s" % (len(no_out), ", ".join(n["name"][:14] for n in no_out[:12])))

    print("\n③ 可疑节点 (疑似旧版/测试/占位/重复):")
    pat = re.compile(r"(v[0-9]+|旧|test|demo|占位|TODO|临时|废弃|deprecated|_bak|副本|copy)", re.I)
    susp = [n for n in real if pat.search(n["name"]) or pat.search(n.get("id", ""))]
    for n in susp:
        print("      - %-32s id=%-18s 入%d 出%d" % (n["name"][:32], n["id"], deg[n["id"]][0], deg[n["id"]][1]))
    if not susp:
        print("      (无)")

    print("\n⑤ 任务面盘点:")
    print("   · 台账: docs/TASK_LEDGER_20260925.md (%d 段会话)" %
          sh("grep -c '^## 2026' docs/TASK_LEDGER_20260925.md").count and
          sh("grep -c '^## 2026' docs/TASK_LEDGER_20260925.md"))
    svc = sh("systemctl list-units --type=service --state=running --no-legend 'zmax*' 'ss-*' 'aoi*' 2>/dev/null | awk '{print $1}' | tr '\\n' ' '")
    print("   · 在役服务: %s" % svc)
    print("   · cron 任务:")
    for ln in sh("python3 -c \"import json,os;d=json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')));print('\\n'.join('   - %s | %s | %s' % (v.get('name') or k, v.get('schedule'), 'enabled' if v.get('enabled') else 'PAUSED') for k,v in (d.get('jobs') or d).items()))\" 2>/dev/null").splitlines()[:12]:
        print(ln)
    print("   · 验证器数量: %s 个 (tools/verify_*.py)" % sh("ls tools/verify_*.py 2>/dev/null | wc -l"))
    print("   · 一次性脚本(tools/ 根) 数量: %s" % sh("ls tools/*.py 2>/dev/null | wc -l"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
