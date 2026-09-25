#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 桌面 APP 内置 DDS 硬件采集器（老倪: "硬件参数必须用DDS传递"）

在 APP 进程内起一个后台线程, **直接订阅 DDS** 话题 zmax/hw_state / train_prog / heartbeat,
把 4060(本机) 与 Mac(小芳·备份端) 的硬件参数收集到共享字典, 供硬件卡渲染。

三级降级（保证"能用", 但首选永远是 DDS）:
  ① 进程内直连 DDS（打包时 --collect-all cyclonedds 带上原生库）→ **DDS 传递** ✓
  ② dds-venv 子进程桥（tools/dds_bridge.py）→ 数据仍经 DDS, 只是跨进程 ✓
  ③ 最后才是 HTTP /api/hardware（仅在 DDS 完全不可用时, 且会明确标注 "非DDS"）

线程安全: nodes 字典只在后台线程写、主线程读; 用 _lock 保护。
"""
import json
import os
import threading
import time

TOPICS = ("hw_state", "train_prog", "heartbeat")


class DdsHwCollector:
    def __init__(self, domain=0, cfg=None, stale_after=15.0):
        self.nodes = {}
        self.transport = "初始化中"     # dds-inproc / dds-subproc / http-fallback
        self.err = ""
        self.stale_after = stale_after
        self._lock = threading.Lock()
        self._stop = False
        self.cfg = cfg
        self.domain = domain
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    # ---------- 对外 ----------
    def snapshot(self):
        """返回 {node: {hw, prog, hb, age_s, stale}}（已加锁拷贝）"""
        with self._lock:
            now = time.time()
            out = {}
            for k, v in self.nodes.items():
                age = round(now - (v.get("recv_ts") or 0), 1)
                out[k] = {**v, "age_s": age, "stale": age > self.stale_after}
            return out

    # ---------- 内部 ----------
    def _put(self, topic, d):
        key = str(d.get("node") or "?").strip()
        with self._lock:
            slot = self.nodes.setdefault(key, {})
            slot["hw" if topic == "hw_state" else ("prog" if topic == "train_prog" else "hb")] = d
            slot["recv_ts"] = time.time()
            slot["role"] = d.get("role") or slot.get("role") or ""

    def _run(self):
        # ① 进程内直连 DDS
        try:
            self._run_inproc()
            return
        except Exception as e:                                                  # noqa: BLE001
            self.err = "①进程内DDS失败: %s: %s" % (type(e).__name__, str(e)[:70])
        # ② dds-venv 子进程桥（读它写的 JSON）
        try:
            self._run_subproc_bridge()
            return
        except Exception as e:                                                  # noqa: BLE001
            self.err += " ②子进程桥失败: %s" % str(e)[:60]
        self.transport = "不可用"

    def _run_inproc(self):
        """进程内直连 DDS（首选）"""
        import sys
        # 允许从仓库 dds/ 目录导入类型与节点封装
        here = os.path.dirname(os.path.abspath(__file__))
        _mp = getattr(sys, "_MEIPASS", "")          # PyInstaller 解包目录（打包后 dds 在这里）
        for cand in (os.path.join(here, "..", "..", "dds"), os.path.join(here, "dds"),
                     (os.path.join(_mp, "dds") if _mp else "")):
            if os.path.isdir(cand):
                sys.path.insert(0, os.path.abspath(cand))
        from zmax_node import Node                       # noqa: F401  (无 cyclonedds 会抛异常)
        cfg = self.cfg
        if not cfg:
            for cand in (os.path.join(here, "..", "..", "dds", "cyclonedds_unicast.xml"),
                         os.environ.get("ZMAX_DDS_CFG", "")):
                if cand and os.path.isfile(cand):
                    cfg = cand
                    break
        n = Node("app", domain=self.domain, config_xml=cfg)
        for t in TOPICS:
            n.sub(t)
        self.transport = "dds-inproc"
        while not self._stop:
            for t in TOPICS:
                for m in n.take(t, 0.2):
                    d = {}
                    for k, v in vars(m).items():
                        if k.startswith("_"):
                            continue
                        if isinstance(v, (str, int, float)):
                            d[k] = v
                        elif isinstance(v, list):
                            d[k] = [str(x) for x in v]
                    self._put(t, d)

    def _run_subproc_bridge(self):
        """② 读 dds-venv 子进程桥写的 JSON（数据仍经 DDS 传输）"""
        p = "/home/ubuntu/stable-wm-cache/reports/dds_latest.json"
        if not os.path.isfile(p):
            raise RuntimeError("桥 JSON 不存在: %s" % p)
        last = 0.0
        while not self._stop:
            try:
                mt = os.path.getmtime(p)
                if mt > last:
                    last = mt
                    d = json.load(open(p, encoding="utf-8"))
                    for k, v in (d.get("nodes") or {}).items():
                        with self._lock:
                            self.nodes[k] = v
                    self.transport = "dds-subproc"
            except Exception:                                                   # noqa: BLE001
                pass
            time.sleep(1.0)

    def stop(self):
        self._stop = True
