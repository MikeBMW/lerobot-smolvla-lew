#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_dds_lite.py — DDS 观测层后端 (仅供 ss_topic_bus 启用时加载)
==================================================================
设计要点:
  · 本模块**只在 ZMAX_SS_TOPIC_MODE != off 时被 import**
    → 量产模式下进程里没有 cyclonedds/websockets, 也无 RTPS 端口
  · 双通道:
      远端 (跨公网) → ECS WebSocket DDS 网关 (wss://datadrive.world/ws/dds/)
      本机 (局域网) → 原生 CycloneDDS (可选, 需 ZMAX_SS_LOCAL_DDS=1)
  · 线程池异步发送 + 有界队列 (绝不阻塞引擎热路径)
    —— 观测层慢/断线时丢帧而不是拖慢数据面
"""
import atexit
import json
import os
import queue
import threading
import time

DDS_WS = os.environ.get("ZMAX_DDS_WS", "wss://datadrive.world/ws/dds/")
TS_TOPIC = os.environ.get("ZMAX_SS_TS_TOPIC", "ZMAX_StateSpace")
QUEUE_MAX = int(os.environ.get("ZMAX_SS_TOPIC_QUEUE", "2000"))
SEND_HZ = float(os.environ.get("ZMAX_SS_TOPIC_HZ", "20"))


class DdsLiteWriter:
    """轻量 DDS 写端: 有界队列 + 后台线程, 热路径永不阻塞"""

    def __init__(self):
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._stop = threading.Event()
        self._ws = None
        self._local = None
        self._lock = threading.Lock()
        self._pub_count = 0
        self._drop_count = 0
        self._err = ""
        # 本机原生 DDS (可选)
        if os.environ.get("ZMAX_SS_LOCAL_DDS", "0") == "1":
            self._init_local()
        self._t = threading.Thread(target=self._loop, name="ss-dds-lite", daemon=True)
        self._t.start()
        atexit.register(self.close)

    def _init_local(self):
        try:
            from cyclonedds.domain import DomainParticipant
            from cyclonedds.idl import make_idl_struct
            from cyclonedds.idl.types import bounded_str
            from cyclonedds.pub import DataWriter
            from cyclonedds.topic import Topic
            Msg = make_idl_struct("Msg", "ZMAX.Msg", {"payload": bounded_str(8192)})
            dp = DomainParticipant()
            self._local = DataWriter(dp, Topic(dp, TS_TOPIC, Msg))
            self._Msg = Msg
        except Exception as e:
            self._err = f"local dds: {type(e).__name__}"
            self._local = None

    # ── 热路径入口 (由 ss_topic_bus 调用) ──
    def send(self, topic: str, payload, *, kind: str = "link"):
        """入队即返回 (非阻塞); 队列满则丢最旧一帧 (观测层不做背压)"""
        item = {"topic": topic, "kind": kind, "ts": time.time(),
                "data": payload}
        try:
            self.q.put_nowait(item)
        except queue.Full:
            try:
                self.q.get_nowait()          # 丢最旧
                self.q.put_nowait(item)
            except Exception:
                pass
            self._drop_count += 1

    # ── 后台发送 ──
    def _loop(self):
        min_gap = 1.0 / max(1.0, SEND_HZ)
        last = 0.0
        while not self._stop.is_set():
            try:
                item = self.q.get(timeout=0.5)
            except queue.Empty:
                self._keepalive()
                continue
            gap = time.time() - last
            if gap < min_gap:
                time.sleep(min_gap - gap)
            last = time.time()
            self._emit(item)

    def _emit(self, item):
        # ① 本机原生 DDS
        if self._local is not None:
            try:
                self._local.write(self._Msg(
                    payload=json.dumps(item, ensure_ascii=False)[:8000]))
            except Exception as e:
                self._err = f"local write: {type(e).__name__}"
        # ② 远端 WS 网关
        try:
            ws = self._ensure_ws()
            if ws:
                ws.send(json.dumps({"type": "statespace", "payload": item},
                                   ensure_ascii=False))
                self._pub_count += 1
        except Exception as e:
            self._err = f"ws: {type(e).__name__}: {str(e)[:60]}"
            self._reset_ws()

    def _ensure_ws(self):
        with self._lock:
            if self._ws is not None:
                return self._ws
            try:
                from websockets.sync.client import connect  # noqa: PLC0415
                self._ws = connect(DDS_WS, open_timeout=10,
                                   close_timeout=2, max_size=None)
                return self._ws
            except Exception as e:
                self._err = f"ws connect: {type(e).__name__}: {str(e)[:70]}"
                self._ws = None
                return None

    def _reset_ws(self):
        with self._lock:
            try:
                if self._ws:
                    self._ws.close()
            except Exception:
                pass
            self._ws = None

    def _keepalive(self):
        """空闲时保持连接 (免得每次重连)"""
        if self._ws is None and self._pub_count:
            return

    def stats(self) -> dict:
        return {"published": self._pub_count, "dropped": self._drop_count,
                "queue": self.q.qsize(), "local_dds": self._local is not None,
                "ws": self._ws is not None, "error": self._err}

    def close(self):
        self._stop.set()
        try:
            if self._t.is_alive() and self._t is not threading.current_thread():
                self._t.join(timeout=2.0)
        except Exception:
            pass
        self._reset_ws()


if __name__ == "__main__":
    w = DdsLiteWriter()
    for i in range(5):
        w.send(f"zmax/ss/test/link{i}", {"i": i, "v": [0.1] * 39})
        time.sleep(0.2)
    time.sleep(2)
    print(json.dumps(w.stats(), ensure_ascii=False, indent=1))
    w.close()
