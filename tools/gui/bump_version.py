#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bump_version.py — Z-MAX 版本一条龙 (跨机可移植版)
=====================================================
老倪版本约定 (记忆): 小改直接推 / 中改 tag / 大改 release+同步 tag
  · 小版本 (patch): 提交即可
  · 中版本 (minor): 提交 + git tag
  · 大版本 (major): 提交 + tag + Release Note

本工具把版本号在**所有出现点**一次改到位, 并追加 changelog 条目。
(静安机器上有过同名工具但路径写死; 此为 Mac 可移植版)

用法:
  python3 tools/gui/bump_version.py 5.12.1 "fix: xxx — 一句话说明"
  python3 tools/gui/bump_version.py --show          # 只显示当前版本
  python3 tools/gui/bump_version.py 5.12.1 MSG --tag   # 顺带打 tag
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STUDIO = os.path.join(REPO, "tools", "gui", "studio.py")
VSYNC = os.path.join(REPO, "tools", "gui", "version_sync.py")
VER_RE = re.compile(r"\bv?(\d+)\.(\d+)\.(\d+)\b")


def read_current() -> str:
    """从 studio.py 的侧边栏标签读当前版本 (界面显示的真源)"""
    try:
        s = open(STUDIO, encoding="utf-8").read()
        m = re.search(r'ver\s*=\s*QLabel\("Z-MAX v([\d.]+)"\)', s)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "?"


def bump_occurrences(path: str, old: str, new: str) -> list:
    """把文件中所有 `vX.Y.Z` / `"X.Y.Z"` 形式的旧版本改成新版本; 返回命中描述"""
    if not os.path.exists(path):
        return []
    s = open(path, encoding="utf-8").read()
    hits = []
    # ① 带 v 前缀 (界面标签/窗口标题/注释标题)
    pat_v = re.compile(r"(?<![\d.])v" + re.escape(old) + r"(?![\d.])")
    n1 = len(pat_v.findall(s))
    if n1:
        s = pat_v.sub("v" + new, s)
        hits.append(f"{os.path.basename(path)}: v{old} → v{new} ×{n1}")
    # ② 纯数字带引号 (version_sync.py 的 zmax_ver = "5.11.4")
    pat_q = re.compile(r'(["\'])' + re.escape(old) + r'\1')
    n2 = len(pat_q.findall(s))
    if n2:
        s = pat_q.sub(lambda m: f'{m.group(1)}{new}{m.group(1)}', s)
        hits.append(f"{os.path.basename(path)}: \"{old}\" → \"{new}\" ×{n2}")
    if n1 or n2:
        open(path, "w", encoding="utf-8").write(s)
    return hits


def add_changelog(msg: str, new: str) -> str | None:
    """在 studio.py 的 changelog 注释区顶部插入一条 (先找已有 v5.11.5 锚点)"""
    if not msg:
        return None
    s = open(STUDIO, encoding="utf-8").read()
    entry = (f'        # v{new}: {msg}  '
             f'({datetime.now().strftime("%Y-%m-%d")})\n')
    if f"# v{new}:" in s:
        return f"changelog 已有 v{new} 条目, 跳过"
    # 锚点: 找到第一条 `        # v X.Y.Z:` 形注释行, 插在它前面
    m = re.search(r"^(\s*)#\s*v(\d+\.\d+\.\d+):", s, re.M)
    if not m:
        return "未找到 changelog 锚点, 跳过 (请手工补)"
    idx = m.start()
    s = s[:idx] + entry + s[idx:]
    open(STUDIO, "w", encoding="utf-8").write(s)
    return f"changelog 已插入 v{new} 条目"


def main():
    ap = argparse.ArgumentParser(description="Z-MAX 版本一条龙")
    ap.add_argument("version", nargs="?", help="新版本号, 如 5.12.1")
    ap.add_argument("message", nargs="?", default="", help="变更说明 (changelog)")
    ap.add_argument("--show", action="store_true", help="只显示当前版本")
    ap.add_argument("--tag", action="store_true", help="打 git tag")
    ap.add_argument("--no-commit", action="store_true", help="不自动提交")
    a = ap.parse_args()

    cur = read_current()
    if a.show or not a.version:
        print(f"  当前版本 (studio.py 界面标签): v{cur}")
        print(f"  version_sync.py:", end=" ")
        try:
            s = open(VSYNC, encoding="utf-8").read()
            m = re.search(r'zmax_ver\s*=\s*"([\d.]+)"', s)
            print(f'"{m.group(1)}"' if m else "(未找到)")
        except Exception:
            print("(读失败)")
        return 0

    new = a.version.lstrip("v")
    if not VER_RE.fullmatch(new):
        print(f"  ❌ 版本号格式不对: {new} (应如 5.12.1)")
        return 2
    if new == cur:
        print(f"  已是 v{new}, 无需改动")
        return 0

    parts = [int(x) for x in new.split(".")]
    oldp = [int(x) for x in cur.split(".")] if VER_RE.fullmatch(cur) else None
    kind = "?"
    if oldp:
        kind = ("大版本 (major)" if parts[0] > oldp[0] else
                "中版本 (minor)" if parts[1] > oldp[1] else "小版本 (patch)")
    print(f"═══ 版本升级 v{cur} → v{new}  [{kind}] ═══")

    all_hits = []
    for p in (STUDIO, VSYNC):
        all_hits += bump_occurrences(p, cur, new)
    for h in all_hits:
        print(f"  ✅ {h}")
    if not all_hits:
        print("  ⚠️ 没有命中任何位置 — 请检查版本号真源")

    r = add_changelog(a.message, new)
    if r:
        print(f"  {'✅' if '插入' in r else 'ℹ️'} {r}")

    if not a.no_commit and all_hits:
        try:
            subprocess.run(["git", "add", STUDIO, VSYNC], cwd=REPO, check=True)
            subprocess.run(["git", "commit", "-q", "-m",
                            f"chore(version): v{cur} → v{new} [{kind}]\n\n{a.message or '小版本迭代'}"],
                           cwd=REPO, check=True)
            print(f"  ✅ 已提交 v{new}")
        except Exception as e:
            print(f"  ⚠️ 提交失败: {e}")
        if a.tag:
            try:
                subprocess.run(["git", "tag", "-a", f"v{new}", "-m",
                                a.message or f"Z-MAX v{new}"], cwd=REPO, check=True)
                print(f"  ✅ 已打 tag v{new}")
            except Exception as e:
                print(f"  ⚠️ tag 失败: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
