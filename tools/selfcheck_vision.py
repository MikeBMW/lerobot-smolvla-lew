#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检: 把一张截图交给 L5 视觉大模型, 问它"看到了什么" —— 用来证明交付的画面真的可读。

老倪会目检画面细节 ⇒ 交图前必须自己先读一遍, 不能交没自检的图。
用法: selfcheck_vision.py <图片路径> [问题]
"""
import base64
import json
import os
import sys
import urllib.request

ENV = os.path.expanduser("~/.hermes/.env")


def _env(key, default=""):
    if os.environ.get(key):
        return os.environ[key]
    try:
        for ln in open(ENV, encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return default


def ask(img_path, question, timeout=180):
    base = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    key = _env("DEEPSEEK_API_KEY")
    model = _env("DEEPSEEK_VLM_MODEL", "deepseek-v4-flash")
    if not key:
        return {"ok": False, "err": "DEEPSEEK_API_KEY 未配置"}
    b64 = base64.b64encode(open(img_path, "rb").read()).decode()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
            {"type": "text", "text": question},
        ]}],
        "max_tokens": 3000,          # 推理型: 太小会被思考吃满导致 content 空
    }
    req = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode() or "{}")
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    return {"ok": True, "text": (msg.get("content") or "").strip(),
            "usage": d.get("usage")}


if __name__ == "__main__":
    p = sys.argv[1]
    q = sys.argv[2] if len(sys.argv) > 2 else (
        "这是 Z-MAX 手机 APP 里的『场景叠加』页面截图。请客观描述: "
        "① 页面上有哪些文字/按钮; ② 两张画面里能看到什么真实物体(机械臂/光模块/托盘/标定板等); "
        "③ 画面里有没有彩色的矩形检测框, 分别什么颜色、大致框住了什么。"
        "只描述你真实看到的, 看不清就说看不清。")
    r = ask(p, q)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2600])
