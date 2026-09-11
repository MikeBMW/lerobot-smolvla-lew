# -*- coding: utf-8 -*-
"""🎓 训练 yaw 试抓/插入头: (z7, a4, yaw_norm) → 预测真实结果 (2026-09-11)

数据 = tools/yaw_grasp_probe.py / yaw_insert_probe.py 的**真实物理**标签:
  · grasp 探针 → 抬升 Δz (m) + ok
  · insert 探针 → 推入深度 (mm) + ok
监督意义: 预测器输入含 yaw (act_dim 4→5 语义), 且标签是真实成败 → φ* = argmax 预测分数
才可能是"最优对准角" (旧 v5 无 yaw 维 → 打分退化落边界, 已实测)。

拆分: 多 seed → 留一 seed 交叉验证 (报告"预测最优 δ 是否命中经验最优 δ");
      单 seed → 每隔 3 个 δ 留一 (防同布局泄漏)。
用法:
  gui-venv311/bin/python tools/train_yaw_head.py --data 'reports/yaw_insert_probe_*.json' \
      --target insert_depth --epochs 3000
输出: models/l4_yaw_head_<target>_v1.pt + reports/yaw_head_metrics_<ts>.json (含诚实指标)
"""
import argparse
import glob
import importlib.util
import json
import os
import sys
import time

import numpy as np
import torch
from torch import nn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
_SPEC = importlib.util.spec_from_file_location(
    "_yaw_head", os.path.join(ROOT, "src", "lerobot", "manifold", "yaw_head.py"))
_YH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_YH)


def load_rows(pattern):
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, pattern))):
        d = json.load(open(p, encoding="utf-8"))
        for r in d.get("rows", []):
            if len(r.get("z7") or []) == 7:
                r["_src"] = os.path.basename(p)
                rows.append(r)
    return rows


def feats(r):
    yaw_deg = r.get("delta_deg", r.get("phi_deg", 0.0))
    x = np.asarray(list(r["z7"]) + list(r.get("a4") or [0, 0, 0, 0]) + [float(yaw_deg) / 90.0],
                   dtype=np.float32)
    return x, float(yaw_deg)


def targets(r, kind):
    if kind == "insert_depth":
        y = float(r.get("depth_mm", 0.0)) / 50.0      # 归一化 (目标 50mm)
        ok = 1.0 if r.get("ok") else 0.0
    else:                                             # grasp_dz
        y = float(r.get("dz_m", 0.0)) / 0.2
        ok = 1.0 if r.get("ok") else 0.0
    return y, ok


def fit(tr_rows, kind, epochs, seed=0):
    torch.manual_seed(seed)
    X = torch.tensor(np.stack([feats(r)[0] for r in tr_rows]))
    Y = torch.tensor([targets(r, kind)[0] for r in tr_rows], dtype=torch.float32)
    O = torch.tensor([targets(r, kind)[1] for r in tr_rows], dtype=torch.float32)
    head = _YH.YawGraspHead(z_dim=7, act_dim=4, hidden=256, num_layers=2)
    opt = torch.optim.Adam(head.parameters(), lr=2e-3, weight_decay=1e-5)
    lossf = nn.MSELoss()
    lossb = nn.BCEWithLogitsLoss()
    for ep in range(epochs):
        head.train()
        opt.zero_grad()
        o = head(X[:, :7], X[:, 7:11], X[:, 11])
        loss = lossf(o["dz"], Y) + 0.5 * lossb(o["ok_logit"], O)
        loss.backward()
        opt.step()
    head.eval()
    return head, float(loss.item())


def evaluate(head, te_rows, kind):
    """诚实指标: 回归 MSE/MAE + 成败 ACC + 逐组"预测最优 δ 命中经验最优 δ" """
    if not te_rows:
        return {}
    with torch.no_grad():
        X = torch.tensor(np.stack([feats(r)[0] for r in te_rows]))
        o = head(X[:, :7], X[:, 7:11], X[:, 11])
        p_dz = o["dz"].numpy()
        p_ok = torch.sigmoid(o["ok_logit"]).numpy()
    y = np.array([targets(r, kind)[0] for r in te_rows])
    ok = np.array([targets(r, kind)[1] for r in te_rows])
    groups, hits, rows_out = {}, 0, []
    for r, p, po in zip(te_rows, p_dz, p_ok):
        groups.setdefault(r.get("seed", 0), []).append((float(r.get("delta_deg", r.get("phi_deg", 0))), y[len(rows_out)], p, po))
        rows_out.append(r)
    for g, arr in groups.items():
        emp_best = max(arr, key=lambda t: t[1])[0]
        pred_best = max(arr, key=lambda t: t[2])[0]
        hits += int(abs(emp_best - pred_best) < 1e-6)
    return {"mse": float(np.mean((p_dz - y) ** 2)), "mae": float(np.mean(np.abs(p_dz - y))),
            "ok_acc": float(np.mean((p_ok > 0.5) == (ok > 0.5))),
            "group_argmax_hit": f"{hits}/{len(groups)}",
            "groups": {int(k): sorted([(float(a), round(float(b), 3), round(float(c), 3),
                                        round(float(d), 3)) for a, b, c, d in v])
                       for k, v in groups.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="reports/yaw_insert_probe_*.json")
    ap.add_argument("--target", default="insert_depth", choices=["insert_depth", "grasp_dz"])
    ap.add_argument("--epochs", type=int, default=3000)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rows = load_rows(a.data)
    seeds = sorted({r.get("seed", 0) for r in rows})
    print(f"数据 {len(rows)} 行 · seeds={seeds} · target={a.target}")
    if len(rows) < 12:
        print("⚠️ 数据太少 (<12), 先跑探针")
        return
    modes = [("全部训练", rows, rows)]
    if len(seeds) >= 2:
        for s in seeds[:4]:                       # 留一 seed 交叉验证
            modes.append((f"留出 seed={s}", [r for r in rows if r.get("seed") != s],
                          [r for r in rows if r.get("seed") == s]))
    else:
        te = [r for i, r in enumerate(rows) if i % 3 == 0]
        tr = [r for i, r in enumerate(rows) if i % 3 != 0]
        modes.append(("留出 δ 每3取1", tr, te))
    report = {"data": a.data, "target": a.target, "n_rows": len(rows), "seeds": seeds, "folds": []}
    for tag, tr, te in modes:
        head, loss = fit(tr, a.target, a.epochs)
        ev = evaluate(head, te, a.target)
        print(f"[{tag}] loss={loss:.4f} {ev}")
        report["folds"].append({"fold": tag, "loss": loss, "eval": ev})
        if tag == "全部训练":
            out = a.out or os.path.join(ROOT, "models", f"l4_yaw_head_{a.target}_v1.pt")
            torch.save(head.state_dict(), out)
            print(" → 权重:", out)
    mp = os.path.join(ROOT, "reports", f"yaw_head_metrics_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(report, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(" → 指标:", mp)


if __name__ == "__main__":
    main()
