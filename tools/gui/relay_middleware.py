#!/usr/bin/env python3
"""📡 Z-MAX 控制台中间件消息通道 (2026-08-09 老倪: 控制台封装统一消息通道)

背景: 本地 WSL (172.18.x) 与 Orin (192.168.23.x) 不同网段 — 直连永远不通。
      一切远程硬件操作 (塔灯/部署/摄像头/Orin状态) 统一经 ECS relay 中转。

通道模型:
    [控制台] --POST /api/relay/command--> [ECS relay] --轮询 GET /command--> [Mac 守护]
        ^                                                        | ssh tashan@.66
        └---------- GET /api/relay/command (结果/状态) <---------- [Orin 执行]

用法:
    mw = RelayMiddleware()                    # 单例
    mw.send("tower_light green")              # 下发指令 (不等待执行)
    mw.request("tower_light green", wait=15)  # 下发 + 轮询确认 (指令被消费)
    mw.status()                               # ECS 中转状态
    mw.orin_status()                          # Orin 在线/模型/推理计数
    mw.snapshot_bytes()                       # 摄像头最新帧 JPEG
"""
import os
import time
import json
import threading
import logging
import requests as _rq

_log = logging.getLogger("zmax.middleware")

# 唯一后端入口 (nginx → relay 39053); 旧 106.75.239.80:50053 已废
RELAY_BASE = os.environ.get("ZMAX_RELAY", "https://datadrive.world/api/relay")
SNAPSHOT_URL = "https://datadrive.world/api/snapshot/latest"
WS_URL = os.environ.get("ZMAX_WS", "wss://datadrive.world/ws")  # WebSocket 实时通道


class RelayError(Exception):
    """中间件通道错误 (网络/HTTP/relay 端)"""


class RelayMiddleware:
    """📡 统一消息通道 — 所有远程/硬件操作经此中转"""

    def __init__(self, base=RELAY_BASE, timeout=10):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._session = _rq.Session()

    # ─── 指令下发 ───
    def send(self, cmd: str, timeout=None) -> dict:
        """下发指令到 ECS relay (Mac 守护轮询执行)。返回 relay 响应。"""
        try:
            r = self._session.post(f"{self.base}/command", json={"cmd": cmd},
                                   timeout=timeout or self.timeout)
            r.raise_for_status()
            return r.json()
        except _rq.RequestException as e:
            raise RelayError(f"指令下发失败: {e}") from e

    def request(self, cmd: str, wait=15, poll=3) -> dict:
        """下发指令 + 轮询等待 relay 确认 (指令被消费/覆盖)。超时抛 RelayError。"""
        resp = self.send(cmd)
        deadline = time.time() + wait
        while time.time() < deadline:
            cur = self.peek()
            # 指令已被执行/消费 (command.json 变化或清空)
            if cur.get("cmd") != cmd and cur.get("cmd") not in (None, ""):
                return {"sent": cmd, "relay": resp, "consumed_by": cur.get("cmd")}
            time.sleep(poll)
        raise RelayError(f"指令未在 {wait}s 内被消费: {cmd}")

    def peek(self) -> dict:
        """读取当前 relay 指令 (Mac 轮询视角)"""
        try:
            r = self._session.get(f"{self.base}/command", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except _rq.RequestException as e:
            raise RelayError(f"指令读取失败: {e}") from e

    # ─── 状态查询 ───
    def status(self) -> dict:
        """ECS 中转状态 (在线/队列/最新包)"""
        try:
            r = self._session.get(f"{self.base}/status", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except _rq.RequestException as e:
            raise RelayError(f"ECS 中转状态查询失败: {e}") from e

    def orin_status(self) -> dict:
        """Orin 状态 (在线/模型/推理计数/CPU/内存)"""
        try:
            r = self._session.get(f"{self.base}/orin/status", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except _rq.RequestException as e:
            raise RelayError(f"Orin 状态查询失败: {e}") from e

    # ─── 摄像头 ───
    def snapshot_bytes(self, timeout=None) -> bytes:
        """摄像头最新帧 JPEG (Orin 快照归档)"""
        try:
            r = _rq.get(f"{SNAPSHOT_URL}?t={int(time.time())}",
                        timeout=timeout or self.timeout)
            if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image"):
                return r.content
            raise RelayError(f"快照端点异常: HTTP {r.status_code}")
        except _rq.RequestException as e:
            raise RelayError(f"快照获取失败: {e}") from e

    # ─── 健康检查 ───
    def health(self) -> dict:
        """全链路健康: ECS 中转 + Orin + 快照"""
        h = {"ecs": False, "orin": False, "snapshot": False}
        try:
            self.status()
            h["ecs"] = True
        except RelayError:
            pass
        try:
            self.orin_status()
            h["orin"] = True
        except RelayError:
            pass
        try:
            self.snapshot_bytes()
            h["snapshot"] = True
        except RelayError:
            pass
        return h


class WSClient:
    """🔌 WebSocket 实时通道客户端 (2026-08-09 老倪: 接通 ws/orin — 实时推送, 非轮询)

    订阅 ECS ws_relay (:8765): 实时接收 orin_status / data_arrived 事件。
    断线自动重连 (5s 退避), 事件经回调分发到主线程。
    """

    def __init__(self, url=WS_URL, on_event=None, on_status=None, autostart=True):
        self.url = url
        self.on_event = on_event      # callable(event_dict) — 所有事件
        self.on_status = on_status    # callable(orin_status_dict) — orin_status 专用
        self._stop = threading.Event()
        self._thread = None
        self._connected = False
        self._last_event = None
        self._last_status = None
        if autostart:
            self.start()

    # ─── 线程控制 ───
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="zmax-ws-client")
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_status(self) -> dict:
        return self._last_status or {}

    @property
    def last_event(self) -> dict:
        return self._last_event or {}

    # ─── 主循环 (后台线程) ───
    def _run(self):
        import websocket as _ws
        while not self._stop.is_set():
            try:
                ws = _ws.create_connection(self.url, timeout=10)
                self._connected = True
                ws.settimeout(10)
                while not self._stop.is_set():
                    try:
                        raw = ws.recv()
                        if not raw:
                            continue
                        evt = json.loads(raw)
                        self._last_event = evt
                        if evt.get("type") == "orin_status":
                            self._last_status = evt
                            if self.on_status:
                                self.on_status(evt)
                        if self.on_event:
                            self.on_event(evt)
                    except Exception:
                        break  # 接收超时/断开 → 重连
            except Exception as e:
                _log.warning("WS 连接失败: %s (5s 后重连)", e)
            finally:
                self._connected = False
                try:
                    ws.close()
                except Exception:
                    pass
            self._stop.wait(5)  # 重连退避


# 单例 (控制台全局复用)
_mw = None


def get_middleware() -> RelayMiddleware:
    global _mw
    if _mw is None:
        _mw = RelayMiddleware()
    return _mw
