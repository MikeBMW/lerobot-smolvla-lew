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


_PUB_THREAD = None
_PUB_ERR = ""


def _collect_local_hw():
    """采集本机硬件（跨平台: nvidia-smi 可选 + psutil/标准库; 读不到 = -1）"""
    import shutil
    import subprocess
    d = {"node": os.environ.get("ZMAX_NODE", ""), "role": os.environ.get("ZMAX_ROLE", ""),
         "backend": "cpu", "device_name": "", "ts": time.time()}
    # GPU（CUDA）
    try:
        o = subprocess.run("nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,"
                           "temperature.gpu,power.draw,clocks.sm --format=csv,noheader,nounits",
                           shell=True, capture_output=True, text=True, timeout=8).stdout.strip()
        if o and "," in o:
            p = [x.strip() for x in o.split(",")]
            f = lambda v: (float(v) if v.replace(".", "").replace("-", "").isdigit() else -1.0)  # noqa: E731
            d.update(backend="cuda", device_name=p[0], util_pct=f(p[1]), mem_used_mb=f(p[2]),
                     mem_total_mb=f(p[3]), temp_c=f(p[4]), power_w=f(p[5]), clk_mhz=f(p[6]))
    except Exception:                                                           # noqa: BLE001
        pass
    # MPS（Mac）
    if d["backend"] == "cpu":
        try:
            import torch
            if torch.backends.mps.is_available():
                d.update(backend="mps", device_name="Apple MPS (Metal)")
        except Exception:                                                       # noqa: BLE001
            pass
    # CPU / 内存 / 磁盘
    try:
        d["cpu_cores"] = os.cpu_count() or -1
        la = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
        d["load1"] = round(la[0], 2)
    except Exception:                                                           # noqa: BLE001
        pass
    try:
        du = shutil.disk_usage(os.path.expanduser("~"))
        d["disk_total_gb"] = round(du.total / 1073741824, 1)
        d["disk_free_gb"] = round(du.free / 1073741824, 1)
    except Exception:                                                           # noqa: BLE001
        pass
    # 内存（Linux /proc; Mac sysctl; Windows 走 psutil 若有）
    try:
        if os.path.isfile("/proc/meminfo"):
            mi = {}
            for ln in open("/proc/meminfo"):
                mi[ln.split(":")[0]] = int(ln.split()[1]) / 1048576.0
            d["mem_total_gb"] = round(mi.get("MemTotal", -1), 1)
            d["mem_avail_gb"] = round(mi.get("MemAvailable", -1), 1)
        else:
            import subprocess
            tot = subprocess.run("sysctl -n hw.memsize", shell=True, capture_output=True,
                                 text=True, timeout=6).stdout.strip()
            if tot.isdigit():
                d["mem_total_gb"] = round(int(tot) / 1073741824, 1)
    except Exception:                                                           # noqa: BLE001
        pass
    # 兜底默认值: 未测到 = -1
    for k in ("util_pct", "mem_used_mb", "mem_total_mb", "temp_c", "power_w", "clk_mhz",
              "cpu_util_pct", "load1", "mem_total_gb", "mem_avail_gb", "disk_total_gb",
              "disk_free_gb", "train_steps_per_s"):
        d.setdefault(k, -1.0)
    d.setdefault("cpu_cores", -1)
    if not d.get("device_name"):
        d["device_name"] = "本机(未检测到 GPU)"
    return d


def start_local_publisher(domain=0, cfg=None, interval=5.0):
    """★ 在 APP 进程内启动本机 DDS 发布（发布硬件到 zmax/hw_state）
    返回 (ok, msg)。失败原因明确回传（不静默）。"""
    global _PUB_THREAD, _PUB_ERR
    if _PUB_THREAD is not None and _PUB_THREAD.is_alive():
        return True, "已在运行"

    def _loop():
        global _PUB_ERR
        try:
            import sys
            here = os.path.dirname(os.path.abspath(__file__))
            _mp = getattr(sys, "_MEIPASS", "")
            for cand in (os.path.join(here, "..", "..", "dds"), os.path.join(here, "dds"),
                         (os.path.join(_mp, "dds") if _mp else "")):
                if cand and os.path.isdir(cand):
                    sys.path.insert(0, os.path.abspath(cand))
            from zmax_node import Node
            from zmax_types import HardwareState, Heartbeat
            _c = cfg
            if not _c:
                for cand in (os.path.join(here, "..", "..", "dds", "cyclonedds_unicast.xml"),
                             (os.path.join(_mp, "dds", "cyclonedds_unicast.xml") if _mp else "")):
                    if cand and os.path.isfile(cand):
                        _c = cand
                        break
            n = Node("app-pub", domain=domain, config_xml=_c)
            n.pub("hw_state")
            n.pub("heartbeat")
            while True:
                d = _collect_local_hw()
                msg = HardwareState(**{k: v for k, v in d.items()
                                       if k in HardwareState.__dataclass_fields__})
                n.send("hw_state", msg)
                n.send("heartbeat", Heartbeat(node=d.get("node") or "本机",
                                              role=d.get("role") or "工作端", alive=1, ts=time.time()))
                time.sleep(interval)
        except Exception as e:                                                  # noqa: BLE001
            _PUB_ERR = "%s: %s" % (type(e).__name__, str(e)[:120])

    _PUB_THREAD = threading.Thread(target=_loop, daemon=True)
    _PUB_THREAD.start()
    time.sleep(2.0)
    if _PUB_THREAD.is_alive():
        return True, "本机 DDS 发布已启动（zmax/hw_state，每 %.0fs）" % interval
    return False, _PUB_ERR or "线程未启动"


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
