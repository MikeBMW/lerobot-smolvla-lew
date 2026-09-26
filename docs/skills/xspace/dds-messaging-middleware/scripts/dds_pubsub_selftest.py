#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DDS 同进程 pub→sub 自检 —— 改任何 DDS 配置/类型/QoS 之后先跑这个。

用法（必须用装 cyclonedds 的那个 venv 的解释器）:
  ~/dds-venv/bin/python dds_pubsub_selftest.py
  CYCLONEDDS_URI=file://$PWD/dds/cyclonedds_unicast.xml ~/dds-venv/bin/python dds_pubsub_selftest.py

判定:
  ① 配对: wait_for_match 通过（发现已建立）
  ② 收到 ≥1 条且字段值 == 发出的值（栈真的通了）
两个都 ✅ 才继续查业务; 只"发送无异常"不算通过。

也用来定位"收不到"是环境还是代码: 本机同进程都不通过 → 是 DDS/配置问题;
本机通过、跨机不通过 → 是多网卡/防火墙/单播配置问题。
"""
import sys
import time

from cyclonedds.core import Policy, Qos
from cyclonedds.domain import DomainParticipant
from cyclonedds.idl import IdlStruct
from cyclonedds.idl.types import float64, int32          # ★ 无 string: 用内置 str
from cyclonedds.pub import DataWriter
from cyclonedds.sub import DataReader
from cyclonedds.topic import Topic


class Hw(IdlStruct, typename="selftest::Hw"):
    """-1.0 = 未测到（不用 0 冒充: 0 是合法实测值）"""
    node: str = ""
    backend: str = ""
    util_pct: float64 = -1.0
    mem_used_mb: float64 = -1.0
    temp_c: float64 = -1.0
    cpu_cores: int32 = -1


def _p(cls, *a):
    """Policy 子类 API 不一致: Reliable/KeepLast 可调用, BestEffort/TransientLocal 不可 → 兜底"""
    try:
        return cls(*a)
    except TypeError:
        return cls


def main():
    print("=" * 70)
    print("DDS 自检: 同进程 pub → sub 往返")
    print("=" * 70)
    dp = DomainParticipant(0)
    tp = Topic(dp, "selftest/hw", Hw)
    qos = Qos(_p(Policy.Reliability.Reliable, 0), _p(Policy.History.KeepLast, 1),
              _p(Policy.Durability.TransientLocal))
    w, r = DataWriter(dp, tp, qos=qos), DataReader(dp, tp, qos=qos)

    # ① 等配对（DDS 发现是异步的）
    t0, matched = time.time(), 0
    while time.time() - t0 < 15:
        matched = len(w.get_matched_subscriptions())
        if matched:
            break
        time.sleep(0.2)
    print("① 发现配对: %s (matched=%d)" % ("✅" if matched else "❌ 超时", matched))

    sent = Hw(node="selftest", backend="cuda", util_pct=100.0,
              mem_used_mb=1629.0, temp_c=68.0, cpu_cores=32)
    w.write(sent)

    # ② 收回来并比对字段
    got, t1 = [], time.time()
    while time.time() - t1 < 8 and not got:
        got.extend(r.take() or [])
        if not got:
            time.sleep(0.2)
    ok_fields = False
    for m in got[:1]:
        print("   收到: %s/%s util=%.0f%% mem=%.0fMB %.0f°C cores=%d" %
              (m.node, m.backend, m.util_pct, m.mem_used_mb, m.temp_c, m.cpu_cores))
        ok_fields = (m.util_pct == sent.util_pct and m.cpu_cores == sent.cpu_cores
                     and m.node == sent.node)
    print("② 收到 %d 条 · 字段一致: %s" % (len(got), "✅" if ok_fields else "❌"))

    verdict = bool(matched) and ok_fields
    print("\n🎯 %s" % ("DDS 栈成立 ✅" if verdict else
                       "不通过 ❌ → 检查: 多网卡是否用单播配置 / XML 是否含被拒元素 / venv 解释器"))
    return 0 if verdict else 2


if __name__ == "__main__":
    sys.exit(main())
