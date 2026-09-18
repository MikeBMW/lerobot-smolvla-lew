#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eng_memory.py — 📚 工程记忆 (技能与经验库): 把"工程的记忆"同步进 🧠总装记忆节点

老倪 2026-09-19: 「当前的工程记忆, 要同步到大模型层的总装记忆节点」(与飞书端商量好)

工程记忆 = 三类真实文件的汇总 (只读, 不改任何源文件):
  ① 跨端同步记忆  docs/memory/*.md      (我这边 ↔ 飞书端 共用的记忆/同步文档)
  ② Hermes 记忆    ~/.hermes/memories/*.md  (MEMORY/USER — 会话间的持久记忆)
  ③ 技能库        ~/.hermes/skills/**/SKILL.md (可复用流程 = 工程经验)

同步目标: MacroMemory (顶层宏观记忆, 飞书端 09-19 新增 macro_memory.py) 的 `engineering` 段
  · **追加式**写入 (不覆盖他们的 knowledge/capability/diagnosis/advice/seen)
  · 幂等: 用 (路径+大小+mtime) 指纹去重, 内容没变就不重写
  · 原子写 (tmp + rename, 与 macro_memory 同套路)
  · 无 LLM 端点时照样同步 (标记 llm=False), 绝不假装做过语义归纳

对外:
  EngMemory(repo=…).collect()          → 工程记忆快照 (文件清单/条数/摘要)
  EngMemory(repo=…).sync_to_macro()    → 同步进总装 (返回 {ok, wrote, added, macro_path, llm})
  EngMemory(repo=…).summary()          → 一行给人看的摘要
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

_HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_root() -> str:
    d = _HERE
    for _ in range(8):
        d = os.path.dirname(d)
        if not d or d == "/":
            break
        if os.path.isdir(os.path.join(d, "flows")):
            return d
    return os.path.normpath(os.path.join(_HERE, "..", "..", ".."))


def _stat(p: str) -> dict:
    st = os.stat(p)
    return {"path": p, "size": st.st_size, "mtime": int(st.st_mtime),
            "mtime_str": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime))}


def _read(p: str, limit: int = 200_000) -> str:
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except Exception:                                                          # noqa: BLE001
        return ""


class EngMemory:
    """工程记忆 (技能与经验库) → 总装记忆节点的上行通道"""

    def __init__(self, repo: str | None = None, hermes_dir: str | None = None, macro_path: str | None = None):
        self.repo = repo or _repo_root()
        self.hermes = hermes_dir or os.path.expanduser("~/.hermes")
        self.macro_path = macro_path or os.path.join(self.repo, "data", "macro_memory.json")

    # ── ① 收集 (真读文件) ──
    def collect(self) -> dict:
        docs = sorted([os.path.join(self.repo, "docs", "memory", f)
                       for f in os.listdir(os.path.join(self.repo, "docs", "memory"))
                       if f.endswith(".md")]) if os.path.isdir(os.path.join(self.repo, "docs", "memory")) else []
        mems = sorted([os.path.join(self.hermes, "memories", f)
                       for f in os.listdir(os.path.join(self.hermes, "memories"))
                       if f.endswith(".md")]) if os.path.isdir(os.path.join(self.hermes, "memories")) else []
        skills = []
        skroot = os.path.join(self.hermes, "skills")
        for dp, _dn, fn in os.walk(skroot):
            for f in fn:
                if f == "SKILL.md":
                    skills.append(os.path.join(dp, f))
        skills.sort()

        files = [_stat(p) for p in (docs + mems + skills) if os.path.exists(p)]
        # 技能条目数 (按 SKILL.md 里 "## " 小节粗略计) + 工程记忆里的条目 (§ 分段)
        doc_items = 0
        for p in docs + mems:
            doc_items += len([1 for ln in _read(p).splitlines() if ln.strip() == "§"])
        skill_sections = 0
        for p in skills:
            skill_sections += len(re.findall(r"^## ", _read(p), flags=re.M))
        newest = max(files, key=lambda x: x["mtime"]) if files else None
        return {
            "docs_memory": [f for f in files if "/docs/memory/" in f["path"]],
            "hermes_memory": [f for f in files if "/memories/" in f["path"]],
            "skills": [f for f in files if f["path"].endswith("/SKILL.md")],
            "counts": {"docs_memory_files": len(docs), "hermes_memory_files": len(mems),
                        "skills": len(skills), "memory_items(§)": doc_items,
                        "skill_sections": skill_sections},
            "newest": newest,
            "collected_at": time.strftime("%F %T"),
        }

    # ── ② 同步进总装 (追加式 + 幂等 + 原子写) ──
    def sync_to_macro(self) -> dict:
        snap = self.collect()
        fp_src = json.dumps([[f["path"], f["size"], f["mtime"]] for f in
                             snap["docs_memory"] + snap["hermes_memory"] + snap["skills"]],
                            sort_keys=True)
        fp = hashlib.sha256(fp_src.encode()).hexdigest()[:16]
        try:
            store = json.load(open(self.macro_path, encoding="utf-8")) if os.path.exists(self.macro_path) else {}
        except Exception as e:                                                 # noqa: BLE001
            return {"ok": False, "why": f"读总装记忆失败: {type(e).__name__}: {e}"}
        eng = store.get("engineering") or {}
        if eng.get("fingerprint") == fp:
            return {"ok": True, "wrote": False, "why": "内容未变 (指纹相同) — 幂等跳过",
                    "macro_path": self.macro_path, "counts": snap["counts"],
                    "llm": bool(os.environ.get("SS_MACRO_LLM_URL"))}
        store.setdefault("version", 1)
        store["engineering"] = {
            "source": "docs/memory/*.md + ~/.hermes/memories/*.md + ~/.hermes/skills/**/SKILL.md",
            "counts": snap["counts"],
            "newest": snap["newest"],
            "files": [{"path": os.path.relpath(f["path"], self.repo) if f["path"].startswith(self.repo) else f["path"],
                        "size": f["size"], "mtime": f["mtime"]} for f in
                       snap["docs_memory"] + snap["hermes_memory"] + snap["skills"]],
            "fingerprint": fp,
            "synced_at": time.strftime("%F %T"),
            "llm": bool(os.environ.get("SS_MACRO_LLM_URL")),
        }
        store.setdefault("meta", {})["updated"] = time.strftime("%F %T")
        os.makedirs(os.path.dirname(self.macro_path), exist_ok=True)
        tmp = self.macro_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.macro_path)
        # 读回验证 (外部写入必须回读)
        back = json.load(open(self.macro_path, encoding="utf-8"))
        ok = (back.get("engineering") or {}).get("fingerprint") == fp
        return {"ok": bool(ok), "wrote": True, "added_files": len(store["engineering"]["files"]),
                "counts": snap["counts"], "macro_path": self.macro_path,
                "llm": store["engineering"]["llm"],
                "note": ("工程记忆已并入总装 (顶层宏观记忆); 无 LLM 端点 → 只做结构化同步, 未做语义归纳"
                          if not store["engineering"]["llm"] else "")}

    # ── ③ 一行摘要 ──
    def summary(self) -> str:
        c = self.collect()["counts"]
        n = self.collect()["newest"] or {}
        return (f"工程记忆: 同步文档 {c['docs_memory_files']} 篇 · Hermes 记忆 {c['hermes_memory_files']} 个 · "
                f"技能 {c['skills']} 条 (小节 {c['skill_sections']}) · 记忆条目 {c['memory_items(§)']} 条 · "
                f"最新更新 {n.get('mtime_str', '?')} ({os.path.basename(n.get('path', ''))})")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true", help="同步进总装记忆 (macro_memory)")
    a = ap.parse_args()
    m = EngMemory()
    print(m.summary())
    if a.sync:
        r = m.sync_to_macro()
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r.get("ok") else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
