#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_node_loc_lines.py — 画布源码映射(_EXTERNAL_LOC)行号全量自动对账

背景: 验证层 t_auto_srcmap 检查 61 条 (path, line, sym) 里 sym 是否落在 line ±2 行内,
      但它只报 bad[:3] → 行号漂移是"挤牙膏"式修. 本脚本一次全查全修:
  ① import tools/gui/node_logic(与验证层同一入口, 拿解析后的真实 path/line/sym)
  ② 逐条在目标文件里找 sym 的**真实行**(取离旧行最近的命中)
  ③ 回写 node_logic.py 里的行号(只改数字, 幂等)
用法: gui-venv311/bin/python tools/fix_node_loc_lines.py [--apply]
"""
from __future__ import annotations

import os
import re
import sys

REPO = "/home/ubuntu/lerobot-smolvla-lew"
SYS_GUI = os.path.join(REPO, "tools", "gui")
NL = os.path.join(SYS_GUI, "node_logic.py")


def load_locs():
    sys.path.insert(0, SYS_GUI)
    import node_logic as nl                                     # noqa: PLC0415
    return dict(nl._EXTERNAL_LOC)


def find_line(path, sym, old):
    """在文件里找含 sym 的行; 多个命中取离 old 最近的。返回 (new_line 或 None, 命中数)"""
    try:
        lines = open(path, encoding="utf-8", errors="ignore").readlines()
    except OSError:
        return None, 0
    hits = [i + 1 for i, ln in enumerate(lines) if sym in ln]
    if not hits:
        return None, 0
    return min(hits, key=lambda h: abs(h - old)), len(hits)


def main():
    apply = "--apply" in sys.argv
    locs = load_locs()
    src = open(NL, encoding="utf-8").read()
    bad = fixed = unresolved = 0
    plans = []
    for key, (path, line, sym) in sorted(locs.items()):
        if not os.path.isfile(path):
            print("  ✗ %-16s 文件缺: %s" % (key, path))
            unresolved += 1
            continue
        lines = open(path, encoding="utf-8", errors="ignore").readlines()
        near = "".join(lines[max(0, line - 3):line + 2])
        if 1 <= line <= len(lines) and sym in near:
            continue                                            # 已有效
        bad += 1
        new, nhit = find_line(path, sym, line)
        if new is None:
            print("  ⚠️ %-16s L%-5s sym=%r 在 %s 里找不到 → 符号名本身就过期, 需人工"
                  % (key, line, sym, os.path.basename(path)))
            unresolved += 1
            continue
        print("  ✅ %-16s L%-5s → L%-5s (命中%d) sym=%r" % (key, line, new, nhit, sym))
        plans.append((key, line, new, sym))
        fixed += 1
    print("\n汇总: 检查 %d 条 · 漂移 %d 条 · 可修 %d · 需人工 %d" % (len(locs), bad, fixed, unresolved))
    if not apply:
        print("(DRY-RUN; 加 --apply 回写)")
        return 0
    for key, old, new, sym in plans:
        # 在 ["KEY"] 条目块内把 ", <old>, " 的第三个字段行号改成 new (只改一次)
        pat = re.compile(r'(_EXTERNAL_LOC\["' + re.escape(key) + r'"\]\s*=\s*\(.*?,\s*)' + str(old)
                         + r'(\s*,\s*")', re.S)
        src2, n = pat.subn(lambda m: m.group(1) + str(new) + m.group(2), src, count=1)
        if n == 0:
            print("  ⚠️ 回写失败(文本模式不匹配): %s (%s→%s)" % (key, old, new))
        else:
            src = src2
    open(NL, "w", encoding="utf-8").write(src)
    print("已回写 %s (%d 处)" % (NL, len(plans)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
