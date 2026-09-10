#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 全局数据空间 (Global Data Space) — 2026-08-07 老倪: 全息系统设计
控制台所有相关数据对象统一注册表 + simulink node 映射 + 数据一致性。

数据对象五类 (全息信息):
  DATASETS  数据集    (data/ 扫描: 光模块/套环/Orin, 帧数/eps/维度)
  CURVES    训练曲线  (reports/train_curve_*.json)
  MODELS    模型产物  (outputs/train/*/checkpoints 最后 ckpt)
  ROLLOUTS  推理视频  (reports/rollout_*/frame_*.png)
  REPORTS   报告图表  (reports/*.pdf / *.png)

node 映射 (simulink 节点类型 → 关联数据对象):
  数据源节点  → DATASETS
  训练节点    → CURVES + MODELS
  仿真推理节点 → ROLLOUTS
  Scope 节点  → CURVES + REPORTS
  PDF 节点    → REPORTS

一致性: 文件存在性 + 时间戳匹配 (对象 mtime vs 关联文件)。
"""
import os, glob, json, time


class GlobalDataSpace:
    def __init__(self, root=None):
        self.root = root or os.path.expanduser("~/lerobot-smolvla-lew")
        self.datasets = []      # 数据集注册表
        self.curves = {}        # policy → 曲线信息
        self.models = {}        # policy → checkpoint 信息
        self.rollouts = {}      # policy → 视频信息
        self.reports = []       # 报告列表
        self.nodes = []         # 2026-08-08 老倪: 模块库节点主数据 (LIBRARY 全部节点)
        self._last_scan = 0

    # ── 扫描 ──────────────────────────────────────────────
    def scan(self, force=False):
        """全量扫描 (数据空间刷新)"""
        now = time.time()
        if not force and now - self._last_scan < 3:
            return self
        self._scan_datasets()
        self._scan_curves()
        self._scan_models()
        self._scan_rollouts()
        self._scan_reports()
        self._scan_nodes()
        self._last_scan = now
        return self

    def _scan_nodes(self):
        """2026-08-08 老倪: 模块库节点主数据 — LIBRARY 全部节点 (组/名/类型/params 摘要)"""
        self.nodes = []
        try:
            import simulink_module as _sm
            for ntype, gname, items in getattr(_sm, "LIBRARY", []):
                for it in items:
                    p = it.get("params", {})
                    self.nodes.append({
                        "group": gname, "name": it["name"], "type": ntype,
                        "params": {k: str(v)[:40] for k, v in list(p.items())[:4]},
                    })
        except Exception:
            pass

    def _scan_datasets(self):
        self.datasets = []
        cands = [
            ("metaworld_peg", "光模块插拔 (lerobot)", "peg"),
            ("metaworld_peg_v2", "光模块插拔 (npz)", "peg"),
            ("metaworld_act", "套环 nut-on-peg", "act"),
            ("metaworld_mt50", "MT50 套环 (task0)", "mt50"),
            ("closed_loop", "Orin 闭环采集", "orin"),
            ("orin_live", "Orin 实时采集", "orin"),
            ("orin_real_v1", "Orin 真机 v1", "orin"),
            ("orin_archive", "Orin 归档", "orin"),
        ]
        for d, desc, tag in cands:
            dp = os.path.join(self.root, "data", d)
            if not os.path.isdir(dp):
                continue
            info = {"id": d, "path": f"data/{d}", "type": tag, "desc": desc,
                    "frames": "?", "eps": "?", "state_dim": "?", "action_dim": "?", "ts": "?"}
            try:
                ij = os.path.join(dp, "meta", "info.json")
                if os.path.exists(ij):
                    m = json.load(open(ij, encoding="utf-8"))
                    info["frames"], info["eps"] = m.get("total_frames", "?"), m.get("total_episodes", "?")
            except Exception:
                pass
            try:
                tn = os.path.join(dp, "train.npz")
                if os.path.exists(tn):
                    import numpy as _np
                    darr = _np.load(tn)
                    info["frames"], info["eps"] = len(darr["observations"]), "npz"
                    info["state_dim"], info["action_dim"] = darr["states"].shape[1], darr["actions"].shape[1]
            except Exception:
                pass
            info["ts"] = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(dp)))
            info["mtime"] = os.path.getmtime(dp)
            self.datasets.append(info)

    def _scan_curves(self):
        self.curves = {}
        for f in sorted(glob.glob(os.path.join(self.root, "reports", "train_curve_*.json"))):
            try:
                d = json.load(open(f, encoding="utf-8"))
                policy = d.get("policy", os.path.basename(f).replace("train_curve_", "").replace(".json", ""))
                n = len(d.get("curve") or [])
                tail = d["curve"][-1] if n else None
                self.curves[policy] = {
                    "policy": policy, "file": os.path.relpath(f, self.root),
                    "points": n, "tail": tail, "ts": d.get("ts", "?"),
                    "mtime": os.path.getmtime(f),
                }
            except Exception:
                continue

    def _scan_models(self):
        self.models = {}
        for d in sorted(glob.glob(os.path.join(self.root, "outputs", "train", "*")),
                        key=os.path.getmtime):
            if not os.path.isdir(d):
                continue
            ck = os.path.join(d, "checkpoints")
            if not os.path.isdir(ck):
                continue
            steps = sorted([x for x in os.listdir(ck) if x.isdigit()], key=lambda x: int(x))
            if not steps:
                continue
            last = steps[-1]
            pm = os.path.join(ck, last, "pretrained_model")
            if not os.path.isdir(pm):
                continue
            policy = os.path.basename(d).rsplit("_", 2)[0]  # act_20260807_161435 → act
            self.models[os.path.basename(d)] = {
                "dir": os.path.basename(d), "policy": policy, "steps": int(last),
                "ts": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(pm))),
                "mtime": os.path.getmtime(pm),
            }

    def _scan_rollouts(self):
        self.rollouts = {}
        for d in sorted(glob.glob(os.path.join(self.root, "reports", "rollout_*"))):
            if not os.path.isdir(d):
                continue
            frames = glob.glob(os.path.join(d, "frame_*.png"))
            if not frames:
                continue
            policy = os.path.basename(d).replace("rollout_final_", "").replace("rollout_", "")
            self.rollouts[os.path.basename(d)] = {
                "dir": os.path.basename(d), "policy": policy, "frames": len(frames),
                "ts": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(frames[0]))),
                "mtime": os.path.getmtime(frames[0]),
            }

    def _scan_reports(self):
        self.reports = []
        for f in sorted(glob.glob(os.path.join(self.root, "reports", "*.pdf")) +
                        sorted(glob.glob(os.path.join(self.root, "reports", "*对比*.mp4"))),
                        key=os.path.getmtime, reverse=True):
            self.reports.append({
                "file": os.path.basename(f),
                "size": os.path.getsize(f) // 1024,
                "ts": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(f))),
                "mtime": os.path.getmtime(f),
            })

    # ── node 映射 (全息: node → 关联数据对象) ───────────────
    def node_objects(self, node):
        """simulink node → 关联数据对象列表 (全息信息)"""
        name = node.get("name", "")
        params = node.get("params", {})
        objs = []
        # 2026-08-08 老倪: 节点本身是主数据 (模块库主数据 — 每个 node 关联自身注册表项)
        for n in self.nodes:
            if n["name"] == name:
                objs.append(("节点", n))
        # 数据源节点 → 数据集
        if "数据" in name or params.get("source"):
            src = params.get("source", "metaworld")
            for ds in self.datasets:
                if src == "orin" and ds["type"] == "orin":
                    objs.append(("数据集", ds))
                elif src != "orin" and ds["type"] != "orin":
                    objs.append(("数据集", ds))
        # 训练节点 → 曲线 + 模型
        if "训练" in name or "蒸馏" in name or "基准" in name:
            for p, c in self.curves.items():
                objs.append(("曲线", c))
            for m in list(self.models.values())[-7:]:
                objs.append(("模型", m))
        # 推理/视频节点 → rollout
        if "推理" in name or "视频" in name or "仿真" in name:
            pol = params.get("video_policy")
            for d, r in self.rollouts.items():
                if pol is None or pol in d:
                    objs.append(("视频", r))
        # Scope → 曲线
        if "Scope" in name or "评估" in name:
            for p, c in self.curves.items():
                objs.append(("曲线", c))
        # PDF → 报告
        if "PDF" in name or "报告" in name:
            for r in self.reports:
                objs.append(("报告", r))
        return objs

    # ── 数据一致性检查 ─────────────────────────────────────
    def consistency(self):
        """返回 (问题列表) — 注册表对象 vs 实际文件"""
        issues = []
        # 数据集: 引用路径存在
        for ds in self.datasets:
            if not os.path.isdir(os.path.join(self.root, ds["path"])):
                issues.append(f"数据集 {ds['id']} 目录缺失")
        # 曲线: 训练完成但曲线缺失
        for d in sorted(glob.glob(os.path.join(self.root, "outputs", "train", "*"))):
            if not os.path.isdir(os.path.join(d, "checkpoints")):
                continue
            base = os.path.basename(d)
            policy = base.rsplit("_", 2)[0]
            if policy in ("act", "smolvla", "smolvla_lew", "vla_touch", "awe_zflow"):
                cf = os.path.join(self.root, "reports", f"train_curve_{policy}.json")
                if not os.path.exists(cf):
                    issues.append(f"模型 {base} 无对应曲线文件")
        return issues

    # ── 全息摘要 ───────────────────────────────────────────
    def summary(self):
        self.scan()
        return {
            "datasets": len(self.datasets),
            "curves": len(self.curves),
            "models": len(self.models),
            "rollouts": len(self.rollouts),
            "reports": len(self.reports),
            "issues": len(self.consistency()),
        }
