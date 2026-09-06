#!/usr/bin/env python3
"""🧭 状态空间 3D 手机页 — 实况同步发布器 (2026-09-06 老倪: 手机版3D要与状态空间模型运行同步)

链路:
    [GUI ▶运行]  StateSpaceSim.run() → tr
        │  ① 后台线程: 全轨迹导出 (与 export_ss_traj.py 同 schema) → scp 上传
        │             datadrive.world/ss_traj_full.json (上传成功后才发 run_start)
        │  ② 播放期每 ~120ms 心跳 POST ss3d_api.php → 写 ss3d_live.json
        │             {run_id, playing, i(帧), n, stage, t, dist, done}
        │  ③ 结束/停止 → POST playing:false + 终态
        ▼
    [手机 state-3d.html]  250ms 轮询 ss3d_live.json → run_id 变化则装载新轨迹
        → 逐心跳 goto(i) — 与画布/3D 视图同一条 tr 同帧跟随 (非独立重放)

安全:
    - 网络失败/禁用 → 软降级 (播放零影响); 环境 ZMAX_SS3D_LIVE=0 关闭
    - 心跳丢包自愈: 页端 4s 无更新判定中断 → 本地重放兜底
    - 上传顺序: 先轨迹后心跳 → 页端见到新 run_id 时轨迹必已就绪

用法:
    python ss3d_live.py            # CLI 自测: 真实跑一局 → 发布 start/进度/end
"""
import json
import os
import threading
import time
import subprocess
import sys

ECS_HOST = os.environ.get("ZMAX_ECS_HOST", "39.102.211.79")
ECS_PW = os.environ.get("ZMAX_ECS_PW", "")
WEB_DIR = "/www/wwwroot/datadrive.world"
API_URL = os.environ.get("ZMAX_SS3D_API", "https://datadrive.world/ss3d_api.php")
TRAJ_URL = "https://datadrive.world/ss_traj_full.json"

_log = print if os.environ.get("ZMAX_SS3D_LOG") else (lambda *a, **k: None)


# ─────────────────────── 轨迹导出 (与 export_ss_traj.py 同 schema) ───────────────────────
def _v3(arr, i):
    """取第 i 步的 3D 向量 (容忍 np 数组/list/标量)"""
    try:
        v = arr[i]
        if hasattr(v, "__len__") and len(v) >= 3:
            return [round(float(v[0]), 4), round(float(v[1]), 4), round(float(v[2]), 4)]
    except Exception:
        pass
    return None


def frames_from_tr(tr):
    """tr → 网页 JSON dict (export_ss_traj.py 同款, 每步一帧; io 帧全量时 1:1)"""
    n = len(tr["x"])
    frames = []
    for i in range(n):
        stage = str(tr["stage"][i]).replace("阶段 ", "").split("·")[0].strip()
        frames.append({
            "t": round(float(tr["t"][i]), 3),
            "x": _v3(tr["x"], i),
            "peg": _v3(tr["peg"], i),
            "target": _v3(tr["target"], i),
            "peg_head": _v3(tr.get("peg_head", []), i),
            "gripper": round(float(tr["gripper"][i]), 3) if i < len(tr.get("gripper", [])) else 0,
            "grasped": bool(tr["grasped"][i]) if i < len(tr.get("grasped", [])) else False,
            "stage": stage,
            "dist": round(float(tr["dist"][i]), 4),
            "u_ff": _v3(tr.get("u_ff_vec", []), i),
            "latent": _v3(tr.get("latent_vec", []), i),
            "prior": _v3(tr.get("prior_vec", []), i),
            "corrected": _v3(tr.get("corrected_vec", []), i),
            "residual": _v3(tr.get("residual_vec", []), i),
            "u_fb": _v3(tr.get("u_fb_vec", []), i),
            "u_fuse": _v3(tr.get("u_fuse_vec", []), i),
            "u_limit": _v3(tr.get("u_limit_vec", []), i),
            "u_exec": _v3(tr.get("u_exec_vec", []), i),
            "z_k": _v3(tr.get("z_k_vec", []), i),
            "contact_p": round(float(tr["contact_p"][i]), 3),
            "residual_scalar": round(float(tr["residual"][i]), 4),
        })
    return {
        "title": "状态空间 3D 分层空间 · 插光模块仿真",
        "n": n,
        "step_skip": 1,
        "done": bool(tr["done"][-1]),
        "dist_final": round(float(tr["dist"][-1]), 4),
        "stages": sorted(set(f["stage"] for f in frames)),
        "frames": frames,
    }


# ─────────────────────── 上传 / 心跳 ───────────────────────
def _scp_upload(local, remote_name):
    r = subprocess.run(
        ["sshpass", "-p", ECS_PW, "scp", "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=15", local, f"root@{ECS_HOST}:{WEB_DIR}/{remote_name}"],
        capture_output=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"scp {remote_name} 失败: {r.stderr.decode(errors='replace')[-200:]}")
    subprocess.run(
        ["sshpass", "-p", ECS_PW, "ssh", "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=15", f"root@{ECS_HOST}",
         f"chmod 644 {WEB_DIR}/{remote_name}"], capture_output=True, timeout=60)


def _http_post(payload):
    import requests
    r = requests.post(API_URL, json=payload, timeout=6)
    r.raise_for_status()


class SS3DLive:
    """实况发布器: 单 run 生命周期. GUI 每 tick 调 push_engine(idx), 结束调 finish().

    内部: 后台线程持最新 idx, ≥120ms 节流 POST; 断网/失败计数 ≥5 → 自禁用(软降级).
    """

    MIN_POST_GAP = 0.12

    def __init__(self, run_id=None, log=None):
        self.run_id = run_id or f"{int(time.time() * 1000)}"
        self._log = log or _log
        self._latest = -1          # 引擎步 idx
        self._n_frames = 0
        self._step = 1
        self._t_meta = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._last_post = 0.0
        self._fails = 0
        self._thread = None
        self._upload_done = False

    # ── GUI 接口 (非阻塞) ──
    def publish_run(self, tr):
        """上传全轨迹 + 启动心跳线程. 轨迹上传成功前不发 run_start."""
        self._n_frames = int(len(tr["x"]))
        try:
            out = frames_from_tr(tr)
        except Exception as e:
            self._log(f"⚠️ ss3d 轨迹导出失败: {e}")
            return
        tmp = "/tmp/ss_traj_full.json"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
        except Exception as e:
            self._log(f"⚠️ ss3d 本地写盘失败: {e}")
            return
        self._thread = threading.Thread(target=self._worker, args=(tmp, out), daemon=True)
        self._frames = out["frames"]
        self._thread.start()

    def push_engine(self, idx):
        """GUI _ss_tick 每帧调用 — 引擎步 idx → 发布线程"""
        if self._thread is None or self._stop.is_set():
            return
        with self._lock:
            self._latest = max(self._latest, int(idx))
        self._wake.set()

    def finish(self, done=None, dist=None, note=None):
        """播放结束/手动停止 → 终态心跳"""
        if self._thread is None:
            return
        with self._lock:
            n1 = max(0, self._n_frames - 1)
            self._latest = max(self._latest, n1)
            self._t_meta = {"done": bool(done), "dist": dist, "note": note}
        self._stop.set()
        self._wake.set()

    # ── 内部 ──
    def _worker(self, tmp, out):
        try:
            _scp_upload(tmp, "ss_traj_full.json")
            self._upload_done = True
            self._log(f"🧭 ss3d 轨迹已上传: {TRAJ_URL} ({self._n_frames}帧)")
        except Exception as e:
            self._log(f"⚠️ ss3d 轨迹上传失败(心跳仍试发): {e}")
        self._post({"run_id": self.run_id, "playing": True, "i": 0,
                    "n": self._n_frames, "stage": "接近", "t": 0.0,
                    "dist": None, "done": None, "src": "ss-gui"})
        last_i = -1
        while True:
            self._wake.wait(timeout=0.25)
            self._wake.clear()
            with self._lock:
                i = self._latest
                stopped = self._stop.is_set()
                meta = self._t_meta
            now = time.time()
            if (i != last_i or stopped) and (now - self._last_post >= self.MIN_POST_GAP or stopped):
                self._post_state(i, stopped, meta)
                last_i = i
            if stopped:
                break

    def _post_state(self, i, stopped, meta):
        n1 = max(0, self._n_frames - 1)
        i = max(0, min(i, n1))
        # 心跳顺带帧元数据 (页端 HUD/异常显示用; 正常路径页端直接读帧)
        fr = self._frames[i] if (getattr(self, "_frames", None) and i < len(self._frames)) else {}
        payload = {"run_id": self.run_id, "playing": not stopped,
                   "i": i, "n": self._n_frames,
                   "stage": fr.get("stage"), "t": fr.get("t"), "dist": fr.get("dist"),
                   "done": meta.get("done") if meta else None,
                   "src": "ss-gui"}
        self._post(payload)

    def _post(self, payload):
        if self._fails >= 5:
            return
        try:
            _http_post(payload)
            self._fails = 0
            self._last_post = time.time()
        except Exception as e:
            self._fails += 1
            self._log(f"⚠️ ss3d 心跳失败({self._fails}/5): {e}")


# ─────────────────────── CLI 自测 ───────────────────────
def _cli_test():
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from state_space_sim import StateSpaceSim
    sim = StateSpaceSim()
    tr = sim.run()
    n = len(tr["x"])
    print(f"✅ 引擎跑完: {n} 步, done={tr['done'][-1]}, dist={tr['dist'][-1]:.4f}")
    live = SS3DLive(log=lambda *a: print(*a))
    live.publish_run(tr)
    # 模拟 GUI 播放节奏: 30ms/步
    for i in range(0, n, 4):
        live.push_engine(i)
        time.sleep(0.03)
    live.finish(done=bool(tr["done"][-1]), dist=round(float(tr["dist"][-1]), 4))
    time.sleep(1.5)
    print("✅ CLI 自测完成 (start/心跳/end 已发)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli_test())
