#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚌 DDS 总线 · 工程回灌器 (Restbus Simulation) + 总线自检

对标 Vector CANoe 的 Restbus/回灌: **把状态空间工程导出的 json 值发到 DDS 总线上**,
这样在没有真机/量产不序列化的情况下, 工程上也能随时"看到"全图数据流、检查数据质量。

用法(必须 dds-venv, 且**非 prod 档** —— 量产档按老倪要求零开销不发):
  ~/dds-venv/bin/python tools/dds_bus.py --check                 # 只读: 总线库/档位/是否允许回灌
  ~/dds-venv/bin/python tools/dds_bus.py --simulate --once       # 全图 182 条信号各发一次
  ~/dds-venv/bin/python tools/dds_bus.py --simulate --watch --rate 1 --layer L2

诚实口径(不许含糊):
  · 回灌的消息 kind='bus-sim', text 里写明 "from canvas json (工程回灌·非实测)"
  · 真机/引擎的实测值走自己的话题(ss_state 等), 两者在 UI 上必须区分得出来(source 字段 + 颜色)
"""
import argparse
import json
import os
import signal
import sys
import time

# ⚠️ link_value(画布连线)的 IDL 类型目前在 tools/gui/dds_link_bus.py 里, 而 zmax_node 靠
#    `from dds_link_bus import LinkValue` 注册它 ⇒ 本进程必须把 tools/gui 加进 sys.path,
#    否则 TOPICS 里没有 link_value, 连线话题就发不出去/订阅不到。
#    收口计划: 该类型应搬到 src/lerobot/dataspace/ 下(见 docs/design/global_data_space_mapping_*.md §7)。
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
for p in (REPO, os.path.join(REPO, "src"), "/home/ubuntu/zmax/dds", os.path.join(REPO, "tools/gui")):
    if p not in sys.path:
        sys.path.insert(0, p)

from lerobot.dataspace import busdb                                       # noqa: E402

CFG = os.environ.get("ZMAX_DDS_CFG", "/home/ubuntu/zmax/dds/cyclonedds_unicast.xml")
MODE_FILE = os.path.join(os.path.expanduser("~"), ".zmax_telemetry_mode")
STOP = {"v": False}


def _on_sig(*_a):
    STOP["v"] = True


def mode():
    env = (os.environ.get("ZMAX_TELEMETRY") or "").strip().lower()
    if env:
        return env, "env"
    try:
        with open(MODE_FILE, encoding="utf-8") as f:
            return (f.read().strip().lower() or "prod"), "file"
    except OSError:
        return "prod", "default"


def check():
    db = busdb.load() or busdb.build()
    if not db:
        print("❌ 总线库为空"); return 2
    m, src = mode()
    from lerobot.dataspace import topics as T
    allowed = T.topics_for_mode(m)
    link_ok = "link_value" in allowed
    print("=" * 82)
    print("🚌 DDS 总线自检 —— 工程可探测性")
    print("=" * 82)
    c = db["counts"]
    print("总线库  : %d 节点 · %d 信号 · %d 报文(%d 类型化 + %d 连线话题) · 画布 %s v%s"
          % (c["nodes"], c["signals"], c["messages"],
             sum(1 for v in db["messages"].values() if v["kind"] == "typed"),
             sum(1 for v in db["messages"].values() if v["kind"] == "canvas_link"),
             db["canvas"]["format"], db["canvas"]["version"]))
    print("节点分层: %s" % c["nodes_by_layer"])
    print("遥测档位: %s (来源 %s) · 本档允许 %d 话题" % (m, src, len(allowed)))
    _why = "" if link_ok else (
        "  ← 当前档位 %s 不含 link_value; 量产(prod)不序列化是**预期行为**, "
        "工程探测切 calib 或 test 即可回灌" % m)
    print("回灌可用: %s%s" % ("✅ 可以" if link_ok else "⛔ 不可以", _why))
    print("-" * 82)
    print("%-22s %-18s %6s %8s %6s %s" % ("报文(topic)", "类型", "信号数", "设计Hz", "实测Hz", "实测配对"))
    live = {}
    try:
        with open(os.environ.get("ZMAX_DATASPACE_LIVE", "/home/ubuntu/zmax_data/dataspace/live.json"),
                  encoding="utf-8") as f:
            live = json.load(f)
    except Exception:                                                        # noqa: BLE001
        pass
    for r in busdb.stats_rows(db, live):
        print("%-22s %-18s %6s %8s %6s %s" % (r["topic"], r["type"].split("::")[-1],
                                              r["n_signals"] or "-", r["hz_design"], r["hz"],
                                              r["matched"] if r["matched"] is not None else "-"))
    return 0


def simulate(layer=None, rate=1.0, watch=False, once=False, max_signals=0, pace=0.001):
    m, _src = mode()
    from lerobot.dataspace import topics as T
    from zmax_node import TOPICS, Node
    LV = TOPICS.get("link_value")
    if LV is None:
        print("⛔ 总线库里没有 link_value 类型(画布连线话题); 无法回灌")
        return 2
    if "link_value" not in T.topics_for_mode(m):
        print("⛔ 当前档位 %s 不允许 link_value —— 量产(prod)不序列化是**预期行为**。\n"
              "   工程探测请先切档:  echo calib > ~/.zmax_telemetry_mode  (守护 2s 内跟随)" % m)
        return 3
    db = busdb.load() or busdb.build()
    sigs = [s for s in db["signals"] if not layer or s["layer"] == layer]
    if max_signals:
        sigs = sigs[:max_signals]
    if not sigs:
        print("⚠ 该层没有信号"); return 1
    n = Node("dds-bus-sim", domain=0, config_xml=CFG if os.path.exists(CFG) and os.path.getsize(CFG) else None)
    # Node.pub/send 自己会加 "zmax/" 前缀 ⇒ 这里必须传**短键**(实测: 传全名会 KeyError)
    def _key(full):
        return full.split("/", 1)[1] if full.startswith("zmax/") else full
    topics = sorted({_key(s["topic"]) for s in sigs})
    for t in topics:
        n.pub(t)
    # ★ DDS 发现是异步的: 不等配对就发, 消息全丢给"还没发现你"的读者(实测: 只收到 1/182)
    for t in topics:
        _ok = n.wait_for_match(t, 1, timeout=8.0)
        print("   配对 %s: %s" % (t, "✅" if _ok else "⚠️ 超时(订阅端没起来?)"))
    print("🚌 回灌: %d 信号 → %d 个话题 %s (档位=%s, 节流=%sms/条)" % (len(sigs), len(topics), topics, m, pace * 1000))
    print("   口径: kind='bus-sim', text='from canvas json (工程回灌·非实测)' —— UI 上必须与实测区分")
    seq = 0
    while not STOP["v"]:
        t0 = time.time()
        for s in sigs:
            seq += 1
            try:
                n.send(_key(s["topic"]), LV(ts=time.time(), node_id=s["src"], node_name=s["src_name"][:60],
                                      port=str(s["src_port"]), kind="bus-sim",
                                      text="from canvas json (工程回灌·非实测) | %s→%s" %
                                           (s["src_name"][:20], s["dst_name"][:20]),
                                      vec=[float(s["sid"].replace("S", ""))], seq=seq))
            except Exception as e:                                           # noqa: BLE001
                print("  ✗ 发送失败 %s: %s" % (s["topic"], str(e)[:70])); break
            # ★ 节流: 发布端 QoS=beat(KEEP_LAST(1)), 一口气灌 182 条会被覆盖(实测只到 80/182);
            #   摊到 ~1ms/条 让传输跟上 —— 这是 BEST_EFFORT 的物理性质, 不是丢包 bug
            time.sleep(pace)
        if once:
            break
        dt = 1.0 / max(0.1, rate)
        time.sleep(max(0.0, dt - (time.time() - t0)))
    # 发完多留一会儿: BEST_EFFORT 下进程立刻退出, 读者可能还没收完
    time.sleep(2.0)
    print("✅ 回灌结束(共 %d 条)" % seq)
    return 0


def main():
    ap = argparse.ArgumentParser(description="DDS 总线回灌/自检 (Restbus)")
    ap.add_argument("--check", action="store_true", help="只读自检: 总线库+档位+是否允许回灌")
    ap.add_argument("--simulate", action="store_true", help="把画布 json 的值发到总线上")
    ap.add_argument("--once", action="store_true", help="只发一轮")
    ap.add_argument("--watch", action="store_true", help="持续发")
    ap.add_argument("--rate", type=float, default=1.0, help="每秒轮次")
    ap.add_argument("--layer", default=None, help="只回灌某一层(L2/L3/L4/L5/meta)")
    ap.add_argument("--max-signals", type=int, default=0)
    ap.add_argument("--pace", type=float, default=0.001, help="每条之间的间隔秒(默认 1ms, 防 BEST_EFFORT 覆盖)")
    a = ap.parse_args()
    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)
    if a.check or not a.simulate:
        return check()
    return simulate(a.layer, a.rate, a.watch, a.once or not a.watch, a.max_signals, a.pace)


if __name__ == "__main__":
    sys.exit(main())
