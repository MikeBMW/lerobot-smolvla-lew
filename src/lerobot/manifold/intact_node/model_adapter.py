# -*- coding: utf-8 -*-
"""🧠 模型适配层 (intact_node.model_adapter) — 节点 ↔ INTACT-JEPA (跨 venv 子进程桥)。

设计理由: INTACT 依赖 (stable_worldmodel / stable_pretraining / hydra) 只装在其自身 .venv,
与本工程 venv 不兼容 → **常驻子进程 + 行式 JSON 协议** (tools/intact_worker.py)。
节点侧只见 `get_action(info)` → `(actions, diagnostics)`; 不依赖任何 INTACT 内部符号。

诚实标注: 依赖/权重缺失 → `trained=False` + `reason`, `get_action` 返回**零动作** (不许假动作)。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading

import numpy as np

DEFAULT_REPO = os.environ.get("INTACT_REPO", "/home/ubuntu/INTACT-JEPA")


class IntactRuntime:
    """INTACT 推理运行时 (子进程桥; 断点可进本类方法)。"""

    def __init__(self, repo: str | None = None, venv_python: str | None = None,
                 ckpt: str | None = None, task: str = "pusht",
                 hf_repo: str = "INTACT-JEPA/INTACT", hf_rev: str = "paper-e5-goal-v1",
                 device: str = "cuda", policy: str = "direct", autostart: bool = True):
        self.repo = repo or DEFAULT_REPO
        self.venv_python = venv_python or os.path.join(self.repo, ".venv", "bin", "python")
        self.ckpt, self.task = ckpt, task
        self.hf_repo, self.hf_rev = hf_repo, hf_rev
        self.device, self.policy = device, policy
        self.proc: subprocess.Popen | None = None
        self.trained = False
        self.reason: str | None = None
        self.dims: dict = {}
        self._lock = threading.Lock()
        if autostart:
            self.start()

    # ── 可用性 (不启动进程, 只做静态检查) ──
    def available(self) -> tuple[bool, str]:
        if not os.path.isdir(self.repo):
            return False, f"INTACT 仓库不存在: {self.repo}"
        if not os.path.isfile(self.venv_python):
            return False, f"INTACT venv 不存在: {self.venv_python} (先 bash scripts/install.sh cu124)"
        return True, "ok"

    # ── 启动 + 握手 ──
    def start(self) -> bool:
        ok, why = self.available()
        if not ok:
            self.reason = why
            return False
        # 找本工程根 (含 reports/ 或 tools/intact_worker.py)
        d = os.path.dirname(os.path.abspath(__file__))
        while d != os.path.dirname(d) and not os.path.isfile(os.path.join(d, "tools", "intact_worker.py")):
            d = os.path.dirname(d)
        script = os.path.join(d, "tools", "intact_worker.py")
        if not os.path.isfile(script):
            script = "/home/ubuntu/lerobot-smolvla-lew/tools/intact_worker.py"
        cmd = [self.venv_python, script, "--repo", self.repo, "--task", self.task,
               "--hf-repo", self.hf_repo, "--hf-rev", self.hf_rev,
               "--device", self.device, "--policy", self.policy]
        if self.ckpt:
            cmd += ["--ckpt", self.ckpt]
        env = {**os.environ, "PYTHONUNBUFFERED": "1",
               "STABLEWM_HOME": os.environ.get("STABLEWM_HOME", os.path.join(self.repo, ".cache")),
               "LOCAL_DATASET_DIR": os.environ.get("LOCAL_DATASET_DIR", os.path.join(self.repo, ".cache")),
               "MUJOCO_GL": os.environ.get("MUJOCO_GL", "egl")}
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        except Exception as e:
            self.reason = f"worker 启动失败: {type(e).__name__}: {e}"
            return False
        resp = self._rpc({"cmd": "hello"}, timeout=1800)     # 首次含 HF 下载 + 权重加载
        if not resp.get("ok"):
            self.reason = resp.get("reason") or "worker hello 失败"
            return False
        self.trained = bool(resp.get("trained"))
        self.reason = resp.get("reason")
        self.dims = resp.get("dims") or {}
        return True

    # ── 协议收发 ──
    def _rpc(self, req: dict, timeout: float = 600.0) -> dict:
        if self.proc is None or self.proc.poll() is not None:
            return {"ok": False, "reason": self.reason or "worker 未运行"}
        with self._lock:
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                return {"ok": False, "reason": f"写 worker 失败: {e}"}
            line = self.proc.stdout.readline()
        if not line:
            return {"ok": False, "reason": "worker 无响应 (可能崩溃, 见 stderr/日志)"}
        try:
            return json.loads(line)
        except Exception as e:
            return {"ok": False, "reason": f"worker 返回非 JSON: {e}: {line[:200]}"}

    # ── 推理: info(dict of np/torch) → action chunk ──
    def get_action(self, info: dict, horizon: int = 8) -> tuple[np.ndarray, dict]:
        if not self.trained:
            if self.proc is None:
                self.start()
            if not self.trained:                     # 仍不可用 → 零动作 (诚实)
                d = self.dims.get("action_dim") or 4
                return (np.zeros((int(horizon), int(d)), dtype=np.float32),
                        {"trained": 0.0, "reason_zero_action": 1.0})
        with tempfile.TemporaryDirectory() as td:
            fin, fout = os.path.join(td, "in.npz"), os.path.join(td, "out.npz")
            arrs = {}
            for k, v in info.items():
                if hasattr(v, "detach"):
                    v = v.detach().cpu().numpy()
                arrs[k] = np.asarray(v)
            np.savez(fin, **arrs)
            resp = self._rpc({"cmd": "act", "in": fin, "out": fout, "horizon": int(horizon)})
            if not resp.get("ok"):
                self.reason = resp.get("reason") or "act 失败"
                d = self.dims.get("action_dim") or 4
                return (np.zeros((int(horizon), int(d)), dtype=np.float32),
                        {"trained": 0.0, "act_failed": 1.0})
            actions = np.load(fout)["actions"]
            return actions, {**dict(resp.get("diagnostics") or {}), "trained": 1.0}

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                self._rpc({"cmd": "bye"}, timeout=5)
            except Exception:
                pass
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None

    def info(self) -> dict:
        return {"repo": self.repo, "trained": self.trained, "reason": self.reason,
                "dims": self.dims, "policy": self.policy, "ckpt": self.ckpt,
                "worker_alive": bool(self.proc is not None and self.proc.poll() is None)}
