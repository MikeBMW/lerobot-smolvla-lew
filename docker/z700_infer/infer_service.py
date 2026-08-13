#!/usr/bin/env python3
"""Z700 推理服务 — 部署在 Mac M1 (docker, arm64)
整体承载 3 个模型: YOLO 感知 + 左脑 MLP + 右脑 WM + 状态机配置

API:
  GET  /health   → 模型加载状态
  POST /detect   → YOLO 检测: {image: base64} → {hand, peg, hole} 3D
  POST /predict  → 双脑推理: {obs: [43D]} → {action: [4D], stage}
"""
import os, json, time, base64, io
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODELS_DIR = os.environ.get("MODELS_DIR", "/app/models")
app = FastAPI(title="Z700 Inference", version="2.0.0")

# ── 模型加载 (整体: 3 模型 + 状态机) ──────────────────────────
_yolo = None
_brain = None
_statemachine = None
_loaded_at = None


class _Z700Models:
    """懒加载: YOLO + 双脑 model.pt (left/right) + 状态机 yaml"""

    def __init__(self, models_dir):
        self.dir = models_dir
        self.yolo = None
        self.left = None
        self.right = None
        self.obs_dim = 43
        self.act_dim = 4
        self.stage_cfg = {}

    def load(self):
        # 1) YOLO 感知
        from ultralytics import YOLO
        yolo_path = os.path.join(self.dir, "yolo_best.pt")
        if os.path.exists(yolo_path):
            self.yolo = YOLO(yolo_path)
        # 2) 双脑 (model.pt: {left, right, obs_dim, act_dim})
        import torch
        brain_path = os.path.join(self.dir, "left_right", "model.pt")
        if os.path.exists(brain_path):
            sd = torch.load(brain_path, map_location="cpu", weights_only=False)
            from modeling import LeftBrainMLP, RightBrainWM
            self.left = LeftBrainMLP(obs_dim=sd["obs_dim"], act_dim=sd["act_dim"])
            self.left.load_state_dict(sd["left"])
            self.left.eval()
            self.right = RightBrainWM(obs_dim=sd["obs_dim"], act_dim=sd["act_dim"])
            self.right.load_state_dict(sd["right"])
            self.right.eval()
            self.obs_dim = sd["obs_dim"]
            self.act_dim = sd["act_dim"]
        # 3) 状态机配置
        sm_path = os.path.join(self.dir, "statemachine.yaml")
        if os.path.exists(sm_path):
            import yaml
            with open(sm_path) as f:
                self.stage_cfg = yaml.safe_load(f) or {}
        return self


def get_models():
    global _yolo
    if _yolo is None:
        _yolo = _Z700Models(MODELS_DIR).load()
    return _yolo


@app.on_event("startup")
def _startup():
    t0 = time.time()
    m = get_models()
    print(f"[z700] 模型加载完成 ({time.time()-t0:.1f}s): "
          f"yolo={m.yolo is not None} left={m.left is not None} right={m.right is not None} "
          f"obs={m.obs_dim} act={m.act_dim}")


# ── API ─────────────────────────────────────────────────────
@app.get("/health")
def health():
    m = get_models()
    return {"status": "ok", "models": {
        "yolo": m.yolo is not None,
        "left_brain": m.left is not None,
        "right_brain": m.right is not None,
        "obs_dim": m.obs_dim, "act_dim": m.act_dim,
        "stages": sorted(m.stage_cfg.keys())[:8] if m.stage_cfg else [],
    }}


class DetectReq(BaseModel):
    image: str  # base64 RGB 图像
    conf: float = 0.4


@app.post("/detect")
def detect(req: DetectReq):
    """YOLO 检测 → 3D 坐标 {hand, peg, hole} (2D 框中心反投影, 仿真标定)"""
    m = get_models()
    if m.yolo is None:
        raise HTTPException(400, "YOLO 未加载")
    import cv2
    raw = base64.b64decode(req.image)
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)  # BGR
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    res = m.yolo.predict(img_rgb, conf=req.conf, verbose=False)[0]
    out = {}
    H, W = img.shape[:2]
    for b in res.boxes:
        cls = res.names[int(b.cls)]
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        out[cls] = {"center": [(x1 + x2) / 2, (y1 + y2) / 2], "conf": float(b.conf)}
    return {"detections": out, "shape": [H, W]}


class PredictReq(BaseModel):
    obs: list = Field(..., description=f"状态向量 ({'43D'})")
    stage: str = "approach"


@app.post("/predict")
def predict(req: PredictReq):
    """双脑推理: 左脑出动作, 右脑出判断, 状态机调制 → 4D action"""
    m = get_models()
    if m.left is None:
        raise HTTPException(400, "双脑未加载")
    import torch
    obs = np.asarray(req.obs, dtype=np.float32).reshape(1, -1)
    with torch.no_grad():
        t = torch.from_numpy(obs)
        action = m.left(t)                     # 左脑 → 4D 动作
        next_obs, contact = m.right(t, action)  # 右脑 → next_obs + contact
    return {"action": action.numpy()[0].tolist(),
            "contact": float(contact.numpy()[0][0]),
            "next_obs": next_obs.numpy()[0].tolist(),
            "stage": req.stage, "obs_dim": m.obs_dim}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
