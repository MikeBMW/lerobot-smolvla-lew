#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmax_dds_ss_daemon.py — 📡 全局数据空间发布守护 (状态空间真实数据源 → DDS, 受模式控制)

老倪 2026-09-25/26:
  「topic 用于测试, 标定, 诊断, 量产时不用」+「写全局数据空间发布守护 (把所有真实数据源接上 DDS, 受模式控制)」

════════════════════ 设计 (与 docs/DDS-TELEMETRY-ARCHITECTURE.md 同口径) ════════════════════
① **受模式控制**: 模式 = env `ZMAX_TELEMETRY` > 运行时 > 文件 `~/.zmax_telemetry_mode` > prod
   · prod: **根本不 import cyclonedds**、不建参与者、不开线程 → 量产零开销 (只空转等模式变化)
   · diag/calib/test: 只发该档允许的话题 (见 zmax_telemetry.MODE_TOPICS)
② **只读真实数据源** (不触发任何动作, 不写任何业务文件):
   ss_state  ← 真机 tap `~/zmax_ss_remote/state_*.jsonl` 最新行 (tcp / jpos / gripper / prod_stage / pubs)
   ss_action ← 真机 tap `~/zmax_ss_remote/proposal_*.jsonl` 最新行 (action 6 维 / yaw / model_ms)
   ss_infer  ← 本机推理服务 `http://127.0.0.1:8790/health` (models / infer_count / last_ms / device)
   ss_calib  ← 标定真源文件 (手眼 / 相机外参 / 对齐图 / 质量门) —— 有则实发, 无则 valid=0
   ss_diag   ← 诊断: 各话题发布计数 / 源帧龄 / 推理延时 / 服务健康度 (systemctl 每 10s)
   ss_test   ← 最近一次取证结果 (reports/verify_*.json · sim2real_preflight · web agent 27/27)
③ **未测量 = -1.0** (不用 0 冒充) · 每条消息带 ts + 每话题 seq · 源帧过期 (>5s) 只发 diag 告警不发状态
④ 通道分离: 本守护只做 **通道 A (内网遥测)**; APP 硬件上报 (hw_state) 属通道 B, 由 zmax-dds-pub 独立跑

用法:
  python3 zmax_dds_ss_daemon.py --status          # 看模式 + 允许话题 + 各源可用性
  python3 zmax_dds_ss_daemon.py --once            # 发一轮(按当前模式) 后退出 (取证/自检用)
  python3 zmax_dds_ss_daemon.py --seconds 30      # 跑 30 秒
  python3 zmax_dds_ss_daemon.py                   # 常驻 (systemd 用)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
SS_REMOTE = os.environ.get("SS_REMOTE_DIR", os.path.join(HOME, "zmax_ss_remote"))
REPO = "/home/ubuntu/lerobot-smolvla-lew"
MODELS = os.path.join(REPO, "models")
REPORTS = os.path.join(REPO, "reports")
REPORTS_CANDS = [os.path.join("/home/ubuntu/zmax_rel", "reports"), REPORTS]
INFER = "http://127.0.0.1:8790/health"
MODE_FILE = os.path.join(HOME, ".zmax_telemetry_mode")
DDS_DIR = "/home/ubuntu/zmax_dds"
LOG = os.path.join("/tmp", "zmax_dds_ss.log")
STALE_S = 5.0                     # 源帧龄超过它就只发 diag, 不发状态/动作 (老倪: 负帧龄拒用)

# 模式 → 允许话题 (与 tools/gui/zmax_telemetry.py::MODE_TOPICS 同口径)
MODE_TOPICS = {
    "prod": [],
    "diag": ["hw_state", "heartbeat", "ss_infer", "train_prog", "ss_diag"],
    "calib": ["ss_state", "ss_action", "link_value", "hw_state", "heartbeat", "ss_calib", "ss_diag"],
    "test": ["hw_state", "heartbeat", "train_prog", "deploy_cmd", "link_value", "ss_state", "ss_action",
             "ss_infer", "ss_canvas", "ss_macro", "ss_nodes", "ss_calib", "ss_diag", "ss_test"],
}
MODE_TOPICS["dev"] = MODE_TOPICS["test"]


def log(m):
    line = "%s %s" % (time.strftime("%F %T"), m)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:                                                        # noqa: BLE001
        pass


# ───────────────────────── 模式 (单一真源优先, 读不到则按同口径兜底) ─────────────────────────
def mode():
    env = (os.environ.get("ZMAX_TELEMETRY") or "").strip().lower()
    if env in MODE_TOPICS:
        return env
    for p in (os.path.join(REPO, "tools", "gui"),):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import zmax_telemetry as zt                                  # noqa: PLC0415
        return zt.mode()
    except Exception:                                                # noqa: BLE001
        pass
    try:
        m = open(MODE_FILE, encoding="utf-8").read().strip().lower()
        if m in MODE_TOPICS:
            return m
    except Exception:                                                # noqa: BLE001
        pass
    return "prod"


def allowed(topic):
    return topic in MODE_TOPICS.get(mode(), [])


# ───────────────────────── 真实数据源读取 (全只读) ─────────────────────────
def _newest(pattern):
    c = glob.glob(pattern)
    return max(c, key=os.path.getmtime) if c else None


def _last_line(path, max_bytes=262144):
    """只读文件尾 (不整文件读入 — state_*.jsonl 已 500MB+)"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            chunk = f.read().decode("utf-8", "ignore").strip().splitlines()
        for ln in reversed(chunk):
            if ln.strip().startswith("{"):
                try:
                    return json.loads(ln)
                except Exception:                                    # noqa: BLE001
                    continue
    except Exception:                                                # noqa: BLE001
        pass
    return None


def read_state():
    """真机 tap 状态帧 (tcp/jpos/gripper/prod_stage)"""
    p = _newest(os.path.join(SS_REMOTE, "state_*.jsonl"))
    if not p:
        return None, None
    d = _last_line(p)
    return d, (os.path.getmtime(p) if p else None)


def read_proposal():
    """推理服务对真机帧的输出 (action 6 / yaw / model_ms)"""
    p = _newest(os.path.join(SS_REMOTE, "proposal_*.jsonl"))
    if not p:
        return None, None
    d = _last_line(p)
    return d, (os.path.getmtime(p) if p else None)


def read_infer():
    try:
        import urllib.request
        with urllib.request.urlopen(INFER, timeout=3) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:                                                # noqa: BLE001
        return {}


def read_calibs():
    """标定真源 (存在才发, 不发假值)

    ⚠️ 2026-09-26: 标定文件在 **main 线检出** (worktree /home/ubuntu/zmax_rel/models) ——
    共享目录 /home/ubuntu/lerobot-smolvla-lew 被切到别的分支后这些文件会"消失"
    → 必须在多候选目录里找, 否则标定通道静默空转。
    """
    out = []
    trees = [os.path.join("/home/ubuntu/zmax_rel", "models"),
             MODELS,
             os.path.join(HOME, "zmax_data", "calib")]
    seen = set()
    cands = []
    for t in trees:
        for fn, kind in (("handeye_state.json", "handeye"), ("real_cam_calib.json", "extrinsic"),
                         ("l4_align_map.json", "align"), ("lie_quality_gate.json", "gate")):
            p = os.path.join(t, fn)
            if p in seen:
                continue
            seen.add(p)
            cands.append((p, kind))
    for p, kind in cands:
        if os.path.isfile(p):
            try:
                out.append((kind, json.load(open(p, encoding="utf-8"))))
            except Exception:                                        # noqa: BLE001
                out.append((kind, {}))
    return out


def read_test_result():
    """最近一次取证结果 (passed/total 若有)"""
    pats = ["verify_*.json", "*preflight_*.json", "intact_v4_*.json", "l4_intact_ab_*.json"]
    best = None
    for pat in pats:
        for rd in REPORTS_CANDS:
            for p in glob.glob(os.path.join(rd, pat)):
                if best is None or os.path.getmtime(p) > best[1]:
                    best = (p, os.path.getmtime(p))
    if not best:
        return None
    p, mt = best
    passed = failed = total = None
    detail = os.path.basename(p)
    try:
        d = json.load(open(p, encoding="utf-8"))
        if isinstance(d, dict):
            for k in ("passed", "ok_count", "judge_passed", "n_pass"):
                if isinstance(d.get(k), int):
                    passed = d[k]
                    break
            for k in ("failed", "ng_count", "n_fail"):
                if isinstance(d.get(k), int):
                    failed = d[k]
                    break
            for k in ("total", "n", "judge_total", "n_total"):
                if isinstance(d.get(k), int):
                    total = d[k]
                    break
            detail = "%s %s" % (detail, json.dumps({k: d[k] for k in list(d)[:3]}, ensure_ascii=False)[:120])
    except Exception:                                                # noqa: BLE001
        pass
    return {"path": p, "suite": pat.split("*")[0].strip("_") or "verify",
            "passed": passed, "failed": failed, "total": total, "detail": detail, "ts": mt}


def services_health():
    out = {}
    for s in ("ss-local-infer", "ss-bypass", "ss-remote-tap", "ss-yolo-bypass",
              "zmax-dds-pub", "zmax-dds-agg"):
        try:
            r = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True, timeout=5)
            out[s] = (r.stdout or "").strip() or "unknown"
        except Exception:                                            # noqa: BLE001
            out[s] = "?"
    return out


# ───────────────────────── 发布守护 ─────────────────────────
class SSDaemon:
    def __init__(self):
        self.node = None
        self.seq = {}
        self.sent = {}
        self.errs = 0
        self.t0 = time.time()
        self._svc = {}
        self._svc_t = 0.0
        self._mode = None
        self._pending = {}      # topic → 等配对是否成功 (只提示一次)

    def ensure_node(self):
        if self.node is not None:
            return True
        if DDS_DIR not in sys.path:
            sys.path.insert(0, DDS_DIR)
        try:
            from zmax_node import Node                              # noqa: PLC0415
            cfg = os.path.join(DDS_DIR, "cyclonedds_unicast.xml")
            self.node = Node("ss_daemon", domain=0, config_xml=cfg if os.path.getsize(cfg) else None)
            log("📡 DDS 参与者已建立 (mode=%s, 允许话题 %d 个)" % (mode(), len(MODE_TOPICS.get(mode(), []))))
            return True
        except Exception as e:                                        # noqa: BLE001
            self.errs += 1
            log("⚠️ DDS 不可用: %s" % str(e)[:140])
            self.node = None
            return False

    def drop_node(self):
        self.node = None
        log("🔴 切到 prod: DDS 参与者已释放 (量产零开销)")

    def publish(self, topic, msg):
        """按模式发一条 (带 ts/seq)"""
        if not allowed(topic):
            return False
        if not self.ensure_node():
            return False
        self.seq[topic] = self.seq.get(topic, 0) + 1
        if topic not in self._pending and self.node.wait_for_match(topic, 1, 1.5):
            self._pending[topic] = True
        try:
            self.node.send(topic, msg)
            self.sent[topic] = self.sent.get(topic, 0) + 1
            return True
        except Exception as e:                                        # noqa: BLE001
            self.errs += 1
            log("⚠️ 发 %s 失败: %s" % (topic, str(e)[:110]))
            return False

    # ── 各真实源 → DDS 消息 ──
    def pub_state(self):
        from ss_types import SSState                                 # noqa: PLC0415
        d, mt = read_state()
        age = (time.time() - mt) if mt else -1.0
        if not d or age > STALE_S:
            return False
        tcp = d.get("tcp") or []
        jpos = d.get("jpos") or []
        vec = [float(x) for x in (jpos + ([float(d["gripper"])] if isinstance(d.get("gripper"), (int, float)) else []))]
        self.publish("ss_state", SSState(
            ts=time.time(), layer="L2", stage=str(d.get("prod_stage", "") or ""),
            vec=vec, dim=len(vec),
            pos_x=float(tcp[0]) if len(tcp) > 0 else -1.0,
            pos_y=float(tcp[1]) if len(tcp) > 1 else -1.0,
            pos_z=float(tcp[2]) if len(tcp) > 2 else -1.0,
            source="real(tap)", note="frame_age=%.2fs tcp_frame=%s" % (age, d.get("tcp_frame", ""))))
        return True

    def pub_action(self):
        from ss_types import SSAction                                # noqa: PLC0415
        d, mt = read_proposal()
        age = (time.time() - mt) if mt else -1.0
        if not d or age > STALE_S:
            return False
        act = d.get("action") or []
        yaw = d.get("yaw") or {}
        self.publish("ss_action", SSAction(
            ts=time.time(), kind="joint", joints=[float(x) for x in act][:6],
            source="infer-8790(%s)" % d.get("input_map", ""),
            gate_reason="model_ms=%s yaw_ok=%s" % (d.get("model_ms"),
                                                  (yaw.get("ok") if isinstance(yaw, dict) else yaw))))
        return True

    def pub_infer(self):
        from ss_types import SSInfer                                 # noqa: PLC0415
        h = read_infer()
        if not h:
            return False
        self.publish("ss_infer", SSInfer(
            ts=time.time(), model="+".join(h.get("models") or [])[:120], layer="L4",
            latency_ms=float(h.get("last_ms") if h.get("last_ms") is not None else -1.0),
            device=str(h.get("device", "")),
            ok=1 if h.get("online") else 0,
            note="infer_count=%s load_ms=%s port=%s" % (h.get("infer_count"), h.get("load_ms"), h.get("port"))))
        return True

    def pub_calib(self):
        from ss_types import SSCalib                                 # noqa: PLC0415
        n = 0
        for kind, d in read_calibs():
            T = []
            for k in ("T", "T_base_cam", "handeye", "transform"):
                v = d.get(k) if isinstance(d, dict) else None
                if isinstance(v, list) and len(v) == 16:
                    T = [float(x) for x in v]
                    break
            def g(*ks):
                for k in ks:
                    if isinstance(d, dict) and isinstance(d.get(k), (int, float)):
                        return float(d[k])
                return -1.0
            self.publish("ss_calib", SSCalib(
                ts=time.time(), kind=kind,
                src_frame=str((d or {}).get("src_frame", (d or {}).get("parent", "")) if isinstance(d, dict) else ""),
                dst_frame=str((d or {}).get("dst_frame", (d or {}).get("child", "")) if isinstance(d, dict) else ""),
                T=T, plane_z_mm=g("plane_z_mm", "plane_z", "z_mm"),
                tx=g("tx", "x"), ty=g("ty", "y"), tz=g("tz", "z"),
                rx_deg=g("rx_deg", "rx"), ry_deg=g("ry_deg", "ry"), rz_deg=g("rz_deg", "rz"),
                rms_mm=g("rms_mm", "residual_mm", "rmse_mm"), samples=int(g("samples", "n")),
                valid=1 if T or g("rms_mm") >= 0 else 0,
                note="file=%s" % kind))
            n += 1
        return n > 0

    def pub_diag(self):
        from ss_types import SSDiag                                  # noqa: PLC0415
        now = time.time()
        _, st_mt = read_state()
        _, pr_mt = read_proposal()
        h = read_infer()
        if now - self._svc_t > 10:
            self._svc = services_health()
            self._svc_t = now
        self.publish("ss_diag", SSDiag(
            ts=now, node="ss_daemon", kind="frame_age",
            frame_age_s=round(now - st_mt, 3) if st_mt else -1.0,
            hz=-1.0, dropped=self.errs, health=1.0 if (st_mt and now - st_mt < STALE_S) else 0.0,
            level="ok" if (st_mt and now - st_mt < STALE_S) else "warn",
            msg="state=%s proposal=%s" % (round(now - st_mt, 2) if st_mt else "无",
                                          round(now - pr_mt, 2) if pr_mt else "无")))
        self.publish("ss_diag", SSDiag(
            ts=now, node="ss-local-infer", kind="latency",
            latency_ms=float(h.get("last_ms")) if isinstance(h.get("last_ms"), (int, float)) else -1.0,
            count=int(h.get("infer_count") or -1), health=1.0 if h.get("online") else 0.0,
            level="ok" if h.get("online") else "error",
            msg="models=%s" % ",".join((h.get("models") or [])[:2])))
        okn = sum(1 for v in self._svc.values() if v == "active")
        self.publish("ss_diag", SSDiag(
            ts=now, node="services", kind="health", count=okn,
            health=round(okn / max(1, len(self._svc)), 3), level="ok" if okn == len(self._svc) else "warn",
            msg=json.dumps(self._svc, ensure_ascii=False)[:180]))
        for t, c in self.sent.items():
            self.publish("ss_diag", SSDiag(ts=now, node="ss_daemon", kind="throughput",
                                           count=c, hz=round(c / max(1.0, now - self.t0), 3),
                                           queue=self.seq.get(t, 0) - c, level="ok", msg="topic=" + t))
        return True

    def pub_test(self):
        from ss_types import SSTest                                  # noqa: PLC0415
        r = read_test_result()
        if not r:
            return False
        n = 0
        for key, val in (("passed", r["passed"]), ("failed", r["failed"]), ("total", r["total"])):
            if isinstance(val, int):
                self.publish("ss_test", SSTest(
                    ts=time.time(), suite=r["suite"], case=key,
                    passed=1 if (key == "passed" and val > 0) else (0 if key == "failed" and val > 0 else -1),
                    total=r["total"] if isinstance(r["total"], int) else -1,
                    failed=r["failed"] if isinstance(r["failed"], int) else -1,
                    detail=r["detail"][:200]))
                n += 1
        if n == 0:
            self.publish("ss_test", SSTest(ts=time.time(), suite=r["suite"], case="artifact",
                                           passed=-1, total=-1, detail=r["detail"][:200]))
            n = 1
        return n > 0

    def tick(self, fast=True):
        m = mode()
        if m != self._mode:
            log("🔀 遥测模式 → %s (允许 %d 个话题)" % (m, len(MODE_TOPICS.get(m, []))))
            self._mode = m
        if m == "prod":
            if self.node is not None:
                self.drop_node()
            return
        if not self.ensure_node():
            return
        # ⚠️ 每个允许话题**每轮都发**: DDS 发现是异步的, 只发一次会丢给"还没发现"的读者
        #    (实测: diag 首发命中, 低频的 infer/calib/test 首发丢失 → 取证假失败)
        #    文件类源 (calib/test) 用 mtime 缓存解析结果, 保持每轮发但不重复读盘。
        if allowed("ss_state"):
            self.pub_state()
        if allowed("ss_action"):
            self.pub_action()
        if allowed("ss_diag"):
            self.pub_diag()
        if allowed("ss_infer"):
            self.pub_infer()
        if allowed("ss_calib"):
            self.pub_calib()
        if allowed("ss_test"):
            self.pub_test()

    def run(self, seconds=0.0, once=False):
        t0 = time.time()
        n = 0
        while True:
            try:
                fast = (n % 5 == 0)
                self.tick(fast=fast)
            except Exception as e:                                    # noqa: BLE001
                self.errs += 1
                log("⚠️ tick 异常: %s" % str(e)[:140])
            n += 1
            if once:
                return
            if seconds and time.time() - t0 >= seconds:
                log("⏹ 到时长退出 (sent=%s)" % json.dumps(self.sent, ensure_ascii=False))
                return
            time.sleep(2.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="发一轮后退出")
    ap.add_argument("--seconds", type=float, default=0.0, help="跑多久 (0=常驻)")
    ap.add_argument("--status", action="store_true", help="只看模式与源可用性")
    a = ap.parse_args()
    m = mode()
    if a.status:
        st, smt = read_state()
        pr, pmt = read_proposal()
        h = read_infer()
        print(json.dumps({"mode": m, "allowed_topics": MODE_TOPICS.get(m, []),
                          "state_src": {"file": _newest(os.path.join(SS_REMOTE, "state_*.jsonl")),
                                        "keys": list(st) if st else None},
                          "action_src": {"file": _newest(os.path.join(SS_REMOTE, "proposal_*.jsonl")),
                                         "keys": list(pr) if pr else None},
                          "infer": {"online": h.get("online"), "infer_count": h.get("infer_count")},
                          "calib_files": [k for k, _ in read_calibs()],
                          "test_src": (read_test_result() or {}).get("path")},
                         ensure_ascii=False, indent=1))
        return 0
    d = SSDaemon()
    log("📡 全局数据空间发布守护启动 (模式=%s · 允许=%d 话题 · prod 时不 import cyclonedds)"
        % (m, len(MODE_TOPICS.get(m, []))))
    d.run(seconds=a.seconds, once=a.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
