"""
Z-MAX Docs Sync — 文档同步模块
动态从 GitHub API 拉取文件清单，避免手动维护 manifest 漂移
"""

import os, sys, json, urllib.request, time

GITHUB_API = "https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/contents/docs"
RAW_BASE = "https://raw.githubusercontent.com/MikeBMW/lerobot-smolvla-lew/main/docs"

# 排除的目录/文件前缀
EXCLUDE_PREFIXES = [
    "source/",       # LeRobot 官方文档
    "skills/",       # Hermes skills
    "archive/",      # 归档
    "供应链/",        # 供应商文档
    "memory/",       # 内部记忆
    "screenshots/",  # 截图
    "web/",          # web 数据
    "test-reports/", # 测试报告
    "survey/",       # 调研
    "patents/",      # 专利（通过菜单单独打开）
    "L1-",           # 发布PPT
    "BRAND-",        # 品牌
    ".archived",     # 归档标记
]

def get_docs_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "zmax", "docs")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "zmax", "docs")


def get_meta_path():
    return os.path.join(get_docs_dir(), ".sync_meta.json")


def _list_recursive(token=None):
    """递归列出 docs/ 下所有文件"""
    files = []
    def _walk(path, prefix=""):
        url = f"https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/contents/{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "ZMAX-Console/1.0"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                items = json.loads(resp.read())
        except Exception:
            return
        for item in items:
            name = item["name"]
            rel = prefix + name
            if item["type"] == "dir":
                # 检查排除
                if any(rel.startswith(p) or rel + "/" == p for p in EXCLUDE_PREFIXES):
                    continue
                _walk(item["path"], rel + "/")
            elif item["type"] == "file":
                if any(rel.startswith(p) for p in EXCLUDE_PREFIXES):
                    continue
                # 只同步文档格式
                ext = os.path.splitext(name)[1].lower()
                if ext in (".md", ".pptx", ".docx", ".pdf", ".txt"):
                    files.append(rel)
    _walk("docs")
    return sorted(set(files))


def get_status():
    meta = {}
    mp = get_meta_path()
    if os.path.exists(mp):
        try:
            with open(mp) as f:
                meta = json.load(f)
        except: pass
    return {
        "doc_dir": get_docs_dir(),
        "last_sync": meta.get("last_sync", "从未同步"),
        "version": meta.get("version", "N/A"),
        "doc_count": meta.get("doc_count", 0),
    }


def sync(log_callback=print):
    docs_dir = get_docs_dir()
    os.makedirs(docs_dir, exist_ok=True)

    log_callback("正在获取文件列表...")
    files = _list_recursive()
    log_callback(f"发现 {len(files)} 个文档")

    success, failed = 0, 0
    for rel in files:
        local_path = os.path.join(docs_dir, rel)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        url = f"{RAW_BASE}/{rel}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZMAX-Console/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(local_path, "wb") as f:
                    f.write(resp.read())
            log_callback(f"  ✅ {rel}")
            success += 1
        except Exception as e:
            log_callback(f"  ❌ {rel}: {e}")
            failed += 1

    meta = {
        "last_sync": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "v1.0.5",
        "doc_count": success,
    }
    with open(get_meta_path(), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    log_callback(f"\n📊 完成: {success} 成功, {failed} 失败")
    return success, failed
