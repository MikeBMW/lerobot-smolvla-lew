#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📦 可复制清单生成器 —— 把状态空间系统分级, 产出可交付的复制清单

老倪 2026-09-23: "把全套状态空间的系统, 包括必要的数据, 训练, 推理, 运行程序, 复制到mac上"
               "小芳你的系统资源有限...资源要先评估"

分级原则 (小芳是备份端, Mac 资源有限 → 不能全量搬):
  T1 核心(必须) : 能跑通推理/训练的最小集合 (代码+配置+流程拓扑+关键权重+小样本)
  T2 重要        : 复现与运维所需 (报告/记忆/注册表/小数据)
  T3 可选        : 大数据集/大数据产物 (按需拉, 不随包)
  X  排除        : venv(须重建)/.git历史/__pycache__/大 h5·npz
每项带 sha256(前16) 便于小芳收到后校验完整性。
"""
import argparse
import hashlib
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWM = "/home/ubuntu/stable-wm-cache"

# T1: 核心 (路径, 说明)
T1 = [
    ("tools", "全部工具链 (流水线/闭环/标定/端侧微调/评估)"),
    ("src/lerobot/policies", "策略与推理核心"),
    ("src/lerobot/manifold", "流形/节点实现"),
    ("flows", "画布拓扑 (pipeline_closure / calib_closure 等)"),
    ("config", "标定注册表/机器人规格 (禁硬编码的来源)"),
    ("data/memory_layers.json", "五层记忆 (16条/31链接)"),
    ("docs/PIPELINE_STATE.json", "闭环运行状态 (画布/控制台读这个)"),
    ("zmax_robot_spec", "机器人规格/URDF 引用"),
]
# T1 关键权重 (小体积、可跑推理)
T1_W = [
    (f"{SWM}/checkpoints/backbone_cont/unified.pt", "统一主干 (SigLIP+四头, 留出 L4 0.008)"),
    (f"{SWM}/checkpoints/unified_aug/unified.pt", "统一主干+几何增强 (鲁棒性版)"),
    (f"{SWM}/checkpoints/intact_l4_current", "在役 L4 (INTACT, 含 config.json)"),
    (f"{SWM}/checkpoints/joint_v5", "联合训练产物 (含 config.json)"),
]
# T2: 重要
T2 = [
    ("reports", "评测/训练报告 (小 json 为主)"),
    ("data", "数据集索引与元信息"),
    ("docs", "文档与技能引用"),
]
# T3: 可选 (大数据)
T3 = [
    (f"{SWM}/datasets", "全量数据集 (127G — 按需拉, 不随包)"),
    (f"{REPO}/reports/joint_train_20260922_141238", "训练可视化大目录"),
]
# X: 排除
EXCL = [".git", "__pycache__", ".venv", "gui-venv311", "node_modules", ".pytest_cache"]


def sha16(p):
    h = hashlib.sha256()
    if os.path.isfile(p):
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                h.update(c)
        return h.hexdigest()[:16]
    return "-"


def dirsize(p, cap_files=None):
    if os.path.isfile(p):
        return os.path.getsize(p), 1
    tot, n = 0, 0
    for root, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d not in EXCL]
        for fn in files:
            try:
                tot += os.path.getsize(os.path.join(root, fn))
                n += 1
            except OSError:
                pass
    return tot, n


def human(b):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return "%.1f%s" % (b, u)
        b /= 1024.0
    return "%.1fPB" % b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/replica_manifest.json")
    ap.add_argument("--hash", type=int, default=1, help="1=算 sha256 前16 (慢但可校验)")
    a = ap.parse_args()

    items, total = [], {"T1": 0, "T2": 0, "T3": 0}
    for tier, group in (("T1", T1), ("T2", T2), ("T3", T3)):
        for rel, desc in group:
            p = rel if os.path.isabs(rel) else os.path.join(REPO, rel)
            if not os.path.exists(p):
                items.append({"tier": tier, "path": rel, "exists": False, "desc": desc})
                continue
            sz, nf = dirsize(p)
            total[tier] += sz
            items.append({"tier": tier, "path": rel, "exists": True, "size": sz,
                          "files": nf, "desc": desc,
                          "sha16": sha16(p) if (a.hash and os.path.isfile(p)) else "-",
                          "abs": p})
    for ab, desc in T1_W:
        if not os.path.exists(ab):
            items.append({"tier": "T1", "path": ab, "exists": False, "desc": desc})
            continue
        sz, nf = dirsize(ab)
        total["T1"] += sz
        items.append({"tier": "T1", "path": ab, "exists": True, "size": sz, "files": nf,
                      "desc": desc, "sha16": sha16(ab) if (a.hash and os.path.isfile(ab)) else "-",
                      "abs": ab})
    for ab, desc in T3:
        if os.path.exists(ab):
            sz, nf = dirsize(ab)
            total["T3"] += sz

    m = {"generated": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
         "src_host": "4060-workspace (静静=工作端)",
         "dst_role": "小芳=孪生备份端",
         "excludes": EXCL,
         "totals": {"T1": total["T1"], "T2": total["T2"], "T3": total["T3"]},
         "items": items}
    json.dump(m, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("=" * 78)
    print("📦 可复制清单 → %s" % a.out)
    print("=" * 78)
    for tier in ("T1", "T2", "T3"):
        print("\n【%s】合计 %s" % (tier, human(total[tier])))
        for it in items:
            if it["tier"] == tier:
                st = human(it["size"]) if it.get("size") else "缺失"
                print("   %-58s %9s  %s" % (it["path"][-58:], st, it["desc"][:26]))
    print("\n【X 排除】venv(须在 Mac 重建) · .git · __pycache__ · 大 h5/npz")
    print("\n📊 交付建议: T1 + T2 = %s (Mac 直接可跑推理与微调)"
          % human(total["T1"] + total["T2"]))
    print("             T3 = %s (127G 数据集 — 按需拉, 建议只带 1 个小样本切片)"
          % human(total["T3"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
