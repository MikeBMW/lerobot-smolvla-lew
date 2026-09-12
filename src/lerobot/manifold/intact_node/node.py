# -*- coding: utf-8 -*-
"""🧠 INTACT 节点 (intact_node.node) — 状态空间 L4 层的封装单元。

对外只有 4 个方法 (画布/引擎只认这些):
    node.set_data_source("l4_episode", path=...)   # 输入: 数据源层
    node.set_goal(goal_frame | waypoint)           # 目标意图
    node.attach_robot(io)                          # 输出: RobotIO (硬件预留)
    node.step() -> IntactOutput                    # 一步: obs → 零搜索 action chunk → 下发

内部封装: IntactRuntime(子进程桥) + 观测滑窗 + 动作历史(raw 零 reset 语义) + 诊断统计。
"""
from __future__ import annotations

import time

import numpy as np

from .contracts import (DEFAULT_FEATURE_LAYOUT, HISTORY_SIZE, IntactInput, IntactOutput,
                        build_info_dict, zero_action_history)
from .data_source import IntactDataSource, registry
from .model_adapter import IntactRuntime
from .robot_io import RobotIO, SimRobotIO

NODE_NAME = "🧠 INTACT 意图-动作"
NODE_LAYER = "L4"


class IntactNode:
    """INTACT 意图-动作节点 (L4)。"""

    name = NODE_NAME
    layer = NODE_LAYER

    def __init__(self, horizon: int = 8, action_dim: int = 4,
                 intent_mode: str = "goal_displacement", policy: str = "direct",
                 feature_layout: str = DEFAULT_FEATURE_LAYOUT,
                 runtime: IntactRuntime | None = None, repo: str | None = None,
                 log=print) -> None:
        self.horizon = int(horizon)
        self.action_dim = int(action_dim)
        self.intent_mode = intent_mode
        self.feature_layout = feature_layout
        self.policy = policy
        self.log = log
        self.runtime = runtime or IntactRuntime(repo=repo, policy=policy)
        # 单步前置: 真模型的动作维/上下文长度以 runtime 实测为准 (paper pusht 模型 action_dim=10,
        # 而节点默认 4 → 动作历史维度不符会直接报错; 这里自动对齐, 保证"单步"可跑)
        self._sync_from_runtime()
        self.source: IntactDataSource | None = None
        self.goal: np.ndarray | None = None
        self.waypoint: np.ndarray | None = None
        self.robot: RobotIO = SimRobotIO()
        self.reset()
        self.log(f"{NODE_NAME}: 数据源={type(self.source).__name__ if self.source else '未设置'} · "
                 f"策略={policy}(零搜索) · action_dim={self.action_dim} · horizon={self.horizon} · "
                 f"trained={self.runtime.trained}")

    # ── 接口 1: 数据源层 ──
    def _sync_from_runtime(self) -> None:
        """把 runtime 实测维数同步到节点 (单步要用真实维度构造动作历史)。"""
        d = getattr(self.runtime, "dims", None) or {}
        ad = int(d.get("action_dim") or 0)
        if ad and ad != self.action_dim:
            self.log(f"{NODE_NAME}: 动作维对齐 {self.action_dim} → {ad} (来自模型实测)")
            self.action_dim = ad
        hs = int(d.get("history_size") or 0)
        if hs:
            self.hist_size = hs
        else:
            self.hist_size = HISTORY_SIZE

    def set_data_source(self, src: str | IntactDataSource, **kw) -> IntactDataSource:
        self.source = registry.create(src, **kw) if isinstance(src, str) else src
        self.log(f"{NODE_NAME}: 数据源 = {self.source.name} {self.source.info()}")
        return self.source

    # ── 接口 2: 目标意图 ──
    def set_goal(self, goal: np.ndarray | None = None, waypoint: np.ndarray | None = None) -> None:
        self.goal = None if goal is None else np.asarray(goal, dtype=np.float32)
        self.waypoint = None if waypoint is None else np.asarray(waypoint, dtype=np.float32)
        self.intent_mode = "waypoint" if waypoint is not None else "goal_displacement"

    # ── 接口 3: 机器人输出 (硬件预留) ──
    def attach_robot(self, io: RobotIO) -> None:
        self.robot = io
        self.log(f"{NODE_NAME}: 输出 → {io.name} {io.capabilities()}")

    # ── 状态 ──
    def reset(self) -> None:
        self.obs_buf: list[np.ndarray] = []
        self.action_hist = zero_action_history(HISTORY_SIZE, self.action_dim)   # raw 零 (官方语义)
        self.n_steps = 0
        self.last: IntactOutput | None = None
        self.stats = {"n": 0, "t_ms": [], "intent_norm": [], "terminal_latent_error": [],
                      "forward_calls": [], "candidate_sequences": [],
                      "latent_norm": [], "latent_dim": [], "obs_source": []}
        if self.source is not None:
            self.source.reset()
        if self.robot is not None:
            self.robot.reset()

    # ── 接口 4: 一步 ──
    def step(self, obs_frame: np.ndarray | None = None,
             obs_source: str | None = None) -> IntactOutput:
        """obs_frame=None → 从数据源取; 否则用给定帧构造输入。

        单步语义: 一次调用 = **一次真实前向** (obs 滑窗 → 模型 get_action → action chunk),
        无候选搜索; 断点可进 (runtime.get_action → 子进程桥 → 模型 forward)。

        obs_source: 观测来源标注 (Step 0 真实性红线) —— 传 obs_frame 时默认 "engine_render"
        (引擎真实渲染帧); 从数据源取时取数据源自报的 obs_mode (如 synthetic_from_trace = 合成)。
        输出里逐帧带上, 面板/报告必须显示, 禁止拿合成观测冒充真实相机图。
        """
        t0 = time.perf_counter()
        self._sync_from_runtime()          # 懒启动的 runtime 首步也会补上真实维数
        if obs_frame is None:
            if self.source is None:
                raise RuntimeError("未设置数据源 (set_data_source)")
            inp = self.source.next_input(action_dim=self.action_dim, seq_len=HISTORY_SIZE)
            # ★ 动作历史由**节点**持有并滚动 (数据源每次给的是 raw 零 = reset 语义);
            #   不注入的话每步都看到零历史 → 输出不随动作历史变化 (实测踩坑)
            inp.action_history = self.action_hist.copy()
            _osrc = obs_source or str((self.source.info() or {}).get("obs_mode") or "source")
        else:
            _osrc = obs_source or "engine_render"
            fr = np.asarray(obs_frame, dtype=np.float32)
            self.obs_buf.append(fr)
            self.obs_buf = self.obs_buf[-HISTORY_SIZE:]
            while len(self.obs_buf) < HISTORY_SIZE:                # 冷启动用首帧填充
                self.obs_buf.insert(0, self.obs_buf[0])
            inp = IntactInput(pixels=np.stack(self.obs_buf, axis=0), goal=self.goal,
                              waypoint=self.waypoint, action_history=self.action_hist)

        info = build_info_dict(inp, intent_mode=self.intent_mode)
        actions, diag = self.runtime.get_action(info, horizon=self.horizon)
        # ★ 防"假成功"硬闸: adapter 在 act 失败时会返回零动作并标 act_failed/trained=0,
        #   这里必须显式报错 —— 否则"形状对+全零"会被当成成功 (实测踩坑: 零回退冒充真推理)
        if float(diag.get("act_failed") or 0.0) > 0 or float(diag.get("trained", 1.0)) == 0.0:
            self.last = None
            raise RuntimeError(f"INTACT 推理失败/未训练, 拒绝返回零动作: {self.runtime.reason}")
        # 模型返回可能带 batch 维 [1,H,D] → 统一成 [H,D] (节点对外契约)
        actions = np.asarray(actions, dtype=np.float32)
        if actions.ndim == 3:
            actions = actions[0]
        elif actions.ndim == 1:
            actions = actions[None]
        self.robot.send_chunk(actions)                              # 唯一硬件出口
        # 动作历史滚动 (重置语义: 初始 raw 零, 之后为真实下发动作)
        self.action_hist = np.concatenate([self.action_hist, actions], axis=0)[-HISTORY_SIZE:]
        self.n_steps += 1

        out = IntactOutput(chunk=actions, horizon=self.horizon, action_dim=self.action_dim,
                           diagnostics=diag, policy=self.policy,
                           trained=bool(self.runtime.trained),
                           source=(self.source.name if self.source else ""),
                           latent=(getattr(self.runtime, "last_latent", None) or None),
                           obs_source=_osrc)
        self.last = out
        dt = (time.perf_counter() - t0) * 1000.0
        self.stats["n"] += 1
        self.stats["t_ms"].append(dt)
        self.stats["obs_source"] = [_osrc]
        for k in ("intent_norm", "terminal_latent_error", "forward_calls", "candidate_sequences",
                  "latent_norm", "latent_dim"):
            if k in diag:
                self.stats[k].append(float(diag[k]))
        return out

    # ── 诊断/描述 (画布节点面板 + 引擎 io 通道用) ──
    def diagnostics(self) -> dict:
        s = self.stats
        mean = lambda v: (sum(v) / len(v)) if v else 0.0        # noqa: E731
        return {
            "steps": s["n"], "latency_ms": round(mean(s["t_ms"]), 2),
            "intent_norm": round(mean(s["intent_norm"]), 4),
            "terminal_latent_error": round(mean(s["terminal_latent_error"]), 4),
            "forward_calls": round(mean(s["forward_calls"]), 2),
            "candidate_sequences": round(mean(s["candidate_sequences"]), 2),
            "trained": bool(self.runtime.trained), "policy": self.policy,
            # ── Step 0: 潜空间 + 观测来源 (真实性溯源) ──
            "latent_dim": int(mean(s["latent_dim"])), "latent_norm": round(mean(s["latent_norm"]), 4),
            "latent_exported": bool(s["latent_norm"]), "obs_source": (s["obs_source"] or [""])[0],
        }

    def describe(self) -> dict:
        return {"node": self.name, "layer": self.layer, "policy": self.policy,
                "intent_mode": self.intent_mode, "horizon": self.horizon,
                "action_dim": self.action_dim, "feature_layout": self.feature_layout,
                "feature_grammar": "[z, m_t, z*m_t, A(a_{t-1})]",
                "source": (self.source.info() if self.source else None),
                "robot": self.robot.capabilities(), "runtime": self.runtime.info(),
                "diagnostics": self.diagnostics()}

    def close(self) -> None:
        try:
            self.runtime.close()
        except Exception:
            pass
