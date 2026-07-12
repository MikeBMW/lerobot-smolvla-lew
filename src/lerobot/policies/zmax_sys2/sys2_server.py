"""
Z-MAX Sys2 gRPC 推理服务

运行在 4090 上，为 Sys1 (4060) 提供大模型推理 API。

gRPC 接口:
- LoadModel(model_type) → 加载指定模型
- PredictAction(observation) → 推理动作
- HealthCheck() → 健康检查
- GetStatus() → 状态查询

启动: python -m lerobot.policies.zmax_sys2.sys2_server
"""
from __future__ import annotations
import sys
import os
import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional
from concurrent import futures

import numpy as np
import grpc
import torch

logging.basicConfig(level=logging.INFO, format='[Sys2-Server] %(message)s')
logger = logging.getLogger("zmax.sys2.server")


# ═══════════════════════════════════════════════════════════════
# Proto 定义 (内联 - 避免外部依赖)
# ═══════════════════════════════════════════════════════════════

# 如果 lerobot transport proto 可用，使用它；否则用内联定义
try:
    # 尝试使用 lerobot 的 transport proto
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from lerobot.transport import services_pb2, services_pb2_grpc
    _HAS_GRPC_PROTO = True
except ImportError:
    _HAS_GRPC_PROTO = False
    logger.warning("lerobot transport proto not available, using standalone mode")


# ═══════════════════════════════════════════════════════════════
# Sys2 gRPC 服务定义
# ═══════════════════════════════════════════════════════════════

# 内联 proto 生成的 Python 类 (简化版)
import types

def _create_proto_classes():
    """动态创建简化的 proto 类 (不依赖 .proto 编译)"""

    class Sys2Request:
        def __init__(self, model_type="auto", task_text="", images=None,
                     state=None, force=None, tactile=None, gripper=0.0):
            self.model_type = model_type
            self.task_text = task_text
            self.images = images  # bytes (PNG/JPEG encoded)
            self.state = state if state is not None else []
            self.force = force if force is not None else []
            self.tactile = tactile if tactile is not None else []
            self.gripper = gripper

    class Sys2Response:
        def __init__(self, action=None, model_used="", task_type="",
                     inference_time_ms=0.0, confidence=1.0, plan="{}",
                     error=""):
            self.action = action if action is not None else []
            self.model_used = model_used
            self.task_type = task_type
            self.inference_time_ms = inference_time_ms
            self.confidence = confidence
            self.plan = plan
            self.error = error

    class Sys2Status:
        def __init__(self, loaded_models=None, inference_count="{}",
                     gpu_memory_mb=0.0, uptime_seconds=0.0):
            self.loaded_models = loaded_models if loaded_models is not None else []
            self.inference_count = inference_count
            self.gpu_memory_mb = gpu_memory_mb
            self.uptime_seconds = uptime_seconds

    return Sys2Request, Sys2Response, Sys2Status


Sys2Request, Sys2Response, Sys2Status = _create_proto_classes()


# ═══════════════════════════════════════════════════════════════
# gRPC 服务实现
# ═══════════════════════════════════════════════════════════════

class Sys2Servicer:
    """
    Sys2 gRPC 服务实现

    提供 JSON-over-gRPC 接口，兼容 HTTP 调试。
    """

    def __init__(self, sys2_policy):
        self._policy = sys2_policy
        self._start_time = time.time()

    # ── 通用 RPC handler ──

    def HandleRequest(self, request_json: str) -> str:
        """统一 JSON RPC 入口"""
        try:
            req = json.loads(request_json)
            method = req.get("method", "")
            params = req.get("params", {})

            if method == "predict":
                return self._handle_predict(params)
            elif method == "load_model":
                return self._handle_load_model(params)
            elif method == "health":
                return self._handle_health()
            elif method == "status":
                return self._handle_status()
            elif method == "list_models":
                return self._handle_list_models()
            else:
                return json.dumps({"error": f"Unknown method: {method}"})

        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _handle_predict(self, params: dict) -> str:
        """处理推理请求"""
        from lerobot.policies.zmax_sys2.modeling_zmax_sys2 import SimFeedback

        # 解析图像
        images_bytes = params.get("images", b"")
        if isinstance(images_bytes, str):
            # Base64 编码的图像
            import base64
            images_bytes = base64.b64decode(images_bytes)

        # 尝试从 bytes 解码图像
        camera_rgb = np.zeros((3, 512, 512), dtype=np.float32)
        if images_bytes:
            try:
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(images_bytes))
                img = img.resize((512, 512))
                camera_rgb = np.array(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
            except Exception as e:
                logger.warning(f"Image decode failed: {e}")

        # 构建仿真数据
        sim = SimFeedback(
            camera_rgb=camera_rgb,
            force_torque=np.array(params.get("force", [0]*6), dtype=np.float32),
            tactile=np.array(params.get("tactile", [0]*16), dtype=np.float32),
            joint_states=np.array(params.get("state", [0]*14), dtype=np.float32),
            gripper_pos=float(params.get("gripper", 0.0)),
            task_text=params.get("task_text", ""),
        )

        model = params.get("model", "auto")
        result = self._policy.predict(sim, model=model)

        return json.dumps({
            "action": result.action.tolist(),
            "model_used": result.model_used,
            "task_type": result.task_type,
            "inference_time_ms": result.inference_time_ms,
            "confidence": result.confidence,
            "plan": result.plan,
        })

    def _handle_load_model(self, params: dict) -> str:
        """加载模型"""
        model_type = params.get("model_type", "all")
        self._policy.load_models(model_type)
        return json.dumps({
            "status": "ok",
            "loaded": self._policy.list_loaded_models(),
        })

    def _handle_health(self) -> str:
        """健康检查"""
        return json.dumps({
            "status": "healthy",
            "uptime_seconds": time.time() - self._start_time,
            "gpu_available": torch.cuda.is_available(),
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A",
        })

    def _handle_status(self) -> str:
        """状态查询"""
        status = self._policy.get_status()
        status["uptime_seconds"] = time.time() - self._start_time
        return json.dumps(status)

    def _handle_list_models(self) -> str:
        """列出已加载模型"""
        return json.dumps({
            "loaded": self._policy.list_loaded_models(),
        })


# ═══════════════════════════════════════════════════════════════
# gRPC 服务器 (JSON-RPC over gRPC)
# ═══════════════════════════════════════════════════════════════

class Sys2GRPCServer:
    """
    Sys2 gRPC 推理服务器

    标准 gRPC unary 服务，接受 JSON 请求返回 JSON 响应。
    同时提供 HTTP/JSON 端点用于调试。
    """

    def __init__(self, sys2_policy, config):
        self._policy = sys2_policy
        self._config = config
        self._server: Optional[grpc.Server] = None
        self._servicer = Sys2Servicer(sys2_policy)
        self._http_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """启动 gRPC + HTTP 服务"""
        if self._running:
            return

        # ── gRPC 服务 ──
        if self._config.enable_grpc:
            self._start_grpc()

        # ── HTTP 服务 (调试用) ──
        if self._config.enable_http:
            self._start_http()

        self._running = True

    def _start_grpc(self):
        """启动 gRPC 服务"""
        host = self._config.grpc_host
        port = self._config.grpc_port

        self._server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=8),
            options=[
                ('grpc.max_send_message_length', 100 * 1024 * 1024),
                ('grpc.max_receive_message_length', 100 * 1024 * 1024),
            ]
        )

        # 注册通用服务 (使用反射实现 JSON-RPC)
        import types

        # 创建动态 gRPC service
        service_descriptor = types.SimpleNamespace()
        service_descriptor.full_name = "zmax.sys2.Sys2Service"

        def handle_unary(request, context):
            return self._servicer.HandleRequest(request.decode('utf-8')).encode('utf-8')

        # 使用 grpc 的 generic handler
        handler = grpc.method_handlers_generic_handler(
            "zmax.sys2.Sys2Service",
            {"HandleRequest": grpc.unary_unary_rpc_method_handler(handle_unary)}
        )
        self._server.add_generic_rpc_handlers((handler,))

        addr = f"{host}:{port}"
        self._server.add_insecure_port(addr)
        self._server.start()

        logger.info(f"✅ Sys2 gRPC server running on {addr}")
        logger.info(f"   Models: {self._policy.list_loaded_models()}")

    def _start_http(self):
        """启动 HTTP JSON-RPC 服务 (调试用)"""
        from http.server import HTTPServer, BaseHTTPRequestHandler

        servicer = self._servicer

        class Sys2HTTPHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')

                response = servicer.HandleRequest(body)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(response.encode('utf-8'))

            def do_GET(self):
                if self.path == '/health':
                    response = servicer._handle_health()
                    status = 200
                elif self.path == '/status':
                    response = servicer._handle_status()
                    status = 200
                elif self.path == '/models':
                    response = servicer._handle_list_models()
                    status = 200
                else:
                    response = json.dumps({
                        "service": "Z-MAX Sys2 Inference Server",
                        "endpoints": {
                            "POST /": "JSON-RPC inference",
                            "GET /health": "Health check",
                            "GET /status": "Runtime status",
                            "GET /models": "Loaded models",
                        }
                    })
                    status = 200

                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(response.encode('utf-8'))

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()

            def log_message(self, format, *args):
                logger.debug(f"HTTP: {args}")

        host = self._config.http_host
        port = self._config.http_port

        def run_http():
            httpd = HTTPServer((host, port), Sys2HTTPHandler)
            logger.info(f"✅ Sys2 HTTP API running on http://{host}:{port}")
            httpd.serve_forever()

        self._http_thread = threading.Thread(target=run_http, daemon=True)
        self._http_thread.start()

    def stop(self):
        """停止服务"""
        if self._server:
            self._server.stop(2)
            self._server = None
        self._running = False
        logger.info("Sys2 server stopped")

    def wait(self):
        """等待服务结束"""
        if self._server:
            self._server.wait_for_termination()


# ═══════════════════════════════════════════════════════════════
# Sys2 客户端 (供 Sys1/4060 使用)
# ═══════════════════════════════════════════════════════════════

class Sys2Client:
    """
    Sys2 推理客户端

    在 4060 (Sys1) 上使用，通过 gRPC 调用 4090 (Sys2) 的推理服务。

    用法:
        client = Sys2Client("4090-ip:50052")
        action = client.predict(observation, model="groot")
    """

    def __init__(self, server_addr: str = "localhost:50052"):
        self.server_addr = server_addr
        self._channel: Optional[grpc.Channel] = None

    def connect(self):
        """建立 gRPC 连接"""
        self._channel = grpc.insecure_channel(
            self.server_addr,
            options=[
                ('grpc.max_send_message_length', 100 * 1024 * 1024),
                ('grpc.max_receive_message_length', 100 * 1024 * 1024),
            ]
        )

    def _call(self, method: str, params: dict = None) -> dict:
        """调用远程方法"""
        if self._channel is None:
            self.connect()

        request = json.dumps({
            "method": method,
            "params": params or {},
        })

        # 使用 generic unary call
        response = grpc.unary_unary(
            f"/zmax.sys2.Sys2Service/HandleRequest",
            request_serializer=lambda x: x.encode('utf-8'),
            response_deserializer=lambda x: json.loads(x.decode('utf-8')),
        )

        try:
            result = response(request, timeout=30)
            return result if isinstance(result, dict) else json.loads(result)
        except Exception as e:
            return {"error": str(e)}

    def predict(
        self,
        images: np.ndarray = None,
        state: np.ndarray = None,
        force: np.ndarray = None,
        tactile: np.ndarray = None,
        gripper: float = 0.0,
        task_text: str = "",
        model: str = "auto",
    ) -> dict:
        """远程推理请求"""
        import base64
        import io
        from PIL import Image as PILImage

        # 编码图像
        images_b64 = ""
        if images is not None:
            if images.shape[0] == 3:  # (C,H,W) → (H,W,C)
                images = np.transpose(images, (1, 2, 0))
            if images.max() <= 1.0:
                images = (images * 255).astype(np.uint8)
            buf = io.BytesIO()
            PILImage.fromarray(images).save(buf, format="JPEG", quality=90)
            images_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

        return self._call("predict", {
            "images": images_b64,
            "state": state.tolist() if state is not None else [],
            "force": force.tolist() if force is not None else [],
            "tactile": tactile.tolist() if tactile is not None else [],
            "gripper": float(gripper),
            "task_text": task_text,
            "model": model,
        })

    def health(self) -> dict:
        return self._call("health")

    def status(self) -> dict:
        return self._call("status")

    def load_model(self, model_type: str = "all") -> dict:
        return self._call("load_model", {"model_type": model_type})


# ═══════════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════════

def main():
    """Sys2 服务启动入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Z-MAX Sys2 Inference Server (4090)")
    parser.add_argument("--vtla-model", type=str, default="lerobot/smolvla_base",
                        help="VTLA model path")
    parser.add_argument("--groot-model", type=str, default="",
                        help="GR00T model path")
    parser.add_argument("--embodiment-tag", type=str, default="new_embodiment",
                        help="GR00T embodiment tag")
    parser.add_argument("--grpc-port", type=int, default=50052,
                        help="gRPC port")
    parser.add_argument("--http-port", type=int, default=8080,
                        help="HTTP port")
    parser.add_argument("--load", type=str, default="vtla",
                        help="Models to load: all, vtla, groot, act")

    args = parser.parse_args()

    from lerobot.policies.zmax_sys2.configuration_zmax_sys2 import ZmaxSys2Config

    config = ZmaxSys2Config(
        vtla_model_path=args.vtla_model,
        groot_model_path=args.groot_model,
        groot_embodiment_tag=args.embodiment_tag,
        grpc_port=args.grpc_port,
        http_port=args.http_port,
    )

    from lerobot.policies.zmax_sys2.modeling_zmax_sys2 import ZmaxSys2Policy

    logger.info("Initializing Z-MAX Sys2 on 4090...")
    sys2 = ZmaxSys2Policy(config)
    sys2.load_models(args.load)

    loaded = sys2.list_loaded_models()
    logger.info(f"Loaded models: {loaded}")

    if not loaded:
        logger.warning("⚠️  No models loaded! Sys2 will return empty actions.")
        logger.warning("   Set --vtla-model or --groot-model to load models.")

    # 启动服务
    from lerobot.policies.zmax_sys2.sys2_server import Sys2GRPCServer
    server = Sys2GRPCServer(sys2, config)
    server.start()

    logger.info(f"""
╔══════════════════════════════════════════════════════╗
║     Z-MAX Sys2 Inference Server (4090)              ║
╠══════════════════════════════════════════════════════╣
║  gRPC : {config.grpc_host}:{config.grpc_port:<5}                          ║
║  HTTP : {config.http_host}:{config.http_port:<5}                          ║
║  VTLA : {'✅' if 'vtla' in loaded else '❌':<36} ║
║  GR00T: {'✅' if 'groot' in loaded else '❌':<36} ║
║  ACT  : {'✅' if 'act' in loaded else '❌':<36} ║
╚══════════════════════════════════════════════════════╝
""")

    try:
        server.wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.stop()


if __name__ == "__main__":
    main()
