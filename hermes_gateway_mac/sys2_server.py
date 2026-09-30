"""
Z-MAX Sys-2 gRPC 服务端 · 部署在4090

服务:
  - /sys2.InferService/Infer → 单次推理(VTLA/GR00T)
  - /sys2.InferService/Health → 健康检查

启动: python sys2_grpc_server.py --port 50051
"""
import grpc
from concurrent import futures
import torch, time, json, argparse
import numpy as np

# ═══ Proto定义 (内联, 无protobuf依赖) ═══
# 生产环境用: python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. sys2.proto
# 此处使用简化JSON-based gRPC方案避免编译依赖

import sys
sys.path.insert(0, '/root/lerobot-smolvla-lew')

class Sys2Service:
    """Sys-2推理服务: VTLA + GR00T"""

    def __init__(self):
        self._vtla = None
        self._groot = None
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"[Sys2] Device: {self._device}")
        print(f"[Sys2] VRAM: {torch.cuda.get_device_properties(0).total_memory/1024**3:.0f}GB" if self._device=='cuda' else "")

    def health(self):
        return {"status": "ok", "device": self._device,
                "vtla_loaded": self._vtla is not None,
                "groot_loaded": self._groot is not None}

    def load_vtla(self):
        """加载VTLA (smolvla)"""
        if self._vtla is None:
            try:
                from lerobot.configs.types import FeatureType, PolicyFeature
                from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
                from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
                features = {
                    'observation.images.camera1': PolicyFeature(FeatureType.VISUAL, (3,256,256)),
                    'observation.images.camera2': PolicyFeature(FeatureType.VISUAL, (3,256,256)),
                    'observation.images.camera3': PolicyFeature(FeatureType.VISUAL, (3,256,256)),
                    'observation.state': PolicyFeature(FeatureType.STATE, (2,)),
                }
                cfg = SmolVLAConfig(input_features=features,
                                    output_features={'action': PolicyFeature(FeatureType.ACTION, (2,))})
                self._vtla = SmolVLAPolicy(cfg).to(self._device).eval()
                print(f"[Sys2] VTLA loaded: {sum(p.numel() for p in self._vtla.parameters())/1e6:.0f}M")
            except Exception as e:
                print(f"[Sys2] VTLA load failed: {e}")

    def load_groot(self):
        """加载GR00T N1.7"""
        if self._groot is None:
            try:
                from gr00t import Gr00tPolicy
                self._groot = Gr00tPolicy.from_pretrained("nvidia/GR00T-N1-7")
                if self._device == 'cuda':
                    self._groot.to(self._device)
                self._groot.eval()
                print(f"[Sys2] GR00T loaded")
            except Exception as e:
                print(f"[Sys2] GR00T load failed (pending model download): {e}")

    def infer(self, model_type: str, state: list, image: list = None, image_shape: list = None, task: str = "execute"):
        """推理接口"""
        t0 = time.time()

        try:
            # 准备输入
            state_t = torch.tensor(state, device=self._device).float().reshape(1, -1)
            img_t = None
            if image and len(image) > 0:
                img_t = torch.tensor(image, device=self._device).float().reshape(image_shape)

            if model_type == 'vtla':
                self.load_vtla()
                if self._vtla is None:
                    return {"action": [0.0]*7, "error": "VTLA not loaded"}
                batch = {
                    'observation.images.camera1': img_t if img_t is not None else torch.randn(1,3,256,256,device=self._device),
                    'observation.images.camera2': torch.randn(1,3,256,256,device=self._device),
                    'observation.images.camera3': torch.randn(1,3,256,256,device=self._device),
                    'observation.state': state_t,
                }
                with torch.no_grad():
                    action = self._vtla.select_action(batch)
                if action.dim() == 3:
                    action = action[:, -1, :]

            elif model_type == 'groot':
                self.load_groot()
                if self._groot is None:
                    return {"action": [0.0]*7, "error": "GR00T not loaded"}
                batch = {'observation.state': state_t}
                if img_t is not None:
                    batch['observation.image'] = img_t
                with torch.no_grad():
                    action = self._groot.select_action(batch)

            else:
                return {"action": [0.0]*7, "error": f"Unknown model: {model_type}"}

            action = action.cpu().numpy().flatten()[:7].tolist()
            latency = (time.time() - t0) * 1000
            return {"action": action, "model": model_type, "latency_ms": round(latency, 1)}

        except Exception as e:
            return {"action": [0.0]*7, "error": str(e), "model": model_type,
                    "latency_ms": round((time.time()-t0)*1000, 1)}


# ═══ 简化gRPC实现 (HTTP+JSON代替protobuf) ═══
from http.server import HTTPServer, BaseHTTPRequestHandler

class Sys2Handler(BaseHTTPRequestHandler):
    service = Sys2Service()

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len)
        req = json.loads(body)

        if self.path == '/infer':
            resp = self.service.infer(
                model_type=req.get('model_type', 'vtla'),
                state=req.get('state', [0]*6),
                image=req.get('image'),
                image_shape=req.get('image_shape'),
                task=req.get('task', 'execute'),
            )
        elif self.path == '/health':
            resp = self.service.health()
        elif self.path == '/load':
            model = req.get('model', 'vtla')
            if model == 'vtla':
                self.service.load_vtla()
            elif model == 'groot':
                self.service.load_groot()
            resp = self.service.health()
        else:
            resp = {"error": "unknown endpoint"}

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def do_GET(self):
        if self.path == '/health':
            resp = self.service.health()
        else:
            resp = {"status": "ok", "endpoints": ["/health", "/infer", "/load"]}
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def log_message(self, format, *args):
        pass  # 静默日志


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=50051)
    parser.add_argument('--load', choices=['vtla','groot','both'], default='both')
    args = parser.parse_args()

    # 预加载模型
    svc = Sys2Handler.service
    if args.load in ('vtla', 'both'):
        print("[Sys2] Loading VTLA...")
        svc.load_vtla()
    if args.load in ('groot', 'both'):
        print("[Sys2] Loading GR00T...")
        svc.load_groot()

    server = HTTPServer(('0.0.0.0', args.port), Sys2Handler)
    print(f"[Sys2] Server running on :{args.port}")
    print(f"[Sys2] Endpoints: POST /infer, GET /health, POST /load")
    server.serve_forever()


if __name__ == '__main__':
    main()
