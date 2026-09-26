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

REPO = os.environ.get("ZMAX_REPO") or "/home/ubuntu/zmax_rel"
# 🐛 2026-09-27 实测: 这里原来写死 /home/ubuntu/lerobot-smolvla-lew —— 那是**共享检出**,
#   会被切到别的分支 (当时在 mac-hw), 于是"改版本必同步"的 5 处改到了**另一棵树的另一个分支**上,
#   而 main 线真源是 worktree /home/ubuntu/zmax_rel ⇒ 版本号在真源里根本没变 (静默错改)。
#   口径: 真源 = worktree; 需要改别的树就显式 --repo / ZMAX_REPO。
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
    ap.add_argument("--repo", default="", help="仓库根 (缺省 = ZMAX_REPO 环境变量或 worktree /home/ubuntu/zmax_rel)")
    a = ap.parse_args()
    global REPO, STUDIO, UPD, DOCS, VSYNC, VM
    if a.repo:
        REPO = a.repo
        STUDIO = os.path.join(REPO, "tools/gui/studio.py")
        UPD = os.path.join(REPO, "tools/gui/update_checker.py")
        DOCS = os.path.join(REPO, "tools/gui/docs_sync.py")
        VSYNC = os.path.join(REPO, "tools/gui/version_sync.py")
        VM = os.path.join(REPO, "VERSION.md")
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
    #   🐛 2026-09-27: 原锚点是死串 "# v5.15.13:" —— 但真源里的 changelog 行长这样
    #     "# v5.15.13 (2026-09-27): **手眼标定 T_base_cam 首次解出…**"
    #   带日期括号 ⇒ 死串永远匹配不到 (在真源上直接崩, 在别的树上则可能静默改错)。
    #   改成"行首版本号"正则 = 认版本号不认记法。
    pat = re.compile(r"(?m)^([ \t]*)# %s\b.*$" % re.escape(ov))
    mm = pat.search(s2)
    assert mm, "找不到 changelog 锚点 (# %s …) — 先确认 repo/分支: %s" % (ov, REPO)
    #   行首可能有缩进 (真源里就是 8 空格缩进的注释块) ⇒ 连带缩进一起还原
    s2 = s2[:mm.start()] + "%s# %s: %s\n" % (mm.group(1), nv, summ) + s2[mm.start():]
    chk.append(("studio.py changelog 行", 1, s2.count("# %s:" % nv)))

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

    # 4b) 🐛 2026-09-27 实测补: tools/ci/integrity_check.py 的 EXPECTED_VERSION 是**硬编码**,
    #   原先不在同步清单里 ⇒ 每次 bump 完, 自家完整性门必红 ("CURRENT_VERSION 不是 vX"),
    #   等于"改版本必同步"清单漏了一处。门自己就是判据, 必须一起改。
    INTEG = os.path.join(REPO, "tools/ci/integrity_check.py")
    ic = _read(INTEG)
    ic2 = ic.replace('EXPECTED_VERSION = "%s"' % ov, 'EXPECTED_VERSION = "%s"' % nv)
    chk.append(("integrity_check EXPECTED_VERSION", ic.count('EXPECTED_VERSION = "%s"' % ov),
                ic2.count('EXPECTED_VERSION = "%s"' % nv)))

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
    for p, txt in ((STUDIO, s2), (UPD, u), (DOCS, d2), (VSYNC, v2), (INTEG, ic2), (VM, vm2)):
        open(p, "w", encoding="utf-8").write(txt)
    import py_compile
    for p in (STUDIO, UPD, DOCS, VSYNC, INTEG):
        py_compile.compile(p, doraise=True)
    print("✅ 已写盘并语法校验通过; 下一步: git add/commit → git tag %s → push (CI 出 Windows/macOS 包)" % nv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
