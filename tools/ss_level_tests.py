#!/usr/bin/env python3
"""🧪 ss_level_tests.py — Z-MAX 三级能力自动测试 (L2基础/L3高级/L4专家)
用法 (gui-venv311):
  gui-venv311/bin/python tools/ss_level_tests.py --list        # 三级清单
  gui-venv311/bin/python tools/ss_level_tests.py --level L2    # 只跑 L2
  gui-venv311/bin/python tools/ss_level_tests.py               # 三级全量
  echo $?   # 0=全过 1=有 FAIL
"""
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "verification"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

# 真源加载
_VL_P = os.path.join(ROOT, "src", "lerobot", "verification", "verification_layer.py")
_spec = importlib.util.spec_from_file_location("lerobot.verification.verification_layer", _VL_P)
_vl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vl)

from capability_levels import CAPABILITY_LEVELS, resolve_tests, level_list  # noqa: E402


def run_level(level, only_func=None):
    """跑某级全部真实断言 → [(fid, name, method, ok, detail)]"""
    import numpy as np
    tests = resolve_tests(level)
    if only_func:
        tests = [t for t in tests if t["fid"] == only_func]
    results = []
    inst = _vl.VerificationLayer()
    for t in tests:
        fn = getattr(inst, t["method"], None)
        if fn is None:
            results.append((t["fid"], t["name"], t["method"], False, "方法不存在"))
            continue
        try:
            r = fn(np)  # np 参数 (同 run_tree 签名)
            ok = bool(r[0]) if isinstance(r, tuple) else bool(r)
            detail = str(r[1]) if isinstance(r, tuple) and len(r) > 1 else "OK"
            results.append((t["fid"], t["name"], t["method"], ok, detail))
        except Exception as e:
            results.append((t["fid"], t["name"], t["method"], False,
                            f"{type(e).__name__}: {str(e)[:100]}"))
    return results


def main():
    args = [a for a in sys.argv[1:]]
    if "--list" in args:
        for lv in level_list():
            print(f"[{lv['level']}] {lv['name']} · {lv['tech']} · {lv['funcs']} 功能")
            print(f"    {lv['summary']}")
        return 0
    only_level = None
    if "--level" in args:
        only_level = args[args.index("--level") + 1]
    levels = ["L2", "L3", "L4"] if not only_level else [only_level]
    all_ok = True
    for lv in levels:
        t0 = time.time()
        res = run_level(lv)
        n_ok = sum(1 for r in res if r[3])
        n_fail = len(res) - n_ok
        print(f"\n{'='*56}\n[{lv}] {CAPABILITY_LEVELS[lv]['name']} · {len(res)} 断言 · "
              f"✅{n_ok} ❌{n_fail} · {time.time()-t0:.0f}s\n{'='*56}")
        for fid, name, method, ok, detail in res:
            mark = "✅" if ok else "❌"
            print(f"  {mark} {fid} {name} [{method}] {'' if ok else detail}")
        if n_fail:
            all_ok = False
    print(f"\n{'✅ 三级全过' if all_ok else '❌ 有失败'} (L2基础辅助→L3高级NOA→L4专家城区)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
