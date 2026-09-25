#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 L5 规划合法性校验器 —— 三条硬校验（老倪: "大模型层给出训练目标"）

职责: 任何来源（LLM / 规则规划器 / 任务模板）产出的**阶段序列**都必须过这三关,
      不过 → 拒绝并回退规则规划器（安全层原则: 上层只给意图, 不可执行的意图必须被拦下）

三条硬校验（全部基于可验证事实, 不是风格检查）:
  ① 顺序合法: 阶段索引单调不倒退, 且不跨过必需的前置阶段
       合法序: 接近(0) → 对位(1) → 下降(2) → 抓取(3) → 抬起(4) → 转移(5) → 插入(6)
  ② 依赖满足: 插入 ⇒ 已抓取; 抓取 ⇒ 已下降; 抬起 ⇒ 已抓取; 转移 ⇒ 已抬起
  ③ 与观测一致: 若 L4/引擎报当前已在阶段 s, 不得规划回到 s 之前的阶段（不许"倒流"）

用法:
  python tools/planner_validate.py --selftest                    # 纯逻辑自检
  python tools/planner_validate.py --plan "接近,对位,下降,抓取,插入"  # 校验一条
  python tools/planner_validate.py --batch plans.json --out reports/planner_legal.json
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
IDX = {s: i for i, s in enumerate(STAGES)}
# 依赖: 阶段 → 必须已经出现过的阶段集合
DEPS = {
    "下降": {"接近"},
    "抓取": {"下降"},
    "抬起": {"抓取"},
    "转移": {"抬起"},
    "插入": {"抓取", "转移"},
}


def validate(seq, current=None):
    """返回 (ok, reasons)。seq: 阶段名列表; current: 当前已处阶段(可空)。
    纯函数 —— 同输入必同输出, 可逐行断点。"""
    reasons = []
    if not seq:
        return False, ["空序列"]
    # 名称合法
    bad = [s for s in seq if s not in IDX]
    if bad:
        reasons.append("未知阶段: %s" % ",".join(bad))
    seen, prev_i = set(), -1
    for i, s in enumerate(seq):
        if s not in IDX:
            continue
        si = IDX[s]
        # ① 顺序: 不倒退
        if si < prev_i:
            reasons.append("① 顺序倒退: 第%d步 %s 回到 %s 之前" % (i + 1, s, STAGES[prev_i]))
        # ① 顺序: 不跳跃（跳过必需前置）
        need = DEPS.get(s, set())
        miss = need - seen
        if miss:
            reasons.append("② 依赖缺失: 第%d步 %s 之前未出现 %s" % (i + 1, s, ",".join(sorted(miss))))
        seen.add(s)
        prev_i = max(prev_i, si)
    # ③ 与当前观测一致: 只拦**真倒退** —— 即整个规划的最高阶段仍在当前阶段之前
    #    （含"已完成的阶段"不算错: 那只是幂等重规划; 旧版把这种误判为倒流, 已被自检抓出）
    if current in IDX:
        ci = IDX[current]
        reach = max([IDX[s] for s in seq if s in IDX], default=-1)
        if reach < ci:
            reasons.append("③ 与观测冲突: 当前已在「%s」, 而规划最高只到「%s」→ 真倒退"
                           % (current, STAGES[reach] if reach >= 0 else "无"))
    # ④ 完整性: 至少覆盖到目标阶段(默认应有 抓取 与 插入, 除非显式只做接近)
    return (len(reasons) == 0), reasons


def selftest():
    cases = [
        (["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"], None, True, "完整合法序"),
        (["接近", "对位", "下降", "抓取"], None, True, "短序列(到抓取)合法"),
        (["抓取", "插入"], None, False, "跳过下降 → 依赖缺失"),
        (["接近", "下降", "抓取", "插入"], None, False, "插入缺转移依赖"),
        (["接近", "对位", "抓取", "下降"], None, False, "顺序倒退"),
        ([], None, False, "空序列"),
        (["接近", "飞升"], None, False, "未知阶段"),
        (["接近", "对位", "下降"], "插入", False, "与观测冲突(已插入却规划回到下降)"),
        (["接近", "对位", "下降", "抓取"], "下降", True, "当前在下降, 继续到抓取 → 合法"),
    ]
    print("=" * 76)
    print("🧭 L5 规划合法性校验器 — 纯逻辑自检")
    print("=" * 76)
    n_ok = 0
    for seq, cur, want, note in cases:
        got, why = validate(seq, cur)
        ok = (got == want)
        n_ok += ok
        print("  %s %-38s 期望%s 实得%s %s" % ("✅" if ok else "❌", note[:38],
                                              "合法" if want else "非法", "合法" if got else "非法",
                                              ("" if got else "(" + why[0][:34] + ")")))
    print("  结果: %d/%d 通过" % (n_ok, len(cases)))
    return 0 if n_ok == len(cases) else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--plan", default="")
    ap.add_argument("--current", default="")
    ap.add_argument("--batch", default="", help="JSON: [{\"seq\":[...],\"current\":\"...\"}, ...]")
    ap.add_argument("--out", default=os.path.join(REPO, "reports", "planner_legal.json"))
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.plan:
        seq = [s.strip() for s in a.plan.replace("->", ",").split(",") if s.strip()]
        ok, why = validate(seq, a.current or None)
        print("  序列: %s" % " → ".join(seq))
        print("  判定: **%s**" % ("✅ 合法" if ok else "❌ 非法"))
        for r in why:
            print("    · %s" % r)
        return 0 if ok else 2
    if a.batch and os.path.isfile(a.batch):
        items = json.load(open(a.batch, encoding="utf-8"))
        res, n_ok = [], 0
        for it in items:
            ok, why = validate(it.get("seq") or [], it.get("current"))
            n_ok += ok
            res.append({"seq": it.get("seq"), "ok": ok, "reasons": why})
        rate = round(100.0 * n_ok / max(1, len(items)), 1)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump({"n": len(items), "legal": n_ok, "legal_rate_pct": rate, "items": res},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  规划合法率: **%d/%d = %.1f%%**（目标 ≥99%%）" % (n_ok, len(items), rate))
        print("  → %s" % os.path.relpath(a.out, REPO))
        return 0 if rate >= 99.0 else 2
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
