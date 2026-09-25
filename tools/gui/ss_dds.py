#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_dds.py — 状态空间工程 · 全局数据空间 DDS 发布器
======================================================
把状态空间工程的**全局数据空间**（7 个闭环节点状态）通过 **DDS** 发布到总线。

链路:
  本机采集真实状态 → WebSocket(TCP443) → ECS DDS 网关 → DDS 总线(ZMAX_Status)
                                              ↓
                                    web/APP 全局数据空间页

话题: ZMAX_Status (复用现有 DDS 总线)
消息: {"type":"status","payload":{"kind":"ss_node_state","nodes":[...]}}
节点字段: node_id / node_name / stage / state / detail / updated
  (与 dds.db 的 dds_node_state 表同构 — 可直接落库)

用法:
    python3 ss_dds.py --once              # 采集一次并发布
    python3 ss_dds.py --loop              # 常驻 (默认 15s)
    python3 ss_dds.py --show              # 只看采集结果, 不发布
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ECS = os.environ.get("ZMAX_ECS", "http://datadrive.world")
DDS_WS = os.environ.get("ZMAX_DDS_WS", "wss://datadrive.world/ws/dds/")
ORIN = os.environ.get("ZMAX_ORIN", "192.168.23.66")


def _get(url: str, timeout: float = 6.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "zmax-ss-dds"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:
        return None


def _port_ok(host: str, port: int, timeout: float = 2.0) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def _fmt_age(age) -> str:
    if age is None:
        return "?"
    try:
        age = float(age)
    except Exception:
        return "?"
    if age < 90:
        return f"{age:.0f}s"
    if age < 5400:
        return f"{age/60:.1f}min"
    return f"{age/3600:.1f}h"


def collect_node_states() -> list:
    """**真实采集**状态空间 7 个闭环节点的当前状态 (不编数, 取不到就标 offline)"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    nodes = []

    # ── ① Orin 采集 ──
    relay = _get(f"{ECS}/api/relay/status")
    orin_up = _port_ok(ORIN, 22, 2.0)
    orin_st = _get(f"{ECS}/orin/status")
    orin_online = bool(orin_st and orin_st.get("online"))
    age = None
    if relay and relay.get("latest_meta"):
        age = time.time() - (relay["latest_meta"].get("time") or 0)
    nodes.append({
        "node_id": "orin_collect", "node_name": "Orin 采集", "stage": "采集",
        "state": "ok" if orin_up else "offline",
        "detail": f"SSH {'可达' if orin_up else '不可达'} · 快照延迟{_fmt_age(age)}"
                  f" · 技能:P001 作业对象识别",
        "updated": now,
    })

    # ── ② ECS 中转 ──
    if relay:
        n_pkg = relay.get("packages")
        nodes.append({
            "node_id": "ecs_relay", "node_name": "ECS 中转", "stage": "上传",
            "state": "flow", "detail": f"队列{n_pkg}包 · 技能:P007 数据采集与上传",
            "updated": now,
        })
    else:
        nodes.append({
            "node_id": "ecs_relay", "node_name": "ECS 中转", "stage": "上传",
            "state": "offline", "detail": "relay 不可达 · 技能:P007",
            "updated": now,
        })

    # ── ③ 4060 训练/推理 (从 DDS 总线拿) ──
    hw = _get(f"{ECS}/api/train/hardware")
    m4060 = (hw or {}).get("machines", {}).get("4060", {}) if hw else {}
    models = m4060.get("models") or []
    infer_n = m4060.get("infer_count")
    last_ms = m4060.get("last_ms")
    if m4060:
        detail = (f"模型:{','.join(models) if models else '—'}"
                  f" · 推理{infer_n if infer_n is not None else '—'}次"
                  f" · 延迟{last_ms if last_ms is not None else '—'}ms"
                  f" · 技能:P003 策略训练")
        state = "ok" if infer_n else "idle"
    else:
        detail = "未上报 · 技能:P003"
        state = "offline"
    nodes.append({
        "node_id": "train_4060", "node_name": "4060 训练/推理", "stage": "训练",
        "state": state, "detail": detail, "updated": now,
    })

    # ── ④ 模型静态 URL ──
    code = None
    try:
        req = urllib.request.Request(f"{ECS}/models/l4_mani_predictor_v5.pt", method="HEAD")
        with urllib.request.urlopen(req, timeout=6) as r:
            code = r.status
    except Exception:
        code = None
    nodes.append({
        "node_id": "model_url", "node_name": "模型静态URL", "stage": "集成",
        "state": "ok" if code == 200 else "unknown",
        "detail": f"HTTP {code if code else '未取到'} · 技能:P004 模型集成",
        "updated": now,
    })

    # ── ⑤ Orin 部署 ──
    infer_up = _port_ok(ORIN, 8767, 2.0)
    nodes.append({
        "node_id": "orin_deploy", "node_name": "Orin 部署", "stage": "部署",
        "state": "ok" if infer_up else "offline",
        "detail": f":8767 {'在线' if infer_up else '不可达'} · 技能:P005 模型部署",
        "updated": now,
    })

    # ── ⑥ Orin 推理 ──
    inf_cnt = (orin_st or {}).get("infer_count")
    nodes.append({
        "node_id": "orin_infer", "node_name": "Orin 推理", "stage": "推理",
        "state": "flow" if inf_cnt else ("offline" if not orin_online else "idle"),
        "detail": f"推理{inf_cnt if inf_cnt is not None else 0}次"
                  f" · 模型:{(orin_st or {}).get('model') or '—'} · 技能:P006 动作执行",
        "updated": now,
    })

    # ── ⑦ 控制台 (本机) ──
    try:
        from hw_monitor import probe
        d = probe(measure=False)
        cpu = d["cpu"].get("percent")
        mem = d["mem"].get("percent")
        g = d["gpu"]
        gpu = f"{g.get('name')} {g.get('util_pct')}%"
        from hw_monitor import fmt  # noqa
        detail = f"Mac {cpu}%/{mem}% · GPU {gpu} · 技能:P008 闭环监控"
        state = "ok"
    except Exception as e:
        detail = f"本机采集异常 {type(e).__name__} · 技能:P008"
        state = "unknown"
    nodes.append({
        "node_id": "console", "node_name": "控制台", "stage": "监控",
        "state": state, "detail": detail, "updated": now,
    })

    return nodes


def publish(nodes: list) -> dict:
    """发布到 DDS 总线 (WebSocket → ECS DDS 网关 → **ZMAX_StateSpace**)
    网关契约 (2026-09-25 实测 /root/dds_ws_gateway.py):
        type="statespace" → statespace[payload['node']] = payload
      ⇒ 按 node 逐条发, payload 内含 node 字段
    """
    from websockets.sync.client import connect
    sent = 0
    last = {}
    with connect(DDS_WS, open_timeout=15) as ws:
        for n in nodes:
            payload = {
                "node": n["node_id"],            # ← 网关按这个键聚合
                "node_name": n["node_name"],
                "stage": n["stage"],
                "state": n["state"],
                "detail": n["detail"],
                "updated": n["updated"],
                "project": "zmax_state_space",
                "source": "mac",
            }
            ws.send(json.dumps({"type": "statespace", "payload": payload}, ensure_ascii=False))
            sent += 1
        try:
            last = json.loads(ws.recv(timeout=3.0) or "{}")
        except TimeoutError:
            last = {"sent": sent}
    return {"sent": sent, **last}


def _show(nodes: list):
    icons = {"ok": "✅", "flow": "🔄", "idle": "⏸", "offline": "❌", "unknown": "❓"}
    print(f"═══ 状态空间全局数据空间 · {len(nodes)} 个节点 ═══")
    for n in nodes:
        print(f"  {icons.get(n['state'],'?')} [{n['stage']}] {n['node_name']:14s} "
              f"{n['state']:8s} {n['detail']}")


def main():
    ap = argparse.ArgumentParser(description="状态空间全局数据空间 DDS 发布器")
    ap.add_argument("--once", action="store_true", help="采集一次并发布")
    ap.add_argument("--loop", action="store_true", help="常驻循环")
    ap.add_argument("--interval", type=float, default=15.0, help="循环间隔秒 (默认15)")
    ap.add_argument("--show", action="store_true", help="只显示不发布")
    a = ap.parse_args()

    if not (a.once or a.loop or a.show):
        a.once = True

    def _tick() -> list:
        nodes = collect_node_states()
        if a.show:
            _show(nodes)
            return nodes
        try:
            r = publish(nodes)
            _show(nodes)
            print(f"  → DDS 已发布 (总线节点: {r.get('nodes') or r.get('sent')})", flush=True)
        except Exception as e:
            _show(nodes)
            print(f"  → ⚠️ DDS 发布失败: {type(e).__name__}: {str(e)[:110]}", flush=True)
        return nodes

    if a.once or a.show:
        _tick()
        return 0

    print(f"🛰  状态空间数据空间 DDS 发布器启动 (每 {a.interval:.0f}s)", flush=True)
    while True:
        _tick()
        time.sleep(max(3.0, a.interval))


if __name__ == "__main__":
    sys.exit(main())
