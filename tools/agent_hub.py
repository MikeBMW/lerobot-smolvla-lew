#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent_hub.py — 工件机(Windows)反向通道的**我这端**。

背景: 工控机 192.168.23.23 只开 135/139/445/10081-10083, 22/3389/5985 全闭, SMB 匿名被拒
      ⇒ 我没有登录口, 但老倪可以在那台机器上贴一行命令 ⇒ 用**反向牵引(pull)**通道:
      他在那边开一个 PowerShell 窗口跑一小段循环, 循环来我这里**取命令**并把输出送回;
      我这边只管往本地队列里写命令(队列文件只有本机能写, 网络侧只能"取", 不能"投毒")。

接口(都带 token):
  GET  /agent/cmd?t=TOKEN   取一条待执行命令(取走即出队; 没有则返回 NONE)
  POST /agent/out?t=TOKEN   把命令的输出送回来(存 /tmp/zmax_agent_out/<n>.txt 并打印)
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

QUEUE_FILE = "/tmp/zmax_agent_cmd.jsonl"
OUT_DIR = "/tmp/zmax_agent_out"
LOG_FILE = "/tmp/zmax_agent.log"
_LOCK = threading.Lock()
STATE = {"token": "", "last_beat": 0.0, "served": 0, "outs": 0}


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
        return (q.get("t", [""])[0] or "") == STATE["token"]

    def _beat(self, who=""):
        """记一次 agent 侧活动, 并把时刻落到文件里 —— 让主节点(4060)的看门狗能不看日志就判通道死活。
           只认**远程**客户端(工控机)的活动, 本机自检/人工探测不算, 免得把死的通道探活成活的。"""
        STATE["last_beat"] = time.time()
        if who in ("127.0.0.1", "::1", "localhost", ""):
            return
        try:
            with open("/tmp/zmax_agent_beat", "w") as f:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8794)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--token", default="")
    ap.add_argument("--enqueue", default="")
    a = ap.parse_args()
    if a.enqueue:
        with _LOCK:
            with open(QUEUE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"cmd": a.enqueue, "t": time.time()}, ensure_ascii=False) + "\n")
        print("已入队: %s" % a.enqueue)
        return
    if not a.token:
        raise SystemExit("必须给 --token")
    STATE["token"] = a.token
    Handler.token = a.token
    Handler.root = a.dir
    os.makedirs(OUT_DIR, exist_ok=True)
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    _log("命令台启动: %s:%d  静态目录=%s" % (a.bind, a.port, a.dir))
    srv.serve_forever()


if __name__ == "__main__":
    main()
