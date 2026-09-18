#!/usr/bin/env python3
"""F20 用例: 顶层宏观记忆 (总装↔Qwen 宏观层) — 只读下层 + 幂等 + 双向同步

对应功能: F20 "顶层宏观记忆(跨任务画像+失败归因+下行建议)" (模块 memory/macro_memory)
判据:
  ① uplink 只读下层 (assembly/shared/muscle 文件 mtime 不变) — 不污染状态空间工程数据
  ② 幂等: 同批 run 重复 sync 不重复消化 (fresh 第二次 = 0)
  ③ downlink 阶段建议覆盖 ≥7 阶段, 且每条**有依据** (why 非空)
  ④ 无 LLM 端点时如实标 llm=False (不假装大模型分析过)
  ⑤ 能力画像数字与下层台账**同源** (runs 数 = assembly_memory.runs 长度)
"""
import os
import sys

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, f"{ROOT}/src")
os.chdir(ROOT)

import json
import tempfile

fails = []


def chk(name, ok, extra=""):
    print(f"  {'OK ' if ok else 'FAIL'} {name} {extra}")
    if not ok:
        fails.append(name)


try:
    from lerobot.memory.macro_memory import MacroMemory, ASSEMBLY, SHARED, MUSCLE
except Exception as e:                                     # noqa: BLE001
    print(f"  FAIL 导入 macro_memory: {type(e).__name__}: {e}")
    sys.exit(1)

tmp = tempfile.mkdtemp(prefix="f20_")
mm = MacroMemory(path=os.path.join(tmp, "m.json"))

# ① 只读下层
before = {p: os.path.getmtime(p) for p in (ASSEMBLY, SHARED, MUSCLE) if os.path.exists(p)}
r1 = mm.sync()
after = {p: os.path.getmtime(p) for p in before}
chk("① 只读下层 (状态空间工程数据未被改写)", before == after, f"| 监控 {len(before)} 个文件")

# ② 幂等
r2 = mm.sync()
chk("② 幂等 (重复 sync 不重复消化)", r2["uplink"]["fresh"] == 0,
    f"| 1st fresh={r1['uplink']['fresh']} 2nd fresh={r2['uplink']['fresh']}")

# ③ 建议有据
adv = mm.downlink()
stages = [k for k in adv if not k.startswith("_")]
no_why = [k for k in stages if not adv[k].get("why")]
chk("③ 下行建议覆盖 ≥7 阶段且条条有依据", len(stages) >= 7 and not no_why,
    f"| 阶段 {len(stages)} 个, 缺依据 {no_why}")

# ④ llm 诚实标注
meta = mm.store.get("meta", {})
chk("④ 无端点时如实标 llm=False", meta.get("llm") in (False, None),
    f"| llm={meta.get('llm')}")

# ⑤ 画像与台账同源
runs = (json.load(open(ASSEMBLY)).get("runs") or []) if os.path.exists(ASSEMBLY) else []
ov = mm.store.get("capability", {}).get("overall", {})
chk("⑤ 能力画像与下层台账同源", ov.get("runs") == len(runs),
    f"| 画像 runs={ov.get('runs')} vs assembly runs={len(runs)}")

print("结论:", "✅ 通过" if not fails else f"❌ 有不通过项: {fails}")
sys.exit(0 if not fails else 1)
