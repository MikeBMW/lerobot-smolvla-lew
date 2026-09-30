#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凭据扫描 / 脱敏 (共享技能+记忆到仓库前必跑; 2026-09-15 因 GitHub Push Protection 拦截而沉淀)

用法:
    python3 scan_redact_secrets.py              # 只扫: 打印 文件:行 + 类型 + 长度 (绝不打印密钥值)
    python3 scan_redact_secrets.py --apply      # 脱敏: 替换为 [REDACTED:<类型>] (幂等)

为什么必须跑: 技能 references 里最容易藏凭据 (历史会话转写/排障记录/.env 片段)。
被 GitHub 拦下 (GH013 "Push cannot contain secrets") 时**绝不点 unblock-secret**,
而是 ← 本脚本脱敏 (源文件与镜像一起!) → `git commit --amend` → 复扫 0 命中 → 重推。
⚠️ 只改镜像不改源文件 = 下次 cron 同步又把密钥带回来。

默认扫描面: ~/.hermes/skills · ~/.hermes/memories · <repo>/docs/skills · <repo>/docs/memory · <repo>/backups
可用环境变量覆盖: SCAN_ROOTS='p1:p2' · REDACT_LABEL='[REDACTED]'
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

PATS = {
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "aws_ak": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "google": re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".gz", ".tar", ".zip", ".mp4", ".npz", ".h5", ".pt"}
SKIP_DIRS = {".git", "__pycache__", ".curator_backups", "node_modules"}


def roots() -> list[pathlib.Path]:
    env = os.environ.get("SCAN_ROOTS")
    if env:
        return [pathlib.Path(p).expanduser() for p in env.split(":") if p]
    home = pathlib.Path.home()
    repo = pathlib.Path(os.environ.get("ZMAX_REPO", str(home / "lerobot-smolvla-lew")))
    return [home / ".hermes" / "skills", home / ".hermes" / "memories",
            repo / "docs" / "skills", repo / "docs" / "memory", repo / "backups"]


def scan(apply: bool) -> int:
    label = os.environ.get("REDACT_LABEL", "[REDACTED]")
    hits = changed = 0
    for root in roots():
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if not f.is_file() or f.suffix.lower() in SKIP_SUFFIX:
                continue
            if any(p in SKIP_DIRS for p in f.parts):
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            orig = txt
            for name, pat in PATS.items():
                for m in pat.finditer(txt):
                    hits += 1
                    print(f"  [{name}] len={len(m.group(0))}  {f}:{txt[:m.start()].count(chr(10)) + 1}")
                if apply:
                    txt = pat.sub(f"{label}:{name}]".replace("]", "]") if False else f"{label[:-1]}:{name}]", txt)
            if apply and txt != orig:
                f.write_text(txt, encoding="utf-8")
                changed += 1
    print(f"\n{'脱敏' if apply else '扫描'}完成: 命中 {hits} 处" + (f" · 改写文件 {changed} 个" if apply else ""))
    if apply:
        print("下一步: git add <改动文件> && git commit --amend (改写未推提交) → 复扫应 0 命中 → 重推")
    return 0


if __name__ == "__main__":
    sys.exit(scan(apply="--apply" in sys.argv))
