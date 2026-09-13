# -*- coding: utf-8 -*-
"""📥 数据源层扩展 (intact_node.data_source) — 节点输入侧, 数据可再下载。

注册表用法:
    from lerobot.manifold.intact_node.data_source import registry
    registry.register("l4_episode", lambda **kw: L4EpisodeSource(**kw))
    src = registry.create("l4_episode", path="reports/l4_demo_x.npz")

内置数据源:
  · official — INTACT/LeWM 官方数据 (需先 download_intact_dataset 下载)
  · l4_episode — 我们自己的 L4 演示 episode (reports/l4_demo_*.npz)
  · (预留) 真机相机流 — 实现 next_input() 即可注册
"""
from __future__ import annotations

import abc
import glob
import os
from typing import Callable

import numpy as np

from .contracts import HISTORY_SIZE, IMG_SIZE, IntactInput, zero_action_history

# 官方数据集清单 (README: HuggingFace LeWM collection; 训练脚本**不会**隐式下载)
OFFICIAL_DATASETS = {
    "pusht": "pusht_expert_train.h5  (或 .lance, 由 convert 生成)",
    "cube": "ogbench/cube_single_expert.h5",
    "reacher": "reacher.h5",
    "tworoom": "tworoom.h5",
}


class IntactDataSource(abc.ABC):
    """节点输入侧接口: 数据源只需实现 next_input()。"""

    name = "abstract"

    @abc.abstractmethod
    def next_input(self, action_dim: int = 4, seq_len: int | None = None) -> IntactInput:
        """取一段输入 (含 obs 帧序列 [+goal])。seq_len 缺省 = HISTORY_SIZE。"""

    def reset(self) -> None:  # 可选
        pass

    def info(self) -> dict:
        return {"source": self.name}


class DataSourceRegistry:
    def __init__(self) -> None:
        self._f: dict[str, Callable[..., IntactDataSource]] = {}

    def register(self, name: str, factory: Callable[..., IntactDataSource]) -> None:
        self._f[name] = factory

    def create(self, name: str, **kw) -> IntactDataSource:
        if name not in self._f:
            raise KeyError(f"未注册的数据源 {name!r}; 已注册: {sorted(self._f)}")
        return self._f[name](**kw)

    def names(self) -> list[str]:
        return sorted(self._f)


registry = DataSourceRegistry()


class L4EpisodeSource(IntactDataSource):
    """我们自己的 L4 演示 episode → 节点输入。

    npz 里若有真实渲染帧 (`frames`) 就直接用; 否则从轨迹**合成**观测
    (obs_mode='synthetic_from_trace', 诚实标注: 不是相机图, 只用于链路自检)。
    """

    name = "l4_episode"

    def __init__(self, path: str | None = None, obs_mode: str = "auto",
                 goal_frame_index: int = -1, seed: int = 0) -> None:
        path = path or self._latest()
        self.path = path
        self.goal_idx = goal_frame_index
        self.rng = np.random.default_rng(seed)
        d = np.load(path, allow_pickle=True)
        self.trace = {k: d[k] for k in d.files}
        self.frames = self.trace.get("frames")
        # L4 demo npz 里只有 meta (object 数组, 长度 1) → 取出 dict 供合成观测用
        _m = self.trace.get("meta")
        if _m is not None and getattr(_m, "dtype", None) == object and _m.size == 1:
            _m = _m.reshape(-1)[0]
        self.meta = _m if isinstance(_m, dict) else {}
        self.n_anim_frames = int(os.environ.get("INTACT_ANIM_FRAMES", "24"))   # 合成观测推进帧数
        if obs_mode == "auto":
            obs_mode = "frames" if self.frames is not None and len(self.frames) else "synthetic_from_trace"
        self.obs_mode = obs_mode
        self.i = 0

    @staticmethod
    def _repo_root() -> str:
        """向上找含 reports/ 的仓库根 (比数 dirname 层数稳)。"""
        d = os.path.dirname(os.path.abspath(__file__))
        while d != os.path.dirname(d):
            if os.path.isdir(os.path.join(d, "reports")):
                return d
            d = os.path.dirname(d)
        return os.getcwd()

    @staticmethod
    def _latest() -> str:
        root = L4EpisodeSource._repo_root()
        cand = sorted(glob.glob(os.path.join(root, "reports", "l4_demo_*.npz")))
        if not cand:
            raise FileNotFoundError(f"{root}/reports/l4_demo_*.npz 不存在 — 先跑一次 L4 演示")
        return cand[-1]

    def _obs(self, k: int) -> np.ndarray:
        """取第 k 帧观测 [C,H,W]。合成模式 = 语义运动序列 (诚实标注: 非相机图)。"""
        if self.obs_mode == "frames":
            fr = np.asarray(self.frames[k], dtype=np.float32)
            if fr.max() > 1.5:
                fr = fr / 255.0
            return np.transpose(fr, (2, 0, 1))
        # ── 合成运动观测: 依据 meta 几何 (来料转台 → 耦合台) 画一个随时间推进的目标 ──
        #    目的: 让"单步"演示有真实的时间变化 (obs 变 → 动作 chunk 变), 证明每帧真推理
        geo = (self.meta.get("demo_geom") or {}) if isinstance(self.meta, dict) else {}
        tt = (geo.get("turntable") or {}).get("pos", [0.42, 0.60])
        cp = (geo.get("coupler") or {}).get("pos", [0.55, 0.42])
        u = min(1.0, max(0.0, k / max(1, self.n_anim_frames)))          # 进度 0→1
        px = tt[0] + (cp[0] - tt[0]) * u
        py = tt[1] + (cp[1] - tt[1]) * u

        def to_pix(x, y):
            xn = (float(x) - 0.25) / 0.60
            yn = (float(y) - 0.25) / 0.60
            return (int(np.clip(yn, 0, 1) * (IMG_SIZE - 1)),
                    int(np.clip(xn, 0, 1) * (IMG_SIZE - 1)))

        out = np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.float32)
        gy, gx = to_pix(*cp)                                            # 目标位 (耦合台)
        out[max(0, gy - 4):gy + 5, max(0, gx - 4):gx + 5] = 0.55
        my, mx = to_pix(px, py)                                         # 运动件 (光模块)
        out[max(0, my - 3):my + 4, max(0, mx - 3):mx + 4] = 1.0
        ty, tx = to_pix(*tt)                                            # 来料转台位
        out[max(0, ty - 2):ty + 3, max(0, tx - 2):tx + 3] = 0.3
        return np.stack([out * 0.6, out, out * 1.2], axis=0)

    def next_input(self, action_dim: int = 4, seq_len: int | None = None) -> IntactInput:
        seq_len = int(seq_len or HISTORY_SIZE)
        n = len(np.asarray(self.trace.get("hand", []))) or 1
        k = min(self.i, max(0, n - 1))
        idx = [min(k + j, n - 1) for j in range(seq_len)]
        pixels = np.stack([self._obs(j) for j in idx], axis=0)      # [T,C,H,W]
        goal = self._obs(min(k + self.goal_idx, n - 1)) if self.goal_idx is not None else None
        self.i += 1
        return IntactInput(pixels=pixels, goal=goal,
                           action_history=zero_action_history(seq_len, action_dim))

    def info(self) -> dict:
        return {"source": self.name, "path": os.path.basename(self.path),
                "obs_mode": self.obs_mode, "frames": int(len(self.frames)) if self.frames is not None else 0}


class OfficialIntactSource(IntactDataSource):
    """官方 INTACT/LeWM 数据 (pusht/cube/reacher/tworoom)。需先下载。"""

    name = "official"

    def __init__(self, task: str = "pusht", root: str | None = None, seed: int = 0) -> None:
        if task not in OFFICIAL_DATASETS:
            raise KeyError(f"未知任务 {task}; 可选 {sorted(OFFICIAL_DATASETS)}")
        self.task = task
        self.root = root or os.environ.get("LOCAL_DATASET_DIR", "")
        self.rng = np.random.default_rng(seed)
        self._h5 = None

    def _open(self):
        if self._h5 is None:
            import h5py                                    # noqa: PLC0415
            try:                                           # 官方数据用 HDF5 插件压缩
                import hdf5plugin                          # noqa: F401,PLC0415
            except ImportError:
                pass
            if not os.environ.get("HDF5_PLUGIN_PATH"):
                try:
                    import hdf5plugin as _hp          # noqa: PLC0415
                    os.environ.setdefault("HDF5_PLUGIN_PATH", _hp.PLUGIN_PATH)
                except ImportError:
                    pass
            rel = OFFICIAL_DATASETS[self.task].split()[0]
            p = os.path.join(self.root, "datasets", rel)
            if not os.path.isfile(p):
                raise FileNotFoundError(
                    f"官方数据缺失: {p} — 先 download_intact_dataset('{self.task}') 或按 README 放置")
            self._h5 = h5py.File(p, "r")
        return self._h5

    def next_input(self, action_dim: int = 4, seq_len: int | None = None) -> IntactInput:
        import torch  # noqa: F401  # 仅确认 torch 可用
        seq_len = int(seq_len or HISTORY_SIZE)
        f = self._open()
        # 官方 h5 结构: obs / action 两组 (LeWM 约定); 找不到就诚实报错, 不猜结构
        obs_key = next((k for k in f.keys() if "pixel" in k.lower()), None) \
            or next((k for k in f.keys() if "obs" in k.lower()), None)
        if obs_key is None:
            raise KeyError(f"{self.task}: h5 里找不到观测组, 键={list(f.keys())}")
        grp = f[obs_key]
        ep = int(self.rng.integers(len(grp)))
        if hasattr(grp, "keys"):                           # Group: 每 episode 一个 dataset
            _keys = list(grp.keys())
            _key = str(ep) if str(ep) in _keys else _keys[ep]
            arr = np.asarray(grp[_key], dtype=np.float32)
        elif {"ep_offset", "ep_len"} <= set(f.keys()):      # ★ 官方扁平存储
            _off = np.asarray(f["ep_offset"]); _len = np.asarray(f["ep_len"])
            _e = int(self.rng.integers(len(_len)))
            _o, _l = int(_off[_e]), int(_len[_e])
            arr = np.asarray(grp[_o:_o + _l], dtype=np.float32)   # [T,H,W,C]
        else:                                               # 单块 Dataset
            arr = np.asarray(grp[ep], dtype=np.float32)
        if arr.ndim != 4:                                  # [T,H,W,C] → [T,C,H,W]
            arr = np.moveaxis(arr, -1, 1)
        arr = arr / 255.0 if arr.max() > 1.5 else arr
        t = min(seq_len, arr.shape[0] - 1)
        pixels = arr[:t + 1]
        return IntactInput(pixels=pixels, goal=arr[-1],
                           action_history=zero_action_history(pixels.shape[0], action_dim))

    def info(self) -> dict:
        return {"source": self.name, "task": self.task, "root": self.root}


def download_intact_dataset(task: str = "pusht", dest: str | None = None) -> str:
    """下载官方数据到 dest (默认 $LOCAL_DATASET_DIR/datasets)。返回落盘路径。

    ⚠️ 官方源在 HuggingFace (LeWM collection)。国内网络按需设置 HF_ENDPOINT 镜像。
    """
    from huggingface_hub import hf_hub_download               # noqa: PLC0415
    dest = dest or os.path.join(os.environ.get("LOCAL_DATASET_DIR", "."), "datasets")
    os.makedirs(dest, exist_ok=True)
    rel = OFFICIAL_DATASETS[task].split()[0]
    repo, fn = ("quentinll/lewm", os.path.basename(rel)) if "/" not in rel else \
        ("quentinll/lewm", rel)
    src = hf_hub_download(repo_id=repo, filename=fn, repo_type="dataset",
                          local_dir=dest)
    print(f"✅ {task} → {src}")
    return src


registry.register("l4_episode", lambda **kw: L4EpisodeSource(**kw))
registry.register("official", lambda **kw: OfficialIntactSource(**kw))
