#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hw_dds.py — 硬件资源 DDS 中间件 (Mac / 4060 / Orin 统一上报)
================================================================
用**真 DDS (CycloneDDS)** 把各机器的硬件资源播到同一话题, APP 订阅后统一显示。

数据模型 (IDL):
  topic : zmax/hw/metrics
  type  : ZMaxHwMetrics  (见下, 固定字段便于跨语言/跨端对齐)

用法:
  # 各机器自报 (Mac / 4060 / Orin 各跑一份)
  python3 tools/gui/hw_dds.py publish --role mac --hz 1

  # 订阅所有机器的指标 (APP / 命令行查看)
  python3 tools/gui/hw_dds.py subscribe
  python3 tools/gui/hw_dds.py subscribe --json

  # 单次发布 (不需要常驻时)
  python3 tools/gui/hw_dds.py once --role mac

依赖: cyclonedds (pip install cyclonedds) — Mac/Orin/4060 都要装

⚠️ 本文件**不能**加 `from __future__ import annotations`:
   PEP 563 会把注解变成字符串, CycloneDDS 解析 IDL 类型时按 "字符串→模块属性"
   去找 (getattr(module, "bounded_str[24]")), 必然失败 →
   TypeError: Type bounded_str[24] as used in hw_dds cannot be resolved
"""
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOPIC_NAME = "zmax/hw/metrics"
DOMAIN_ID = int(os.environ.get("ZMAX_DDS_DOMAIN", "0"))


# ────────────────────────── IDL 数据模型 ──────────────────────────
# ⚠️ CycloneDDS 要求 IDL 类定义在**模块级** (函数内定义会导致类型无法解析)
try:
    from dataclasses import dataclass as _dc

    from cyclonedds.idl import IdlStruct
    from cyclonedds.idl.types import bounded_str, float64, int32

    @_dc
    class ZMaxHwMetrics(IdlStruct, typename="ZMaxHwMetrics"):
        # 身份
        ts: float64 = 0.0
        role: bounded_str[24] = ""          # mac / 4060 / orin / ecs
        host: bounded_str[64] = ""
        # CPU
        cpu_cores: int32 = 0
        cpu_percent: float64 = 0.0
        load1: float64 = 0.0
        load5: float64 = 0.0
        load15: float64 = 0.0
        # 内存
        mem_total_gb: float64 = 0.0
        mem_used_gb: float64 = 0.0
        mem_percent: float64 = 0.0
        swap_percent: float64 = 0.0
        # 存储
        disk_total_gb: float64 = 0.0
        disk_used_gb: float64 = 0.0
        disk_free_gb: float64 = 0.0
        disk_percent: float64 = 0.0
        # GPU
        gpu_backend: bounded_str[16] = ""
        gpu_name: bounded_str[64] = ""
        gpu_util_pct: float64 = 0.0
        gpu_mem_used_gb: float64 = 0.0
        gpu_mem_total_gb: float64 = 0.0
        # 算力
        tflops_measured: float64 = 0.0
        tflops_nominal: float64 = 0.0
        # 训练
        training_active: int32 = 0
        training_count: int32 = 0
        # 降级标志 (0=全部真实; >0 表示有字段取不到)
        degraded: int32 = 0

except Exception:  # pragma: no cover
    ZMaxHwMetrics = None  # type: ignore


# ────────────────────────── 字典 <-> IDL ──────────────────────────
def to_idl(d: dict):
    """hw_monitor.probe() 的 dict → IDL 样本"""
    if ZMaxHwMetrics is None:
        raise RuntimeError("cyclonedds 不可用")
    c, m, k, g, cp, t = d["cpu"], d["mem"], d["disk"], d["gpu"], d["compute"], d["training"]
    degraded = 0
    def _f(v):
        nonlocal degraded
        if v is None:
            degraded += 1
            return 0.0
        return float(v)
    return ZMaxHwMetrics(
        ts=float(d.get("ts") or time.time()), role=str(d.get("role", ""))[:23],
        host=str(d.get("host", ""))[:63],
        cpu_cores=int(c.get("cores") or 0), cpu_percent=_f(c.get("percent")),
        load1=_f(c.get("load1")), load5=_f(c.get("load5")), load15=_f(c.get("load15")),
        mem_total_gb=_f(m.get("total_gb")), mem_used_gb=_f(m.get("used_gb")),
        mem_percent=_f(m.get("percent")), swap_percent=_f(m.get("swap_percent")),
        disk_total_gb=_f(k.get("total_gb")), disk_used_gb=_f(k.get("used_gb")),
        disk_free_gb=_f(k.get("free_gb")), disk_percent=_f(k.get("percent")),
        gpu_backend=str(g.get("backend", ""))[:15], gpu_name=str(g.get("name", ""))[:63],
        gpu_util_pct=_f(g.get("util_pct")), gpu_mem_used_gb=_f(g.get("mem_used_gb")),
        gpu_mem_total_gb=_f(g.get("mem_total_gb")),
        tflops_measured=_f(cp.get("tflops_measured")), tflops_nominal=_f(cp.get("tflops_fp32")),
        training_active=1 if t.get("active") else 0, training_count=int(t.get("count") or 0),
        degraded=degraded,
    )


def from_idl(s) -> dict:
    """IDL 样本 → 统一 dict (APP/终端消费)"""
    return {
        "role": s.role, "host": s.host, "ts": s.ts,
        "cpu": {"cores": s.cpu_cores, "percent": s.cpu_percent,
                "load1": s.load1, "load5": s.load5, "load15": s.load15},
        "mem": {"total_gb": s.mem_total_gb, "used_gb": s.mem_used_gb,
                "percent": s.mem_percent, "swap_percent": s.swap_percent},
        "disk": {"total_gb": s.disk_total_gb, "used_gb": s.disk_used_gb,
                 "free_gb": s.disk_free_gb, "percent": s.disk_percent},
        "gpu": {"backend": s.gpu_backend, "name": s.gpu_name, "util_pct": s.gpu_util_pct,
                "mem_used_gb": s.gpu_mem_used_gb, "mem_total_gb": s.gpu_mem_total_gb},
        "compute": {"tflops_measured": s.tflops_measured or None,
                    "tflops_nominal": s.tflops_nominal or None},
        "training": {"active": bool(s.training_active), "count": s.training_count},
        "degraded": s.degraded,
        "age_s": round(max(0.0, time.time() - s.ts), 1),
    }


# ────────────────────────── DDS 端点 ──────────────────────────
def _participant():
    from cyclonedds.domain import DomainParticipant
    return DomainParticipant(DOMAIN_ID)


def _topic(dp):
    from cyclonedds.topic import Topic
    return Topic(dp, TOPIC_NAME, ZMaxHwMetrics)


class HwPublisher:
    """把本机硬件指标播到 zmax/hw/metrics"""

    def __init__(self, role: str, measure_tflops: bool = True):
        from cyclonedds.pub import DataWriter
        self.role = role
        self.measure = measure_tflops
        self.dp = _participant()
        self.wr = DataWriter(self.dp, _topic(self.dp))
        self._probe = None
        self.n = 0

    def _get_probe(self):
        if self._probe is None:
            from hw_monitor import probe  # noqa: PLC0415
            self._probe = probe
        return self._probe

    def tick(self) -> dict:
        d = self._get_probe()(measure=self.measure)
        d["role"] = self.role
        self.wr.write(to_idl(d))
        self.n += 1
        return d

    def run(self, hz: float = 1.0, log=print):
        period = 1.0 / max(0.05, hz)
        log(f"[{self.role}] DDS 播报启动 · topic={TOPIC_NAME} · {hz}Hz · domain={DOMAIN_ID}")
        while True:
            t0 = time.time()
            try:
                d = self.tick()
                if self.n % 10 == 1:
                    g = d["gpu"]
                    log(f"[{self.role}] #{self.n} cpu={d['cpu']['percent']}% "
                        f"mem={d['mem']['percent']}% gpu={g['backend']}:{g['util_pct']}% "
                        f"tflops={d['compute'].get('tflops_measured')}")
            except Exception as e:
                log(f"[{self.role}] 播报异常: {type(e).__name__}: {str(e)[:70]}")
            time.sleep(max(0.0, period - (time.time() - t0)))


class HwSubscriber:
    """订阅所有机器的硬件指标, 按 role 去重保留最新"""

    def __init__(self, stale_s: float = 15.0):
        from cyclonedds.sub import DataReader
        self.stale_s = stale_s
        self.dp = _participant()
        self.rd = DataReader(self.dp, _topic(self.dp))
        self.latest: dict = {}     # role -> dict

    def poll(self) -> dict:
        for s in self.rd.take(N=200):
            m = from_idl(s)
            r = m["role"] or "unknown"
            cur = self.latest.get(r)
            if cur is None or m["ts"] >= cur["ts"]:
                self.latest[r] = m
        return self.latest

    def online(self) -> dict:
        """过滤掉超时的机器 (掉线判据)"""
        now = time.time()
        return {r: m for r, m in self.latest.items() if now - m["ts"] <= self.stale_s}


# ────────────────────────── CLI ──────────────────────────
def _fmt_one(m: dict) -> str:
    c, mm, k, g, cp = m["cpu"], m["mem"], m["disk"], m["gpu"], m["compute"]
    tf = cp.get("tflops_measured")
    tf_s = f"实测{tf}" if tf else f"标称{cp.get('tflops_nominal')}"
    tr = f"🏋️训练中×{m['training']['count']}" if m["training"]["active"] else "空闲"
    return (f"  【{m['role']}】{m['host']}  (age {m['age_s']}s)\n"
            f"    CPU {c['percent']}% · {c['cores']}核 负载{c['load1']}\n"
            f"    内存 {mm['used_gb']}/{mm['total_gb']}GB ({mm['percent']}%)\n"
            f"    磁盘 {k['used_gb']}/{k['total_gb']}GB ({k['percent']}%) 可用{k['free_gb']}GB\n"
            f"    GPU  {g['backend'].upper()} {g['name']} {g['util_pct']}% 显存{g['mem_used_gb']}GB\n"
            f"    算力 {tf_s} TFLOPS · {tr}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Z-MAX 硬件资源 DDS 中间件")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("publish", help="常驻播报本机硬件指标")
    p1.add_argument("--role", required=True, help="机器角色: mac / 4060 / orin / ecs")
    p1.add_argument("--hz", type=float, default=1.0)
    p1.add_argument("--no-tflops", action="store_true", help="不跑算力实测(只测一次后缓存)")

    p2 = sub.add_parser("once", help="单次播报")
    p2.add_argument("--role", required=True)
    p2.add_argument("--no-tflops", action="store_true")

    p3 = sub.add_parser("subscribe", help="订阅并显示所有机器指标")
    p3.add_argument("--json", action="store_true")
    p3.add_argument("--seconds", type=float, default=0, help=">0 则限时退出")

    a = ap.parse_args()
    if ZMaxHwMetrics is None:
        print("❌ cyclonedds 不可用 — 请先 pip install cyclonedds")
        return 2

    if a.cmd == "publish":
        HwPublisher(a.role, measure_tflops=not a.no_tflops).run(hz=a.hz)
        return 0
    if a.cmd == "once":
        pub = HwPublisher(a.role, measure_tflops=not a.no_tflops)
        d = pub.tick()
        time.sleep(1.2)   # 给 DDS 一点发送时间
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0

    # subscribe
    s = HwSubscriber()
    t0 = time.time()
    last_n = 0
    while True:
        s.poll()
        on = s.online()
        if a.json:
            print(json.dumps(on, ensure_ascii=False))
        else:
            if len(on) != last_n or time.time() - t0 > 3:
                print(f"\n══ 在线机器 {len(on)} 台 ══")
                for m in sorted(on.values(), key=lambda x: x["role"]):
                    print(_fmt_one(m))
                last_n = len(on)
                t0 = time.time()
        if a.seconds and time.time() - t0 > a.seconds:
            break
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n停止")
        sys.exit(0)
