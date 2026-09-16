#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 状态空间工程 · 4060 本机侧推理服务 (跨机闭环 Step 1)

用途: 本机 venv(有 torch/CUDA) 里加载状态空间模型权重, 供 Docker 里的 ROS 桥节点通过
      127.0.0.1 调用 —— 模型留在 venv, ROS 在容器, 两边解耦 (老倪 2026-09-16 定的方案)。

模型: models/l4_mani_predictor_v5.pt  → 11D 输入 / 6D 输出
      models/l4_yaw_head_grasp_dz_v2.pt → 12D 输入 / (dz, ok)
      (权重与 Orin 端 8767 服务同一套; 加载键格式兼容 predictor./readout./trunk./mlp.N)

端口: 8790 (仅监听 127.0.0.1, 不对外)

契约 (与 tools/ss_bridge_node.py 一致):
  GET  /health                          → {"online":true,"device":..,"models":[..],"infer_count":..}
  POST /infer   {"state": {…边缘 state 报文…}} → {"action":[6], "yaw":{dz,ok}, "model_ms":.., "input_map":"…"}

⚠️ 诚实标注: 本版本 input_map = placeholder_v0 —— 引擎口径的 z7(手/头−目标, 手/头−光模块, 夹持)
   需要 TCP 笛卡尔位姿与现场几何, 本机拿不到, 故用 real 可用量按固定位置投影填 11D/12D。
   响应里显式回传 input_map 字段, 不伪装成"标定完成"。映射函数集中在这一个地方, 标定后只改它。
"""
import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEV = "cuda" if torch.cuda.is_available() else "cpu"
STATS = {"infer_count": 0, "last_ms": 0.0, "started": time.strftime("%Y-%m-%d %H:%M:%S")}


def collect_layers(sd, prefix):
    """收集 prefix 下的 Linear 层: 兼容 'mlp.N.weight' 与 'N.weight' (与 Orin 8767 服务同源)"""
    idx = {}
    for k in sd:
        if not k.startswith(prefix + "."):
            continue
        parts = k[len(prefix) + 1:].split(".")
        if len(parts) == 3 and parts[0] == "mlp" and parts[-1] in ("weight", "bias"):
            i = int(parts[1])
        elif len(parts) == 2 and parts[-1] in ("weight", "bias"):
            i = int(parts[0])
        else:
            continue
        idx.setdefault(i, {})[parts[-1]] = sd[k]
    layers = []
    for i in sorted(idx):
        w = idx[i]["weight"]
        lin = nn.Linear(w.shape[1], w.shape[0])
        lin.weight.data = w.clone().float()
        if "bias" in idx[i]:
            lin.bias.data = idx[i]["bias"].clone().float()
        layers.append(lin)
        if i != max(idx):
            layers.append(nn.ReLU())
    return nn.Sequential(*layers)


class YawHead(nn.Module):
    def __init__(self, trunk, sd):
        super().__init__()
        self.trunk = trunk
        self.head_dz = nn.Linear(256, 1)
        self.head_ok = nn.Linear(256, 1)
        self.head_dz.weight.data = sd["head_dz.weight"].clone().float()
        self.head_dz.bias.data = sd["head_dz.bias"].clone().float()
        self.head_ok.weight.data = sd["head_ok.weight"].clone().float()
        self.head_ok.bias.data = sd["head_ok.bias"].clone().float()

    def forward(self, x):
        h = self.trunk(x)
        return self.head_dz(h), self.head_ok(h)


def load_models():
    t0 = time.time()
    p1 = os.path.join(ROOT, "models", "l4_mani_predictor_v5.pt")
    p2 = os.path.join(ROOT, "models", "l4_yaw_head_grasp_dz_v2.pt")
    sd1 = torch.load(p1, map_location="cpu", weights_only=False)
    mani = nn.Sequential(collect_layers(sd1, "predictor"), collect_layers(sd1, "readout")).to(DEV).eval()
    sd2 = torch.load(p2, map_location="cpu", weights_only=False)
    yaw = YawHead(collect_layers(sd2, "trunk"), sd2).to(DEV).eval()
    return mani, yaw, round((time.time() - t0) * 1000, 1)


MANI = YAW = None
LOAD_MS = 0.0
INPUT_MAP = os.environ.get("SS_INFER_MAP", "auto")   # auto|tcp_pose_v1|placeholder_v0
STRICT = os.environ.get("SS_INFER_STRICT", "0") == "1"


def build_model_inputs(state: dict):
    """优先真实口径: state["z7"] (7 维, 由 Orin 标定桥按引擎公式算出) + a4(未知→0) → 11D/12D。"""
    """real 边缘 state → 模型原生输入 (11D / 12D)。

    ⚠️ placeholder_v0: 模型训练时的输入是引擎口径 z7(手−目标, 手−光模块, 夹持) + 动作 4D(+候选角),
       这些量依赖 TCP 笛卡尔位姿与现场几何 —— 现场目前不发布该位姿, 故这里用**真实可用量**按固定位置投影:
         d0..d2 = 关节速度前 3 维(缩放)      d3 = 夹爪(归一)      d4..d6 = 六维力前 3 维(缩放)
         a0..a3 = 0 (无上一条动作信息)        cand  = 0
       只为把跨机链路跑通并给出真实前向结果; 标定完成后**只改这个函数**。
    """
    z7 = state.get("z7")
    if isinstance(z7, (list, tuple)) and len(z7) == 7:
        z = [float(x) for x in z7]
        if any(abs(x) > 2.0 for x in z):
            raise ValueError(f"z7 超范围 {z} — 几何/位姿可疑, 拒绝推理")
        a = [0.0, 0.0, 0.0, 0.0]
        return z + a, z + a + [0.0], "tcp_pose_v1"
    if STRICT:
        raise ValueError("严格模式: 无真实 z7 (标定桥未就绪) → 拒绝用 placeholder 兜底")
    jv = (state.get("jvel") or [0.0] * 6)[:6]
    jv = (jv + [0.0] * 6)[:6]
    ft = state.get("ft") or [0.0] * 6
    g = state.get("gripper")
    g = 0.0 if g is None else float(g) / 1000.0
    z = [jv[0] * 5, jv[1] * 5, jv[2] * 5, g, ft[0] / 20.0, ft[1] / 20.0, ft[2] / 20.0]
    a = [0.0, 0.0, 0.0, 0.0]
    mani_in = z + a                      # 11D
    yaw_in = z + a + [0.0]               # 12D (末位=候选角)
    return mani_in, yaw_in, "placeholder_v0"


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"online": True, "device": DEV, "port": PORT,
                             "models": ["l4_mani_predictor_v5", "l4_yaw_head_grasp_dz_v2"],
                             "load_ms": LOAD_MS, "infer_count": STATS["infer_count"],
                             "last_ms": STATS["last_ms"], "started": STATS["started"],
                             "torch": torch.__version__, "input_map": INPUT_MAP})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._json(400, {"error": f"bad json: {e}"})
            return
        if self.path != "/infer":
            self._json(404, {"error": "not found"})
            return
        state = body.get("state") or body
        try:
            mani_in, yaw_in, used_map = build_model_inputs(state)
        except ValueError as e:
            self._json(409, {"error": str(e), "refused": True})
            return
        t0 = time.time()
        with torch.no_grad():
            a = MANI(torch.tensor([mani_in], dtype=torch.float32, device=DEV))[0].tolist()
            dz, ok = YAW(torch.tensor([yaw_in], dtype=torch.float32, device=DEV))
        ms = round((time.time() - t0) * 1000, 2)
        STATS["infer_count"] += 1
        STATS["last_ms"] = ms
        self._json(200, {"action": [round(float(v), 6) for v in a],
                         "yaw": {"dz": round(float(dz.item()), 4), "ok": round(float(ok.item()), 4)},
                         "model_ms": ms, "device": DEV, "input_map": used_map})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    _args = ap.parse_args()
    PORT = _args.port
    MANI, YAW, LOAD_MS = load_models()
    print(f"✅ 模型已加载: l4_mani_predictor_v5 + l4_yaw_head_grasp_dz_v2 ({DEV}, {LOAD_MS}ms)", flush=True)
    print(f"🖥️  4060 状态空间推理服务: http://{_args.host}:{PORT} · input_map={INPUT_MAP}", flush=True)
    HTTPServer((_args.host, PORT), Handler).serve_forever()
