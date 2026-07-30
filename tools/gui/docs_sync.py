"""
Z-MAX Docs Sync — 文档同步模块
下载最新文档到本地，支持版本跟踪
"""

import os
import sys
import json
import urllib.request
import time
from pathlib import Path

# GitHub raw base URL
RAW_BASE = "https://raw.githubusercontent.com/MikeBMW/lerobot-smolvla-lew/main/docs"

# 文档清单: (本地相对路径, 文件名/远程路径)
DOC_MANIFEST = [
    # === 产品培训 ===
    ("Z700F-L2产品培训手册.md",           "Z700F-L2产品培训手册.md"),
    ("Z700F-L2产品培训手册.pptx",         "Z700F-L2产品培训手册.pptx"),
    # === 产品定义 ===
    ("Z-MAX产品等级定义-L1-L5标准.md",     "Z-MAX产品等级定义-L1-L5标准.md"),
    ("Z-MAX-SmolVLA训练方案.md",          "Z-MAX-SmolVLA训练方案.md"),
    # === 解决方案 ===
    ("L2-Z-MAX解决方案-v1.0.6.md",        "L2-Z-MAX解决方案-v1.0.6.md"),
    ("L3-技术路线与开发指南-v1.0.4.md",    "L3-技术路线与开发指南-v1.0.4.md"),
    # === 开发宝典 ===
    ("HELP-DEVELOPMENT-BIBLE.md",         "HELP-DEVELOPMENT-BIBLE.md"),
    # === 运维 ===
    ("Orin运维手册.md",                   "Orin运维手册.md"),
    # === 数据 ===
    ("Z-MAX数据日志方案-MCAP分析.md",      "Z-MAX数据日志方案-MCAP分析.md"),
    # === 版本管理 ===
    ("VERSION.md",                        "VERSION.md"),
    ("Z-MAX-UPSTREAM-SYNC.md",           "Z-MAX-UPSTREAM-SYNC.md"),
    # === L1 发布 ===
    ("L1/Z-MAX产品发布-v1.0.4.pptx",      "L1-Z-MAX产品发布-v1.0.4.pptx"),
    # === 品牌 ===
    ("brand/品牌注册材料.pptx",            "BRAND-品牌注册材料.pptx"),
    # === 其他 ===
    ("README.md",                         "README.md"),
]


def get_docs_dir():
    """获取文档根目录"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "zmax", "docs")
    else:
        return os.path.join(os.path.expanduser("~"), ".local", "share", "zmax", "docs")


def get_metadata_path():
    """元数据文件路径（记录同步状态）"""
    return os.path.join(get_docs_dir(), ".sync_meta.json")


def get_status():
    """返回同步状态: {last_sync, version, doc_count, doc_dir}"""
    meta = {}
    meta_path = get_metadata_path()
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except: pass
    return {
        "doc_dir": get_docs_dir(),
        "last_sync": meta.get("last_sync", "从未同步"),
        "version": meta.get("version", "N/A"),
        "doc_count": meta.get("doc_count", 0),
        "exists": os.path.isdir(get_docs_dir()),
    }


def sync(log_callback=print):
    """从 GitHub 下载最新文档到本地"""
    docs_dir = get_docs_dir()
    os.makedirs(docs_dir, exist_ok=True)

    success = 0
    failed = 0

    for local_rel, remote_name in DOC_MANIFEST:
        local_path = os.path.join(docs_dir, local_rel)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        url = f"{RAW_BASE}/{remote_name}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZMAX-Console/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with open(local_path, "wb") as f:
                f.write(data)
            log_callback(f"  ✅ {local_rel}")
            success += 1
        except Exception as e:
            log_callback(f"  ❌ {local_rel}: {e}")
            failed += 1

    # 写元数据
    meta = {
        "last_sync": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "v1.0.5",
        "doc_count": success,
    }
    with open(get_metadata_path(), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    log_callback(f"\n📊 完成: {success} 成功, {failed} 失败")
    return success, failed
