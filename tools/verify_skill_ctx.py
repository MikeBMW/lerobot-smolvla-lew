#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_skill_ctx.py — L3 取证: skill_ctx 不再常量 (独立读 h5 复核) + 旧数据对照

判据:
  ① 新生成数据集: skill_ctx 的不同 one-hot 种类 > 1, 且热点维度落在 13..20 (8 阶段 + 未知槽)
  ② 旧 v6 数据对照: 只有 1 种 (dim13) —— 证明修复前后差异是**真实数据差异**而非读取口径
  ③ 未识别阶段 0 帧 (阶段名归一化生效)
"""
import sys

import h5py
import numpy as np

ok = []


def chk(n, c, d=""):
    ok.append(bool(c))
    print("  %s %s%s" % ("✅" if c else "❌", n, (" — " + d) if d else ""), flush=True)


NEW = "/tmp/l5_skill_probe.h5"
OLD = "/home/ubuntu/stable-wm-cache/datasets/l5_gen_v6.h5"
NAMES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def stats(path, n_max=None):
    with h5py.File(path, "r") as f:
        if "skill_ctx" not in f:
            return None
        sk = np.asarray(f["skill_ctx"][:n_max] if n_max else f["skill_ctx"], dtype=np.float32)
    rows = {tuple(np.round(r, 3)) for r in sk}
    hot = sorted({int(np.argmax(r)) for r in sk})
    return {"path": path, "frames": len(sk), "kinds": len(rows), "hot_dims": hot}


print("① 新数据集 (L3 修复后)")
a = stats(NEW)
chk("读到新数据集", a is not None, a["path"] if a else "")
if a:
    chk("skill_ctx 不同阶段 one-hot > 1 种", a["kinds"] > 1, "kinds=%d hot=%s" % (a["kinds"], a["hot_dims"]))
    chk("热点维度落在 13..20 (8 阶段 + 未知槽)", all(13 <= d <= 20 for d in a["hot_dims"]),
        "hot=%s → 阶段名 %s" % (a["hot_dims"], [NAMES[d - 13] if 13 <= d <= 20 else "?" for d in a["hot_dims"]]))
    chk("不含未知槽 20 (阶段名归一化生效)", 20 not in a["hot_dims"], "hot=%s" % a["hot_dims"])

print("② 旧 v6 数据对照 (修复前)")
b = stats(OLD, n_max=2000)
chk("旧数据仍是常量 (1 种)", (b is None) or b["kinds"] == 1, "kinds=%s hot=%s" % (b["kinds"], b["hot_dims"]) if b else "")
chk("结论: 差异来自生成器修复, 非读取口径", bool(a and b and a["kinds"] > b["kinds"]),
    "新 %s 种 vs 旧 %s 种" % (a["kinds"] if a else "?", b["kinds"] if b else "?"))

print("\n判据通过: %d/%d" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 3)
