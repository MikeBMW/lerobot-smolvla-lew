#!/usr/bin/env python3
"""训练完成哨兵: 完成则打印摘要(→飞书), 否则静默(不打扰)"""
import os
import re

MARK = "/tmp/backbone_cont.done"
SENT = "/tmp/backbone_cont.sent"
LOG = "/tmp/backbone_cont.log"

if not os.path.exists(MARK):
    raise SystemExit(0)          # 未完成 → 静默
if os.path.exists(SENT):
    raise SystemExit(0)          # 已上报过 → 静默

rc = "?"
try:
    with open(MARK, encoding="utf-8") as f:
        m = re.search(r"rc=(-?\d+)", f.read())
        if m:
            rc = m.group(1)
except Exception:
    pass

lines = []
try:
    with open(LOG, encoding="utf-8", errors="ignore") as f:
        raw = f.read().splitlines()
    steps = [l for l in raw if "step " in l and "/4000" in l]
    done = [l for l in raw if l.startswith("\u2705") or "完成" in l or "产物" in l]
    lines = steps[-2:] + done[-2:]
except Exception as e:
    lines = [f"(读日志失败: {e})"]

out = ["\U0001F3C1 **backbone 继续训练已完成**", f"退出码 rc={rc}", "```"]
out += [l.strip()[:190] for l in lines] or ["(无 step 行, 请查 /tmp/backbone_cont.log)"]
out += ["```", "产物: /home/ubuntu/stable-wm-cache/checkpoints/backbone_cont"]

print("\n".join(out))
open(SENT, "w").close()
