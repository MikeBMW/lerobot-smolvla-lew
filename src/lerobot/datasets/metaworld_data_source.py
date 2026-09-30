# -*- coding: utf-8 -*-
"""
══════════════════════════════════════════════════════════════════
📦 metaworld 数据源 — Z-MAX 真实数据层 (lerobot 框架)
══════════════════════════════════════════════════════════════════

🐛 2026-09-02 老倪: 画布「📦 metaworld 数据源」节点的真实实现必须落在
lerobot 框架数据层 (src/lerobot/datasets/), 而不是 tools/gui 控制台的
node_logic.py 模板 — 与传感器融合(perception.py)/前馈(parallel.py)等
节点"右键打开真实源码、断点进真实实现"保持同构。

本文件职责:
  · probe_data_source()   — 真实探测本机训练数据仓库 (帧数/集数/特征/源)
  · resolve_source(kind)  — 数据源策略: metaworld(占位集) / orin(真实产线)
  · 无 GUI / 无 torch 依赖 — 画布节点、训练入口、代码讲解共用同一权威实现
══════════════════════════════════════════════════════════════════
"""
import json
import os

# ── 数据仓库优先级 (与 node_logic._probe_data_root / _ensure_training_data 同源) ──
#   (源类型, 相对路径, 中文标签) — Orin 真实产线 → 长轨迹 → 标准 光模块 → 状态空间 insert
DATA_ROOTS = (
    ("orin",      "data/closed_loop",        "Orin 真实产线"),
    ("metaworld", "data/metaworld_peg_long", "metaworld 长轨迹"),
    ("metaworld", "data/metaworld_peg",      "metaworld 标准 peg"),
    ("metaworld", "data/ss_insert_lerobot",  "状态空间 insert"),
)

# 数据源切换语义 (画布节点 params.source 取值)
SOURCE_LABELS = {
    "metaworld": "metaworld 占位集",
    "orin":      "Orin 真实产线",
}


def _repo_root():
    """仓库根定位 — 本文件在 <root>/src/lerobot/datasets/ → 上溯三级;
    兼容 env ZMAX_REPO_ROOT (Windows exe 解压目录) 与 frozen _MEIPASS"""
    env = os.environ.get("ZMAX_REPO_ROOT")
    if env and os.path.isdir(env):
        return env
    _d = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    while True:
        if os.path.isdir(os.path.join(_d, "src", "lerobot")):
            return _d
        _p = os.path.dirname(_d)
        if _p == _d:
            break
        _d = _p
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def probe_data_source(root=None):
    """真实探测本机训练数据仓库 (按 DATA_ROOTS 优先级).

    Returns:
        dict(path, frames, episodes, source, label, features) — 命中首个含
        info.json 的仓库; 全部缺失返回 None (画布占位/提示引导采集).
    """
    root = root or _repo_root()
    for src, rel, label in DATA_ROOTS:
        d = os.path.join(root, rel)
        for ij in (os.path.join(d, "meta", "info.json"), os.path.join(d, "info.json")):
            if not os.path.isfile(ij):
                continue
            try:
                with open(ij, encoding="utf-8") as f:
                    info = json.load(f)
                nf = info.get("total_frames", "?")
                ne = info.get("total_episodes", "?")
                feats = [str(x).replace("observation.", "")
                         for x in list(info.get("features", {}).keys())[:4]]
                return {
                    "path": rel,
                    "frames": nf,
                    "episodes": ne,
                    "source": src,
                    "label": label,
                    "features": feats,
                }
            except Exception:
                continue
    return None


def resolve_source(kind="metaworld"):
    """数据源策略: metaworld(占位集) → 本机仓库探测结果;
    orin(真实产线) → 标记 relay 链路 (拉取需链路就绪, 采集由小芳 Orin/Mac 侧触发).
    """
    if kind == "orin":
        return {"kind": "orin", "note": "Orin 真实产线 (relay 中转, 需链路就绪)"}
    info = probe_data_source()
    if info:
        return {"kind": "metaworld", **info}
    return {"kind": "metaworld", "note": "本机无训练仓库 (仅画布占位)"}
