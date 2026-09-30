#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent_hub.py — 工件机(Windows)反向通道的**我这端**。

背景: 工控机 192.168.23.23 只开 135/139/445/10081-10083, 22/3389/5985 全闭, SMB 匿名被拒
      ⇒ 我没有登录口, 但老倪可以在那台机器上贴一行命令 ⇒ 用**反向牵引(pull)**通道:
      他在那边开一个 PowerShell 窗口跑一小段循环, 循环来我这里**取命令**并把输出送回;
      我这边只管往本地队列里写命令(队列文件只有本机能写, 网络侧只能"取", 不能"投毒")。

接口(都带 token):
  GET  /agent/cmd?t=TOKEN   取一条待执行命令(取走即出队; 没有则返回 NONE)
  POST /agent/out?t=TOKEN   把命令的输出送回来(存 ~/zmax_data/agent_hub/out/<n>.txt 并打印)
  GET  /agent/beat?t=TOKEN  心跳(看那边还活着)
  GET  /agent/log?t=TOKEN   看最近几条命令/输出(人在手机上也能瞄一眼)
其余路径照旧当静态文件服务(交付包下载不受影响)。
用法: python3 tools/agent_hub.py --port 8794 --dir <静态目录> --token <TOKEN>
入队: python3 tools/agent_hub.py --enqueue "命令" [--port 8794]
"""
import argparse
import json
import os
import queue
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# ⚠️ 2026-09-29 踩坑: 运行态文件**不能再放 /tmp** —— 本机 ubuntu 用 CLI 入队/服务以 root 跑,
#    root 去"重写"一个 ubuntu 属主的 /tmp 文件会被内核 `fs.protected_regular`(sticky 目录保护)拒掉:
#    PermissionError: '/tmp/zmax_agent_cmd.jsonl' ⇒ 队列取不走, 通道**看着断着其实是权限**
#    (现象: 客户端每 5s 来 GET /agent/cmd 都 403/报错, served 恒为 0)
#    ⇒ 运行态统一放数据目录(非 sticky 目录, 两个属主都能写)。
HUB_DATA = os.environ.get("ZMAX_AGENT_DATA", "/home/ubuntu/zmax_data/agent_hub")
OUT_DIR = os.path.join(HUB_DATA, "out")
LOG_FILE = os.path.join(HUB_DATA, "hub.log")
BEAT_FILE = os.path.join(HUB_DATA, "beat")
BEAT_FILE_LEGACY = "/tmp/zmax_agent_beat"        # 兼容老看门狗脚本(aoi_watch.sh)读取
QUEUE_FILE = os.path.join(HUB_DATA, "cmd.jsonl")
_LOCK = threading.Lock()
STATE = {"token": "", "tokens": set(), "last_beat": 0.0, "served": 0, "outs": 0}


def _log(msg: str):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _pop_cmd() -> str:
    """从本地队列取一条(取走即删)。队列文件只有本机进程能写 ⇒ 网络侧无法投毒。"""
    with _LOCK:
        try:
            with open(QUEUE_FILE, encoding="utf-8") as f:
                lines = [x for x in f.read().splitlines() if x.strip()]
        except OSError:
            return "NONE"
        if not lines:
            return "NONE"
        head, rest = lines[0], lines[1:]
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(rest) + ("\n" if rest else ""))
    try:
        return json.loads(head)["cmd"]
    except Exception:                                                          # noqa: BLE001
        return head


class Handler(SimpleHTTPRequestHandler):
    token = ""
    root = "."

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=Handler.root, **kw)

    def log_message(self, *_a):          # 静音默认访问日志(只留我们自己的)
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok_token(self, q) -> bool:
        """v2 (2026-09-29): 允许多个 token(逗号分隔)。
        起因: 工控机上那条轮询循环带的 token 与 agent 脚本里的写法不同(一个是轮询态、一个是固定串),
        一直 403 ⇒ 通道"看着断着"其实客户端活着。多 token 兼容, 不让一个字的差异卡死整条链路。
        ⚠️ 2026-09-30: token 真值不再写进代码/单元 —— 见 _resolve_token(), 从 env 或本机 secrets 读。"""
        v = (q.get("t", [""])[0] or "")
        return bool(v) and (v == STATE["token"] or v in (STATE.get("tokens") or set()))

    def _beat(self, who=""):
        """记一次 agent 侧活动, 并把时刻落到文件里 —— 让主节点(4060)的看门狗能不看日志就判通道死活。
           只认**远程**客户端(工控机)的活动, 本机自检/人工探测不算, 免得把死的通道探活成活的。"""
        STATE["last_beat"] = time.time()
        if who in ("127.0.0.1", "::1", "localhost", ""):
            return
        for p in (BEAT_FILE, BEAT_FILE_LEGACY):
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write("%.3f" % STATE["last_beat"])
            except OSError:
                pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path.startswith("/agent/"):
            if not self._ok_token(q):
                return self._json(403, {"ok": False, "msg": "token 不对"})
            who = self.client_address[0]
            if u.path == "/agent/cmd":
                self._beat(who)
                cmd = _pop_cmd()
                if cmd != "NONE":
                    STATE["served"] += 1
                    _log("→ 给 %s 下发: %s" % (who, cmd[:160]))
                return self._text(200, cmd)
            if u.path == "/agent/beat":
                self._beat(who)
                return self._json(200, {"ok": True, "last_beat": STATE["last_beat"],
                                        "served": STATE["served"], "outs": STATE["outs"]})
            if u.path == "/agent/log":
                try:
                    txt = open(LOG_FILE, encoding="utf-8").read()[-4000:]
                except OSError:
                    txt = ""
                return self._text(200, txt)
            return self._json(404, {"ok": False, "msg": "no route"})
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/agent/out":
            if not self._ok_token(q):
                return self._json(403, {"ok": False, "msg": "token 不对"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            body = self.rfile.read(n).decode("utf-8", "ignore") if n else ""
            os.makedirs(OUT_DIR, exist_ok=True)
            fn = os.path.join(OUT_DIR, "%d.txt" % int(time.time()))
            with open(fn, "w", encoding="utf-8") as f:
                f.write(body)
            STATE["outs"] += 1
            STATE["last_beat"] = time.time()
            _log("← %s 回执 %d 字节 → %s" % (self.client_address[0], len(body), fn))
            for ln in body.splitlines()[:12]:
                print("      | " + ln[:150], flush=True)
            return self._json(200, {"ok": True})
        return self._json(404, {"ok": False, "msg": "no route"})


def _resolve_token(cli_token: str) -> str:
    """token 真值来源优先级: --token 参数 → 环境变量 ZMAX_AGENT_TOKEN → 本机 secrets 文件。

    2026-09-30: 以前真值直接写在这份代码和 systemd 单元里 ⇒ 公开仓库等于把通道密钥贴出去。
    现在代码/单元里只有 `$ZMAX_AGENT_TOKEN` 占位, 真值只落在 /home/ubuntu/zmax_data/secrets/zmax.env (600)。
    找不到值就 fail-closed(拒绝启动), 不当成"没密钥也能跑"。
    """
    if cli_token:
        return cli_token
    v = (os.environ.get("ZMAX_AGENT_TOKEN") or "").strip()
    if v:
        return v
    for p in (os.environ.get("ZMAX_SECRETS_FILE") or "", "/home/ubuntu/zmax_data/secrets/zmax.env"):
        if not p or not os.path.isfile(p):
            continue
        try:
            for ln in open(p, encoding="utf-8"):
                if ln.strip().startswith("ZMAX_AGENT_TOKEN="):
                    return ln.split("=", 1)[1].strip()
        except OSError:
            continue
    raise SystemExit(
        "缺少 agent hub token: 给 --token、或设置环境变量 ZMAX_AGENT_TOKEN、\n"
        "或写入 /home/ubuntu/zmax_data/secrets/zmax.env (键名 ZMAX_AGENT_TOKEN)。\n"
        "首次部署: bash tools/zmax_bootstrap.sh --secrets  可生成占位文件。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8794)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--token", default="", help="可逗号分隔多个(兼容旧客户端); 缺省从 env/secrets 读")
    ap.add_argument("--enqueue", default="")
    a = ap.parse_args()
    if a.enqueue:
        with _LOCK:
            with open(QUEUE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"cmd": a.enqueue, "t": time.time()}, ensure_ascii=False) + "\n")
        print("已入队: %s" % a.enqueue)
        return
    a.token = _resolve_token(a.token)
    STATE["token"] = a.token.split(",")[0].strip()
    STATE["tokens"] = {x.strip() for x in a.token.split(",") if x.strip()}
    Handler.token = a.token
    Handler.root = a.dir
    os.makedirs(OUT_DIR, exist_ok=True)
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    _log("命令台启动: %s:%d  静态目录=%s" % (a.bind, a.port, a.dir))
    srv.serve_forever()


if __name__ == "__main__":
    main()
