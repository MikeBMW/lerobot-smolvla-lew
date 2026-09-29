#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 全链路 topic 可视化探针 —— 全局数据空间的"眼睛"

干什么: 按当前遥测模式订阅**全空间话题**, 实测 频率/帧龄/发布者数/字段值, 逐帧跑质量规则,
        把结果写成一个 JSON —— 控制台(数据空间页)、网页、巡检脚本都读它。
为什么这样做: cyclonedds 只装在独立 venv(~/dds-venv), 控制台/主应用不该被它污染依赖
        ⇒ 「DDS → JSON 桥」(见技能 dds-messaging)。

用法(必须 dds-venv):
    ~/dds-venv/bin/python -m lerobot.dataspace.probe --seconds 12          # 采 12 秒后打印+落盘
    ~/dds-venv/bin/python -m lerobot.dataspace.probe --watch --interval 2  # 常驻, 每 2s 更新 JSON
    ~/dds-venv/bin/python -m lerobot.dataspace.probe --once --json         # 只打 JSON

输出: /home/ubuntu/zmax_data/dataspace/live.json
"""
import argparse
import json
import os
import signal
import sys
import time

# ── 依赖路径 ────────────────────────────────────────────────────────────────
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax_rel")
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if os.path.join(REPO, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "src"))

# ⚠️ 待收口(老倪: 逻辑代码只能有一个 CICD 路径): DDS 类型/Node 目前在仓库外
#    /home/ubuntu/zmax_dds/{ss_types,zmax_types,zmax_node}.py —— 见 docs/design/global_data_space_mapping_*.md
DDS_DIR = os.environ.get("ZMAX_DDS_DIR", "/home/ubuntu/zmax_dds")
for _p in (DDS_DIR, os.path.join(REPO, "tools", "gui")):
    # tools/gui 也要加: link_value(画布连线)类型还住在 tools/gui/dds_link_bus.py(待收口)
    if _p not in sys.path:
        sys.path.insert(0, _p)
CFG = os.environ.get("ZMAX_DDS_CFG", "/home/ubuntu/zmax_dds/cyclonedds_unicast.xml")
OUT = os.environ.get("ZMAX_DATASPACE_LIVE", "/home/ubuntu/zmax_data/dataspace/live.json")

from lerobot.dataspace import quality, topics as T                      # noqa: E402

_STOP = {"v": False}


def _on_sig(*_a):
    _STOP["v"] = True


def np_std(xs):
    """纯 python 标准差(不引 numpy, dds-venv 保持干净)"""
    if len(xs) < 2:
        return 0.0
    mu = sum(xs) / len(xs)
    return (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _jsonable(v):
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


def _fields_of(msg):
    """按 dataclass 声明白名单取字段 —— 丢掉 DDS 元数据(否则 json 会爆 SampleInfo)"""
    keys = list(getattr(type(msg), "__dataclass_fields__", {}).keys())
    return {k: _jsonable(getattr(msg, k, None)) for k in keys if not k.startswith("_")}


def _mode():
    env = (os.environ.get("ZMAX_TELEMETRY") or "").strip().lower()
    if env in T.MODE_TOPICS:
        return env
    try:
        m = open(os.path.join(os.path.expanduser("~"), ".zmax_telemetry_mode"),
                 encoding="utf-8").read().strip().lower()
        if m in T.MODE_TOPICS:
            return m
    except OSError:
        pass
    return "prod"


class Probe:
    def __init__(self, mode=None, out=OUT):
        self.mode = mode or _mode()
        self.fixed_mode = mode
        self.keys = T.topics_for_mode(self.mode)
        self.out = out
        self.node = None
        self.st = {}          # topic → 统计(所有曾经见过的)
        self.hist = {}        # topic → 接收时刻(最近 120s)
        self.trace = []       # 🚌 Trace 窗口(CANoe 报文追踪): 最近 N 条
        self.tr_bytes = {}    # topic → 累计载荷估算(bytes)
        self.t0 = time.time()
        if self.keys:
            from zmax_node import Node
            self.node = Node("dataspace-probe", domain=0, config_xml=CFG)
            self._ensure(self.keys)

    def _make_reader(self, k):
        """观察者读取端: BEST_EFFORT·KEEP_LAST(200) —— 深历史, 只观察不改发布端语义"""
        import zmax_node as ZN
        from cyclonedds.core import Policy, Qos
        from cyclonedds.sub import DataReader
        from cyclonedds.topic import Topic
        t = Topic(self.node.dp, "zmax/" + k, ZN.TOPICS[k])
        q = Qos(ZN._p(Policy.Reliability.BestEffort, 0), ZN._p(Policy.History.KeepLast, 200))
        return DataReader(self.node.dp, t, qos=q)

    def _ensure(self, keys):
        """给新话题建 reader + 统计槽(档位切换后补订, 不用重建进程)"""
        for k in keys:
            if k not in self.st:
                self.st[k] = {"count": 0, "last_ts": None, "last_fields": None,
                              "verdict": "-", "score": -1.0, "rules": []}
                self.hist[k] = []
                self.tr_bytes[k] = 0
                if self.node is not None:
                    try:
                        self.node._r[k] = self._make_reader(k)      # 深历史观察者(见上)
                        self.node.wait_for_match(k, 1, timeout=1.0)
                    except Exception:                                        # noqa: BLE001
                        try:
                            self.node.sub(k)
                        except Exception:                                    # noqa: BLE001
                            pass

    def follow_mode(self):
        """档位跟随: 工程上任何时候切档, 探针 2s 内跟上(不重启进程)"""
        m = self.fixed_mode or _mode()
        if m == self.mode:
            return False
        self.mode = m
        self.keys = T.topics_for_mode(m)
        if self.node is None and self.keys:
            from zmax_node import Node
            self.node = Node("dataspace-probe", domain=0, config_xml=CFG)
        self._ensure(self.keys)
        return True

    # ── 采一轮 ──────────────────────────────────────────────────────────
    def pump(self, seconds):
        t0, now = time.time(), time.time()
        while time.time() - t0 < seconds and not _STOP["v"]:
            now = time.time()
            self.follow_mode()
            for k in self.st:                       # 已订的全部收(含刚切档前订的, 便于对照)
                if k not in self.keys and self.node is not None:
                    try:
                        self.node.sub(k).take()    # 本档不允许的话题: 只抽干不统计
                    except Exception:                                        # noqa: BLE001
                        pass
                    continue
                try:
                    samples = self.node.sub(k).take()
                except Exception as e:                                       # noqa: BLE001
                    self.st[k]["rules"] = [{"rule": "take", "ok": False, "level": "warn", "msg": str(e)[:80]}]
                    continue
                for m in samples or []:
                    f = _fields_of(m)
                    s = self.st[k]
                    s["count"] += 1
                    s["last_ts"] = f.get("ts")
                    s["last_fields"] = f
                    body = json.dumps(f, ensure_ascii=False)
                    self.tr_bytes[k] = self.tr_bytes.get(k, 0) + len(body)
                    if len(self.trace) < 500 or s["count"] % 20 == 0:
                        self.trace.append({"t": round(now, 3), "topic": T.full_name(k),
                                           "type": (T.TOPICS.get(k, {}).get("type") or "").split("::")[-1],
                                           "n": s["count"], "bytes": len(body),
                                           "digest": body[:180]})
                        if len(self.trace) > 800:
                            self.trace = self.trace[-600:]
                    self.hist[k].append(now)
                    if len(self.hist[k]) > 4000:
                        self.hist[k] = self.hist[k][-2000:]
            time.sleep(0.05)
        return now

    def snapshot(self, now=None):
        now = now or time.time()
        win = 5.0
        rows = {}
        elapsed = max(1e-6, now - self.t0)
        for k in self.st:
            s = self.st[k]
            _allowed = k in self.keys
            # 平均频率按**整个观测窗**算(低速率话题在 5s 滑窗里只有 1~2 条, 会系统性低估)
            # ★ 诊断关键: 配到了几个发布者 —— 0=发现层没通, >0 而 0 条=发布端没在发/QoS 不兼容
            matched = 0
            try:
                if self.node is not None:
                    matched = len(self.node.sub(k).get_matched_publications() or [])
            except Exception:                                                # noqa: BLE001
                matched = -1
            h = [t for t in self.hist[k] if now - t <= 120.0]     # 频率按最近 120s 算(长跑收敛, 短窗不抖)
            span = (h[-1] - h[0]) if len(h) > 1 else 0.0
            hz = round((len(h) - 1) / span, 2) if span > 0.5 else (0.0 if s["count"] else -1.0)
            want = T.TOPICS.get(k, {}).get("rate_hz")
            rules = []
            if s["last_fields"] is not None:
                rules = quality.check(k, s["last_fields"], now=now,
                                      meta={"hz": hz if hz >= 0 else None, "want_hz": want, "prev_step": None})
            vd = quality.verdict(rules) if rules else "-"
            # 🚌 Statistics 窗口口径: 抖动(相邻间隔标准差) / 丢包估算 / 载荷
            iv = [round((b - a) * 1000.0, 2) for a, b in zip(h, h[1:])]
            jit = round(float(np_std(iv)), 2) if len(iv) > 1 else None
            exp = (want or 0) * elapsed
            loss = round(max(0.0, 1.0 - s["count"] / exp) * 100.0, 1) if exp > 5 else None
            rows[k] = {
                "topic": T.full_name(k), "type": T.TOPICS.get(k, {}).get("type"),
                "qos": T.TOPICS.get(k, {}).get("qos"), "allowed": _allowed,
                "hz": hz, "hz_design": want, "count": s["count"], "matched_pubs": matched,
                "jitter_ms": jit, "loss_pct": loss, "bytes": self.tr_bytes.get(k, 0),
                "age_s": (round(now - s["last_ts"], 2) if s["last_ts"] else None),
                "verdict": vd, "score": quality.score(rules),
                "rules": rules, "fields": s["last_fields"],
            }
            # 🚦 状态灯(绿正常/红故障/黄报警/黑无信号) —— 口径在 lamps.py, UI 不许自己另判
            try:
                from lerobot.dataspace import lamps as L
                st, why = L.topic_state(k, rows[k], rows[k].get("hz_design"), _allowed, now=now)
                rows[k]["lamp"], rows[k]["lamp_reason"] = st, why
            except Exception:                                                    # noqa: BLE001
                rows[k]["lamp"], rows[k]["lamp_reason"] = "-", ""
        lamp_tally = {}
        try:
            from lerobot.dataspace import lamps as L2
            lamp_tally = L2.tally([r.get("lamp", "-") for r in rows.values() if r.get("lamp") != "-"])
        except Exception:                                                        # noqa: BLE001
            pass
        return {
            "ts": now, "mode": self.mode, "mode_desc": T.MODE_DESC.get(self.mode, ""),
            "lamp_tally": lamp_tally,
            "n_topics_allowed": len(self.keys), "n_topics_registered": len(T.TOPICS),
            "n_topic_alive": sum(1 for r in rows.values() if r["count"]),
            "rule_defs": len(T.QUALITY_RULES), "registry_version": T.VERSION,
            "topics": rows,
            "loop": [{"id": s["id"], "name": s["name"], "gate": s["gate"]} for s in T.CLOSED_LOOP],
        }

    def write(self, snap):
        os.makedirs(os.path.dirname(self.out), exist_ok=True)
        # 🚌 Trace 窗口(CANoe 报文追踪): 单独落一份, UI 只读它, 便于暂停/导出
        try:
            tp = self.out.replace("live.json", "trace.jsonl")
            with open(tp + ".tmp", "w", encoding="utf-8") as f:
                for r in self.trace[-600:]:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            os.replace(tp + ".tmp", tp)
        except Exception:                                                    # noqa: BLE001
            pass
        tmp = self.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.out)
        return self.out

    def print_table(self, snap):
        print("=" * 96)
        print("📡 全局数据空间 · 全链路 topic 可视化   mode=%s(%s) · 允许 %d / 注册 %d 话题 · 注册表 v%s"
              % (snap["mode"], snap["mode_desc"][:28], snap["n_topics_allowed"],
                 snap["n_topics_registered"], snap["registry_version"]))
        print("=" * 96)
        print("%-14s %-13s %8s %8s %8s %7s %6s %-6s %s" %
              ("topic", "type", "实测Hz", "设计Hz", "帧龄s", "条数", "配对", "裁决", "质量"))
        for k, r in sorted(snap["topics"].items()):
            bad = [x["rule"] for x in r["rules"] if not x["ok"]]
            print("zmax/%-9s %-13s %8s %8s %8s %7d %6s %-6s %s" %
                  (k, (r["type"] or "").split("::")[-1], r["hz"], r["hz_design"],
                   r["age_s"] if r["age_s"] is not None else "-", r["count"], r.get("matched_pubs"),
                   r["verdict"], ("%s %s" % ({"green": "🟢", "yellow": "🟡", "red": "🔴",
                                              "black": "⚫"}.get(r.get("lamp", ""), "·"),
                                             r.get("lamp_reason", "")[:34])) if not bad else ("⚠ " + ",".join(bad))))
        if not self.keys:
            print("  (mode=prod: 量产零开销, 不建参与者 —— 想看话题请切 diag/calib/test)")
        print("-" * 96)
        for s in T.CLOSED_LOOP:
            print("  %-3s %-12s 门: %s" % (s["id"], s["name"], s["gate"][:70]))


def main():
    ap = argparse.ArgumentParser(description="全局数据空间探针(全链路 topic 可视化)")
    ap.add_argument("--seconds", type=float, default=10.0, help="采集窗口秒数")
    ap.add_argument("--watch", action="store_true", help="常驻: 每 interval 秒刷新 JSON")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--mode", default=None, help="覆盖遥测模式(prod/diag/calib/test)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--json", action="store_true", help="只打 JSON")
    a = ap.parse_args()

    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)
    p = Probe(mode=a.mode, out=a.out)
    if a.mode and p.node is None and a.mode != "prod":
        print("⚠ 该模式不与守护口径一致或 DDS 不可用", file=sys.stderr)

    if a.watch:
        while not _STOP["v"]:
            p.pump(a.interval)
            snap = p.snapshot()
            p.write(snap)
            if not a.json:
                os.system("clear") if os.isatty(1) else None
                p.print_table(snap)
        return 0

    p.pump(a.seconds)
    snap = p.snapshot()
    p.write(snap)
    if a.json:
        print(json.dumps(snap, ensure_ascii=False, indent=1))
    else:
        p.print_table(snap)
        print("\n落盘: %s" % p.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
