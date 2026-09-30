# -*- coding: utf-8 -*-
"""节点注册表 (registry) —— 语义 key ↔ 节点名关键字 ↔ 真函数 ↔ 所在文件。

lerobot 式做法: 注册表是唯一入口, 逻辑文件只负责"定义 + 注册", 谁来调用都走这里。
  register(key, matches, doc, fn)  —— 注册一个节点逻辑 (由 nodes/library.py 在导入时调用)
  match_node(name)               —— 节点显示名 → 语义 key (最长关键字匹配)
  home_file(key)                 —— 该逻辑的**真实所在文件** (源码视图/VSCode 跳转用)
  set_logic_globals(g)           —— 逻辑模块的命名空间 (用户改过的代码 exec 时复用同一份)
"""
import inspect

NODE_LOGIC = {}      # key → {match:[关键字], fn, doc, module, file, line}
NODE_ORDER = []      # 注册顺序 (UI 列表按此展示)
_SOURCE_CACHE = {}   # key → 用户改过的源码 (优先于磁盘)

_LOGIC_GLOBALS = {}  # nodes/library.py 的 globals()


def register(key, matches, doc, fn):
    """注册一个节点逻辑 (幂等: 同 key 重复注册覆盖, 顺序只记一次)"""
    try:
        f = inspect.getsourcefile(fn) or getattr(fn.__code__, "co_filename", None)
    except Exception:                                                    # noqa: BLE001
        f = getattr(getattr(fn, "__code__", None), "co_filename", None)
    if key not in NODE_LOGIC:
        NODE_ORDER.append(key)
    NODE_LOGIC[key] = {"match": list(matches), "fn": fn, "doc": doc,
                       "module": getattr(fn, "__module__", None), "file": f,
                       "line": getattr(fn.__code__, "co_firstlineno", None)}
    return key


# 旧名兼容 (历史代码/工具里到处是 _reg)
_reg = register


def match_node(name):
    """节点名 → 语义 key (最长关键字匹配, 避免「训练」抢先匹配「全新训练」)"""
    best, best_key = 0, None
    for key, info in NODE_LOGIC.items():
        for m in info["match"]:
            if m in name and len(m) > best:
                best, best_key = len(m), key
    return best_key


def home_file(key):
    """该 key 逻辑的真实文件 (优先动态取, 兜底注册时记录的)"""
    info = NODE_LOGIC.get(key) or {}
    fn = info.get("fn")
    f = getattr(getattr(fn, "__code__", None), "co_filename", None) or info.get("file")
    return f


def home_line(key):
    info = NODE_LOGIC.get(key) or {}
    fn = info.get("fn")
    return getattr(getattr(fn, "__code__", None), "co_firstlineno", None) or info.get("line")


def keys():
    return list(NODE_ORDER)


def get(key):
    return NODE_LOGIC.get(key)


def set_logic_globals(g):
    """逻辑模块命名空间 (nodes/library.py 导入结束时登记)"""
    global _LOGIC_GLOBALS
    _LOGIC_GLOBALS = g
    return True


def logic_globals():
    return _LOGIC_GLOBALS


def stats():
    """自检用: 注册数/所属文件分布"""
    from collections import Counter
    c = Counter(home_file(k) for k in NODE_ORDER)
    return {"keys": len(NODE_ORDER), "files": {k: v for k, v in c.items()}}
