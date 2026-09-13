# -*- coding: utf-8 -*-
"""🎯 L4 意图服务 (policy 层门面) — metaworld → INTACT 策略(桥) → 意图解码器 → L3 条件。

老倪 2026-09-13: 「这段 (node_intact_dec 编排) 应该放到 src/lerobot/policies 这个地方,
你来重构代码」。所以**编排逻辑全部搬到 policy 层**, GUI (tools/gui/node_logic.py) 只留瘦调用。

三层职责 (谁负责什么, 一眼看清):
  · 桥    = runtime/model_adapter.IntactRuntime — 跨 venv 常驻子进程, 跑在 /home/ubuntu/INTACT-JEPA
            (外部仓库**一字不改**; 论文权重必须它自己的冻结运行时, 依赖也不兼容本工程 venv)
  · 节点  = runtime/node.IntactNode — 滑窗 + 动作历史滚动 + 诊断; modeling_intact.IntactPolicy 是 lerobot 外壳
  · 解码  = decoder.IntactIntentDecoder — u_ff 先验 (act×K_ACT, 无需标定) + L3 流形条件 (未标定诚实拒绝)
  · 本文件 = 把三者串成**一次调用** (建桥/接数据源/真推理/解码/证据落盘/日志文本), 供 GUI·脚本·离线批跑复用

对外 (GUI 只调这两个方法):
  svc = get_service(root)                进程内单例 (重复双击复用同一个 worker, 不重复起进程)
  ok, note = svc.ensure_ready()           建桥 + 接数据源 (metaworld → l4_episode 兜底, note 说明原因)
  rep = svc.run_once(stage, decode=True, log=ctx["log"])  一步真推理 (+解码 +证据), 返回 IntentReport
  svc.bridge_status() / svc.describe()    面板/报告用
  svc.close()                            显式收桥

诚实纪律 (老倪红线): 桥/权重不可用 → trained=False + reason (绝不返回假动作冒充成功);
L3 条件未标定 → 拒绝并计数 (不写死映射); 每一步都留证据 reports/intact_l3_cond.json。
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

EVIDENCE_REL = os.path.join("reports", "intact_l3_cond.json")


def _find_root() -> str:
    """向上找工程根 (含 reports/ 目录)。"""
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "reports")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


def _r4(v: np.ndarray | None) -> list | None:
    """数组 → 可 JSON 化 (四位小数)。"""
    if v is None:
        return None
    a = np.asarray(v, dtype=np.float64).ravel()
    return [float(x) for x in np.round(a, 4)]


@dataclass
class IntentReport:
    """一次 L4 推理 + 解码的完整结果 (面板/日志/证据 的唯一来源)。"""
    stage: str = ""
    trained: bool = False
    chunk_shape: tuple = ()
    policy: str = ""
    diagnostics: dict = field(default_factory=dict)
    source: str = ""
    obs_source: str = ""
    robot: str = ""
    latent_keys: list = field(default_factory=list)
    # 解码结果 (decode=False 时全 None)
    decoded: bool = False
    u_ff: np.ndarray | None = None
    u_ff_source: str = ""
    l3_cond: np.ndarray | None = None
    l3_cond_source: str = ""
    weight: float = 0.0
    reason: str = ""
    decoder: dict = field(default_factory=dict)
    evidence_path: str = ""
    bridge: dict = field(default_factory=dict)
    ts: str = ""

    # ── 日志 (文本由 policy 层生成, GUI 只负责打出来) ──
    def log_lines(self) -> list[str]:
        d = self.diagnostics or {}
        out = []
        if self.decoded:
            out.append(f"🎯 INTACT 意图解码器 [L4 → L3] · 阶段={self.stage or '(未标注)'} · "
                       f"权重 w={self.weight:.2f}")
            out.append(f"   ① u_ff 先验 {_r4(self.u_ff)} ← {self.u_ff_source} "
                       f"(下发口径与引擎 state_space_sim_real.py 同源)")
            if self.l3_cond is None:
                out.append(f"   ② L3 条件: **不注入** — {self.l3_cond_source} · "
                           f"原因: {self.decoder.get('reason', self.reason)}")
                out.append("      (L3 仍走 VLM+DiT 原链路 → 零回退; 标定后本通道自动生效)")
            else:
                out.append(f"   ② L3 条件 {_r4(self.l3_cond)} ← {self.l3_cond_source}")
        else:
            out.append(f"🎯 INTACT: action chunk{tuple(self.chunk_shape)} · 策略={self.policy}(零搜索) · "
                       f"candidate_sequences={float(d.get('candidate_sequences', 0)):.0f} · "
                       f"延迟 {float(d.get('latency_ms', 0.0)):.1f}ms · 数据源={self.source} · "
                       f"输出={self.robot}")
        if self.reason and self.decoded:
            out.append(f"   ⚠️ {self.reason}")
        if not self.trained:
            out.append(f"   ⚠️ 模型未就绪 (trained=False) — 原因: {self.bridge.get('reason')}; "
                       f"S1 调试: bash scripts/install.sh cu124 → eval_official.sh direct pusht")
        if self.evidence_path:
            out.append(f"   → 证据: {os.path.relpath(self.evidence_path, _find_root())}")
        return out

    def to_panel(self) -> dict:
        """GUI 面板/引擎读的紧凑结构 (mod._intact_dec)。"""
        return {"stage": self.stage, "u_ff": self.u_ff, "l3_cond": self.l3_cond,
                "w": self.weight, "src": self.u_ff_source, "trained": self.trained,
                "cond_ready": self.l3_cond is not None,
                "cond_src": self.l3_cond_source, "obs_source": self.obs_source,
                "chunk_shape": list(self.chunk_shape), "ts": self.ts}

    def to_dict(self) -> dict:
        return {"stage": self.stage, "trained": self.trained, "chunk_shape": list(self.chunk_shape),
                "policy": self.policy, "source": self.source, "obs_source": self.obs_source,
                "robot": self.robot, "latent_keys": list(self.latent_keys),
                "diagnostics": self.diagnostics, "decoded": self.decoded,
                "u_ff": _r4(self.u_ff), "u_ff_source": self.u_ff_source,
                "l3_cond": _r4(self.l3_cond), "l3_cond_source": self.l3_cond_source,
                "weight": self.weight, "reason": self.reason, "decoder": self.decoder,
                "bridge": self.bridge, "ts": self.ts}

    # ── 证据文件 (保持 v5.5.40 起的字段名, 只增不改 → 引擎/工具不用动) ──
    @staticmethod
    def _r6(v: np.ndarray | None) -> list | None:
        if v is None:
            return None
        return [float(x) for x in np.round(np.asarray(v, dtype=np.float64).ravel(), 6)]

    def evidence(self) -> dict:
        d = self.diagnostics or {}
        return {"stage": self.stage, "w": self.weight,
                "u_ff": self._r6(self.u_ff), "u_ff_source": self.u_ff_source,
                "l3_cond": self._r6(self.l3_cond), "l3_cond_source": self.l3_cond_source,
                "reason": self.reason, "decoder": self.decoder,
                "ts": self.ts,
                # ↓ v5.5.43 新增 (只增不改)
                "trained": self.trained, "chunk_shape": list(self.chunk_shape),
                "policy": self.policy, "source": self.source, "obs_source": self.obs_source,
                "candidate_sequences": float(d.get("candidate_sequences", 0.0)),
                "latency_ms": float(d.get("latency_ms", 0.0)),
                "reuse": float(d.get("reuse", 0.0)), "calls": float(d.get("calls", 0.0)),
                "goal_src": d.get("goal_src"), "bridge": self.bridge}


class IntactIntentService:
    """L4 意图服务 (policy 层; 内部持有一个 IntactNode + 一个 IntactIntentDecoder)。"""

    def __init__(self, root: str | None = None, horizon: int = 8, action_dim: int = 4,
                 cond_dim: int = 6, source: str = "metaworld", seed: int = 0,
                 fallback_source: str = "l4_episode", repo: str | None = None,
                 log=print) -> None:
        self.root = os.path.abspath(root or _find_root())
        self.horizon = int(horizon)
        self.action_dim = int(action_dim)
        self.cond_dim = int(cond_dim)
        self.source_name = str(source)
        self.fallback_source = str(fallback_source)
        self.seed = int(seed)
        self.repo = repo
        self.log = log
        self.node: Any = None            # runtime.node.IntactNode (懒建)
        self.decoder: Any = None         # decoder.IntactIntentDecoder (懒建)
        self.source_note = ""
        self._lock = threading.Lock()

    # ── 建桥 + 接数据源 (幂等; 重复调用不重复起 worker) ──
    def ensure_ready(self) -> tuple[bool, str]:
        with self._lock:
            if self.node is None:
                try:
                    from .runtime import IntactNode
                except Exception as e:                             # noqa: BLE001
                    return False, f"policy 层未就绪: {type(e).__name__}: {e}"
                self.node = IntactNode(horizon=self.horizon, action_dim=self.action_dim,
                                       repo=self.repo, log=self.log)
            if self.node.source is None:
                try:
                    self.node.set_data_source(self.source_name, seed=self.seed)
                except Exception as e:                             # noqa: BLE001
                    self.source_note = (f"{self.source_name} 数据源不可用 "
                                        f"({type(e).__name__}: {e}) → 退回 {self.fallback_source}")
                    self.node.set_data_source(self.fallback_source)
            if self.decoder is None:
                from .decoder import IntactIntentDecoder
                self.decoder = IntactIntentDecoder(cond_dim=self.cond_dim)
            return True, self.source_note

    def set_source(self, name: str, **kw) -> None:
        """换数据源 (显式动作, 不静默)。"""
        ok, why = self.ensure_ready()
        if not ok:
            raise RuntimeError(why)
        self.source_name = str(name)
        self.node.set_data_source(name, **kw)

    # ── 一步真推理 (未就绪 raise, 绝不返回零动作冒称成功) ──
    def step_once(self):
        ok, why = self.ensure_ready()
        if not ok:
            raise RuntimeError(why)
        return self.node.step()

    def run_once(self, stage: str = "", decode: bool = True, write_evidence: bool | None = None,
                 log=None) -> IntentReport:
        log = log or self.log
        ok, why = self.ensure_ready()
        if not ok:
            raise RuntimeError(why)
        if why:
            log(f"   ⚠️ {why}")
        try:                                    # goal 帧来源标注 (goal_displacement 硬需求)
            self.node.ensure_goal()             # ① 已显式 set_goal ② 数据源自报 goal ③ 默认目标帧文件
        except Exception as e:                  # noqa: BLE001
            log(f"   ⚠️ ensure_goal 失败: {type(e).__name__}: {e}")
        src = self.node.source
        st = str(stage or (src.info().get("stage", "") if src is not None else ""))
        out = self.node.step()                                  # 真推理
        diag = dict(self.node.diagnostics() or {})
        rep = IntentReport(stage=st, trained=bool(getattr(out, "trained", False)),
                           chunk_shape=tuple(np.asarray(out.chunk).shape),
                           policy=str(getattr(out, "policy", "")),
                           diagnostics=diag, source=str(getattr(out, "source", "")),
                           obs_source=str(getattr(out, "obs_source", "")),
                           robot=getattr(getattr(self.node, "robot", None), "name", ""),
                           latent_keys=sorted((getattr(out, "latent", None) or {}).keys()),
                           bridge=self.bridge_status(),
                           ts=time.strftime("%F %T"))
        if decode:
            d = self.decoder.decode(out, stage=st)
            rep.decoded = True
            rep.u_ff, rep.u_ff_source = d.u_ff, d.u_ff_source
            rep.l3_cond, rep.l3_cond_source = d.l3_cond, d.l3_cond_source
            rep.weight, rep.reason = float(d.weight), d.reason
            rep.decoder = self.decoder.describe()
            if write_evidence is None:
                write_evidence = True
        if write_evidence:
            rep.evidence_path = self.write_evidence(rep)
        for ln in rep.log_lines():
            log(ln)
        return rep

    def write_evidence(self, rep: IntentReport) -> str:
        p = os.path.join(self.root, EVIDENCE_REL)
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(rep.evidence(), f, ensure_ascii=False, indent=1)
            return p
        except Exception as e:                                   # noqa: BLE001
            self.log(f"   (证据落盘失败: {type(e).__name__}: {e})")
            return ""

    # ── 状态 ──
    def bridge_status(self) -> dict:
        rt = getattr(self.node, "runtime", None)
        if rt is None:
            return {"ready": False, "reason": "未建桥", "repo": self.repo}
        info = dict(rt.info() or {})
        ok, why = rt.available()
        info.update({"ready": bool(ok), "available_reason": why,
                     "venv": rt.venv_python, "task": rt.task,
                     "device": rt.device or os.environ.get("INTACT_DEVICE", "cuda")})
        return info

    def describe(self) -> dict:
        return {"root": self.root, "horizon": self.horizon, "action_dim": self.action_dim,
                "source": self.source_name, "fallback": self.fallback_source,
                "node": (self.node.describe() if self.node is not None else None),
                "decoder": (self.decoder.describe() if self.decoder is not None else None),
                "bridge": self.bridge_status()}

    def close(self) -> None:
        rt = getattr(self.node, "runtime", None)
        if rt is not None:
            try:
                rt.close()
            except Exception:                                     # noqa: BLE001
                pass
        self.node = None


# ── 进程内单例 (GUI 双击复用同一 worker; 按 root 区分) ──
_SERVICES: dict[str, IntactIntentService] = {}
_SERVICES_LOCK = threading.Lock()


def get_service(root: str | None = None, **kw) -> IntactIntentService:
    key = os.path.abspath(root or _find_root())
    with _SERVICES_LOCK:
        if key not in _SERVICES:
            _SERVICES[key] = IntactIntentService(root=key, **kw)
        return _SERVICES[key]


def reset_service(root: str | None = None) -> None:
    """收桥并丢弃单例 (换权重/换任务后需要)。"""
    key = os.path.abspath(root or _find_root())
    with _SERVICES_LOCK:
        svc = _SERVICES.pop(key, None)
    if svc is not None:
        svc.close()
