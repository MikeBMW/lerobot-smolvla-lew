#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程架构自检 (状态空间工程 / 节点逻辑) —— 迁移后长期可复跑的那把尺子。

判据 (任何一条不过 = 架构被改坏了):
  ① 包可导入, 注册表 key 数与画布节点名映射可用
  ② **逻辑住在包里**: 每个 key 的源码文件都在 src/lerobot/engineering 下 (GUI 只显示)
  ③ 画布 JSON 真源在包内 (flows/), 校验无错, 孤立节点 0
  ④ L2/L3/L4/L5 档位契约: 每档节点都能落到已注册逻辑 (levels.check)
  ⑤ GUI 兼容壳: tools/gui/node_logic.py 导入的 NODE_LOGIC 与包里逐 key 一致
  ⑥ 画布渲染: node items / link items 与文件数一致 (调 tools/verify_canvas_render.py 的数字)

用法:
  gui-venv311/bin/python tools/verify_engineering.py
  gui-venv311/bin/python tools/verify_engineering.py --regen-by-level   # 重生成档位索引
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

import lerobot.engineering as E  # noqa: E402

fails = []


def chk(ok, label, extra=""):
    print("  %s %-46s %s" % ("✅" if ok else "❌", label, extra))
    if not ok:
        fails.append(label)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regen-by-level", action="store_true", help="重生成 nodes/by_level.py")
    ap.add_argument("--render", action="store_true", help="连画布渲染一起跑 (慢, 需 Qt)")
    a = ap.parse_args()

    print("=== ① 包与注册表 ===")
    n_keys = len(E.NODE_ORDER)
    chk(n_keys >= 140, "注册 key 数", "%d 个" % n_keys)
    chk(E.paths.REPO_ROOT == REPO, "仓库根解析", E.paths.REPO_ROOT)
    chk(E.paths.LOGIC_FILE.endswith("engineering/nodes/library.py"), "逻辑真源在包内", E.paths.LOGIC_FILE.replace(REPO + "/", ""))

    print("=== ② 逻辑住包里 (GUI 只显示) ===")
    homes = {}
    for k in E.NODE_ORDER:
        f = E.home_file(k) or "?"
        homes[f] = homes.get(f, 0) + 1
    outside = {f: c for f, c in homes.items() if not f.startswith(os.path.join(REPO, "src", "lerobot"))}
    chk(not outside, "没有逻辑留在 GUI/tools 下", "落点文件 %d 个" % len(homes))
    if outside:
        for f, c in sorted(outside.items())[:6]:
            print("        ⚠ 仍在外部: %s (%d 个 key) — 属 _EXTERNAL_LOC 显式指向的真实实现, 允许" % (f.replace(REPO + "/", ""), c))

    print("=== ③ 画布 JSON 真源 ===")
    d, errs = E.flows.load_canvas()
    st = E.flows.stats(d)
    chk(os.path.dirname(E.paths.canvas_json()) == E.paths.FLOWS_DIR, "真源在包内 flows/", E.paths.canvas_json().replace(REPO + "/", ""))
    chk(not errs, "画布校验", "nodes=%d links=%d" % (st["nodes"], st["links"]))
    chk(not E.flows.orphans(d), "孤立节点", "0")

    print("=== ④ L2/L3/L4/L5 档位契约 ===")
    res = E.levels.check(verbose=False)
    for lv, v in res["levels"].items():
        chk(v["nodes"] > 0 and not v["no_logic_key"], "%s 档位可执行" % lv,
            "%d 节点 · 无逻辑 %s" % (v["nodes"], v["no_logic_key"] or 0))
    chk(not res["problems"], "档位契约无问题", str(res["problems"]))

    print("=== ⑤ GUI 兼容壳一致 ===")
    shim = os.path.join(REPO, "tools", "gui", "node_logic.py")
    code = ("import sys; sys.path.insert(0, %r); import node_logic as N, lerobot.engineering as E;"
            "print(len(N.NODE_LOGIC));"
            "print(sorted(N.NODE_LOGIC) == sorted(E.NODE_LOGIC));"
            "print(N.execute_node_logic.__module__)" % os.path.join(REPO, "tools", "gui"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    out = (r.stdout or "").strip().splitlines()
    ok = len(out) == 3 and out[1] == "True" and out[2] == "lerobot.engineering.runtime"
    chk(ok, "壳转发到包 (key 集合一致)", (out[0] + " 个 key" if out else (r.stderr or "")[-120:]))

    print("=== ⑥ 档位索引 nodes/by_level.py ===")
    try:
        from lerobot.engineering.nodes import by_level
        s = by_level.summary()
        chk(sum(v["nodes"] for v in s.values()) > 0, "档位索引可用", str(s))
        if a.regen_by_level:
            subprocess.run([sys.executable, os.path.join(REPO, "tools", "verify_engineering.py"), "--regen-only-note"],
                           capture_output=True)
            print("      (--regen-by-level 由 tools/gen_by_level_index.py 执行)")
    except Exception as ex:                                                       # noqa: BLE001
        chk(False, "档位索引", str(ex)[:80])

    if a.render:
        print("=== ⑦ 画布渲染 (Qt 离屏) ===")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([sys.executable, os.path.join(REPO, "tools", "verify_canvas_render.py")],
                           capture_output=True, text=True, env=env, timeout=600)
        tail = [l for l in (r.stdout or "").splitlines() if l.startswith(("文件:", "渲染:", "判据:"))]
        for l in tail:
            print("     ", l)
        chk(bool(tail) and "渲染正常" in " ".join(tail), "渲染正常", "")

    print()
    print("结论:", "✅ 工程架构自检通过" if not fails else "❌ 不过项: %s" % fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
