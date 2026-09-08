"""🧠 VLM 真实视觉编码器 — SmolVLM2-500M-Video-Instruct 单例懒加载

位置: src/lerobot/policies/smolvla_lew/ (框架层真实算法 — 老倪: 真实算法在 src,
GUI 只做调用壳; node_ss_vlm 通过 exec(compile(真实路径)) 加载本模块 → 断点可进)

SmolVLM2 视觉骨干 = smolvla_lew 策略的通用视觉编码器 (VLM→潜空间 z 高级功能)。
node_ss_vlm 真实路径: 图像帧 → processor → 模型全前向 → hidden_states[-1]
mean-pool → z ∈ R⁹⁶⁰ (仿 _get_multimodal_embeds 通道)。

- 首次加载 ~15s (权重 1GB fp16), 显存峰值 ~1.4GB (4060 无压力) — 后台加载不卡 GUI
- encode() 仅在 ready 后可用; 未就绪返回 {"status": "loading/error"} 不抛异常
- 模型实例进程级单例 (只加载一次)
- 无 GUI 依赖 (torch/transformers/PIL/numpy only) — 框架层纯净

2026-09-08 静静: 真实感知侧接入第一步 (老倪: 感知侧先真实化; 算法层归位 src)
"""
import os
import threading
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

MODEL_ID = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"

_inst = None
_inst_lock = threading.Lock()


def get_encoder():
    """进程级单例"""
    global _inst
    with _inst_lock:
        if _inst is None:
            _inst = SmolVLMEncoder()
        return _inst


class SmolVLMEncoder:
    """SmolVLM 视觉编码器 — 真实前向 → 潜空间特征 (池化摘要)"""

    def __init__(self):
        self.status = "idle"          # idle | loading | ready | error
        self.error = None
        self.proc = None
        self.model = None
        self.load_ms = 0.0
        self._lock = threading.Lock()   # 推理互斥 (encode 串行)
        self._thread = None

    # ── 加载 ──
    def ensure_loaded_async(self):
        """后台线程加载 (主线程不卡); 已加载/加载中则直接返回"""
        if self.status in ("loading", "ready"):
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self.status = "loading"
        self._thread = threading.Thread(target=self._load, daemon=True)
        self._thread.start()

    def _load(self):
        t0 = time.time()
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
            self.proc = AutoProcessor.from_pretrained(MODEL_ID)
            self.model = AutoModelForImageTextToText.from_pretrained(
                MODEL_ID, torch_dtype=torch.float16).to("cuda")
            self.model.eval()
            self.load_ms = (time.time() - t0) * 1000
            self.status = "ready"
        except Exception as e:          # 任何异常不得外泄炸调用方
            self.status = "error"
            self.error = repr(e)[:300]

    def wait_loaded(self, timeout_s=60):
        """阻塞等就绪 (短任务可用); 返回 True=ready"""
        if self.status == "ready":
            return True
        t_end = time.time() + timeout_s
        while time.time() < t_end and self.status == "loading":
            time.sleep(0.2)
        return self.status == "ready"

    # ── 推理 ──
    def encode(self, pil_image, text=""):
        """单帧真实编码: 图像 → 多模态序列 hidden[-1] → mean-pool 潜空间 z

        Returns:
            dict: {status: "ok", dim, tokens, z_mean/z_std/z_norm, top5, ms, model}
                  {status: "loading"/"error", ...} — 不抛异常
        """
        if self.status == "loading":
            return {"status": "loading", "msg": "VLM 权重加载中 (首次 ~15s)"}
        if self.status != "ready" or self.model is None:
            return {"status": "error", "msg": self.error or "VLM 未就绪"}
        try:
            import torch
            with self._lock:
                t0 = time.time()
                out = self.proc(images=[pil_image], text=f"<image>{text}", return_tensors="pt")
                pv = out["pixel_values"].to("cuda", dtype=torch.float16)
                ids = out["input_ids"].to("cuda")
                with torch.no_grad():
                    r = self.model(pixel_values=pv, input_ids=ids,
                                   output_hidden_states=True, return_dict=True)
                h = r.hidden_states[-1].float()               # [1, seq, 960]
                seq = h.shape[1]
                z = h.mean(dim=1)[0]                          # mean-pool → 960 维
                ms = (time.time() - t0) * 1000
                return {
                    "status": "ok",
                    "model": "SmolVLM2-500M",
                    "dim": int(z.shape[0]),
                    "tokens": int(seq),
                    "z_mean": float(z.mean()),
                    "z_std": float(z.std()),
                    "z_norm": float(z.norm()),
                    "top5": [round(float(v), 3) for v in torch.topk(z, 5).values],
                    "ms": round(ms, 1),
                    "load_ms": round(self.load_ms, 0),
                }
        except Exception as e:
            return {"status": "error", "msg": repr(e)[:300]}


if __name__ == "__main__":
    # CLI 自测 (无 GUI 依赖): 合成图走一遍真实前向
    import numpy as np
    from PIL import Image
    enc = get_encoder()
    enc.ensure_loaded_async()
    print("加载中...", flush=True)
    ok = enc.wait_loaded(120)
    if not ok:
        print("❌ 加载失败:", enc.error); raise SystemExit(1)
    print(f"✅ 加载完成 {enc.load_ms:.0f}ms")
    img = Image.fromarray(np.zeros((480, 480, 3), dtype=np.uint8))
    res = enc.encode(img)
    print("编码结果:", {k: v for k, v in res.items() if k != "top5"})
