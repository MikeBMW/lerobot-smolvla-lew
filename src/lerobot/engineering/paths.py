# -*- coding: utf-8 -*-
"""路径真源 (paths) —— 工程内所有路径只从这里取。

2026-09-28 迁移: 节点逻辑搬进包之前, 到处是 `dirname(__file__)/../../..` 上溯
(迁移后深度一变就指错)。这里集中定义, 其它模块一律 `from . import paths`。
"""
import os
import sys

ENGINEERING_DIR = os.path.dirname(os.path.abspath(__file__))
NODES_DIR = os.path.join(ENGINEERING_DIR, "nodes")
LOGIC_FILE = os.path.join(NODES_DIR, "library.py")     # 节点逻辑真源
FLOWS_DIR = os.path.join(ENGINEERING_DIR, "flows")     # 画布/工程 JSON (package data)
CANVAS_DEFAULT = "state_space_obs.json"


def _find_repo_root():
    """仓库根: env ZMAX_REPO_ROOT → 冻结包 → 向上找到同时含 src/lerobot 与 tools 的目录"""
    env = os.environ.get("ZMAX_REPO_ROOT")
    if env and os.path.isdir(env):
        return env
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(ENGINEERING_DIR))
    d = ENGINEERING_DIR
    while True:
        if (os.path.isdir(os.path.join(d, "src", "lerobot"))
                and os.path.isdir(os.path.join(d, "tools"))):
            return d
        p = os.path.dirname(d)
        if p == d:
            break
        d = p
    return os.path.dirname(os.path.dirname(os.path.dirname(ENGINEERING_DIR)))


REPO_ROOT = _find_repo_root()
GUI_DIR = os.path.join(REPO_ROOT, "tools", "gui")          # 剩下还在 GUI 目录里的 Qt 视图
LEGACY_FLOWS_DIR = os.path.join(REPO_ROOT, "flows")        # 历史位置 (保留软链兼容老工具)
DATA_DIR = os.environ.get("ZMAX_DATA_DIR") or os.path.join(os.path.expanduser("~"), "zmax_data")


def canvas_json(name=CANVAS_DEFAULT):
    """画布/工程 JSON 真源: 包内优先 (canonical), 找不到才回落到历史位置"""
    p = os.path.join(FLOWS_DIR, name)
    return p if os.path.exists(p) else os.path.join(LEGACY_FLOWS_DIR, name)


def ensure_dirs():
    for d in (FLOWS_DIR, NODES_DIR):
        os.makedirs(d, exist_ok=True)
    return FLOWS_DIR


def report():
    """自检: 路径口径一行说清"""
    return {"ENGINEERING_DIR": ENGINEERING_DIR, "REPO_ROOT": REPO_ROOT,
            "LOGIC_FILE": LOGIC_FILE, "CANVAS": canvas_json(), "GUI_DIR": GUI_DIR}
