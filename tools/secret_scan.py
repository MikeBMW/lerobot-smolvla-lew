#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密钥扫描 —— 公开仓库不能带真密钥 (2026-09-30 起因: agent hub token 被写进代码+systemd 单元)

用法:
  python3 tools/secret_scan.py            # 扫已跟踪文件
  python3 tools/secret_scan.py --staged   # 只扫暂存区(pre-commit)

口径:
  · 只报**真值形态**(固定前缀+长度), 不报变量名/占位符/文档里的 `***`;
  · 命中的值一律**打码输出**(前4位 + 长度), 避免扫描本身再泄露一遍;
  · 退出码: 有命中 1, 干净 0。
真值该放哪: /home/ubuntu/zmax_data/secrets/*.env (600, 已在 .gitignore 之外, 永不入库)。
"""
import os
import re
import subprocess
import sys

PATTERNS = [
    ("agent hub token", r"zmax-[0-9a-f]{8}\b"),
    ("GitHub token",    r"gh[pousr]_[A-Za-z0-9]{30,}"),
    ("OpenAI key",      r"sk-(?:proj-)?[A-Za-z0-9_\-]{24,}"),
    ("HF token",        r"hf_[A-Za-z0-9]{30,}"),
    ("AWS key",         r"AKIA[0-9A-Z]{16}"),
    ("私钥",            r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("Slack token",     r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
]
# 允许出现的"假阳性"位置(占位符/示例/文档提到密钥名)
ALLOW = re.compile(r"(PLACEHOLDER|example\.com|\*\*\*|<TOKEN>|\$\{?ZMAX_|\$env:|YourPassword|xxx+)")
# 上游/厂商 vendored 代码与文档: 里面的示例 key 不是我们的密钥, 不参与判定
ALLOWPATH = re.compile(r"^(docs/source/|src/lerobot/|docs/skills/hermes-all/.+/references/|node_modules/|gui-venv)")


def files(staged):
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged else ["git", "ls-files"]
    return [p for p in subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines() if p.strip()]


def main():
    staged = "--staged" in sys.argv
    hits = []
    for f in files(staged):
        if ALLOWPATH.search(f):
            continue
        try:
            if os.path.getsize(f) > 3_000_000:
                continue
            txt = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for name, pat in PATTERNS:
            for m in re.finditer(pat, txt):
                line = txt[:m.start()].count("\n") + 1
                seg = txt.splitlines()[line - 1] if line - 1 < len(txt.splitlines()) else ""
                if ALLOW.search(seg):
                    continue
                v = m.group(0)
                hits.append((f, line, name, v[:4] + "…", len(v)))
    print("密钥扫描 %s: %d 个文件" % ("(暂存区)" if staged else "(已跟踪)", len(files(staged))))
    if not hits:
        print("✅ 干净: 没有真密钥形态的值")
        return 0
    print("❌ 命中 %d 处 (值已打码):" % len(hits))
    for f, ln, name, pre, L in hits[:40]:
        print("   %-7s %s:%d  前缀=%s 长度=%d" % (name, f, ln, pre, L))
    print("\n修法: 真值挪到 /home/ubuntu/zmax_data/secrets/zmax.env (600), 代码里用 env 或 secrets 文件读;")
    print("      单元用 EnvironmentFile= + ${VAR}。改完还要清历史(旧提交里仍在) → 见 skill zmax-engineering-repo。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
