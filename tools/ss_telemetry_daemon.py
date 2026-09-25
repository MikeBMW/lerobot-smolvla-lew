#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 状态空间「全局数据空间」发布守护 —— 把真实数据源接上 DDS

老倪 2026-09-25: "状态空间工程全局数据空间用DDS协议" + "topic用于测试/标定/诊断, 量产关闭"

设计:
  · 启动先看**遥测模式**（zmax_telemetry）→ prod 直接退出（零开销, 不占 CPU/端口）
  · 每个话题**只从真实本地源**取数; 取不到就**跳过**（绝不用 0/假值冒充）
  · 各话题独立频率; 单话题失败不影响其它

话题 ← 真实数据源（本机可验证）:
  ss_infer     ← 推理服务 /health (model/latency/infer_count)      http://127.0.0.1:8790/health
  train_prog   ← 训练日志最新步数 (train_*.log / web_job_*.log)
  ss_diag      ← 推理延时 + relay/APP 数据龄 + GPU 利用率 + 健康度
  ss_state     ← 状态空间/流形快照 JSON (docs/manifold_view.json 等)
  ss_canvas    ← 画布节点状态 (docs/PIPELINE_STATE.json)
  ss_calib     ← 标定真源 (zmax_robot_spec/calib.json)
  ss_test      ← 测试/自检结果 JSON (若有)
  hw_state     ← nvidia-smi + /proc（硬件, 已有发布端; 这里兜底补一条）
  heartbeat    ← 存活

用法: python3 tools/ss_telemetry_daemon.py            # 按当前模式跑; prod 自动退出
      python3 tools/ss_telemetry_daemon.py --once     # 只发一轮（自测用）
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

REPO = "/home/ubuntu/lerobot-smolvla-lew"
for _c in ("/home/ubuntu/zmax_dds", os.path.join(REPO, "dds"), os.path.join(REPO, "tools", "gui")):
    if os.path.isdir(_c) and _c not in sys.path:
        sys.path.insert(0, _c)

INFER = "http://127.0.0.1:8790/health"
RELAY_STATUS = "https://datadrive.world/api/relay/status"


def sh(c, t=6):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:                                                           # noqa: BLE001
        return ""


def jget(url, timeout=6):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:                                                           # noqa: BLE001
        return None


# ─────────────────────────── 各话题的真实取值 ───────────────────────────
def src_ss_infer():
    """推理服务 /health → 每个模型一条 SSInfer"""
    j = jget(INFER)
    if not j:
        return []
    out = []
    for m in (j.get("models") or []):
        out.append(dict(model=str(m)[:64], layer="L4", latency_ms=float(j.get("last_ms") or -1.0),
                        device=str(j.get("device") or ""), conf=-1.0, ok=1,
                        out_vec=[], note="infer_count=%s load_ms=%s" % (j.get("infer_count"), j.get("load_ms"))))
    return out


def src_train_prog():
    """训练日志 → 最新 (job, step/total, running)"""
    out = []
    try:
        files = sorted(glob.glob("/tmp/train_*.log") + glob.glob("/tmp/web_job_*.log") + glob.glob("/tmp/joint_*.log"),
                       key=lambda x: -os.path.getmtime(x))[:3]
        for f in files:
            if time.time() - os.path.getmtime(f) > 900:
                continue
            txt = open(f, "r", errors="replace").read()[-6000:]
            step = total = -1
            for ln in reversed(txt.splitlines()):
                m = re.search(r"(\d+)\s*/\s*(\d+)", ln)
                if m and ("step" in ln.lower() or "Training" in ln):
                    step, total = int(m.group(1)), int(m.group(2))
                    break
            running = 1 if "Training" in txt[-2000:] or "it/s" in txt[-500:] else 0
            out.append(dict(job=os.path.basename(f)[:48], layer="L4", step=step, total=total,
                            running=running, loss=-1.0, note=""))
    except Exception:                                                           # noqa: BLE001
        pass
    return out


def src_ss_diag():
    """诊断: 推理延时/计数 · APP 数据龄 · GPU 利用率 → 健康度"""
    out = []
    j = jget(INFER)
    if j:
        lat = float(j.get("last_ms") or -1.0)
        out.append(dict(node="infer_server", kind="latency", latency_ms=lat, count=int(j.get("infer_count") or -1),
                        health=(1.0 if 0 <= lat < 50 else (0.5 if lat < 200 else 0.1)),
                        level=("ok" if 0 <= lat < 50 else "warn"), msg="device=%s" % j.get("device")))
    rs = jget(RELAY_STATUS)
    if rs:
        up = float(rs.get("uptime") or -1)
        out.append(dict(node="ecs_relay", kind="health", count=int(rs.get("packages") or -1),
                        health=1.0 if up > 0 else 0.0, level="ok" if up > 0 else "error",
                        msg="latest=%s" % str(rs.get("latest"))[:40]))
    o = sh("nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits")
    if o and "," in o:
        u, mu = [x.strip() for x in o.split(",")[:2]]
        out.append(dict(node="4060", kind="throughput", hz=-1.0, health=float(u) / 100.0,
                        level="ok", msg="gpu=%s%% mem=%sMB" % (u, mu)))
    return out


def src_ss_state():
    """状态空间/流形快照"""
    for cand in ("docs/manifold_view.json", "docs/state_view.json", "static-wm/reports/manifold_view.json"):
        p = os.path.join(REPO, cand)
        if os.path.isfile(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                th = d.get("theta") or {}
                return [dict(layer="ALL", stage=str(d.get("stage") or ""), dim=-1, vec=[],
                             manifold_theta=float(th.get("mean") or d.get("theta_mean") or -1.0),
                             manifold_norm=float(d.get("residual") or -1.0),
                             pos_x=-1.0, pos_y=-1.0, pos_z=-1.0,
                             lyap_v=-1.0, lyap_dv=-1.0, source="file:%s" % os.path.basename(p),
                             note=str(d.get("generated_at") or "")[:24])]
            except Exception:                                                   # noqa: BLE001
                pass
    return []


def src_ss_canvas():
    """画布/流水线节点状态"""
    p = os.path.join(REPO, "docs/PIPELINE_STATE.json")
    if not os.path.isfile(p):
        return []
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:                                                           # noqa: BLE001
        return []
    out = []
    for name, st in (d.get("stages") or {}).items():
        out.append(dict(node_id=str(name), name=str(name), layer="", status=str(st)[:24], fps=-1.0,
                        last_ms=-1.0, counter=-1, note="stage=%s" % d.get("stage")))
    return out[:24]


def src_ss_calib():
    """标定真源: zmax_robot_spec/calib.json → 手眼/台面"""
    out = []
    for cand in ("zmax_robot_spec/calib.json", "configs/calib.json", "calib.json"):
        p = os.path.join(REPO, cand)
        if not os.path.isfile(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                                       # noqa: BLE001
            continue
        for kind in ("handeye", "plane", "teach_point", "extrinsic"):
            v = d.get(kind)
            if not isinstance(v, dict):
                continue
            T = v.get("T") or v.get("matrix") or []
            T = [float(x) for x in T][:16] if isinstance(T, list) else []
            out.append(dict(kind=kind, src_frame=str(v.get("src") or v.get("src_frame") or "camera"),
                            dst_frame=str(v.get("dst") or v.get("dst_frame") or "base"), T=T,
                            plane_z_mm=float(v.get("plane_z_mm") if v.get("plane_z_mm") is not None else -1.0),
                            tx=float(T[3]) * 1000 if len(T) >= 16 else -1.0,
                            ty=float(T[7]) * 1000 if len(T) >= 16 else -1.0,
                            tz=float(T[11]) * 1000 if len(T) >= 16 else -1.0,
                            rx_deg=-1.0, ry_deg=-1.0, rz_deg=-1.0,
                            rms_mm=float(v.get("rms_mm") or v.get("rms") or -1.0),
                            samples=int(v.get("samples") or -1),
                            valid=1 if (T or v.get("plane_z_mm") is not None) else 0,
                            note="src=%s" % cand))
    return out


def src_ss_test():
    """测试/自检结果 JSON（存在才发）"""
    out = []
    for pat in ("reports/app_train_proof_*.json", "reports/gpu_proof_*.json", "reports/*test*.json"):
        for p in sorted(glob.glob(os.path.join(REPO, pat)), key=lambda x: -os.path.getmtime(x))[:2]:
            try:
                d = json.load(open(p, encoding="utf-8"))
            except Exception:                                                   # noqa: BLE001
                continue
            rings = d.get("rings") or d.get("checks") or d
            ok = 1 if (d.get("ok") is True or d.get("real") is True) else 0
            n = len(rings) if isinstance(rings, (list, dict)) else -1
            out.append(dict(suite=os.path.basename(p)[:40], case="proof_chain", passed=ok, dur_ms=-1.0,
                            total=n, failed=(n - 1 if ok and n > 0 else -1),
                            detail=json.dumps(d, ensure_ascii=False)[:200]))
    return out


def src_hw():
    """硬件（兜底补一条, 主发布端另有服务）"""
    o = sh("nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw "
           "--format=csv,noheader,nounits")
    if not (o and "," in o):
        return None
    p = [x.strip() for x in o.split(",")]
    try:
        f = lambda x: float(x)                                            # noqa: E731
        return dict(node="4060", role="工作端(4060)", backend="cuda", device_name=p[0],
                    util_pct=f(p[1]), mem_used_mb=f(p[2]), mem_total_mb=f(p[3]),
                    temp_c=f(p[4]), power_w=f(p[5]), ts=time.time())
    except Exception:                                                           # noqa: BLE001
        return None


# 话题 → (构造函数, 类名, 间隔秒)
TOPIC_PLAN = [
    ("ss_infer",   src_ss_infer,     "SSInfer",     3.0),
    ("ss_diag",    src_ss_diag,      "SSDiag",      3.0),
    ("train_prog", src_train_prog,   "TrainProgress", 8.0),
    ("ss_state",   src_ss_state,     "SSState",    10.0),
    ("ss_canvas",  src_ss_canvas,    "SSCanvasNode", 10.0),
    ("ss_calib",   src_ss_calib,     "SSCalib",    15.0),
    ("ss_test",    src_ss_test,      "SSTest",     15.0),
    ("hw_state",   src_hw,           "HardwareState", 3.0),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    import zmax_telemetry as T
    if not T.is_enabled():
        print("🔴 遥测模式 = prod（量产关闭）→ 守护不启动, 零开销")
        print("   要启用: python3 tools/gui/zmax_telemetry.py --mode diag")
        return 0
    print("🟢 " + T.status_text())
    allow = set(T.topics())

    from zmax_node import Node
    import zmax_types as ZT
    import ss_types as ST
    node = Node("ss-telemetry", config_xml="/home/ubuntu/zmax_dds/cyclonedds_unicast.xml")
    cls_of = {"SSInfer": ST.SSInfer, "SSDiag": ST.SSDiag, "SSState": ST.SSState,
              "SSCanvasNode": ST.SSCanvasNode, "SSCalib": ST.SSCalib, "SSTest": ST.SSTest,
              "TrainProgress": ZT.TrainProgress, "HardwareState": ZT.HardwareState}
    plan = [x for x in TOPIC_PLAN if x[0] in allow]
    print("   将发布: %s" % ", ".join(x[0] for x in plan))
    if not plan:
        print("   当前模式无允许话题")
        return 0
    for t, _, _, _ in plan:
        node.pub(t)
    last = {}
    hb = 0
    while True:
        now = time.time()
        for topic, fn, clsname, iv in plan:
            if now - last.get(topic, 0) < iv:
                continue
            last[topic] = now
            try:
                rows = fn()
                if rows is None or rows == []:
                    continue                                   # 无真实源 → 跳过（不造假值）
                if isinstance(rows, dict):
                    rows = [rows]
                cls = cls_of[clsname]
                n = 0
                for r in rows:
                    kw = {k: v for k, v in r.items() if k in cls.__dataclass_fields__}
                    kw["ts"] = kw.get("ts") or now
                    node.send(topic, cls(**kw))
                    n += 1
                if n:
                    print("[%s] 📡 %s × %d" % (time.strftime("%H:%M:%S"), topic, n), flush=True)
            except Exception as e:                                              # noqa: BLE001
                print("[%s] ⚠️ %s: %s" % (time.strftime("%H:%M:%S"), topic, str(e)[:90]), flush=True)
        hb += 1
        if hb % 3 == 0 and "heartbeat" in allow:
            try:
                node.send("heartbeat", ZT.Heartbeat(node="ss-telemetry", role="全局数据空间", alive=1, ts=time.time()))
            except Exception:                                                   # noqa: BLE001
                pass
        if a.once:
            return 0
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
