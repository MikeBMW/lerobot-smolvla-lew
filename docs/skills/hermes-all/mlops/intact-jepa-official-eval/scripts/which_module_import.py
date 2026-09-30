#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判决 'import module' 到底命中哪一份 module.py —— 并断言 hydra 能否 locate 目标类。

背景: INTACT-JEPA 仓库里有两份同名 module.py
  <repo>/module.py            根运行时版 (ARPredictor / IntentActionActor / Embedder / MLP ...)
  <repo>/paper_runtime/module.py  INTACT 官方版 (InverseTransitionActor / MixtureGaussianInverseActor ...)
Python 把**正在执行的脚本所在目录**放在 sys.path[0] —— 优先于 PYTHONPATH →
  ② (program=paper_runtime/eval.py) 命中 paper_runtime/module.py  ✅
  ③ (program=<repo>/eval.py)        命中 <repo>/module.py          ❌ 没有 InverseTransitionActor
    → hydra.errors.InstantiationException: Error locating target 'module.InverseTransitionActor'

用法 (必须在 INTACT venv 里跑, hydra 只在那里):
  /home/ubuntu/INTACT-JEPA/.venv/bin/python scripts/which_module_import.py [REPO_ROOT]
  # 默认 REPO_ROOT=/home/ubuntu/INTACT-JEPA
退出码: 0 = 两种场景都符合预期 (② 成功 / ③ 失败); 2 = 与预期不符 (仓库结构变了, 需重新诊断)
"""
import sys
import os

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/INTACT-JEPA"
PR = os.path.join(ROOT, "paper_runtime")

try:
    from hydra._internal.utils import _locate
except Exception as e:  # hydra 不在当前解释器里
    print("!! 请用 repo venv 的 python 运行 (hydra 缺失: %s)" % e)
    raise SystemExit(3)

base = [p for p in sys.path if p not in (ROOT, PR)]  # 保留 site-packages, 不要整体替换!


def probe(label, first_dir, targets):
    sys.modules.pop("module", None)
    sys.path[:] = [first_dir] + [PR, ROOT] + base
    import module as m
    got = getattr(m, "__file__", "?")
    print("%s sys.path[0]=%-14s → import module = %s" % (label, os.path.basename(first_dir.rstrip("/")) or first_dir, got))
    ok = {}
    for t in targets:
        try:
            _locate(t)
            ok[t] = True
            print("   ✅ _locate('%s') 成功: %s" % (t, _locate(t)))
        except Exception as e:
            ok[t] = False
            print("   ❌ _locate('%s') 失败: %s | %s" % (t, type(e).__name__, str(e).splitlines()[0][:90]))
    return ok


paper_cls = "module.InverseTransitionActor"
repo_cls = "module.ARPredictor"

print("REPO =", ROOT)
print("--- 场景 ② : program=paper_runtime/eval.py (脚本目录 = paper_runtime) ---")
b = probe("②", PR, [paper_cls, repo_cls])
print("--- 场景 ③ : program=<repo>/eval.py (脚本目录 = 仓库根) ---")
c = probe("③", ROOT, [paper_cls, repo_cls])

print()
print("结论:")
print("  论文权重 (recovery_delta_full_*_s3072, config 引用 %s)" % paper_cls)
print("    → 必须在 ②(paper_runtime) 里跑; ③ 里必然 InstantiationException。")
print("  repo 自训权重 (intact_goal_zmax_*, config 引用 %s)" % repo_cls)
print("    → ③ 设计上就是给这类权重用的 (但 policy 要显式指到 .pt 文件)。")

expected = b.get(paper_cls) is True and c.get(paper_cls) is False
print("预期形态成立(② 成功 / ③ 失败):", expected)
raise SystemExit(0 if expected else 2)
