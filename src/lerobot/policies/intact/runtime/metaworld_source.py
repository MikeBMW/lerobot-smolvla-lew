# -*- coding: utf-8 -*-
"""📥 metaworld 数据源 (数据源直接接入 metaworld) — INTACT 节点的输入侧。

老倪 2026-09-13: "数据源直接接入metaworld"。
本数据源 = 真 metaworld 环境 (peg-insert-side-v3, 与引擎 RealStateSpaceSim **同一构造**),
逐帧取:
  · 观测 ad:env.render() 真渲染帧 → 224² RGB → [T,C,H,W]
  · 状态   : env._get_obs()[:39]  (与引擎 training 侧同口径 39D)
  · goal   : 本域真实目标帧 (默认 reports/intact_goal_frame_optical.npy, v5.5.37 从解析链末帧取得)
  · 动作历史: 由节点持有并滚动 (数据源给 raw 零 = reset 语义, 与官方一致)

诚实标注: obs_mode='metaworld_render' (真渲染, 非合成)。env 跨进程几何漂移 >10cm
(技能 eval 铁律) → 现场从 MuJoCo data 读几何, 不写死常量。
"""
from __future__ import annotations

import os

import numpy as np

from .contracts import HISTORY_SIZE, IMG_SIZE, IntactInput, zero_action_history
from .data_source import IntactDataSource

TASK = "peg-insert-side-v3"
CAMERA = "corner2"


def _repo_root() -> str:
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "reports")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


class MetaWorldSource(IntactDataSource):
    """真 metaworld 环境数据源 (插拔任务)。"""

    name = "metaworld"

    def __init__(self, task: str = TASK, seed: int = 0, img: int = IMG_SIZE,
                 goal_frame: str | None = None, max_steps: int = 1200,
                 use_yolo_state: bool = False) -> None:
        self.task = task
        self.seed = int(seed)
        self.img = int(img)
        self.max_steps = int(max_steps)
        self.use_yolo_state = bool(use_yolo_state)
        self.n_steps = 0
        self.obs_mode = "metaworld_render"
        self._env = None
        self._frames: list[np.ndarray] = []          # 滚动渲染帧 [C,H,W] float32 0..255
        self._states: list[np.ndarray] = []          # 39D
        self.goal_frame_path = goal_frame or os.path.join(
            _repo_root(), "reports", "intact_goal_frame_optical.npy")
        self._goal = self._load_goal()

    # ── 环境 (懒建, 与引擎同构造) ──
    def env(self):
        if self._env is None:
            import metaworld as _mt                                # noqa: PLC0415
            mt = _mt.MT1(self.task)
            e = mt.train_classes[self.task](render_mode="rgb_array", camera_name=CAMERA)
            e.set_task(mt.train_tasks[0])                          # MT1 单任务
            o, _ = e.reset(seed=self.seed)
            self._env = e
            self._bootstrap(np.asarray(o, dtype=np.float64).ravel())
        return self._env

    def _bootstrap(self, obs39: np.ndarray) -> None:
        """首帧灌入: 让节点第一步就有 HISTORY_SIZE 帧可用 (不会时序错位)。"""
        fr = self._render()
        for _ in range(HISTORY_SIZE):
            self._states.append(np.asarray(obs39[:39], dtype=np.float32))
            self._frames.append(fr.copy())

    def _render(self) -> np.ndarray:
        import cv2                                                     # noqa: PLC0415
        e = self._env
        try:
            raw = np.asarray(e.render())
        except Exception:
            raw = np.zeros((480, 480, 3), np.uint8)
        small = cv2.resize(raw, (self.img, self.img), interpolation=cv2.INTER_AREA)
        return np.transpose(small.astype(np.float32), (2, 0, 1))       # [C,H,W] 0..255

    def _load_goal(self) -> np.ndarray | None:
        """本域真实目标帧 (解析链末帧 = 任务完成态)。缺失 → None, 由调用方 set_goal。"""
        try:
            g = np.load(self.goal_frame_path)
            g = np.asarray(g, dtype=np.float32)
            if g.ndim == 3 and g.shape[0] in (1, 3, 4):                # CHW
                return g
            if g.ndim == 3:                                            # HWC → CHW
                return np.transpose(g, (2, 0, 1))
        except Exception:
            return None
        return None

    @property
    def goal(self) -> np.ndarray | None:
        return self._goal

    # ── 闭环推进 (模型动作真下发) ──
    def step_action(self, act4: np.ndarray) -> np.ndarray:
        """把 4D 动作 (±1) 真下发 env.step, 返回新 39D 状态 (闭环)。"""
        e = self.env()
        a = np.asarray(act4, dtype=np.float64).ravel()[:4]
        a = np.clip(a, -1.0, 1.0)
        o, _r, term, trunc, _i = e.step(np.concatenate([a[:3], a[3:4]]))
        self.n_steps += 1
        st = np.asarray(o, dtype=np.float64).ravel()[:39]
        self._states.append(st.astype(np.float32))
        self._frames.append(self._render())
        self._frames = self._frames[-HISTORY_SIZE:]
        self._states = self._states[-HISTORY_SIZE:]
        if term or trunc:
            self.reset()
        return st

    def current_state(self) -> np.ndarray | None:
        return self._states[-1] if self._states else None

    # ── 节点接口 ──
    def next_input(self, action_dim: int = 4, seq_len: int | None = None) -> IntactInput:
        seq_len = int(seq_len or HISTORY_SIZE)
        self.env()                                                     # 确保已 reset + 首帧
        px = np.stack(self._frames[-seq_len:], axis=0) if self._frames else None
        if px is None or px.shape[0] < seq_len:                        # 冷启动补齐
            px = np.stack([self._frames[-1]] * seq_len, axis=0)
        return IntactInput(pixels=px, goal=self._goal,
                           action_history=zero_action_history(seq_len, action_dim))

    def reset(self) -> None:
        self.n_steps = 0
        self._frames, self._states = [], []
        if self._env is not None:
            o, _ = self._env.reset()          # ⚠️ metaworld reset(seed=) 会被忽略 (引擎同款实测)
            self._bootstrap(np.asarray(o, dtype=np.float64).ravel())

    def info(self) -> dict:
        return {"source": self.name, "task": self.task, "env": f"MT1({self.task})",
                "camera": CAMERA, "state_dim": 39, "action_dim": 4,
                "img": self.img, "obs_mode": self.obs_mode,
                "goal_frame": (os.path.basename(self.goal_frame_path)
                               if self._goal is not None else None),
                "steps": self.n_steps}

    def close(self) -> None:
        try:
            if self._env is not None:
                self._env.close()
        except Exception:
            pass
        self._env = None
