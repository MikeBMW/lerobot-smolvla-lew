#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行期调用链探针模板 — 回答「这段代码到底有没有每帧在跑 / 断点为什么没进来」

照抄后只需改三处: ROOT/REPO 路径、TRACE_FILES 目标文件、patch() 的目标类方法清单。

两条证据一起给, 缺一不可:
  ① 函数级计数 (importlib 取类 → 裹方法) — 回答"这个类/方法进没进"
  ② 行级计数 (sys.settrace, 只对目标文件放行局部 tracer) — 回答"这一行执行了几次"
另加"本次已执行到的行"清单 → 证明文件真被加载执行过, 不是没 import。

🔒 必须以 CUDA_VISIBLE_DEVICES="" 运行: 训练占着 GPU 时探针不能抢显存 (加载模型会把训练搞挂)。

用法:
  CUDA_VISIBLE_DEVICES= python3 templates/probe_runtime_callchain.py <SCEN> [steps]
  CUDA_VISIBLE_DEVICES= python3 templates/probe_runtime_callchain.py micro     # 正对照 (必做)
"""
from __future__ import annotations

import importlib
import os
import sys
import time

import numpy as np

ROOT = os.environ.get("PROBE_ROOT", "/home/ubuntu/<repo>")          # ← 改
sys.path[:0] = [ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "tools", "gui")]
os.chdir(ROOT)

os.environ["CUDA_VISIBLE_DEVICES"] = ""            # 🔒 零 GPU 占用
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.update({"SS_MUSCLE": "0", "SS_MOTOR_HUB": "0", "SS_INTENT": "0",
                   "SS_TDEC": "0", "SS_OBSERVE": "0", "SS_SHADOW": "0"})

SCEN = sys.argv[1] if len(sys.argv) > 1 else "A"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 40

CALLS: dict[str, int] = {}
ERR: list[str] = []


def patch(modname: str, cls: str, meth: str, tag: str) -> None:
    """给 类.方法 裹一层计数器 (函数级证据)。幂等: 重复调用不会叠加包裹。"""
    try:
        m = importlib.import_module(modname)
        k = getattr(m, cls)
        f = getattr(k, meth)
        if getattr(f, "_probe_wrapped", False):
            return

        def w(self, *a, **kw):
            CALLS[tag] = CALLS.get(tag, 0) + 1
            return f(self, *a, **kw)

        w._probe_wrapped = True
        setattr(k, meth, w)
    except Exception as e:                                                       # noqa: BLE001
        ERR.append(f"{tag}: {type(e).__name__}: {e}")


# ── ① 函数级: 改成本工程的目标类/方法 (含 __init__ → 看类有没有被实例化) ────────
patch("pkg.mod.action_head", "MyActionHead", "__init__", "MyActionHead.__init__ ⚠️类被实例化")
patch("pkg.mod.action_head", "MyActionHead", "forward", "MyActionHead.forward  ← loss 行所在")
patch("pkg.mod.action_head", "MyActionHead", "predict_action", "MyActionHead.predict_action (推理)")
patch("pkg.mod.modeling", "MyPolicy", "__init__", "MyPolicy.__init__ ⚠️策略被实例化")
patch("pkg.mod.modeling", "MyPolicy", "forward", "MyPolicy.forward (训练)")
patch("pkg.mod.modeling", "MyPolicy", "select_action", "MyPolicy.select_action")
patch("pkg.mod.decoder", "MyDecoder", "decode", "MyDecoder.decode (真链路)")

# ── ② 行级计数 (只对目标文件放行局部 tracer, 否则整进程逐行 → 慢到不可用) ──────
TRACE_FILES = {
    os.path.join("pkg", "action_head.py"): "action_head.py",        # ← 改
    os.path.join("pkg", "modeling.py"): "modeling.py",
}
LC: dict[str, dict[int, int]] = {}


def _ltrace(frame, event, arg):
    if event == "line":
        fn = frame.f_code.co_filename
        for suf, name in TRACE_FILES.items():
            if fn.endswith(suf):
                LC.setdefault(name, {})
                LC[name][frame.f_lineno] = LC[name].get(frame.f_lineno, 0) + 1
                break
    return _ltrace


def _gtrace(frame, event, arg):
    fn = frame.f_code.co_filename
    for suf in TRACE_FILES:
        if fn.endswith(suf):
            return _ltrace
    return None


def line_hits(name: str, lineno: int) -> int:
    return LC.get(name, {}).get(lineno, 0)


KEY_LINES = [("action_head.py", 307, "👈 用户断点: return (loss*...)/(训练 loss)"),   # ← 改
             ("action_head.py", 280, "def forward( (loss 分支入口)"),
             ("action_head.py", 310, "def predict_action( (推理入口)"),
             ("modeling.py", 234, "def forward( (训练分支)"),
             ("modeling.py", 508, "def select_action( (推理)")]


def report(scen: str, extra: dict) -> None:
    print("\n" + "=" * 78)
    print(f"场景 {scen} · 步数 {extra.get('steps', '-')} · 用时 {extra.get('dt', 0):.1f}s")
    print("=" * 78)
    print("① 函数级调用计数 (0 = 本次运行一次都没进):")
    for k in sorted(CALLS):
        print(f"   {CALLS[k]:>6}  {k}")
    if not CALLS:
        print("   (无)")
    if ERR:
        print("   打桩失败:", ERR)
    print("\n② 行级计数 (关键行):")
    for name, ln, why in KEY_LINES:
        print(f"   {line_hits(name, ln):>6}  {name}:{ln}  {why}")
    print("\n   本次已执行到的行 (证明文件真被加载执行过):")
    hits = sorted(LC.get("action_head.py", {}).items())
    print("     ", ", ".join(f"{ln}({c})" for ln, c in hits[:40]) or "(无)")
    if extra:
        print("\n③ 引擎侧计数:", extra)


def micro() -> None:
    """正对照 (必做): 同进程直接调 forward/predict_action → 证明打桩真的抓得住那行。"""
    import torch
    # head = 用本工程最小 preset / 小 dims 构造一个微型对象
    # loss = head.forward(cond, act, ...)            → KEY_LINES 里 loss 行应 +1
    # out  = head.predict_action(cond, ...)          → 该行增量必须为 0 (推理不走 loss)
    raise SystemExit("把本函数换成你的微型对象调用; 不做这一步, 上面的 0 次无法排除'打桩失效'")


if __name__ == "__main__":
    print(f"探针场景={SCEN} 步数={STEPS} CUDA_VISIBLE_DEVICES='{os.environ['CUDA_VISIBLE_DEVICES']}' "
          f"(空 = 不动 GPU)")
    if SCEN == "micro":
        micro()
    else:
        sys.settrace(_gtrace)
        try:
            extra = run_engine(SCEN)        # ← 复刻被测档位的**同一份**装配调用
        finally:
            sys.settrace(None)
        report(SCEN, extra)
