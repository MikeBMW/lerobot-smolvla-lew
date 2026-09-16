#!/usr/bin/env python3
"""闸门判决汇总: 按注入用例分组统计 verdict (Step 2 验证用, 只读 jsonl)"""
import collections
import glob
import json
import os
import sys

day = os.popen("date +%Y%m%d").read().strip()
f = f"/home/tashan/.zmax/ss_link/gate_{day}.jsonl"
if not os.path.exists(f):
    print("无 gate jsonl:", f); sys.exit(1)

by_case = collections.defaultdict(collections.Counter)
allv = collections.Counter()
n = 0
with open(f) as fp:
    for ln in fp:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        n += 1
        cas = r.get("case") or "(真实提案)"
        by_case[cas][r.get("verdict")] += 1
        allv[r.get("verdict")] += 1

print(f"gate 记录总数: {n}  文件: {f}")
print("--- 按用例 ---")
for k in sorted(by_case):
    print(f"  {k:<12} {dict(by_case[k])}")
print("--- 总计 ---")
print("  ", dict(allv))
print("--- 最近 3 条 ---")
for ln in open(f).readlines()[-3:]:
    r = json.loads(ln)
    print(f"  case={r.get('case')} verdict={r.get('verdict')} detail={str(r.get('detail'))[:110]} executed={r.get('executed')}")
