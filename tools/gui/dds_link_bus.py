#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 DDS 连线总线 —— 状态空间工程「节点连线」的数据全部走 DDS topic

老倪 2026-09-25: "现在状态空间工程里的节点连线是怎么交换数据的？
                 所有连线交换的数据，都应该是DDS topic，改"

改造前（实测）:
  写: simulink_module.py:6829  self._sim_signals[n["id"]] = out     ← 同进程字典
  读: simulink_module.py:6748  src = self._sim_signals.get(lk["f"]) ← 同进程字典
  ⇒ 只能在**同一进程**内传值, 跨机/跨进程/跨语言都不行

改造后:
  每个节点的输出 → DDS topic **zmax/link/<node_id>**（QoS: BEST_EFFORT·KEEP_LAST(3)）
  下游节点按连线 f→t 订阅源节点 topic → 拿到值
  ⇒ 任何进程/机器/语言都能加入这个「全局数据空间」消费连线数据

可靠性设计（关键）:
  · **不破坏原链路**: DDS 不可用时 latest() 返回 None → 调用方回落 _sim_signals（零回退）
  · **不阻塞**: 发布/读取都在内存字典 + 后台线程完成, 绝不卡 UI
  · **可观测**: seq 递增序号, 便于验证「真的流过 DDS」
"""
import os
import sys
import threading
import time
from dataclasses import dataclass, field

# ── DDS 模块路径（稳定目录, 不随 git 分支变化）──
for _c in ("/home/ubuntu/zmax_dds",
           os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
               os.path.abspath(__file__)))), "dds")):
    if _c and os.path.isdir(_c) and _c not in sys.path:
        sys.path.insert(0, _c)

_CFG = next((p for p in ("/home/ubuntu/zmax_dds/cyclonedds_unicast.xml",) if os.path.isfile(p)), None)

try:
    from cyclonedds.idl import IdlStruct
    from cyclonedds.idl.types import float64, int32, sequence
    _HAS_DDS = True
except Exception:                                                               # noqa: BLE001
    _HAS_DDS = False
    IdlStruct = object

    def float64():                                                              # type: ignore
        return 0.0

    def int32():                                                                # type: ignore
        return 0

    def sequence(x):                                                            # type: ignore
        return list


@dataclass
class LinkValue(IdlStruct, typename="zmax::LinkValue"):
    """一条连线上流动的值（节点输出 → 下游输入）"""
    ts: float64 = 0.0
    node_id: str = ""          # 源节点 id（连线 f）
    node_name: str = ""        # 源节点名（再生后 id 变, name 更稳）
    port: str = "out1"         # 输出端口
    kind: str = "str"          # str / num / vec
    text: str = ""             # 文本表示（画布 UI 现在就用文本）
    vec: sequence[float64] = field(default_factory=list)
    seq: int32 = -1            # 递增序号（验证真流过 DDS）


class DdsLinkBus:
    """进程内 DDS 连线总线（发布 + 订阅缓存）

    用法:
        bus = DdsLinkBus()                  # 懒加载, 失败即降级
        bus.publish(node_id, name, port, "obs 43D 就绪")     # 节点产出时
        v = bus.latest(node_id)             # 下游取连线数据; None = 无(回落本地)
    """

    def __init__(self, domain=0):
        self.ok = False
        self.err = ""
        self._seq = 0
        self._lock = threading.Lock()
        self._cache = {}           # node_id → LinkValue
        self._recv = 0
        self._sent = 0
        self._pub = None
        self._sub = None
        self._t = None
        if not _HAS_DDS:
            self.err = "未安装 cyclonedds（在 dds-venv 里跑才有 DDS）"
            return
        try:
            from zmax_node import Node
            self._node = Node("ss-link-bus", domain=domain, config_xml=_CFG)
            # 发布端
            self._pub = self._node.pub("link_value")
            # 订阅端（读全量连线值 → 本地缓存, 读的时候零延迟）
            self._sub = self._node.sub("link_value")
            self._t = threading.Thread(target=self._loop, daemon=True)
            self._t.start()
            self.ok = True
        except Exception as e:                                                  # noqa: BLE001
            self.err = "%s: %s" % (type(e).__name__, str(e)[:120])

    # ---------------- 订阅线程: 把 DDS 来的连线值缓存到内存 ----------------
    def _loop(self):
        while True:
            try:
                for m in self._node.take("link_value", 0.3):
                    nid = str(getattr(m, "node_id", "") or "")
                    if not nid:
                        continue
                    with self._lock:
                        self._cache[nid] = m
                        self._recv += 1
            except Exception:                                                   # noqa: BLE001
                time.sleep(0.5)

    # ---------------- 发布: 节点产出 → DDS ----------------
    def publish(self, node_id, node_name="", port="out1", value=None):
        """发布一条连线值; 失败静默（不打断画布）"""
        if not self.ok or value is None:
            return False
        try:
            with self._lock:
                self._seq += 1
                sq = self._seq
            txt = value if isinstance(value, str) else str(value)
            msg = LinkValue(ts=time.time(), node_id=str(node_id), node_name=str(node_name or ""),
                            port=str(port or "out1"), kind="str", text=txt[:400], seq=sq)
            self._pub.write(msg)
            self._sent += 1
            return True
        except Exception:                                                       # noqa: BLE001
            return False

    # ---------------- 读取: 下游取连线数据 ----------------
    def latest(self, node_id, max_age=3.0):
        """取某源节点最近一次连线值; 无/过期 → None（调用方回落本进程字典）"""
        if not self.ok:
            return None
        with self._lock:
            m = self._cache.get(str(node_id))
        if m is None:
            return None
        try:
            if time.time() - float(getattr(m, "ts", 0.0) or 0.0) > max_age:
                return None
        except Exception:                                                       # noqa: BLE001
            pass
        return getattr(m, "text", None)

    def stats(self):
        return {"ok": self.ok, "err": self.err, "sent": self._sent,
                "recv": self._recv, "cached_nodes": len(self._cache), "cfg": _CFG}


_BUS = None
_BUS_LOCK = threading.Lock()


def get_bus():
    """全局单例（懒加载）"""
    global _BUS
    if _BUS is None:
        with _BUS_LOCK:
            if _BUS is None:
                _BUS = DdsLinkBus()
    return _BUS


if __name__ == "__main__":
    b = get_bus()
    print("  状态:", b.stats())
    if b.ok:
        b.publish("n_test", "测试节点", "out1", "obs 43D 就绪 · seq 验证")
        time.sleep(2.0)
        print("  自测读到:", b.latest("n_test"))
        print("  统计:", b.stats())
