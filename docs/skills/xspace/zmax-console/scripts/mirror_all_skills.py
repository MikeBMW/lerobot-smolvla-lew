#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量镜像 Hermes 技能到仓库 docs/skills/hermes-all/ + 生成可读索引

用途: 老倪说"共享你的**所有**记忆/技能"时用 (既有 cron 通道 tools/sync_hermes_to_repo.sh 只镜像
      zmax-console 全家 + 24 个关键技能到 docs/skills/xspace/, 那是"精选"不是"所有")。
配套: 推前先跑 scripts/scan_redact_secrets.py (技能 references 里最容易藏凭据 → GitHub Push
      Protection 会拦 GH013), 再走 references/hermes-memory-skill-sharing.md §三 的 ghproxy 推送法。

实测规模 (2026-09-15): 155 技能 / 1115 文件 / 13MB。源 ~/.hermes/skills 看似 50MB, 其中大半是
`.curator_backups/*.tar.gz` 本机快照 → 必须排除 (排除后实际跳过 0 个文件)。

用法:
    python3 scripts/mirror_all_skills.py                    # 镜像到 <repo>/docs/skills/hermes-all/
    python3 scripts/mirror_all_skills.py --dest /tmp/x      # 换目标目录 (先干跑检查)
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import shutil

SKIP_DIRS = {".curator_backups", "__pycache__", ".git"}      # 本机快照/缓存不进库
MAX_FILE = 2 * 1024 * 1024                                   # >2MB 单文件不进库 (Git 精简纪律)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(pathlib.Path.home() / ".hermes" / "skills"))
    ap.add_argument("--dest", default="/home/ubuntu/lerobot-smolvla-lew/docs/skills/hermes-all")
    ap.add_argument("--repo-docs", default="/home/ubuntu/lerobot-smolvla-lew/docs/skills")
    a = ap.parse_args()

    src, dest = pathlib.Path(a.src), pathlib.Path(a.dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    skills, skipped, name_map = [], [], {}
    for sk in sorted(src.rglob("SKILL.md")):
        rel_parts = sk.parent.relative_to(src).parts
        if any(p in SKIP_DIRS for p in rel_parts):
            continue
        name = rel_parts[-1]
        cat = rel_parts[0] if len(rel_parts) > 1 else "(root)"
        key = name
        if key in name_map:                                   # 同名跨分类 → 前缀去重
            key = f"{cat}--{name}"
            if key in name_map:
                key = f"{cat}--{name}--{hashlib.md5(str(rel_parts).encode()).hexdigest()[:4]}"
        name_map[key] = str(sk.parent.relative_to(src))

        d = dest / key
        d.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in sk.parent.rglob("*"):
            if any(p in SKIP_DIRS for p in f.relative_to(sk.parent).parts) or not f.is_file():
                continue
            if f.stat().st_size > MAX_FILE:
                skipped.append((str(f), f.stat().st_size))
                continue
            tgt = d / f.relative_to(sk.parent)
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, tgt)
            n += 1

        txt = sk.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^---\s*\n(.*?)\n---", txt, re.S)
        desc = title = ""
        if m:
            dm = re.search(r'^(?:description|title)\s*:\s*"?(.*?)"?\s*$', m.group(1), re.M)
            tm = re.search(r'^title\s*:\s*"?(.*?)"?\s*$', m.group(1), re.M)
            desc = (dm.group(1) if dm else "")[:120]
            title = (tm.group(1) if tm else "")[:80]
        skills.append({"key": key, "cat": cat, "files": n, "desc": desc or title})

    idx = ["# Hermes 技能全量镜像 (静静) — 索引", "",
           f"> 共 {len(skills)} 个技能 · 源 `~/.hermes/skills` · "
           f"排除 `.curator_backups/*.tar.gz` 与 >2MB 单文件", "",
           f"> 目录: `docs/skills/hermes-all/<技能名>/` (SKILL.md + references/ + scripts/ + templates/)", "",
           "| 技能 | 分类 | 文件数 | 说明 |", "|---|---|---|---|"]
    for s in sorted(skills, key=lambda x: (x["cat"], x["key"])):
        idx.append(f"| `{s['key']}` | {s['cat']} | {s['files']} | {s['desc'].replace('|', '/')} |")
    (pathlib.Path(a.repo_docs) / "hermes-all-index.md").write_text("\n".join(idx) + "\n", encoding="utf-8")

    print(f"镜像技能 {len(skills)} 个 / {sum(s['files'] for s in skills)} 文件 → {dest}")
    print(f"跳过的大文件: {skipped or '无(0 个)'}")
    print(f"索引: {pathlib.Path(a.repo_docs) / 'hermes-all-index.md'}")
    print("提醒: 提交+推送前先跑  scripts/scan_redact_secrets.py  (凭据扫描)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
