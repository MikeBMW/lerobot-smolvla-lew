#!/usr/bin/env python3
"""
Z-MAX Docs Sync — 文档管理模块
功能：
  1. 从 GitHub 下载文档到本地
  2. 本地修改后可推回 GitHub
  3. 版本追踪，与 Z-MAX 版本同步
  4. 文档按产品分类组织
"""

import os, sys, json, urllib.request, time, hashlib

# ── 远程源 ──
GITHUB_API = "https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/contents/docs"
RAW_BASE = "https://raw.githubusercontent.com/MikeBMW/lerobot-smolvla-lew/main/docs"

# ── Z-MAX 文档结构（按产品分类组织） ──
# 结构说明：
#   静界/                     ← 文档根目录（.exe 所在目录 / %LOCALAPPDATA%）
#   ├── .version               ← 版本追踪文件
#   ├── 01-培训/                ← 产品培训
#   ├── 02-解决方案/             ← 技术方案
#   ├── 03-训练模型/             ← AI 训练与评测
#   ├── 04-运维部署/             ← 运维手册
#   ├── 05-开发参考/             ← 开发宝典
#   ├── 06-发布品牌/             ← 发布与品牌
#   └── 07-供应链/               ← 供应商文档
#
# MAPPING: (本地路径, 远程文件名模式)
# 远程文件根据文件名前缀自动路由到对应分类

ROUTING_RULES = [
    # (分类目录, 文件名前缀匹配)
    ("01-培训",      ("Z700F", "Z-MAX产品等级定义", "TRAINING", "产品培训")),
    ("02-解决方案",   ("L2-", "L3-", "解决方案", "SOLUTION")),
    ("03-训练模型",   ("SmolVLA", "训练方案", "数据日志", "benchmark", "MODEL-ACCEPTANCE")),
    ("04-运维部署",   ("Orin", "运维", "DEPLOY", "EDGE", "V1.0.6-真机")),
    ("05-开发参考",   ("HELP-DEVELOPMENT", "VERSION", "UPSTREAM", "ARCHITECTURE", "GUI-CHECKLIST")),
    ("06-发布品牌",   ("L1-", "BRAND", "轮式双臂", "立项方案", "竞品分析")),
    ("07-供应链",     ("供应链", "PRO3000", "Thor-", "域控")),
]

UNCATEGORIZED = "00-其他"


def _version_file(docs_dir):
    return os.path.join(docs_dir, ".version")


def get_docs_dir():
    """确定文档根目录：优先 .exe 同级，其次 AppData"""
    if getattr(sys, 'frozen', False):
        # .exe 同级
        exe_dir = os.path.dirname(sys.executable)
        candidate = os.path.join(exe_dir, "静界")
        # 如果 .exe 在临时目录（安装时），回退到 AppData
        if "temp" in exe_dir.lower() or "tmp" in exe_dir.lower():
            fallback = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            return os.path.join(fallback, "zmax", "静界")
        return candidate
    # 开发环境
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo, "静界")


def classify(filename):
    """根据文件名分类到本地目录"""
    for cat, prefixes in ROUTING_RULES:
        for p in prefixes:
            if filename.startswith(p):
                return cat
    return UNCATEGORIZED


def get_status():
    """返回同步状态"""
    docs_dir = get_docs_dir()
    ver = {}
    vf = _version_file(docs_dir)
    if os.path.exists(vf):
        try:
            with open(vf) as f:
                ver = json.load(f)
        except: pass
    return {
        "doc_dir": docs_dir,
        "last_sync": ver.get("last_sync", "从未同步"),
        "version": ver.get("version", "N/A"),
        "doc_count": ver.get("doc_count", 0),
        "local_hash": ver.get("hash", ""),
    }


def _list_remote(log_callback):
    """递归列出 GitHub 上所有文档文件"""
    files = []
    EXCLUDE_DIRS = {"source", "skills", "archive", "memory", "screenshots", "web", "test-reports", "survey", "patents"}
    EXCLUDE_PREFIXES = {".", "_"}

    def walk(path, prefix=""):
        url = f"https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/contents/{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "ZMAX-Console/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                items = json.loads(resp.read())
        except Exception as e:
            log_callback(f"  ⚠  无法访问 {path}: {e}")
            return
        for item in items:
            name = item["name"]
            rel = prefix + name
            if item["type"] == "dir":
                if name in EXCLUDE_DIRS or name.startswith("."):
                    continue
                walk(item["path"], rel + "/")
            elif item["type"] == "file":
                if any(name.startswith(p) for p in EXCLUDE_PREFIXES):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in (".md", ".pptx", ".docx", ".pdf", ".txt", ".json"):
                    files.append((rel, name, ext))
    walk("docs")
    return files


def _compute_hash(docs_dir):
    """计算文档目录的哈希值，用于检测变更"""
    h = hashlib.md5()
    for root, dirs, files in os.walk(docs_dir):
        for f in sorted(files):
            path = os.path.join(root, f)
            try:
                with open(path, "rb") as fh:
                    h.update(fh.read(8192))
            except: pass
    return h.hexdigest()[:16]


def sync(log_callback=print, progress_callback=None):
    """从 GitHub 下载文档到本地"""
    docs_dir = get_docs_dir()
    os.makedirs(docs_dir, exist_ok=True)

    log_callback("正在获取远程文件列表...")
    remote_files = _list_remote(log_callback)
    log_callback(f"发现 {len(remote_files)} 个远程文档")

    # 构建本地路径
    entries = []
    for rel, name, ext in remote_files:
        cat = classify(name)
        local_rel = os.path.join(cat, rel.replace("docs/", ""))
        local_path = os.path.join(docs_dir, local_rel)
        entries.append((local_path, rel, name))

    # 下载
    success, failed = 0, 0
    total = len(entries)
    for i, (local_path, rel, name) in enumerate(entries):
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        url = f"{RAW_BASE}/{rel}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZMAX-Console/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(local_path, "wb") as f:
                    f.write(resp.read())
            success += 1
            if progress_callback:
                progress_callback(i, total, name)
        except Exception as e:
            log_callback(f"  ❌ {name}: {e}")
            failed += 1

    # 清理旧分类目录（移除已不存在的文件）
    for cat, _ in ROUTING_RULES:
        cat_dir = os.path.join(docs_dir, cat)
        if os.path.isdir(cat_dir):
            existing = set()
            for root, _, files in os.walk(cat_dir):
                for f in files:
                    existing.add(os.path.join(root, f))
            downloaded = {e[0] for e in entries}
            stale = existing - downloaded
            for s in stale:
                try:
                    os.remove(s)
                    log_callback(f"  🗑  清理旧文件: {os.path.relpath(s, docs_dir)}")
                except: pass

    # 写版本文件
    h = _compute_hash(docs_dir)
    ver = {
        "version": "v2.7.3",
        "last_sync": time.strftime("%Y-%m-%d %H:%M:%S"),
        "doc_count": success,
        "hash": h,
        "zmax_version": "v2.7.3",
    }
    with open(_version_file(docs_dir), "w") as f:
        json.dump(ver, f, ensure_ascii=False, indent=2)

    log_callback(f"\n📊 完成: {success} 下载, {failed} 失败")
    log_callback(f"📁 路径: {docs_dir}")
    return success, failed


def push_to_github(log_callback=print, token=None):
    """将本地修改同步回 GitHub（需要 GitHub token 或 git CLI）"""
    docs_dir = get_docs_dir()

    if not token:
        # 尝试从环境变量读取
        token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")

    if token:
        log_callback("使用 GitHub API 推送...")
        return _push_via_api(docs_dir, token, log_callback)

    # 尝试 git CLI
    if sys.platform != "win32":
        try:
            import subprocess
            repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            log_callback("使用 git CLI 推送...")
            r = subprocess.run(
                ["git", "-C", repo, "add", "-A", "docs/"],
                capture_output=True, text=True, timeout=30
            )
            r2 = subprocess.run(
                ["git", "-C", repo, "commit", "-m", f"docs: 同步更新 {time.strftime('%Y-%m-%d %H:%M')}"],
                capture_output=True, text=True, timeout=30
            )
            r3 = subprocess.run(
                ["git", "-C", repo, "push"],
                capture_output=True, text=True, timeout=60
            )
            log_callback(r3.stdout or r2.stdout or "已提交")
            return True
        except Exception as e:
            log_callback(f"  ❌ git 推送失败: {e}")
            return False

    log_callback("⚠  需要 GitHub Token 才能推送。请设置 GITHUB_TOKEN 环境变量。")
    return False


def _push_via_api(docs_dir, token, log_callback):
    """通过 GitHub API 推送文件变更（单文件更新）"""
    # 检测变更
    ver = {}
    vf = _version_file(docs_dir)
    if os.path.exists(vf):
        with open(vf) as f:
            ver = json.load(f)
    old_hash = ver.get("hash", "")
    new_hash = _compute_hash(docs_dir)
    if old_hash == new_hash:
        log_callback("没有变更需要推送")
        return True

    log_callback(f"检测到文件变更 (hash: {old_hash}→{new_hash})")
    log_callback("API 推送需要实现文件级 diff 和 blob 上传，请使用 git CLI 替代")
    log_callback("或手动提交: git add docs/ && git commit && git push")
    return False
