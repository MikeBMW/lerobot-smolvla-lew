# -*- coding: utf-8 -*-
"""画布 / 工程 JSON 的读写 (flows) —— 状态空间工程的数据真源在这里, 不在 GUI 里。

口径 (与 tools/ 下既有构图脚本一致, 迁移后由本模块统一):
  · 真源文件 = `src/lerobot/engineering/flows/state_space_obs.json` (package data)
  · 写盘一律: 先备份到 `flows/_archive/<name>_before_<事由>_<ts>.json` → 原子替换 → 打印还原命令
  · 校验: id 唯一 / type 合法 / 端口是字符串列表 / 连线前向 / 孤立节点统计
"""
import json
import os
import shutil
import time

from . import paths

NODE_TYPES = ("model", "data", "hardware", "condition", "system", "mode_switch", "bg", "row_bg")


def canvas_path(name=paths.CANVAS_DEFAULT):
    return paths.canvas_json(name)


def _read(name=paths.CANVAS_DEFAULT):
    """读原始 JSON (dict) —— 类型明确, 供内部使用"""
    with open(canvas_path(name), encoding="utf-8") as f:
        return json.load(f)


def load_canvas(name=paths.CANVAS_DEFAULT, validate=True):
    """读画布 JSON; validate=True 时返回 (data, errors), 否则只返回 data"""
    d = _read(name)
    return (d, validate_canvas(d)) if validate else d


def validate_canvas(d, strict_reverse=False):
    """返回**错误**列表 (空 = 可写盘)。反向连线默认只算警告 (画布上本来就有反馈线), strict_reverse=True 才当错误。"""
    probs, _ = validate_all(d, strict_reverse=strict_reverse)
    return probs


def validate_all(d, strict_reverse=False):
    """→ (errors, warnings)。errors 才是写盘的拦路虎。"""
    probs, warns = [], []
    nodes = d.get("nodes") or []
    links = d.get("links") or []
    ids = [n.get("id") for n in nodes]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        probs.append("id 重复: %s" % sorted(dup)[:6])
    for n in nodes:
        nid, t = n.get("id"), n.get("type")
        if not nid:
            probs.append("有节点缺 id: %r" % (str(n.get("name"))[:30],))
        if t not in NODE_TYPES:
            probs.append("节点 %s 的 type=%r 不在白名单 (会导致加载循环中断)" % (nid, t))
        for side in ("in", "out", "inputs", "outputs"):
            v = n.get(side)
            if v is None:
                continue
            if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
                probs.append("节点 %s 的端口 %s 不是字符串列表: %r" % (nid, side, str(v)[:40]))
    pos = {n.get("id"): n for n in nodes}
    for l in links:
        f = l.get("f", l.get("from"))
        t = l.get("t", l.get("to"))
        if f not in pos or t not in pos:
            probs.append("连线端点不存在: %s → %s" % (f, t))
            continue
        a, b = pos[f], pos[t]
        if not (a.get("type") in ("bg", "row_bg") or b.get("type") in ("bg", "row_bg")):
            if isinstance(a.get("x"), (int, float)) and isinstance(b.get("x"), (int, float)):
                if a["x"] > b["x"]:
                    (probs if strict_reverse else warns).append("连线反向(右→左): %s → %s" % (f, t))
    return probs, warns


def orphans(d):
    """孤立节点 (无入无出, 排除背景)"""
    nodes = [n for n in (d.get("nodes") or []) if n.get("type") not in ("bg", "row_bg")]
    ins, outs = set(), set()
    for l in d.get("links") or []:
        ins.add(l.get("t", l.get("to")))
        outs.add(l.get("f", l.get("from")))
    return [n.get("id") for n in nodes if n.get("id") not in ins and n.get("id") not in outs]


def stats(d=None, name=paths.CANVAS_DEFAULT):
    if d is None:
        d = _read(name)
    from collections import Counter
    return {"nodes": len(d.get("nodes") or []), "links": len(d.get("links") or []),
            "types": dict(Counter(n.get("type") for n in (d.get("nodes") or []))),
            "file": canvas_path(name)}


def save_canvas(d, name=paths.CANVAS_DEFAULT, reason="edit", backup=True):
    """写盘 (原子 + 备份)。返回 (path, backup_path)"""
    p = canvas_path(name)
    probs = validate_canvas(d)
    if probs:
        raise ValueError("画布校验不过, 拒绝写盘 (前 3 条): %s" % probs[:3])
    paths.ensure_dirs()
    bak = None
    if backup and os.path.exists(p):
        ad = os.path.join(os.path.dirname(p), "_archive")
        os.makedirs(ad, exist_ok=True)
        bak = os.path.join(ad, "%s_before_%s_%s.json"
                           % (os.path.splitext(name)[0], reason, time.strftime("%Y%m%d_%H%M%S")))
        shutil.copy2(p, bak)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    if bak:
        print("   ↩️ 还原: cp %s %s" % (bak, p))
    return p, bak
