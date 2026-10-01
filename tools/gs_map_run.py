#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_map_run.py — 自动跑点建图 (老倪 2026-10-01):
「机械臂自动运行 空间的每个点, 可以顺序1到7点, 同时自主建图3DGS功能」。

- 跑点: POST /ctl/move {skill: L2.goto_spaceN, arm:1} —— 与号位按钮**同一条**授权+收口+执行器+安全裁决链, 不新开通道
- 到位判据: rokae_sdk/tcp_out/latest.json 与空间点真值 <3mm 且连续 1.0s 稳定(不靠超时猜)
- 采集: tools/gs_capture.py (与页面同源真值位姿)  建图: gs_dataset.py + gs_train.py (真值位姿, 不用 COLMAP)
- 状态写 ~/zmax_data/gs_map/status.json (页面左上角建图窗口轮询 /ctl/gs_map)
- 任何一步被拒/失败 ⇒ **如实写状态并停**, 绝不假装成功 (老倪: 链路须真实执行+可验证证据)

环境变量: GS_DWELL_S=每点采集秒数(默认6) · GS_STEPS=训练步数(默认15000)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = "/home/ubuntu/zmax"
PY = "/home/ubuntu/gs-venv/bin/python"
GS = os.path.expanduser("~/zmax_data/gs_assets")
ROOT = os.path.expanduser("~/zmax_data/gs_map")
SESS = os.path.join(GS, "map_run_%s" % time.strftime("%Y%m%d_%H%M%S"))
STATUS = os.path.join(ROOT, "status.json")
POSE = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")
SP = os.path.join(REPO, "data/skills/l2_atomic/space_points.json")
DWELL_S = float(os.environ.get("GS_DWELL_S", "6"))
TRAIN_STEPS = int(os.environ.get("GS_STEPS", "15000"))


def w(st, line):
    os.makedirs(ROOT, exist_ok=True)
    st["ts"] = time.strftime("%F %T")
    with open(STATUS + ".tmp", "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(STATUS + ".tmp", STATUS)
    print("[%s] %s" % (time.strftime("%H:%M:%S"), line), flush=True)


def pose():
    try:
        d = json.load(open(POSE, encoding="utf-8"))
        return [float(d["x"]), float(d["y"]), float(d["z"])]
    except Exception:                                                       # noqa: BLE001
        return None


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def move(skill, speed=8):
    req = urllib.request.Request(
        "http://127.0.0.1:8793/ctl/move", method="POST",
        data=json.dumps({"skill": skill, "arm": 1, "speed": speed, "by": "自动跑点建图"}).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def wait_arrive(target, timeout=240):
    t0 = time.time()
    stable = None
    while time.time() - t0 < timeout:
        p = pose()
        if p and dist(p, target) < 0.003:
            stable = stable or time.time()
            if time.time() - stable >= 1.0:
                return True, dist(p, target)
        else:
            stable = None
        time.sleep(0.2)
    p = pose()
    return False, (dist(p, target) if p else -1.0)


def run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def main():
    pts = json.load(open(SP, encoding="utf-8"))["points"]
    names = ["space%d" % i for i in range(1, 8)]
    st = {"running": True, "step": "start", "session": SESS}
    missing = [n for n in names if n not in pts]
    if missing:
        st.update(running=False, status_line="空间点没记全: %s" % missing)
        w(st, "⛔ 空间点没记全: %s" % missing)
        return 1
    # 🔧 2026-10-01: micromamba 那套 CUDA env 布局是混的(nvcc 私有头 legay + 12.4 API 头 targets,
    #    且 legacy 里 cuda_fp16.h 是 13.3 版本 ⇒ gsplat JIT 编译失败)。改用合并好的 shim:
    #    /home/ubuntu/cuda-shim = nvcc 全套工具 + 12.4 API 头(targets) + legacy 私有头(crt/fatbinary/nv)。
    #    实证: 冒烟 .cu(fp16 + nv/target + runtime) 真编译真跑通过。
    os.environ.setdefault("CUDA_HOME", "/home/ubuntu/cuda-shim")
    os.environ.setdefault("TORCH_CUDA_ARCH_LIST", "8.9")
    os.environ["PATH"] = "/home/ubuntu/cuda-shim/bin:/home/ubuntu/gs-venv/bin:" + os.environ.get("PATH", "")
    os.environ.setdefault("CC", "/home/ubuntu/cuda-shim/bin/gcc")
    os.environ.setdefault("CXX", "/home/ubuntu/cuda-shim/bin/g++")
    os.environ.setdefault("CUDAHOSTCXX", "/home/ubuntu/cuda-shim/bin/g++")
    w(st, "开始: 顺序跑 7 个空间点, 每点采 %.0fs, 训练 %d 步" % (DWELL_S, TRAIN_STEPS))
    for i, n in enumerate(names, 1):
        tgt = [float(v) for v in pts[n]["pos"]]
        st.update(step="move", status_line="(%d/7) 去 %s …" % (i, n))
        w(st, "→ %s" % n)
        try:
            j = move("L2.goto_" + n)
        except Exception as e:                                              # noqa: BLE001
            st.update(running=False, status_line="下发异常: %s" % str(e)[:90])
            w(st, "⛔ 下发异常: %s" % e)
            return 1
        if not j.get("ok"):
            msg = str(j.get("msg") or "")[:130]
            st.update(running=False, status_line="%s 被拒: %s" % (n, msg))
            w(st, "⛔ %s 被拒: %s" % (n, msg))
            return 1
        ok, d = wait_arrive(tgt)
        if not ok:
            st.update(running=False, status_line="%s 未到位(偏差 %.1fmm)" % (n, d * 1000))
            w(st, "⛔ %s 未到位 %.1fmm" % (n, d * 1000))
            return 1
        w(st, "  ✓ %s 到位(偏差 %.1fmm)" % (n, d * 1000))
        st.update(step="capture", status_line="(%d/7) %s 采集中 %.0fs" % (i, n, DWELL_S))
        p = run([PY, os.path.join(REPO, "tools/gs_capture.py"), "--out", SESS, "--secs", str(DWELL_S)],
                timeout=DWELL_S + 120)
        if p.returncode != 0:
            st.update(running=False, status_line="采集失败: %s" % ((p.stderr or p.stdout or "")[-110:]))
            w(st, "⛔ 采集失败")
            return 1
    ds = SESS + "_ds"
    for step, cmd in (("dataset", [PY, os.path.join(REPO, "tools/gs_dataset.py"), "--session", SESS, "--out", ds]),
                      ("train", [PY, os.path.join(REPO, "tools/gs_train.py"), "--data", ds,
                                 "--out", SESS + "_model", "--steps", str(TRAIN_STEPS)])):
        st.update(step=step, status_line="%s 运行中(日志 run.log)…" % step)
        w(st, "跑 %s" % step)
        p = run(cmd)
        if p.returncode != 0:
            tail = ((p.stderr or "") + (p.stdout or ""))[-300:].replace("\n", " ")
            st.update(running=False, status_line="%s 失败: %s" % (step, tail[-130:]))
            w(st, "⛔ %s 失败: %s" % (step, tail[-200:]))
            return 1
    st.update(running=False, step="done", status_line="✅ 建图完成: %s" % os.path.basename(SESS + "_model"),
              image_url="/gs_render.png?t=__T__")
    w(st, "✅ 全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
