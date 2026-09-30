#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程仓库入库守卫 —— 大文件/二进制不许进库 (老倪硬性口径: 大文件不进代码库)

用法:
  python3 tools/repo_guard.py            # 检查已跟踪文件 (只看 git ls-files)
  python3 tools/repo_guard.py --staged   # 检查暂存区 (pre-commit 用)

判据:
  ① 单文件 > LIMIT 就报 (白名单: config/moveit_*/urdf/meshes/**.stl —— 机械臂 URDF 网格, MoveIt 必需)
  ② 扩展名黑名单 (权重/交付件/视频/数据库/压缩包) 一律报, 不管多大
退出码: 有问题 1, 干净 0
"""
import os
import subprocess
import sys

LIMIT = 300 * 1024
BAN_EXT_OVER = 200 * 1024      # 这些类型超过 200KB 才算"不该入库"(小的测试夹具/标定矩阵是正常的)
BAN_EXT = {".pt", ".pth", ".h5", ".npz", ".npy", ".onnx", ".whl", ".apk", ".pdf", ".pptx",
           ".docx", ".xlsx", ".zip", ".tar", ".gz", ".zst", ".mp4", ".mov", ".avi", ".db",
           ".sqlite", ".safetensors"}
WHITELIST_PREFIX = ("config/moveit_xms5/urdf/meshes/",)
# 文本/代码类不设体积上限 (studio.py 1MB、uv.lock 1.1MB 都是正常源码); 只有二进制才卡
TEXT_EXT = {".py", ".pyi", ".sh", ".bash", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml",
            ".toml", ".lock", ".html", ".htm", ".css", ".js", ".ts", ".csv", ".dbc", ".in",
            ".cfg", ".ini", ".xml", ".service", ".desktop", ".conf", ".patch", ".diff",
            ".rst", ".tex", ".bib", ".svg"}


def tracked(staged):
    if staged:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                             capture_output=True, text=True).stdout
    else:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout
    return [p for p in out.splitlines() if p.strip()]


def main():
    staged = "--staged" in sys.argv
    bad_size, bad_ext, total, n = [], [], 0, 0
    for p in tracked(staged):
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue                                     # 已删除/被忽略的工作区文件
        n += 1
        total += sz
        ext = os.path.splitext(p)[1].lower()
        if ext in BAN_EXT and sz > BAN_EXT_OVER:
            bad_ext.append((sz, p, ext))                 # 权重/交付件: 大的一个都不该在库里
        elif sz > LIMIT and ext not in TEXT_EXT and not p.startswith(WHITELIST_PREFIX):
            bad_size.append((sz, p))
    print("检查 %s %d 个文件, 合计 %.1f MB" % ("暂存区" if staged else "已跟踪", n, total / 1048576))
    if bad_ext:
        print("❌ 不该入库的类型 (%d):" % len(bad_ext))
        for sz, p, e in sorted(bad_ext, reverse=True)[:20]:
            print("   %8.2f MB  %s" % (sz / 1048576, p))
    if bad_size:
        print("❌ 超过 %.0fKB 且非白名单 (%d):" % (LIMIT / 1024, len(bad_size)))
        for sz, p in sorted(bad_size, reverse=True)[:20]:
            print("   %8.2f MB  %s" % (sz / 1048576, p))
    if not bad_ext and not bad_size:
        print("✅ 干净: 无权重/交付件, 无超限大文件")
        return 0
    print("\n提示: 权重与交付件放 /home/ubuntu/zmax_data/ (或网盘), 库里只留清单; 运行产物走 .gitignore")
    return 1


if __name__ == "__main__":
    sys.exit(main())
