# 桥协议 + 最小可复用骨架

## 协议 (stdin/stdout 行式 JSON；stderr 只放日志)

| 方向 | 报文 |
|---|---|
| → worker | `{"cmd":"hello"}` |
| ← worker | `{"ok":true,"trained":bool,"dims":{...},"reason":null,"repo":"...","policy":"..."}` |
| → worker | `{"cmd":"act","in":"/tmp/x_in.npz","out":"/tmp/x_out.npz","horizon":8}` |
| ← worker | `{"ok":true,"out":"/tmp/x_out.npz","shape":[8,10],"diagnostics":{...}}` |
| → worker | `{"cmd":"reset"}` / `{"cmd":"bye"}` |
| ← worker (失败) | `{"ok":false,"reason":"<人类可读原因>"}` |

**大数组一律走临时 npz**（只传路径），不要塞进 JSON。

## 最小 worker 骨架 (跑在外部项目自己的 venv 里)

```python
#!/usr/bin/env python
"""<name>_worker.py — 外部 venv 里的常驻推理 worker (行式 JSON 协议)。"""
import argparse, json, os, sys

def log(*a): print("[worker]", *a, file=sys.stderr, flush=True)

_PROTO = None
def say(obj):
    (_PROTO or sys.stdout).write(json.dumps(obj) + "\n"); (_PROTO or sys.stdout).flush()

class Runtime:
    def __init__(self, repo, ckpt, device="cuda", runtime_kind="root"):
        self.repo, self.ckpt, self.device, self.runtime_kind = repo, ckpt, device, runtime_kind
        self.model, self.trained, self.reason, self.dims = None, False, None, {}

    def load(self):
        sys.path.insert(0, self.repo)
        if self.runtime_kind == "paper":                     # ★ 冻结运行时 (论文权重必须)
            pr = os.path.join(self.repo, "paper_runtime")
            sys.path.insert(0, pr); os.chdir(pr)
            try:
                import sitecustomize; log("paper_runtime sitecustomize 已加载")
            except Exception as e:
                log("⚠️ sitecustomize 未加载:", e)
        else:
            os.chdir(self.repo)
        try:
            import stable_worldmodel as swm                  # 官方包
            model = swm.wm.utils.load_pretrained(os.environ["POLICY"])   # ★ 官方加载路径
            self.model = model.to(self.device).eval()
            self.model.interpolate_pos_encoding = True
            self.model.set_actor_warmstart(True)             # Direct 必须开 actor
            self.dims = {"action_dim": int(self.model.get_action_dim(None) or 0)}
            self.trained = True
        except Exception as e:
            self.reason = f"{type(e).__name__}: {e}"          # ★ 诚实: 绝不返回假动作

    def act(self, fin, fout, horizon):                           # noqa: D102
        import numpy as np, torch
        if not self.trained:
            raise RuntimeError(self.reason or "模型未就绪")
        d = np.load(fin, allow_pickle=True)
        info = {k: torch.from_numpy(d[k]).to(self.device) for k in d.files if d[k].dtype != object}
        with torch.inference_mode():
            a = self.model.get_action(info, horizon=int(horizon))
        a = a.detach().cpu().numpy(); np.savez(fout, actions=a)
        diag = {k: float(v) for k, v in (getattr(self.model, "last_direct_diagnostics", {}) or {}).items()}
        return {"out": fout, "shape": list(a.shape), "diagnostics": diag}

def main() -> int:
    global _PROTO
    # ★★ 必须最先做: 库日志 (JAX/loguru/httpx) 会污染 stdout → 协议 JSON 解析失败
    _PROTO = os.fdopen(os.dup(1), "w", buffering=1)
    sys.stdout = sys.stderr

    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True); ap.add_argument("--ckpt", default=None)
    ap.add_argument("--device", default=os.environ.get("DEVICE", "cuda"))
    ap.add_argument("--runtime", default=None, choices=[None, "root", "paper"])
    a = ap.parse_args()
    rt = Runtime(a.repo, a.ckpt, a.device, a.runtime or os.environ.get("RUNTIME", "root"))

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except Exception:
            say({"ok": False, "reason": "bad json"}); continue
        cmd = req.get("cmd")
        try:
            if cmd == "hello":
                if rt.model is None:
                    rt.load()
                say({"ok": True, "trained": rt.trained, "reason": rt.reason, "dims": rt.dims})
            elif cmd == "act":
                say({"ok": True, **rt.act(req["in"], req["out"], req.get("horizon", 8))})
            elif cmd == "reset":
                say({"ok": True})
            elif cmd in ("bye", "exit"):
                say({"ok": True}); return 0
            else:
                say({"ok": False, "reason": f"unknown cmd {cmd}"})
        except Exception as e:
            say({"ok": False, "reason": f"{type(e).__name__}: {e}"})
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

## 最小 adapter 骨架 (节点侧，GUI venv)

```python
class Runtime:
    def start(self) -> bool:                      # 握手 (首次含下载+加载, 给足超时)
        cmd = [self.venv_python, SCRIPT, "--repo", self.repo, "--runtime", self.runtime_kind]
        self.proc = subprocess.Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=DEVNULL,
                                     text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"})
        r = self._rpc({"cmd": "hello"}, timeout=1800)
        self.trained, self.reason, self.dims = bool(r.get("trained")), r.get("reason"), r.get("dims") or {}
        return r.get("ok", False)

    def get_action(self, info, horizon=8):        # 不可用 → 零动作 + reason (诚实)
        if not self.trained and not self.start():
            d = self.dims.get("action_dim") or 4
            return np.zeros((horizon, d), np.float32), {"trained": 0.0}
        with tempfile.TemporaryDirectory() as td:
            fin, fout = os.path.join(td, "in.npz"), os.path.join(td, "out.npz")
            np.savez(fin, **{k: (v.detach().cpu().numpy() if hasattr(v, "detach") else np.asarray(v))
                             for k, v in info.items()})
            r = self._rpc({"cmd": "act", "in": fin, "out": fout, "horizon": horizon})
            if not r.get("ok"):
                return np.zeros((horizon, 4), np.float32), {"trained": 0.0}
            return np.load(fout)["actions"], {**r.get("diagnostics", {}), "trained": 1.0}
```

## 外部运行时启动器模式 (冻结 runtime + 官方评测)

```bash
export VIRTUAL_ENV=<repo>/.venv PATH=<repo>/.venv/bin:$PATH
export <CACHE_ENV>=<cache_dir>            # 必须 export; 官方脚本不读 .env
( cd <repo>/paper_runtime && sha256sum -c RUNTIME_SHA256SUMS )   # ★ 指纹先验, 跑完当证据
cp -n <repo>/config/eval/solver/direct.yaml <repo>/paper_runtime/config/eval/solver/direct.yaml  # 只新增, 不动钉住文件
PYTHONPATH=<repo>/paper_runtime:<repo> python eval.py --config-name=pusht solver=direct policy=<policy> seed=42 eval.num_eval=100
```

**报告纪律**: SR 取官方输出；"零搜索"取 `solver_timing` 里的 `get_cost_calls_mean` 与
`candidate_sequences_mean`（顶层 `get_cost_calls` 键在 eval.py 里读 `_sum` 不存在 → 恒为默认 0，**不能**当证据）。
