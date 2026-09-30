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

REPO = os.environ.get("ZMAX_REPO") or "/home/ubuntu/zmax"
# 🐛 2026-09-27 实测: 这里原来写死 /home/ubuntu/zmax —— 那是**共享检出**,
#   会被切到别的分支 (当时在 mac-hw), 于是"改版本必同步"的 5 处改到了**另一棵树的另一个分支**上,
#   而 main 线真源是 worktree /home/ubuntu/zmax ⇒ 版本号在真源里根本没变 (静默错改)。
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
    ap.add_argument("--repo", default="", help="仓库根 (缺省 = ZMAX_REPO 环境变量或 worktree /home/ubuntu/zmax)")
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
    # 🐛 2026-09-30 实测: 品牌字面量自 vv5.16.x 起是**双 v** (`Z-MAX vv5.16.34`), 而旧探测正则写的是
    #   单 v ⇒ 命中到 changelog 里的历史字符串 (实测探出 1.0.4) 或直接崩。口径 = 认版本号不认记法。
    m = (re.findall(r'QLabel\("Z-MAX v{1,2}(\d+\.\d+\.\d+)"\)', s)
         or re.findall(r"XSpace Studio — Z-MAX v{1,2}(\d+\.\d+\.\d+)", s)
         or re.findall(r"Z-MAX v{1,2}(\d+\.\d+\.\d+)", s))
    old = a.frm or (max(set(m), key=m.count) if m else "")
    if not old:
        print("❌ 探测不到旧版本号")
        return 2
    ov = "v" + old
    # 🐛 2026-09-30: 品牌位(QLabel/窗口标题/CURRENT_VERSION/docs_sync/integrity)一律 **vv** 记法;
    #   写回统一用 nv_brand, 匹配用 v{1,2} 正则 ⇒ 单 v 时代的老检出也能平滑升级。
    nv_brand = "vv" + a.to
    if old == a.to:
        print("❌ 新版本号与现有相同")
        return 2
    summ = _read(a.summary_file).strip().replace("\n", " ")
    chk: list[tuple[str, int, int]] = []

    # 1) studio.py 品牌版本
    s2 = s
    _ql = re.compile(r'QLabel\("Z-MAX v{1,2}%s"\)' % re.escape(old))
    n_ql = len(_ql.findall(s2))
    s2 = _ql.sub('QLabel("Z-MAX %s")' % nv_brand, s2)
    chk.append(("studio.py QLabel", n_ql,
                len(re.findall(r'QLabel\("Z-MAX v{1,2}%s"\)' % re.escape(a.to), s2))))
    # 2) studio.py 窗口标题 (两处)
    _ti = re.compile(r"XSpace Studio — Z-MAX v{1,2}%s" % re.escape(old))
    n_t = len(_ti.findall(s2))
    s2 = _ti.sub("XSpace Studio — Z-MAX %s" % nv_brand, s2)
    chk.append(("studio.py 窗口标题", n_t,
                len(re.findall(r"XSpace Studio — Z-MAX v{1,2}%s" % re.escape(a.to), s2))))
    # 3) changelog 前缀 (插在旧版本注释行之前)
    #   🐛 2026-09-27: 原锚点是死串 "# v5.15.13:" —— 但真源里的 changelog 行长这样
    #     "# v5.15.13 (2026-09-27): **手眼标定 T_base_cam 首次解出…**"
    #   带日期括号 ⇒ 死串永远匹配不到 (在真源上直接崩, 在别的树上则可能静默改错)。
    #   改成"行首版本号"正则 = 认版本号不认记法。
    pat = re.compile(r"(?m)^([ \t]*)# v{1,2}%s\b.*$" % re.escape(old))
    mm = pat.search(s2)
    assert mm, "找不到 changelog 锚点 (# v[V]%s …) — 先确认 repo/分支: %s" % (old, REPO)
    #   行首可能有缩进 (真源里就是 8 空格缩进的注释块) ⇒ 连带缩进一起还原
    s2 = s2[:mm.start()] + "%s# %s: %s\n" % (mm.group(1), nv_brand, summ) + s2[mm.start():]
    chk.append(("studio.py changelog 行", 1, len(re.findall(r"# v{1,2}%s:" % re.escape(a.to), s2))))

    _cv = re.compile(r'CURRENT_VERSION = "v{1,2}%s"' % re.escape(old))
    u = _cv.sub('CURRENT_VERSION = "%s"' % nv_brand, _read(UPD))
    chk.append(("update_checker CURRENT_VERSION", 1,
                len(re.findall(r'CURRENT_VERSION = "v{1,2}%s"' % re.escape(a.to), u))))

    d = _read(DOCS)
    d2 = (re.sub(r'"version": "v{1,2}%s"' % re.escape(old), '"version": "%s"' % nv_brand, d)
          .replace('"zmax_version": "v%s"' % old, '"zmax_version": "%s"' % nv_brand)
          .replace('"zmax_version": "vv%s"' % old, '"zmax_version": "%s"' % nv_brand))
    chk.append(("docs_sync 两键", len(re.findall(r'"version": "v{1,2}%s"' % re.escape(old), d)),
                len(re.findall(r'"version": "v{1,2}%s"' % re.escape(a.to), d2))))

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
    _ev = re.compile(r'EXPECTED_VERSION = "v{1,2}%s"' % re.escape(old))
    ic2 = _ev.sub('EXPECTED_VERSION = "%s"' % nv_brand, ic)
    chk.append(("integrity_check EXPECTED_VERSION", len(_ev.findall(ic)),
                len(re.findall(r'EXPECTED_VERSION = "v{1,2}%s"' % re.escape(a.to), ic2))))

    vm = _read(VM)
    row = "| **%s** | %s | %s |\n" % (nv_brand, time.strftime("%m-%d"), summ)     # 🐛 日期原写死 09-22; 品牌位用 vv 记法
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
    resid = len(re.findall(r"\bv{1,2}%s\b" % re.escape(old), s2 + u + d2 + v2)) + len(re.findall(r"\bv{1,2}%s\b" % re.escape(old), vm2))
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
