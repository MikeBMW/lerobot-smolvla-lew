#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bump_version.py — Z-MAX 小版本迭代一条龙 (按 VERSION.md 的"改版本必同步"口径)

同步 5 处 + 1 行历史:
  1. tools/gui/studio.py      — 品牌版本 QLabel + 窗口标题两处
  2. tools/gui/update_checker.py — CURRENT_VERSION
  3. tools/gui/docs_sync.py   — "version" + "zmax_version"
  4. tools/gui/version_sync.py — `zmax_ver = "X.Y.Z"` (版本面板显示; 🐛 2026-09-24 补: 原先漏同步, 长期停在 5.11.4)
  5. tools/gui/studio.py      — changelog 注释前缀 (**只写做了什么 + 根因**)
  6. VERSION.md               — 版本历史表新增一行
最后打印核对清单 (grep 计数 + 旧版本号残留扫描), 不自动 git commit/tag —— 由调用方显式执行。

用法:
  gui-venv311/bin/python tools/bump_version.py --to 5.11.5 --summary-file /tmp/v55115.txt [--dry]
  (summary 一行写完; 支持 markdown, 写进 changelog 注释行与 VERSION.md 表格单元)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
STUDIO = os.path.join(REPO, "tools/gui/studio.py")
UPD = os.path.join(REPO, "tools/gui/update_checker.py")
DOCS = os.path.join(REPO, "tools/gui/docs_sync.py")
VSYNC = os.path.join(REPO, "tools/gui/version_sync.py")
VM = os.path.join(REPO, "VERSION.md")


def _read(p):
    return open(p, encoding="utf-8").read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="新版本号, 如 5.11.5 (不带 v)")
    ap.add_argument("--from", dest="frm", default="", help="旧版本号(默认自动探测)")
    ap.add_argument("--summary-file", required=True)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    new, nv = a.to, "v" + a.to
    s = _read(STUDIO)
    m = re.findall(r"Z-MAX v(\d+\.\d+\.\d+)", s)
    old = a.frm or (max(set(m), key=m.count) if m else "")
    if not old:
        print("❌ 探测不到旧版本号")
        return 2
    ov = "v" + old
    if old == a.to:
        print("❌ 新版本号与现有相同")
        return 2
    summ = _read(a.summary_file).strip().replace("\n", " ")
    chk: list[tuple[str, int, int]] = []

    # 1) studio.py 品牌版本
    s2 = s.replace('QLabel("Z-MAX %s")' % ov, 'QLabel("Z-MAX %s")' % nv)
    chk.append(("studio.py QLabel", s.count('QLabel("Z-MAX %s")' % ov), s2.count('QLabel("Z-MAX %s")' % nv)))
    # 2) studio.py 窗口标题 (两处)
    n_t = s2.count("XSpace Studio — Z-MAX %s" % ov)
    s2 = s2.replace("XSpace Studio — Z-MAX %s" % ov, "XSpace Studio — Z-MAX %s" % nv)
    chk.append(("studio.py 窗口标题", n_t, s2.count("XSpace Studio — Z-MAX %s" % nv)))
    # 3) changelog 前缀 (插在旧版本注释行之前)
    anchor = "# %s:" % ov
    assert anchor in s2, "找不到 changelog 锚点 %s" % anchor
    s2 = s2.replace(anchor, "# %s: %s\n%s" % (nv, summ, anchor), 1)
    chk.append(("studio.py changelog 行", 1 if anchor in s2 else 0, 1))

    u = _read(UPD).replace('CURRENT_VERSION = "%s"' % ov, 'CURRENT_VERSION = "%s"' % nv)
    chk.append(("update_checker CURRENT_VERSION", 1, u.count('CURRENT_VERSION = "%s"' % nv)))

    d = _read(DOCS)
    d2 = d.replace('"version": "%s"' % ov, '"version": "%s"' % nv).replace('"zmax_version": "%s"' % ov, '"zmax_version": "%s"' % nv)
    chk.append(("docs_sync 两键", d.count('"%s"' % ov), d2.count('"%s"' % nv)))

    # 4) version_sync.py 版本面板字面量 (🐛 2026-09-24: 原先漏了这处 → 面板长期显示旧号)
    #   ⚠️ 2026-09-24 实测修: 本文件的值**不带 v 前缀** (`zmax_ver = "5.13.0"`), 而 ov/nv 带 v
    #   → 原正则永远 0 命中 (静默漏同步, 与本次"面板停在旧号"同族根因)。用去 v 版本号匹配。
    ov_bare, nv_bare = ov.lstrip("v"), nv.lstrip("v")
    v = _read(VSYNC)
    v2 = v.replace('zmax_ver = "%s"' % ov_bare, 'zmax_ver = "%s"' % nv_bare)
    chk.append(("version_sync zmax_ver", v.count('zmax_ver = "%s"' % ov_bare),
                v2.count('zmax_ver = "%s"' % nv_bare)))

    vm = _read(VM)
    row = "| **%s** | %s | %s |\n" % (nv, time.strftime("%m-%d"), summ)     # 🐛 日期原写死 09-22
    lines = vm.splitlines(keepends=True)
    idx = next((i for i, l in enumerate(lines) if l.startswith("| **v")), None)
    if idx is None:
        print("❌ VERSION.md 找不到历史表")
        return 2
    lines.insert(idx, row)
    vm2 = "".join(lines)

    print("═══ 版本迭代 %s → %s ═══" % (ov, nv))
    for name, before, after in chk:
        print("  %-32s 旧命中 %-3d → 新命中 %-3d %s" % (name, before, after, "✅" if after >= max(1, before) else "❌"))
    print("  %-32s %s" % ("VERSION.md 新行", "✅ 插入到表首(第 %d 行)" % (idx + 1)))
    resid = len(re.findall(r"\bv%s\b" % re.escape(old), s2 + u + d2 + v2)) + len(re.findall(r"\bv%s\b" % re.escape(old), vm2))
    print("  旧版本号残留 (历史行属正常): %d 处" % resid)
    if a.dry:
        print("(--dry: 未写盘)")
        return 0
    for p, txt in ((STUDIO, s2), (UPD, u), (DOCS, d2), (VSYNC, v2), (VM, vm2)):
        open(p, "w", encoding="utf-8").write(txt)
    import py_compile
    for p in (STUDIO, UPD, DOCS, VSYNC):
        py_compile.compile(p, doraise=True)
    print("✅ 已写盘并语法校验通过; 下一步: git add/commit → git tag %s → push (CI 出 Windows/macOS 包)" % nv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
