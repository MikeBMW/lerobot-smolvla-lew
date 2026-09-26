#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_plan_review.py — L5 大模型层(DeepSeek) 审视全局资源 → 出工程计划/训练安排/产品任务清单

老倪: "大模型层deepseek再次审视全局资源, 优化工程目标, 规划开发计划, 安排模型训练任务,
      给出产品规划具体操作任务清单"

输入 = 真实体检 JSON (dev_platform_check_*.json) + 已定档事实摘要 (全部来自本仓库取证)
输出 = reports/l5_plan_<ts>.md (L5 原始输出, 不做二次加工)
模型 = deepseek-flash (账号内最新 flash, 即 V4.1-Flash); 单次调用实测 ~120s → 超时给 300s
"""
from __future__ import annotations

import glob
import json
import os
import time
import urllib.request

ROOT = "/home/ubuntu/zmax_rel"
REPORTS = os.path.join(ROOT, "reports")
ENV = os.path.expanduser("~/.hermes/.env")


def key():
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    for ln in open(ENV, encoding="utf-8"):
        if ln.strip().startswith("DEEPSEEK_API_KEY="):
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


FACTS = """
【已定档事实 (全部本仓库取证, 2026-09-26)】
· 认知头 值预测靶子判死: 一步预测输持久基线 5.19×; 多步 K=1/5/10 模型 R² 0.95/0.93/0.89 vs 持久 0.999/0.983/0.940、匀速 1.000/0.996/0.967
· 认知头 事件级靶子成立: 未来 H 帧内事件 6/6 赢平凡基线 (夹爪闭合 AUC 0.91、到位 0.79、手在动 0.90), 且跨域 v6→v5 不退化
· 数据缺口: l5_gen_v6 的 obs[7:39] 全 0、skill_ctx 24 维常量 → 只能监督 obs[0:7]+事件标签, 训感知类头需补数据
· L4: INTACT 标定闸判死 (每轴 |ρ|≤0.219 < 0.30 闸, 嵌套5折样本外 R² = -0.0002 < 0.20 闸) → 不写标定文件, adapter 拒映射; 参数寻优 10/10 无差异已关闭; 失败根因=死循环(回撤/遇阻/滑脱)
· MOE 阶段专家: 门控 8 阶段全覆盖(修好"完成"吞阶段) · 同源 A/B 0.0093 vs dense 0.016 · 引擎闭环 52,212 帧 0 失败
· AOI: 数据集 0 标注框(需现场框选) · 10083 /picture 仍 404 · 训练口径=线上 960×960 同源
· 遥测: DDS 9 类型/14 话题, 全局守护取证 20/20, prod 零开销; ECS 中转 relay+ws 已修复
· 现场未授权: 禁止下发真机动作; 只读可读
"""


def main() -> int:
    chk = sorted(glob.glob(os.path.join(REPORTS, "dev_platform_check_*.json")))[-1]
    snap = json.load(open(chk, encoding="utf-8"))
    brief = json.dumps({k: snap.get(k) for k in ("console", "pipeline", "resources")}, ensure_ascii=False)[:4000]

    prompt = (
        "你是 Z-MAX 具身智能工程的大模型层(L5)。下面是本机真实体检数据与已定档事实。请以**状态空间工程为核心**做四件事, 输出中文 Markdown:\n"
        "1) 全局资源审视: 逐项点评 (控制台/数据pipeline五段/资源/功能面), 指出**断点与瓶颈** (只依据给定数据, 不许编)。\n"
        "2) 工程目标优化: 给出 3~5 条可验收的目标 (含判据)。\n"
        "3) 开发计划: 分阶段(本周/下周/现场解锁后), 每阶段列出跨层任务 (L5/L4/L3/L2/硬件/可视化) 与依赖。\n"
        "4) 模型训练任务安排: GPU 现为空转 → 给出**立刻可跑**的训练任务(数据/目标/判据/预计时长/防返工), 以及必须等现场或需决策才能跑的。\n"
        "5) 产品规划具体操作任务清单: 表格(任务|层|判据|依赖|可否立刻执行)。\n"
        "纪律: 全部中文; 只依据给定数据推断; 不确定的写'需确认'; 不写空话。\n\n"
        "【体检数据】\n" + brief + "\n" + FACTS
    )
    body = {"model": "deepseek-flash",
            "messages": [{"role": "user", "content": prompt}], "max_tokens": 9000, "temperature": 0.3}
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key(), "Content-Type": "application/json"},
                                 method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode() or "{}")
    _msg = ((d.get("choices") or [{}])[0].get("message") or {})
    txt = (_msg.get("content") or "").strip()
    if not txt:                      # 🐛 deepseek-flash 是推理模型: max_tokens 被 reasoning 吃光时 content 为空
        txt = "【注意: 正式答案为空, 以下为模型推理过程(reasoning_content)】\n\n" + (_msg.get("reasoning_content") or "")
    dst = os.path.join(REPORTS, "l5_plan_%s.md" % time.strftime("%Y%m%d_%H%M%S"))
    open(dst, "w", encoding="utf-8").write(
        "<!-- L5 (DeepSeek %s) 审视输出 · %s · 用时 %.1fs · usage=%s -->\n\n%s" %
        (d.get("model"), time.strftime("%F %T"), time.time() - t0, json.dumps(d.get("usage"), ensure_ascii=False), txt))
    print("L5 模型: %s · 用时 %.1fs · 输入体检 %s" % (d.get("model"), time.time() - t0, os.path.basename(chk)))
    print("=" * 78)
    print(txt)
    print("=" * 78)
    print("L5 计划已落盘: %s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
