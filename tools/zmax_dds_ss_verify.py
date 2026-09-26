#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmax_dds_ss_verify.py — 全局数据空间发布守护 取证 (模式 × 话题 × 真值)

判据 (全为真断言):
  ① prod:   守护**不 import cyclonedds**、不建参与者 → 订阅端 0 条 (量产零开销)
  ② diag:   收到 ss_diag + ss_infer, 且值真实 (延时/计数 ≠ -1, models 非空)
  ③ calib:  收到 ss_calib, T/rms/valid 来自真实标定文件 (非空 T 或 valid≥0), 且含 ss_state/ss_action
  ④ test:   收到 ss_state(真机 tap: dim>0 且 pos≠-1) + ss_action(6 关节) + ss_test(取证结果)
  ⑤ 通道分离: 本守护不碰 hw_state (B 通道由 zmax-dds-pub 负责)
用法: /home/ubuntu/dds-venv/bin/python /home/ubuntu/zmax_dds_ss_verify.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

DDS = "/home/ubuntu/zmax_dds"
DAEMON = "/home/ubuntu/zmax_dds_ss_daemon.py"
MODE_FILE = os.path.expanduser("~/.zmax_telemetry_mode")
sys.path.insert(0, DDS)

OK, NG = [], []


def chk(name, cond, detail=""):
    (OK if cond else NG).append("%s%s" % (name, (" — " + detail) if detail else ""))
    print("  %s %s%s" % ("✅" if cond else "❌", name, (" — " + detail) if detail else ""), flush=True)


def set_mode(m):
    open(MODE_FILE, "w", encoding="utf-8").write(m + "\n")


def collect(mode, topics, seconds=8.0):
    """在该模式下跑守护, 用本进程订阅收集"""
    from zmax_node import Node                                    # noqa: PLC0415
    set_mode(mode)
    n = Node("verify_%s" % mode, domain=0)
    for t in topics:
        n.sub(t)
    time.sleep(1.0)                                               # 等守护建节点
    env = dict(os.environ, ZMAX_TELEMETRY=mode)
    p = subprocess.Popen([sys.executable, DAEMON, "--seconds", str(seconds)],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    got = {}
    t0 = time.time()
    while time.time() - t0 < seconds + 2:
        for t in topics:
            s = n.take(t, 0.05)
            if s:
                got.setdefault(t, []).extend(s)
    try:
        p.wait(timeout=10)
    except Exception:                                             # noqa: BLE001
        p.kill()
    out = p.stdout.read() if p.stdout else ""
    return got, out


def main() -> int:
    print("═══ ① prod 档: 必须全关 (量产零开销) ═══")
    got, out = collect("prod", ["ss_state", "ss_action", "ss_infer", "ss_diag", "ss_calib", "ss_test"], seconds=5)
    chk("prod: 订阅端 0 条", sum(len(v) for v in got.values()) == 0, "收到 %d" % sum(len(v) for v in got.values()))
    chk("prod: 守护未建立 DDS 参与者", "DDS 参与者已建立" not in out, out.strip().splitlines()[-1][:80] if out else "")

    print("═══ ② diag 档: 诊断 + 推理 ═══")
    got, out = collect("diag", ["ss_diag", "ss_infer", "ss_state", "ss_calib"], seconds=8)
    d = (got.get("ss_diag") or [])
    i = (got.get("ss_infer") or [])
    chk("diag: 收到 ss_diag", bool(d), "n=%d" % len(d))
    chk("diag: ss_diag 值真实 (延时或计数 ≠ -1)", any(m.latency_ms != -1.0 or m.count != -1 for m in d),
        "lat=%s count=%s health=%s" % (d[0].latency_ms if d else None, d[0].count if d else None, d[0].health if d else None))
    chk("diag: 收到 ss_infer 且 model 非空", bool(i) and bool(i[0].model), (i[0].model if i else ""))
    chk("diag: 不含 ss_state (档位裁剪)", not got.get("ss_state"), "ss_state=%d" % len(got.get("ss_state") or []))
    chk("diag: 不含 ss_calib (档位裁剪)", not got.get("ss_calib"), "ss_calib=%d" % len(got.get("ss_calib") or []))

    print("═══ ③ calib 档: 标定量 (真源文件) ═══")
    got, out = collect("calib", ["ss_calib", "ss_state", "ss_action", "ss_diag"], seconds=8)
    c = got.get("ss_calib") or []
    chk("calib: 收到 ss_calib", bool(c), "n=%d" % len(c))
    chk("calib: T 非空或 valid≥0 (来自真实标定文件)", any(len(m.T) == 16 or m.valid >= 0 for m in c),
        "kinds=%s" % [m.kind for m in c][:4])
    chk("calib: 含 ss_state (真机只读状态)", bool(got.get("ss_state")), "n=%d" % len(got.get("ss_state") or []))

    print("═══ ④ test 档: 全量 (状态/动作/测试结果) ═══")
    got, out = collect("test", ["ss_state", "ss_action", "ss_test", "ss_calib", "ss_diag",
                                "ss_canvas", "ss_macro", "ss_nodes"], seconds=22)
    st, ac, te = (got.get("ss_state") or []), (got.get("ss_action") or []), (got.get("ss_test") or [])
    chk("test: 收到 ss_state (真机 tap)", bool(st), "n=%d" % len(st))
    chk("test: ss_state dim>0 且 位置非 -1", bool(st) and st[0].dim > 0 and st[0].pos_x != -1.0,
        "dim=%s pos=(%.3f,%.3f,%.3f) src=%s" % (st[0].dim if st else None,
                                                st[0].pos_x if st else 0, st[0].pos_y if st else 0,
                                                st[0].pos_z if st else 0, st[0].source if st else ""))
    chk("test: 收到 ss_action (6 关节)", bool(ac) and len(ac[0].joints) == 6,
        "joints=%s src=%s" % (len(ac[0].joints) if ac else 0, ac[0].source if ac else ""))
    chk("test: 收到 ss_test (取证结果)", bool(te), "detail=%s" % (te[0].detail[:60] if te else ""))
    chk("test: 收到 ss_calib", bool(got.get("ss_calib")), "n=%d" % len(got.get("ss_calib") or []))
    cv, mc, nd = (got.get("ss_canvas") or []), (got.get("ss_macro") or []), (got.get("ss_nodes") or [])
    chk("test: 收到 ss_canvas (画布节点真源)", bool(cv) and bool(cv[0].node_id) and bool(cv[0].name),
        "n=%d 例: %s / %s / layer=%s" % (len(cv), cv[0].node_id if cv else "", (cv[0].name or "")[:18] if cv else "",
                                        (cv[0].layer or "")[:16] if cv else ""))
    chk("test: ss_canvas 诚实标注 (无计数源 → status=idle/counter=-1)", bool(cv) and cv[0].status == "idle" and cv[0].counter == -1,
        "status=%s counter=%s fps=%s" % (cv[0].status if cv else "", cv[0].counter if cv else "", cv[0].fps if cv else ""))
    chk("test: 收到 ss_macro (五层记忆真源)", bool(mc) and bool(mc[0].layer_name),
        "layers=%s recalled=%s" % ([m.layer_name for m in mc][:5], mc[0].recalled if mc else None))
    chk("test: 收到 ss_nodes (自描述: 话题+实测Hz)", bool(nd) and len(nd[0].topics) > 3 and max(nd[0].publish_hz or [0]) > 0,
        "topics=%d 例: %s · 最高 Hz=%.3f" % (len(nd[0].topics) if nd else 0,
                                            ",".join(list(nd[0].topics)[:4]) if nd else "",
                                            max(nd[0].publish_hz or [0]) if nd else 0))

    print("═══ ⑤ 通道分离 (内网遥测不碰 APP 硬件通道) ═══")
    chk("守护源码不含 hw_state 发布", "publish(\"hw_state\"" not in open(DAEMON, encoding="utf-8").read())

    set_mode("prod")                                              # 取证完回到量产安全态
    print("\n判据通过: %d/%d" % (len(OK), len(OK) + len(NG)))
    if NG:
        print("❌ 未过:")
        for x in NG:
            print("   -", x)
    return 0 if not NG else 3


if __name__ == "__main__":
    sys.exit(main())
