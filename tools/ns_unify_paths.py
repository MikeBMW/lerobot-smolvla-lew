#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-09-30 Phase B: 把工程内绝对路径统一到 /home/ubuntu/zmax 命名空间

规则:
  1) /home/ubuntu/zmax_rel/...        → /home/ubuntu/zmax/...          (zmax_rel 本就是 zmax 的软链, 恒安全)
  2) /home/ubuntu/zmax_dds/...        → /home/ubuntu/zmax/dds/...      (zmax_dds 是 zmax/dds 的软链)
  3) /home/ubuntu/lerobot-smolvla-lew/... → /home/ubuntu/zmax/...      **仅当** zmax 下确实存在同一相对路径
     (两个工作树分支不同、内容有差异 ⇒ 不能盲改; 存在才改, 不存在就保留并报出来)
  4) 数据类路径 (zmax_ss_remote / zmax_moveit_plan / stable-wm-cache ...) 不动 —— 旧路径已留软链, 改了没收益反增风险

用法: python3 tools/ns_unify_paths.py [--dry]
"""
import os
import re
import sys

ROOT = "/home/ubuntu/zmax"
OLD = {"/home/ubuntu/zmax_rel": "/home/ubuntu/zmax",
       "/home/ubuntu/zmax_dds": "/home/ubuntu/zmax/dds"}
FORK = "/home/ubuntu/lerobot-smolvla-lew"
SKIP_DIR = {".git", "__pycache__", "node_modules", ".venv", "venv", "gui-venv311",
            "outputs", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages"}
# 不动的地方: reports/ 是历史取证记录(改写等于篡改证据); docs/skills + docs/memory 是 ~/.hermes 的镜像
# (改了下次同步会被覆盖, 要改就改源), 以及 .git 指针文件与脚本自身
SKIP_PREFIX = (os.path.join(ROOT, "reports") + os.sep,
               os.path.join(ROOT, "docs", "skills") + os.sep,
               os.path.join(ROOT, "docs", "memory") + os.sep)
SKIP_FILES = {os.path.join(ROOT, ".git"), os.path.abspath(__file__)}
BIN_EXT = {".pt", ".pth", ".h5", ".npz", ".npy", ".png", ".jpg", ".jpeg", ".webp", ".gif",
           ".mp4", ".mov", ".avi", ".pdf", ".zip", ".tar", ".gz", ".zst", ".pptx", ".docx",
           ".xlsx", ".apk", ".so", ".bin", ".db", ".sqlite", ".onnx", ".onnx_data", ".ttf",
           ".otf", ".ico", ".wav", ".mp3", ".whl", ".jsonl"}
DRY = "--dry" in sys.argv


def text_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR]
        for f in files:
            p = os.path.join(base, f)
            if p in SKIP_FILES or p.startswith(SKIP_PREFIX):
                continue
            if os.path.splitext(f)[1].lower() in BIN_EXT:
                continue
            try:
                if os.path.getsize(p) > 2 * 1024 * 1024:
                    continue
                with open(p, "rb") as fh:
                    head = fh.read(4096)
                if b"\0" in head:
                    continue
            except OSError:
                continue
            yield p


def main():
    pat_fork = re.compile(re.escape(FORK) + r"(/[A-Za-z0-9_./\-]*)?")
    stat = {"rw": 0, "keep": 0}
    keep_samples, files_changed = [], set()
    counts = {k: 0 for k in OLD}

    for p in text_files():
        try:
            src = open(p, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        out = src
        for old, new in OLD.items():
            if old in out:
                counts[old] += out.count(old)
                out = out.replace(old, new)

        def repl(m):
            tail = m.group(1) or ""
            if os.path.exists(ROOT + tail):            # zmax 下有同一路径 ⇒ 安全改写
                stat["rw"] += 1
                return "/home/ubuntu/zmax" + tail
            stat["keep"] += 1
            if len(keep_samples) < 25:
                keep_samples.append("%s  →  %s%s" % (os.path.relpath(p, ROOT), FORK, tail))
            return m.group(0)

        if FORK in out:
            out = pat_fork.sub(repl, out)

        if out != src:
            files_changed.add(p)
            if not DRY:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(out)

    print("%s改写的文件: %d" % ("[dry] 将" if DRY else "已", len(files_changed)))
    for k, v in counts.items():
        print("  %-28s 命中 %d 处" % (k, v))
    print("  lerobot-smolvla-lew → zmax 安全改写 %d 处; 保留(zmax 下无同路径) %d 处" % (stat["rw"], stat["keep"]))
    if keep_samples:
        print("  保留样例:")
        for s in keep_samples:
            print("    " + s)
    # 结果核验: 还有多少处 zmax_rel
    left = 0
    for p in text_files():
        try:
            left += open(p, encoding="utf-8").read().count("/home/ubuntu/zmax_rel")
        except (OSError, UnicodeDecodeError):
            pass
    print("  剩余 /home/ubuntu/zmax_rel 引用: %d 处" % left)


if __name__ == "__main__":
    main()
