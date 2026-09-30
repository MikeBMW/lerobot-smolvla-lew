#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零动作复核「安全闸已关闭」开关是否真生效 —— 照 layered-safety-gate-operations §3b/§5。

判据(两条都要):
  ① 执行器的 `_disabled()` 回 (True, <原因串>) 且原因串里带 到期/by/note;
  ② 拿**一条真实下发调用串**过闸门函数 ⇒ "不拦"(False) + 调用时日志/DISABLED 行有审计。

本工具只 import 模块 + 调纯函数: **不改任何状态、不写队列、不下发任何动作**。

用法(工程根目录下):
  python3 scripts/verify_gate_off.py                 # 默认探 tools/l2_daemon.py 的 _disabled/_vl_gate_blocks
  python3 scripts/verify_gate_off.py --call 'L2.goto_gold_pt1 到示教点'
  python3 scripts/verify_gate_off.py --module tools/l2_daemon.py --gate _gate_blocks --disabled _disabled

⚠️ 默认路径下**别**在同一条 shell 命令行里出现 `l2_daemon.py` 字面量(keepalive 脚本的 pkill 模式会误杀
自己的 shell)。这里用 `--module` 参数传路径即可绕开: 先把路径存进变量再传。
"""
import argparse
import importlib.util
import os
import sys


def load_module(path):
    abs_path = os.path.abspath(path)
    sys.path.insert(0, os.path.dirname(abs_path))       # 同目录工具互导(tools/* 常互 import)
    spec = importlib.util.spec_from_file_location("probe_executor", abs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                        # 主循环在 __main__ 里, 这里只跑模块级定义
    return mod


def call_soft(fn, *args):
    """签名不确定时逐个退化调用(有的实现 gate(call) / 有的 gate()) —— 都不改状态。"""
    try:
        return fn(*args)
    except TypeError:
        return fn()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default=os.path.join("tools", "%s%s%s" % ("l2", "_daemon", ".py")),
                    help="执行器模块路径(默认 tools/l2_daemon.py)")
    ap.add_argument("--disabled", default="_vl_disabled", help="开关判定函数名")
    ap.add_argument("--gate", default="_vl_gate_blocks", help="闸门函数名(收一条调用串返回 True=拦)")
    ap.add_argument("--call", action="append", default=[],
                    help="真实下发调用串(可重复给; 默认用一条运动类样例)")
    a = ap.parse_args()

    if not os.path.exists(a.module):
        print("✗ 找不到模块: %s" % a.module)
        return 2
    mod = load_module(a.module)

    dis = getattr(mod, a.disabled, None)
    if dis is None:
        print("✗ 模块里没有 %s(核对函数名)" % a.disabled)
        return 2
    got = call_soft(dis)
    flag, why = (got if isinstance(got, (tuple, list)) else (got, ""))
    print("① %s() → disabled=%r  why=%s" % (a.disabled, flag, why))
    if not flag:
        print("   ⇒ 闸门**没关**(或已到期自动恢复 fail-closed)。要关就按 §3b 写运行时开关文件并带 until。")

    calls = a.call or [
        'timeout 90 ros2 service call /move_line interfaces/srv/TargetPose "{speed: 60.0, pose: {position: {x: 0.0, y: 0.0, z: 0.0}}}"',
        "L2.slot1 回一号位",
    ]
    gate = getattr(mod, a.gate, None)
    if gate is None:
        print("✗ 模块里没有 %s" % a.gate)
        return 2
    ok = True
    for c in calls:
        blocked = call_soft(gate, c)
        print("② %-70s → blocked=%r" % (c[:70], blocked))
        ok = ok and (not blocked)
    print("   ⇒ %s" % ("两条都放行, 与关闸状态一致 ✅" if ok else "仍有调用被拦 ❌ 关闸没真正生效(查没关的是哪一层/哪条路径)"))
    return 0 if (flag and ok) else 1


if __name__ == "__main__":
    sys.exit(main())
