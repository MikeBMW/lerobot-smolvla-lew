#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vlm_worker.py — 常驻 VLM worker (子进程桥): 装载视觉语言模型, 行式 JSON 协议应答

为什么要子进程 (老倪 2026-09-19 任务: 让「📝 任务指令」节点能"看到场景", 用它推进真实标定):
  · 画布是 Qt 主线程 —— 在主线程里跑一次 VLM 前向 = 界面卡死 (不可接受);
  · 模型重 (Qwen2.5-VL-3B 等), 要在**独立进程**里只加载一次, 反复问 (标定向导要每次采帧都问).
  形态与既有跨 venv 桥一致: 节点侧只认协议, 不认实现。

协议 (stdin/stdout 行式 JSON; **协议只走 fd 1 的副本**, 库日志一律转 stderr —— 见跨 venv 技能坑):
  {"cmd":"hello"}                          → {"ok":true,"model":...,"device":...,"loaded":true}
  {"cmd":"ask","image":"<png/jpg路径>","prompt":"...","system":"...","max_tokens":256}
                                           → {"ok":true,"text":"...","latency_ms":1234}
  {"cmd":"bye"}                            → {"ok":true}

用法 (常驻, 由 scene_vlm.SceneVLMClient 自动拉起, 也可手工跑):
  gui-venv311/bin/python tools/vlm_worker.py --model Qwen/Qwen2.5-VL-3B-Instruct --device cuda:0
  Qwen2.5-VL 未下载时可用轻量: --model HuggingFaceTB/SmolVLM2-500M-Video-Instruct
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_PROTO = os.fdopen(os.dup(1), "w", buffering=1)      # 协议通道 (库日志不许污染它)
sys.stdout = sys.stderr


def _reply(d):
    _PROTO.write(json.dumps(d, ensure_ascii=False) + "\n")
    _PROTO.flush()


class VLM:
    def __init__(self, model_id, device="cuda:0", max_pixels=None, dtype=None):
        self.model_id = model_id
        self.device = device
        self.max_pixels = max_pixels
        self.dtype = dtype
        self.model = None
        self.proc = None
        self.load_err = None

    def load(self):
        if self.model is not None or self.load_err:
            return
        t0 = time.time()
        try:
            import torch
            from transformers import AutoProcessor
            from transformers import AutoModelForImageTextToText as AutoVLM
            kw = {}
            if self.dtype == "bf16":
                kw["torch_dtype"] = torch.bfloat16
            elif self.dtype == "fp16":
                kw["torch_dtype"] = torch.float16
            try:
                self.model = AutoVLM.from_pretrained(self.model_id, device_map=self.device, **kw)
            except Exception:                                              # noqa: BLE001
                self.model = AutoVLM.from_pretrained(self.model_id, device_map="auto", **kw)
            self.proc = AutoProcessor.from_pretrained(self.model_id)
            # 大幅限制视觉 token (标定场景只需"看得见目标/朝向/是否被夹"), 省显存与时间
            if self.max_pixels:
                try:
                    self.proc.image_processor.max_pixels = int(self.max_pixels)
                    self.proc.image_processor.min_pixels = 4 * 28 * 28
                except Exception:                                          # noqa: BLE001
                    pass
            sys.stderr.write(f"[vlm_worker] loaded {self.model_id} on {self.device} in {time.time()-t0:.1f}s\n")
        except Exception as e:                                             # noqa: BLE001
            self.load_err = f"{type(e).__name__}: {e}"
            sys.stderr.write(f"[vlm_worker] load failed: {self.load_err}\n")

    def ask(self, image, prompt, system=None, max_tokens=256):
        self.load()
        if self.model is None:
            return {"ok": False, "why": f"模型未装载: {self.load_err}"}
        try:
            import torch
            from PIL import Image
            img = Image.open(image).convert("RGB") if isinstance(image, str) else image
            msgs = []
            if system:
                msgs.append({"role": "system", "content": [{"type": "text", "text": system}]})
            msgs.append({"role": "user", "content": [{"type": "image", "image": img},
                                                     {"type": "text", "text": prompt}]})
            t0 = time.time()
            text = self.proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
            inputs = self.proc(text=[text], images=[img], return_tensors="pt", padding=True).to(self.model.device)
            with torch.inference_mode():
                out = self.model.generate(**inputs, max_new_tokens=int(max_tokens), do_sample=False)
            gen = out[:, inputs["input_ids"].shape[1]:]
            res = self.proc.batch_decode(gen, skip_special_tokens=True)[0].strip()
            return {"ok": True, "text": res, "latency_ms": int((time.time() - t0) * 1000)}
        except Exception as e:                                             # noqa: BLE001
            import traceback
            return {"ok": False, "why": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-600:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("SS_VLM_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct"))
    ap.add_argument("--device", default=os.environ.get("SS_VLM_DEVICE", "cuda:0"))
    ap.add_argument("--dtype", default=os.environ.get("SS_VLM_DTYPE"))          # bf16/fp16/None
    ap.add_argument("--max-pixels", type=int, default=int(os.environ.get("SS_VLM_MAX_PIXELS", "501760")))
    a = ap.parse_args()
    v = VLM(a.model, a.device, a.max_pixels, a.dtype)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:                                             # noqa: BLE001
            _reply({"ok": False, "why": f"协议解析失败: {e}"}); continue
        cmd = req.get("cmd")
        if cmd == "hello":
            v.load()
            _reply({"ok": v.model is not None, "model": v.model_id, "device": a.device,
                    "loaded": v.model is not None, "why": v.load_err})
        elif cmd == "ask":
            r = v.ask(req.get("image"), req.get("prompt", ""), req.get("system"),
                      req.get("max_tokens", 256))
            _reply(r)
        elif cmd == "bye":
            _reply({"ok": True}); break
        else:
            _reply({"ok": False, "why": f"未知命令 {cmd}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
