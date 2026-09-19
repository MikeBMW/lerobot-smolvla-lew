#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_vlm.py — 「场景理解 / 标定引导」大模型接口 (策略层, 画布节点只做瘦调用)

老倪 2026-09-19: 「增加一条从环境到 📝 任务指令 节点的数据通道 … 这个节点要能够看到场景,
你来选择一个模型 … 这个大模型可以指导标定 … 我现在缺少人工标定的工具, 利用大语言模型的
视觉和理解能力推进真实场景的标定。」

三条路径 (按优先级, 全部**诚实标注来源**, 拿不到就报 why, 绝不编):
  ① HTTP API  (SS_VLM_URL + SS_VLM_KEY, OpenAI 兼容 /chat/completions, 支持 data URL 图)
                例如 DashScope 兼容口: https://dashscope.aliyuncs.com/compatible-mode/v1
                     模型 qwen2.5-vl-7b-instruct / qwen-vl-max …
  ② 本地子进程 worker (tools/vlm_worker.py, transformers + torch): 开源 Qwen2.5-VL-3B-Instruct
                (默认) 或轻量 SmolVLM2-500M (仓库已有缓存); 常驻, 只加载一次 → 不卡画布主线程
  ③ 规则回退 (无模型可用时): 只把**确定性可得**的信息汇成场景摘要 (YOLO 框/位姿/阶段),
                明确标 "规则回退 (无 VLM)" —— 不假装是模型输出

对外 API:
  SceneVLM.describe(frame, ctx)   → 场景结构化描述 (目标/位置/是否夹持/朝向/质量/建议下一步)
  SceneVLM.guide(frame, ctx)      → 标定引导一步 (judgement / next_action / evidence)
  SceneVLM.quality(frame, ctx)    → 采集帧质检 (能不能拿去标定: 模糊/太远/出画/遮挡)
  SceneVLM.status()               → 当前生效路径与模型名 (面板要显示, 老倪红线: 自解释)
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_repo():
    """向上找仓库根 (含 tools/ + flows/ 的那层) —— 别写死层数, 目录深度一变就错"""
    d = _HERE
    for _ in range(8):
        d = os.path.dirname(d)
        if not d or d == "/":
            break
        if os.path.isdir(os.path.join(d, "tools")) and os.path.isdir(os.path.join(d, "flows")):
            return d
    return os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", ".."))


_REPO = _find_repo()
_WORKER = os.path.join(_REPO, "tools", "vlm_worker.py")
_PY = os.path.join(_REPO, "gui-venv311", "bin", "python")

# 视觉语言模型选型 (老倪 2026-09-19: 大模型层要"看到场景"):
#   · 默认本地开源 Qwen2.5-VL-3B-Instruct (无需 key, 8GB 4060 可跑)
#   · 可换 Qwen3-VL 系 (更强, 显存更大): SS_VLM_MODEL=Qwen/Qwen3-VL-8B-Instruct 等
#   · 或走 API: SS_VLM_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 + SS_VLM_KEY + SS_VLM_MODEL=qwen-vl-max
DEFAULT_MODEL = os.environ.get("SS_VLM_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct")
SYS_PROMPT = ("你是 Z-MAX 光模块插拔工位的现场视觉助手, 面向「把真实场景标定做对」这件事。"
              "只描述你**真的看到**的内容; 看不清就说看不清, 不要猜、不要编数字。"
              "回答用简体中文, 严格按要求的 JSON 格式, 不要输出多余文字。")


def _json_from(text):
    """从模型输出里抠出第一个 JSON 对象 (容错: 代码围栏/前后废话)"""
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(s[i:j + 1])
    except Exception:                                                          # noqa: BLE001
        return None


def _key_from_hermes_env(name):
    """从 ~/.hermes/.env 兜底取 key (GUI 进程 env 里常没有; 这样重启控制台也不用配)"""
    try:
        with open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except Exception:                                                          # noqa: BLE001
        pass
    return None


CALLS_LOG = os.path.expanduser(os.environ.get("SS_VLM_CALLS_LOG", "~/zmax_data/vlm_calls.jsonl"))


def _log_call(mode, image, r, ctx=None):
    """落盘每次判读 (UI 面板/history 的唯一数据源; 不落盘就没有可显示的东西)"""
    try:
        os.makedirs(os.path.dirname(CALLS_LOG), exist_ok=True)
        rec = {"ts": time.time(), "mode": mode, "frame": str(image),
               "src": r.get("src"), "latency_ms": r.get("latency_ms"),
               "ok": bool(r.get("ok")), "json": r.get("json"), "why": r.get("why"),
               "rule": r.get("rule"), "ctx": ctx}
        with open(CALLS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                                          # noqa: BLE001
        pass


class SceneVLM:
    """单例语义: 每进程一个 (worker 常驻, 反复问)"""

    _inst = None

    @classmethod
    def get(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self):
        # 三路径解析 (优先级: 显式 SS_VLM_URL/KEY > DeepSeek 自带 key (本机已配, 无需申请) > 本地开源 worker)
        #   · DeepSeek: deepseek-flash(DeepSeek-V4.1-Flash) **支持 Vision ✓** (官方 pricing 表; v4-pro 不支持)
        #     格式与 OpenAI 兼容完全一致 (content blocks + image_url data URL) —— 官方 Vision 指南 2026-09
        #   · Qwen: SS_VLM_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 + SS_VLM_KEY + model qwen-vl-max
        explicit_model = os.environ.get("SS_VLM_MODEL")
        self.url = os.environ.get("SS_VLM_URL") or None
        self.key = os.environ.get("SS_VLM_KEY") or None
        self.provider = "explicit" if self.url else None
        if not self.url:
            dsk = os.environ.get("DEEPSEEK_API_KEY") or _key_from_hermes_env("DEEPSEEK_API_KEY")
            if dsk:                                  # 本机 ~/.hermes/.env 已有 → 零申请成本, 直接可用
                self.url = os.environ.get("SS_VLM_BASE", os.environ.get("DEEPSEEK_BASE_URL",
                                                                        "https://api.deepseek.com"))
                self.key = dsk
                self.provider = "deepseek"
        if self.url:
            self.model = explicit_model or ("deepseek-flash" if self.provider == "deepseek" else "qwen-vl-max")
        else:
            self.model = explicit_model or DEFAULT_MODEL
        self.timeout = float(os.environ.get("SS_VLM_TIMEOUT", "60"))
        self.proc = None
        self.worker_ok = None
        self.worker_why = None
        self.calls = 0
        self.last = {}

    # ── 路径选择 ──
    def status(self):
        if self.url:
            tag = {"deepseek": "DeepSeek Vision (本机已配 key, 无需申请)",
                   "explicit": "OpenAI 兼容 API"}.get(self.provider or "", "OpenAI 兼容 API")
            return {"path": "http", "provider": self.provider, "model": self.model,
                    "detail": f"{tag} {self.url}" + ("" if self.key else " (无 key)")}
        return {"path": "local", "model": self.model,
                "detail": f"本地子进程 worker ({'已就绪' if self.worker_ok else '未验证'})"}

    def available(self):
        st = self.status()
        if st["path"] == "http":
            return bool(self.key), ("已在 HTTP 路径但缺 SS_VLM_KEY" if not self.key else "")
        return True, ""

    # ── ① HTTP (OpenAI 兼容, 图片走 data URL) ──
    def _ask_http(self, image, prompt, system=None, max_tokens=256):
        import urllib.request
        with open(image, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = "png" if str(image).lower().endswith("png") else "jpeg"
        body = {"model": self.model, "temperature": 0, "max_tokens": int(max_tokens),
                # DeepSeek 默认 thinking → 视觉判读实测 61.7s; 关掉后按需打开 (SS_VLM_THINKING=1)
                **({"thinking": {"type": "enabled" if os.environ.get("SS_VLM_THINKING") == "1" else "disabled"}}
                   if (self.provider == "deepseek" or "deepseek" in str(self.url)) else {}),
                "messages": ([{"role": "system", "content": system or SYS_PROMPT}] if True else []) + [
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}},
                        {"type": "text", "text": prompt}]}]}
        req = urllib.request.Request(self.url.rstrip("/") + "/chat/completions",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.key or ''}"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            d = json.loads(r.read().decode())
        return {"ok": True, "text": d["choices"][0]["message"]["content"],
                "latency_ms": int((time.time() - t0) * 1000), "src": f"http:{self.model}"}

    # ── ② 本地子进程 worker ──
    def _ensure_worker(self):
        if self.worker_ok is not None:
            return self.worker_ok
        if not (os.path.exists(_WORKER) and os.path.exists(_PY)):
            self.worker_ok, self.worker_why = False, f"worker 或解释器不存在 ({_WORKER} / {_PY})"
            return False
        env = dict(os.environ)
        env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        try:
            self.proc = subprocess.Popen([_PY, _WORKER, "--model", self.model], cwd=_REPO, env=env,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=open(os.path.join(os.path.expanduser("~"), "zmax_data",
                                                                  "vlm_worker.log"), "a"),
                                         text=True, bufsize=1)
            hello = self._rpc({"cmd": "hello"}, timeout=max(600.0, self.timeout))
            self.worker_ok = bool(hello and hello.get("ok"))
            self.worker_why = None if self.worker_ok else (hello or {}).get("why", "worker 无应答")
        except Exception as e:                                                 # noqa: BLE001
            self.worker_ok, self.worker_why = False, f"{type(e).__name__}: {e}"
        return self.worker_ok

    def _rpc(self, req, timeout=120.0):
        if self.proc is None or self.proc.poll() is not None:
            return None
        try:
            self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception as e:                                                 # noqa: BLE001
            return {"ok": False, "why": f"写 worker 失败: {e}"}
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    return {"ok": False, "why": f"worker 退出 (rc={self.proc.returncode})"}
                continue
            try:
                return json.loads(line)
            except Exception:                                                  # noqa: BLE001
                continue
        return {"ok": False, "why": f"worker 超时 {timeout}s"}

    def _ask_local(self, image, prompt, system=None, max_tokens=256):
        if not self._ensure_worker():
            return {"ok": False, "why": f"本地 worker 不可用: {self.worker_why}"}
        r = self._rpc({"cmd": "ask", "image": image, "prompt": prompt,
                       "system": system or SYS_PROMPT, "max_tokens": int(max_tokens)},
                      timeout=max(180.0, self.timeout))
        if r and r.get("ok"):
            r["src"] = f"local:{self.model}"
        return r or {"ok": False, "why": "worker 无应答"}

    # ── ③ 规则回退 (确定性信息, 明确标注) ──
    @staticmethod
    def _rule_digest(frame, ctx):
        c = ctx or {}
        box = c.get("box")
        tcp = c.get("tcp")
        parts = [f"帧 {os.path.basename(str(frame)) if frame else '无'}"]
        if c.get("frame_age_s") is not None:
            parts.append(f"帧龄 {c['frame_age_s']}s")
        if box:
            w, h = box[2] - box[0], box[3] - box[1]
            parts.append(f"检测框 {[round(v,1) for v in box]} ({w:.0f}x{h:.0f}px, 中心 "
                         f"({(box[0]+box[2])/2:.0f},{(box[1]+box[3])/2:.0f}))")
        else:
            parts.append("无检测框")
        if tcp:
            parts.append(f"TCP [{tcp[0]:.3f} {tcp[1]:.3f} {tcp[2]:.3f}]m")
        if c.get("conf") is not None:
            parts.append(f"conf {c['conf']}")
        if c.get("stage"):
            parts.append(f"阶段 {c['stage']}")
        return " · ".join(parts)

    # ── 统一入口 ──
    def ask(self, image, prompt, system=None, max_tokens=256, ctx=None, allow_rule=True):
        """返回 {ok, text, src, latency_ms} 或 {ok:False, why} (规则回退时 src='rule')"""
        self.calls += 1
        if self.url and self.key:
            try:
                r = self._ask_http(image, prompt, system, max_tokens)
            except Exception as e:                                             # noqa: BLE001
                r = {"ok": False, "why": f"HTTP 调用失败: {type(e).__name__}: {e}"}
            if r.get("ok"):
                self.last = r
                return r
            http_why = r.get("why")
        else:
            http_why = None
        if not self.url:
            r = self._ask_local(image, prompt, system, max_tokens)
            if r.get("ok"):
                self.last = r
                return r
            if not allow_rule:
                return r
            return {"ok": False, "why": r.get("why", "本地 worker 不可用"),
                    "rule": self._rule_digest(image, ctx), "src": "rule"}
        if http_why and not allow_rule:
            return {"ok": False, "why": http_why}
        return {"ok": False, "why": http_why or "无可用 VLM 路径",
                "rule": self._rule_digest(image, ctx), "src": "rule"}

    # ── 高层语义 ──
    def describe(self, image, ctx=None):
        """场景结构化描述 (标定/任务都用这一份)"""
        p = ("看这张工位相机图, 只回答 JSON:\n"
             '{"目标可见": true/false, "目标是什么": "…", "目标位置": "画面左上/中上/…", '
             '"在夹爪上吗": true/false/"看不清", "朝向": "…", '
             '"画面质量": {"模糊": bool, "过暗或过曝": bool, "太远或太小": bool, "被遮挡": bool}, '
             '"光照": "…", "背景线索": "你能看到的工装/托盘/标定板等", '
             '"标定建议": "下一步该让操作员做什么(一句话, 具体动哪个动作)"}\n'
             "看不清的字段写 \"看不清\", 不要编。只输出 JSON, 第一个字符必须是 {")
        r = self.ask(image, p, ctx=ctx)
        if r.get("ok"):
            j = _json_from(r.get("text"))
            r["json"] = j
            r["ok"] = bool(j)
            if not j:
                r["why"] = f"模型输出不是合法 JSON: {str(r.get('text'))[:120]!r}"
        _log_call("describe", image, r, ctx)
        return r

    def guide(self, image, ctx=None):
        """标定引导一步: 现在这帧能不能用 + 下一步让操作员做什么"""
        p = ("你是 Z-MAX 真机标定向导。目标: 用『相机 + 机器人自身位姿』把光模块的 3D 位置标定准。\n"
             "看这张实时图, 只回答 JSON:\n"
             '{"这帧可用": true/false, "不能用原因": "模糊/太远/出画/遮挡/没看到目标/…或空", '
             '"看见的目标个数": 整数, "目标是否在夹爪里": true/false/"看不清", '
             '"下一步动作": "给操作员的一句具体指令", "为什么": "一句理由", '
             '"验收判据": "做完这步我应该在图里看到什么"}\n'
             "只描述真的看到的。只输出 JSON, 第一个字符必须是 {")
        r = self.ask(image, p, ctx=ctx, max_tokens=320)
        if r.get("ok"):
            j = _json_from(r.get("text"))
            r["json"] = j
            r["ok"] = bool(j)
            if not j:
                r["why"] = f"模型输出不是合法 JSON: {str(r.get('text'))[:120]!r}"
        _log_call("guide", image, r, ctx)
        return r

    def quality(self, image, ctx=None):
        """采集帧质检 (标定数据准入)"""
        p = ('判断这张标定采集帧是否合格, 只回答 JSON:\n'
             '{"合格": true/false, "问题": ["模糊","过暗","目标出画","目标太小","被遮挡"], '
             '"目标清晰度": 0-1 的小数, "周边是否有干扰物": true/false}\n'
             "只描述真的看到的; 没问题就给空数组。")
        r = self.ask(image, p, ctx=ctx, max_tokens=200)
        if r.get("ok"):
            j = _json_from(r.get("text"))
            r["json"] = j
            r["ok"] = bool(j)
            if not j:
                r["why"] = f"模型输出不是合法 JSON: {str(r.get('text'))[:120]!r}"
        _log_call("quality", image, r, ctx)
        return r

    def close(self):
        try:
            if self.proc is not None and self.proc.poll() is None:
                self._rpc({"cmd": "bye"}, timeout=5)
                self.proc.terminate()
        except Exception:                                                      # noqa: BLE001
            pass
        self.proc = None
        self.worker_ok = None


def main():
    """CLI: 快速试一张图 (标定向导要先能手工验证)"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--mode", choices=["describe", "guide", "quality"], default="describe")
    ap.add_argument("--ctx", default=None, help="JSON 串: box/tcp/conf/stage/frame_age_s")
    a = ap.parse_args()
    ctx = json.loads(a.ctx) if a.ctx else None
    v = SceneVLM.get()
    print("路径:", json.dumps(v.status(), ensure_ascii=False))
    r = getattr(v, a.mode)(a.image, ctx)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
