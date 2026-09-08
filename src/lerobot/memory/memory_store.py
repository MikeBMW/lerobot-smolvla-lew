# -*- coding: utf-8 -*-
"""
══════════════════════════════════════════════════════════════════
🧠 共享记忆存储 — Z-MAX 分层记忆 (2026-09-09 老倪: L2/L3/L4 记忆 + 大模型层共享)
══════════════════════════════════════════════════════════════════
三层记忆 (信息半衰期递增) + 共享中枢:
  · L2 肌肉记忆: 固化标杆/命中统计 (引擎 muscle_memory 快通道, 同 data/muscle_memory.json)
  · L3 长程规划: 每轮走通的跨段技能序列/步数/成败 (流程经验, 规划器可检索)
  · L4 筹划: 世界模型预测质量/恢复策略选择 (专家筹划输入)
  · 共享中枢 (大模型层): 三层条目汇总 + 任务/质量门上下文 — LLM 注入用

存储: data/shared_memory.json (画布/引擎/CLI 跨进程桥; 写失败不打断主流程)
"""
import json
import os
import threading

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# 本文件: src/lerobot/memory/memory_store.py → 上溯 4 级 = 仓库根
#   dirname(文件)=src/lerobot/memory → 1 src/lerobot 2 src 3 仓库? 实际 4 次到根
_PATH = os.path.join(_REPO_ROOT, "data", "shared_memory.json")

_LOCK = threading.Lock()
_DEFAULT = {
    "l2": {"muscle": {"skills": {}, "updated": None}},   # 肌肉记忆摘要 (源 muscle_memory.json)
    "l3": {"flows": []},                                  # 长程流程经验 (最近 N 轮)
    "l4": {"predict": [], "recover": []},                 # 筹划: 预测质量 / 恢复策略
    "meta": {"task": None, "cap": None, "updated": None},
}
_CACHE = None


def _path():
    return _PATH


def load(force=False):
    """读共享记忆 (惰性缓存 + 文件刷新)"""
    global _CACHE
    if _CACHE is None or force:
        try:
            with open(_PATH, encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = json.loads(json.dumps(_DEFAULT))
        for k, v in _DEFAULT.items():
            _CACHE.setdefault(k, json.loads(json.dumps(v)))
    return _CACHE


def save():
    global _CACHE
    mem = _CACHE if _CACHE is not None else load()
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with _LOCK:
            with open(_PATH, "w", encoding="utf-8") as f:
                json.dump(mem, f, ensure_ascii=False, indent=1)
    except Exception:
        pass  # 写失败不打断主流程 (记忆是增强不是依赖)


def put(layer, key, value, cap=40):
    """写条目: layer ∈ l2/l3/l4/meta; 列表型追加 + 截断"""
    mem = load()
    if layer == "meta":
        mem["meta"][key] = value
    else:
        if key not in mem[layer]:
            mem[layer][key] = []
        if isinstance(value, list):
            mem[layer][key].extend(value)
        else:
            mem[layer][key].append(value)
        mem[layer][key] = mem[layer][key][-cap:]
    mem["meta"]["updated"] = __import__("time").strftime("%m-%d %H:%M")
    save()
    return True


def summary():
    """三层 + 共享 摘要 (画布记忆节点/共享中枢展示用)"""
    mem = load()
    l2m = (mem.get("l2", {}).get("muscle") or {}).get("skills") or {}
    l2 = {"固化技能": len(l2m)}
    l3f = mem.get("l3", {}).get("flows") or []
    l3 = {"流程经验": len(l3f),
          "最近": (l3f[-1].get("stages", "?") if l3f else None)}
    l4p = mem.get("l4", {}).get("predict") or []
    l4 = {"预测记录": len(l4p),
          "最近残差": (l4p[-1].get("mae", "?") if l4p else None)}
    return {"l2": l2, "l3": l3, "l4": l4, "meta": mem.get("meta", {})}


def muscle_lib():
    """读真实肌肉记忆库 data/muscle_memory.json (引擎 muscle_memory 持久化)"""
    p = os.path.join(_REPO_ROOT, "data", "muscle_memory.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
