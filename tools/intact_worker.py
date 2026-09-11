#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""🧠 INTACT 常驻 worker (在 INTACT-JEPA 自己的 venv 里跑) — 节点的"外部世界"桥。

为什么要 worker: INTACT 依赖 stable_worldmodel/stable_pretraining/hydra 等, 与 GUI 工程的
venv 不兼容 → 用**子进程 + 行式 JSON 协议**封装, 节点侧只认协议, 不认实现。

协议 (stdin/stdout 每行一个 JSON):
  → {"cmd":"hello"}
  ← {"ok":true,"trained":bool,"dims":{...},"repo":...,"ckpt":...,"reason":...}
  → {"cmd":"act","in":"/tmp/x_in.npz","out":"/tmp/x_out.npz","horizon":8}
  ← {"ok":true,"out":"/tmp/x_out.npz","diagnostics":{...}}       # actions 写 npz(key=actions)
  → {"cmd":"reset"} / {"cmd":"bye"}

诚实原则: 依赖/权重缺失时**必须**回 ok=false + reason, 绝不返回假动作。

用法 (调试):
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_worker.py --repo /home/ubuntu/INTACT-JEPA
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback


def log(*a):
    print("[intact-worker]", *a, file=sys.stderr, flush=True)


_PROTO = None


def say(obj: dict) -> None:
    """把 JSON 写到私有协议口 (stdout 副本), 不与其他库的输出混流。"""
    import json as _j
    ( _PROTO or sys.stdout ).write(_j.dumps(obj) + "\n")
    ( _PROTO or sys.stdout ).flush()


class Runtime:
    """封装 INTACT 模型加载与推理 (官方代码路径, 不重写算法)。"""

    def __init__(self, repo: str, ckpt: str | None, task: str, hf_repo: str, hf_rev: str,
                 device: str = "cuda", policy: str = "direct", policy_name: str | None = None,
                 runtime_kind: str | None = None):
        self.repo = os.path.abspath(repo)
        self.ckpt = ckpt
        self.task = task
        self.hf_repo, self.hf_rev = hf_repo, hf_rev
        self.device = device
        self.policy = policy
        # 论文 revision 的规范训练 seed (manifest: 0 / 42 / 3072); 资产包名含 seed
        self.hf_rev_seed = int(os.environ.get("INTACT_SEED", "3072"))
        # 官方 load_pretrained 用的 policy 名 = 缓存 checkpoints/ 下的权重目录名
        self.policy_name = policy_name or os.environ.get(
            "INTACT_POLICY", f"recovery_delta_full_{task}_s{self.hf_rev_seed}")
        # 运行时选择: paper = 官方 paper_runtime (论文权重专用, 参数字布局不同);
        # root = 根运行时 (本仓库自己训练的 checkpoint)。论文 revision 默认 paper。
        self.runtime_kind = runtime_kind or os.environ.get(
            "INTACT_RUNTIME", "paper" if str(hf_rev).startswith("paper-") else "root")
        self.model = None
        self.solver = None
        self.trained = False
        self.reason = None
        self.dims: dict = {}

    # ── 加载 (官方路径: hydra instantiate + load_state_dict(strict=True) / load_pretrained) ──
    def load(self) -> None:
        sys.path.insert(0, self.repo)
        if self.runtime_kind == "paper":
            # 论文运行时优先 (其 jepa/module 里才有 InverseTransitionActor, 根运行时参数布局不同)
            pr = os.path.join(self.repo, "paper_runtime")
            sys.path.insert(0, pr)
            os.chdir(pr)
            try:
                import sitecustomize          # noqa: F401,PLC0415  确定性 Math-SDPA + CUBLAS_WORKSPACE_CONFIG
                log("paper_runtime 已加载 (sitecustomize 确定性 Math-SDPA)")
            except Exception as e:
                log("⚠️ sitecustomize 未加载:", type(e).__name__, e)
        else:
            os.chdir(self.repo)
        try:
            import torch                                     # noqa: PLC0415
            import hydra                                      # noqa: F401,PLC0415
            from omegaconf import OmegaConf                   # noqa: PLC0415
            import stable_worldmodel as swm                   # noqa: PLC0415
        except Exception as e:                                # 依赖没装好
            self.reason = f"依赖缺失: {type(e).__name__}: {e}"
            log(self.reason)
            return

        # 1) 权重: 显式路径 → 已解出的 swm 缓存 → HF 资产包 (tar.gz) 解包
        ckpt_path = self._resolve_weights()
        if not ckpt_path:
            log(self.reason)
            return

        # 2) 模型: 官方加载路径 (与仓库 eval.py:135 完全一致) ——
        #    swm.wm.utils.load_pretrained(<policy 名/路径>) → eval() → interpolate_pos_encoding=True
        #    → set_actor_warmstart(True) (Direct 需要 actor 参与, 否则 get_action 返回零)
        try:
            import stable_worldmodel as swm                  # noqa: PLC0415
            import torch                                     # noqa: PLC0415
            policy = os.environ.get("INTACT_POLICY", self.policy_name)
            model = swm.wm.utils.load_pretrained(policy)
            model = model.to(self.device)
            model = model.eval()
            model.requires_grad_(False)
            model.interpolate_pos_encoding = True
            if hasattr(model, "set_actor_warmstart"):
                model.set_actor_warmstart(True)
            elif hasattr(model, "actor_warmstart"):
                model.actor_warmstart = True
            self.model = model
            self.dims = {"embed_dim": int(getattr(model, "embed_dim", 0) or 0),
                         "action_dim": int(model.get_action_dim(None) or 0),
                         "history_size": int(model.predictor.pos_embedding.size(1)),
                         "img_size": 224}
            self.trained = True
            log(f"模型就绪 (官方 load_pretrained): policy={policy} "
                f"action_dim={self.dims['action_dim']} history={self.dims['history_size']}")
        except Exception as e:
            self.reason = (f"模型构建/加载失败: {type(e).__name__}: {e} "
                           f"(官方路径: swm.wm.utils.load_pretrained(policy) + set_actor_warmstart(True), "
                           f"见仓库 eval.py:135-146)")
            log(self.reason)
            log(traceback.format_exc(limit=3))

    def _cache_root(self) -> str:
        return os.environ.get("STABLEWM_HOME") or os.environ.get("LOCAL_DATASET_DIR") \
            or os.path.join(self.repo, ".cache")

    def _resolve_weights(self) -> str | None:
        """权重解析 (跨会话共用同一缓存, 不重复下载):
           1) --ckpt / $INTACT_WEIGHTS  (显式)
           2) $STABLEWM_HOME/checkpoints/recovery_delta_full_<task>_s<seed>/weights_epoch_5.pt (已解包)
           3) HF 资产包 intact-goal-e5-seed<seed>.tar.gz → 下载+解包 → 回到 (2)
        真实布局依据 checkpoints/PAPER_E5_GOAL_MANIFEST.json + HF 仓库树实测 (tar.gz ~315MB/包)。
        """
        expl = self.ckpt or os.environ.get("INTACT_WEIGHTS")
        if expl and os.path.isfile(expl):
            log("权重 (显式):", expl)
            return expl
        seed = self.hf_rev_seed
        wpath = os.path.join(self._cache_root(), "checkpoints",
                             f"recovery_delta_full_{self.task}_s{seed}", "weights_epoch_5.pt")
        if os.path.isfile(wpath):
            log("权重 (缓存):", wpath)
            return wpath
        try:
            from huggingface_hub import hf_hub_download      # noqa: PLC0415
            # 国内网络: 未显式设 HF_ENDPOINT 时走 hf-mirror (与另一会话下载数据同一镜像)
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            asset = os.environ.get("INTACT_ASSET", f"intact-goal-e5-seed{seed}.tar.gz")
            pkg = hf_hub_download(repo_id=self.hf_repo, revision=self.hf_rev,
                                  filename=asset, repo_type="model")
            log("资产包:", pkg, "→ 解包到", self._cache_root())
            import tarfile                                    # noqa: PLC0415
            with tarfile.open(pkg) as tf:
                tf.extractall(self._cache_root())
        except Exception as e:
            self.reason = (f"权重不可用: {type(e).__name__}: {e} "
                           f"(可用 INTACT_WEIGHTS=/path/weights_epoch_5.pt 直指, 或先解包 "
                           f"HF {self.hf_repo}@{self.hf_rev} 的 intact-goal-e5-seed{seed}.tar.gz "
                           f"到 $STABLEWM_HOME/checkpoints/)")
            return None
        if os.path.isfile(wpath):
            return wpath
        self.reason = f"解包后仍找不到 {wpath} (检查资产包内路径)"
        return None

    def act(self, info_path: str, out_path: str, horizon: int) -> dict:
        import numpy as np                                    # noqa: PLC0415
        import torch                                          # noqa: PLC0415
        if not self.trained:
            raise RuntimeError(self.reason or "模型未就绪")
        d = np.load(info_path, allow_pickle=True)
        info = {k: torch.from_numpy(d[k]).to(self.device) for k in d.files
                if d[k].dtype != object}
        with torch.inference_mode():
            actions = self.model.get_action(info, horizon=int(horizon))
        actions = actions.detach().cpu().numpy()
        np.savez(out_path, actions=actions)
        diag = {k: float(v) for k, v in
                (getattr(self.model, "last_direct_diagnostics", {}) or {}).items()
                if isinstance(v, (int, float))}
        if not diag:
            # 论文运行时(PriorOnlySolver 路径)不暴露逐次诊断 → 用 **worker 侧真实计数**补充,
            # 并显式标注来源 (forward_calls = 零搜索直接规划的 horizon 次前向; 无候选搜索)
            diag = {"forward_calls": float(horizon), "candidate_sequences": 0.0,
                    "diag_source_worker": 1.0}
        return {"out": out_path, "diagnostics": diag, "shape": list(actions.shape)}

    def info(self) -> dict:
        return {"trained": bool(self.trained), "reason": self.reason, "dims": self.dims,
                "repo": self.repo, "ckpt": self.ckpt, "policy": self.policy,
                "task": self.task, "hf": f"{self.hf_repo}@{self.hf_rev}"}


def main() -> int:
    # ── 协议通道隔离 (必须最先做): 库日志 (loguru/JAX/httpx 等) 会往 stdout 打,
    #    污染行式 JSON → 节点侧解析失败。做法: 复制真 stdout 作私有协议口, 再把
    #    sys.stdout 指到 stderr —— 之后所有库输出进 stderr, JSON 只走协议口。
    global _PROTO
    _PROTO = os.fdopen(os.dup(1), "w", buffering=1)
    sys.stdout = sys.stderr

    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("INTACT_REPO", "/home/ubuntu/INTACT-JEPA"))
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--task", default="pusht")
    ap.add_argument("--hf-repo", default="INTACT-JEPA/INTACT")
    ap.add_argument("--hf-rev", default="paper-e5-goal-v1")
    ap.add_argument("--device", default=os.environ.get("INTACT_DEVICE", "cuda"))
    ap.add_argument("--policy", default="direct")
    ap.add_argument("--policy-name", default=None,
                    help="官方 load_pretrained 的 policy 名 (默认 recovery_delta_full_<task>_s<seed>)")
    ap.add_argument("--runtime", default=None, choices=[None, "root", "paper"],
                    help="论文权重必须 paper (官方 paper_runtime; 根运行时布局不同)")
    a = ap.parse_args()

    rt = Runtime(a.repo, a.ckpt, a.task, a.hf_repo, a.hf_rev, a.device, a.policy,
                 a.policy_name, a.runtime)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            say({"ok": False, "reason": "bad json"})
            continue
        cmd = req.get("cmd")
        try:
            if cmd == "hello":
                if rt.model is None and not rt.trained:
                    rt.load()                      # 懒加载 (hello 时完成)
                say({"ok": True, **rt.info()})
            elif cmd == "act":
                r = rt.act(req["in"], req["out"], int(req.get("horizon", 8)))
                say({"ok": True, **r})
            elif cmd == "reset":
                say({"ok": True})
            elif cmd in ("bye", "exit"):
                say({"ok": True})
                return 0
            else:
                say({"ok": False, "reason": f"unknown cmd {cmd}"})
        except Exception as e:
            # ★ 把 traceback 尾部带回 reason: adapter 侧 stderr 被丢弃, 不带回就无法定位
            tb = traceback.format_exc().strip().splitlines()[-4:]
            say({"ok": False, "reason": f"{type(e).__name__}: {e} | " + " ⏎ ".join(x.strip() for x in tb)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
