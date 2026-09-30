#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🏭 全系统 Pipeline 训练编排器 —— 所有层模型按 pipeline 结构统一训练/优化

老倪 2026-09-24: "开始全系统, 所有模型, 同步训练优化; 所有模型按照 pipeline 训练"

设计:
  把每一层视为 pipeline 的一个 stage, 统一编排:
    L5 规划层 → L4 认知层 → L3 调度层 → L2 检测层 → 记忆层
  每层 = 一个 trainer 插件（统一契约: prepare/train/evaluate/report）
  编排器负责: 资源预检 → 按序（或并行）执行 → 汇总报告 → 落盘状态(PIPELINE_STATE.json → 画布高亮)

统一契约:
  class LayerTrainer:
      name, layer            # 标识
      def preflight() -> dict # 资源/数据/依赖检查
      def train(**kw) -> dict # 返回 metrics
      def evaluate() -> dict  # 留出集 + 平凡基线
每个 trainer 的输出都进 PIPELINE_STATE.json → 画布/控制台可见（与既有闭环机制一致）

用法:
  python tools/system_train_orchestrator.py --list          # 列出所有层 trainer
  python tools/system_train_orchestrator.py --layer L4 --steps 2500
  python tools/system_train_orchestrator.py --all           # 按 pipeline 顺序全跑
  python tools/system_train_orchestrator.py --all --dry     # 只做预检不训练
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWM = "/home/ubuntu/stable-wm-cache"
VENV = os.path.join(REPO, "gui-venv311", "bin", "python")
STATE = os.path.join(REPO, "docs", "PIPELINE_STATE.json")


def _sh(cmd, log, timeout=14400):
    t0 = time.time()
    with open(log, "w") as f:
        try:
            r = subprocess.run(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
            return r.returncode, time.time() - t0
        except subprocess.TimeoutExpired:
            return -1, time.time() - t0


def set_state(stage, status, note=""):
    st = {}
    if os.path.isfile(STATE):
        try:
            st = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            st = {}
    st.setdefault("stages", {})[stage] = {"status": status, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note}
    st["stage"], st["state"], st["ts"] = stage, status, time.strftime("%Y-%m-%d %H:%M:%S")
    st["log"] = (st.get("log", "") + "\n[%s] %s: %s %s" % (st["ts"], stage, status, note))[-4000:]
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


# ─────────── 层 trainer 定义（每层: 数据/命令/判据）───────────
LAYERS = {
    "L5": {
        "desc": "规划层（大模型层）: 任务规划 + 场景理解",
        "data": "—（LLM 规划, 无需训练数据; 或 VLM 微调）",
        "cmd": "",                     # L5 是 LLM, 走升级策略而非训练（见 --strategy）
        "gate": "规划输出可解析 + 阶段序列顺序合法",
    },
    "MEM": {
        "desc": "记忆层: 五层记忆联络（已建成 16 条/31 链接）",
        "data": "data/memory_layers.json",
        "cmd": "%s tools/memory_link_build.py" % sys.executable,
        "gate": "零孤儿 + 跨层链接 100%",
    },
    "L4": {
        "desc": "认知层: 统一主干（SigLIP 冻结 + 头）· 两阶段配方",
        "data": "v6_sub25k.h5（含 skill_ctx）",
        "cmd": ("%s tools/joint_unified_backbone.py --steps {steps} --batch 64 --workers 3 "
                "--stats 250 --aug 1 --aug-scale 0.90,1.10 --cache-gb 5 "
                "--holdout %s/datasets/v6_holdout_rand.h5 --files %s/datasets/v6_sub25k.h5 "
                "--save %s/checkpoints/unified_orch_L4" % (VENV, SWM, SWM, SWM)),
        "gate": "留出优于平凡基线（观测 0.0366 / 动作 0.0955）",
    },
    "L4moe": {
        "desc": "认知层(MOE): 阶段专家 7 头（已验证分化 6/7）",
        "data": "v6_sub25k.h5",
        "cmd": ("%s tools/stage_moe_backbone.py --steps {steps} --batch 64 --workers 3 "
                "--stats 250 --aug 1 --aug-scale 0.90,1.10 --cache-gb 5 "
                "--holdout %s/datasets/v6_holdout_rand.h5 --files %s/datasets/v6_sub25k.h5 "
                "--save %s/checkpoints/stage_moe_orch" % (VENV, SWM, SWM, SWM)),
        "gate": "留出优于基线 + 门控分化 ≥6/7",
    },
    "L3": {
        "desc": "调度层: 动作调度（量纲逆运算 act×K_ACT）",
        "data": "—（由 L4 输出驱动, 无独立权重）",
        "cmd": "",
        "gate": "u_ff 量纲正确（|u|≤1）",
    },
    "L2": {
        "desc": "检测层: YOLO 金手指/表面检测",
        "data": "真机/AOI 图（在线）",
        "cmd": "",
        "gate": "检测召回/精度不低于在役基线",
    },
}


def list_layers():
    print("=" * 78)
    print("🏭 全系统 Pipeline 训练编排 —— 层清单")
    print("=" * 78)
    for k, v in LAYERS.items():
        has = "✅ 可训练" if v["cmd"] else "➖ 非训练层（策略/在线）"
        print("  %-6s %-34s %s" % (k, v["desc"][:34], has))
    print("\n  pipeline 顺序: " + " → ".join(LAYERS.keys()))
    return 0


def run_one(name, steps=2500, dry=False):
    v = LAYERS[name]
    print("\n" + "=" * 78)
    print("▶ %s  %s" % (name, v["desc"]))
    print("=" * 78)
    if not v["cmd"]:
        print("  ➖ 非训练层 → 走策略/在线（见 --strategy）")
        set_state(name, "skipped", "非训练层")
        return True
    cmd = v["cmd"].format(steps=steps) if "{steps}" in v["cmd"] else v["cmd"]
    print("  数据: %s" % v["data"])
    print("  判据: %s" % v["gate"])
    if dry:
        print("  (dry-run: 不执行) 命令: %s" % cmd[:120])
        set_state(name, "pending", "dry-run")
        return True
    set_state(name, "running", "训练中")
    log = "/tmp/orch_%s.log" % name.lower()
    rc, dt = _sh(cmd, log)
    ok = (rc == 0)
    tail = ""
    try:
        lines = [ln for ln in open(log, encoding="utf-8", errors="replace").read().splitlines()
                 if "step " in ln or "完成" in ln]
        tail = lines[-1][:150] if lines else ""
    except Exception:
        pass
    print("  rc=%s · %.0fs · %s" % (rc, dt, tail))
    set_state(name, "success" if ok else "failed", "%s · %.0fs" % (tail[:80], dt))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--layer", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--steps", type=int, default=2500)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    if a.list or (not a.layer and not a.all):
        return list_layers()

    order = ["MEM", "L4moe", "L4"] if a.all else [a.layer]
    t0 = time.time()
    results = {}
    for nm in order:
        if nm not in LAYERS:
            print("❌ 未知层: %s (可用: %s)" % (nm, ", ".join(LAYERS)))
            continue
        results[nm] = run_one(nm, a.steps, a.dry)
    print("\n" + "=" * 78)
    print("📊 编排汇总 (%.0fs)" % (time.time() - t0))
    for k, v in results.items():
        print("  %-6s %s" % (k, "✅" if v else "❌"))
    print("  状态已落盘 → docs/PIPELINE_STATE.json（画布/控制台可轮询）")
    print("=" * 78)
    return 0 if all(results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
