# -*- coding: utf-8 -*-
"""从评测日志恢复 per-seed 结果 JSON (sidecar 被下一次运行覆盖时的补救)

诚实标注: 恢复件写入 "_recovered_from_log": "<日志路径>", 不冒充原始 sidecar。
只需 success_rate 与 solver_timing (零搜索凭据) —— 二者在日志的 metrics 打印里都有。
用法: python3 recover_from_log.py <task> <seed> <log_path> <out_dir>
"""
import ast
import json
import os
import re
import sys


def main() -> int:
    task, seed, logp, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    src = open(logp, encoding="utf-8", errors="ignore").read()
    # metrics 打印行: {'success_rate': 95.0, 'episode_successes': array([...]), 'solver_timing': {...}}
    m = re.search(r"\{'success_rate'.*?\}\s*$", src, re.S | re.M)
    if not m:
        print(f"❌ {logp}: 未找到 metrics 打印行")
        return 1
    txt = m.group(0)
    txt = re.sub(r"array\(\[([^]]*)\]\)", r"[\1]", txt)      # numpy array(...) → [...]
    txt = txt.replace("nan", "None")
    try:
        d = ast.literal_eval(txt)
    except Exception as e:
        print(f"❌ {logp}: 解析失败 {e}")
        return 2
    sr = d.get("success_rate")
    eps = d.get("episode_successes") or []
    payload = {"policy": None, "inference_mode": "direct(PriorOnlySolver)",
               "num_eval": len(eps) or None, "horizon": 5,
               "metrics": {"success_rate": sr, "episode_successes": eps,
                           "solver_timing": d.get("solver_timing") or {},
                           "get_cost_calls": d.get("get_cost_calls"),
                           "rollout_candidates": d.get("rollout_candidates")},
               "eval_total_time": d.get("eval_total_time"),
               "_recovered_from_log": os.path.abspath(logp),
               "_note": "sidecar JSON 被后续 seed 覆盖, 本件由运行日志恢复 (success_rate/solver_timing 为日志原文)"}
    os.makedirs(out, exist_ok=True)
    dst = os.path.join(out, f"{task}_seed{seed}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"✅ {dst}: SR={sr} 成功数={sum(1 for x in eps if x)}/{len(eps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
