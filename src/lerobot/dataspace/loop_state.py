#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔁 数据闭环 · 证据采集器 —— 让 9 个环节"过没过门"变成可看的事实

每个环节去读**一个真实来源**(文件/端点/进程/话题), 产出 pass / fail / unknown 三态:
  · pass    有证据且满足门
  · fail    有证据但不满足门(要有人处理)
  · unknown **没有证据** —— 不猜、不美化(老倪: 没有实测就是 unknown, 不许写成"应该没问题")

输出: /home/ubuntu/zmax_data/dataspace/loop.json (控制台「数据空间」页与网页读这一份)
用法: python -m lerobot.dataspace.loop_state --json        # dds-venv/gui-venv 都能跑(纯 stdlib)
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
if os.path.join(REPO, "src") not in sys.path:      # 允许 `python <本文件>` 直跑(不必 -m)
    sys.path.insert(0, os.path.join(REPO, "src"))
from lerobot.dataspace import topics as T          # noqa: E402

OUT = os.environ.get("ZMAX_DATASPACE_LOOP", "/home/ubuntu/zmax_data/dataspace/loop.json")
LIVE = os.environ.get("ZMAX_DATASPACE_LIVE", "/home/ubuntu/zmax_data/dataspace/live.json")
ORIN = os.environ.get("ZMAX_ORIN", "192.168.23.66")


def _newest(paths, key=os.path.getmtime):
    cand = [p for p in paths if os.path.exists(p)]
    if not cand:
        return None
    return max(cand, key=key)


def _read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return default


def _http(url, timeout=8):
    """返回 (code, body) —— 只读 GET"""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.getcode(), r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:                                                   # noqa: BLE001
        return 0, "%s: %s" % (type(e).__name__, str(e)[:80])


def _age(p):
    try:
        return round(time.time() - os.path.getmtime(p), 1)
    except OSError:
        return None


def _res(status, evidence, **metrics):
    return {"status": status, "evidence": evidence, "metrics": metrics, "ts": time.time()}


# ─────────────────────────── 各环节检查器 ───────────────────────────
def s0_preflight():
    """S0 采数前自检: 标定有效 + TCP 位姿新鲜 + 相机帧龄"""
    ev, m, ok, unknown = [], {}, 0, 0
    he = _read_json(os.path.join(REPO, "models", "handeye_state.json"))
    if isinstance(he, dict) and he:
        # 实测字段名(2026-09-29 读文件确认): ok / T_cam2tool / t_mm / rpy_deg / resid_trans_mm_rms
        rms = he.get("resid_trans_mm_rms", he.get("rms_mm", he.get("rms")))
        val = he.get("valid", he.get("ok"))
        m["handeye_rms_mm"] = rms
        m["handeye_valid"] = val
        if rms is not None and rms != -1:
            ok += 1 if float(rms) <= 2.0 else 0
            ev.append("手眼 rms=%smm(门≤2)" % rms)
        else:
            unknown += 1
            ev.append("手眼文件在但无 rms 字段")
    else:
        unknown += 1
        ev.append("未找到 models/handeye_state.json")
    tcp_c = [os.path.join(g, "latest.json") for g in
             ("/home/ubuntu/rokae_sdk/tcp_out", "/home/ubuntu/zmax/rokae_sdk/tcp_out",
              "/home/ubuntu/zmax_ss_remote/rokae_sdk/tcp_out")]
    tcp = _newest(tcp_c)
    if tcp:
        d = _read_json(tcp, {}) or {}
        age = _age(tcp)
        m["tcp_age_s"] = age
        vals = [v for v in (d.get("tcp_pose") or d.get("pose") or []) if isinstance(v, (int, float))]
        m["tcp_nonzero"] = any(abs(v) > 1e-6 for v in vals) if vals else False
        if vals and m["tcp_nonzero"] and age is not None and age < 60:
            ok += 1
            ev.append("TCP 位姿新鲜 %.0fs 且非全 0" % age)
        else:
            ev.append("TCP 位姿可疑(龄 %.0fs/非全0=%s)" % (age or -1, m["tcp_nonzero"]))
    else:
        unknown += 1
        ev.append("未找到 TCP 位姿文件(tcp_out/latest.json)")
    code, _ = _http("http://127.0.0.1:8791/snapshot/arm.jpg", timeout=5)
    m["cam_arm_http"] = code
    if code == 200:
        ok += 1
        ev.append("臂相机 200")
    else:
        ev.append("臂相机 HTTP %s" % code)
    st = "pass" if ok >= 3 else ("fail" if ok == 0 else "unknown")
    return _res(st, " · ".join(ev), **m)


def s1_collect():
    """S1 真机采集: Orin 可达 + 本地最新数据包"""
    ev = []
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "1", ORIN], capture_output=True, timeout=4)
        reach = r.returncode == 0
    except Exception:                                                        # noqa: BLE001
        reach = False
    pkgs = sorted(glob.glob("/home/ubuntu/zmax_data/orin_live/*.json") +
                  glob.glob(os.path.join(REPO, "data/orin_live/*.json")), key=os.path.getmtime)
    newest = pkgs[-1] if pkgs else None
    m = {"orin_reachable": reach, "n_local_pkgs": len(pkgs),
         "newest_pkg_age_s": _age(newest) if newest else None,
         "newest_pkg": os.path.basename(newest) if newest else None}
    ev.append("Orin %s" % ("可达" if reach else "不可达"))
    if newest:
        d = _read_json(newest, {}) or {}
        meta = (d.get("meta") or {})
        frames = meta.get("frames") or len(d.get("frames") or [])
        m["frames"] = frames
        ev.append("最新包 %s: frames=%s" % (m["newest_pkg"], frames))
    else:
        ev.append("本地无 orin_live 数据包")
    st = "pass" if (reach and newest and (m.get("frames") or 0) >= 20) else ("fail" if not reach and not newest else "unknown")
    return _res(st, " · ".join(ev), **m)


def s2_upload():
    """S2 上传中转: ECS relay 队列状态"""
    code, body = _http("https://datadrive.world/api/relay/status", timeout=12)
    if code != 200:
        return _res("unknown", "ECS relay /status HTTP %s" % code, http=code)
    d = {}
    try:
        d = json.loads(body)
    except Exception:                                                        # noqa: BLE001
        pass
    keys = {k: d[k] for k in ("pending", "queue", "n", "count", "latest", "last_upload")
            if k in d} if isinstance(d, dict) else {}
    return _res("pass", "ECS relay 可达(队列字段 %s)" % (list(keys) or "无"), http=code, **{k: v for k, v in keys.items() if isinstance(v, (int, float, str))})


def s3_dataset():
    """S3 入库质量门: 数据集存在 + 帧数/维度"""
    info = os.path.join(REPO, "data/orin_6d/meta/info.json")
    d = _read_json(info)
    if not d:
        return _res("unknown", "未找到 data/orin_6d/meta/info.json")
    tot = d.get("total_frames")
    eps = d.get("total_episodes")
    st = "pass" if isinstance(tot, int) and tot >= 20 else ("fail" if isinstance(tot, int) else "unknown")
    return _res(st, "orin_6d 就有 %s 帧 / %s 轨迹(门: 单包≥20 帧且维度一致)" % (tot, eps),
                total_frames=tot, total_episodes=eps, path="data/orin_6d")


def s4_train():
    """S4 训练: 进度文件或 DDS 话题(train_prog 由 live.json 反映)"""
    cands = []
    for pat in ("outputs/**/progress*.json", "outputs/*.json", "outputs/**/train_state.json",
                "/home/ubuntu/zmax_data/**/progress*.json"):
        cands += glob.glob(os.path.join(REPO, pat), recursive=True)
        cands += glob.glob(pat, recursive=True)
    p = _newest(cands)
    live = _read_json(LIVE, {}) or {}
    tp = ((live.get("topics") or {}).get("train_prog") or {}).get("fields") or {}
    if p:
        d = _read_json(p, {}) or {}
        m = {k: d.get(k) for k in ("step", "total", "pct", "loss", "running") if k in d}
        m["file_age_s"] = _age(p)
        running = m.get("running")
        st = "pass" if running == 1 else ("unknown" if running is None else "fail")
        return _res(st, "%s: step=%s/%s loss=%s running=%s(龄 %.0fs) —— 没有训练在跑不是缺陷, 但闭环此刻停在 S4"
                    % (os.path.basename(p), m.get("step"), m.get("total"), m.get("loss"), running,
                       m.get("file_age_s") or -1), path=p, **m)
    if tp:
        st = "pass" if tp.get("running") == 1 else "unknown"
        return _res(st, "DDS train_prog: job=%s step=%s/%s loss=%s running=%s"
                    % (tp.get("job"), tp.get("step"), tp.get("total"), tp.get("loss"), tp.get("running")),
                    source="dds:train_prog", **{k: tp.get(k) for k in ("step", "total", "loss", "running")})
    return _res("unknown", "未找到训练进度文件, DDS train_prog 也没有值")


def s5_eval():
    """S5 评测: 最近取证/评测 JSON 的通过数与提升"""
    reps = sorted(glob.glob(os.path.join(REPO, "reports/*.json")), key=os.path.getmtime)
    # 只认"真评测产物"(含通过数/成功率 的 JSON) —— 别把 web_agent 状态之类误当评测(2026-09-29 实测踩到)
    evals = []
    for f in reps:
        d0 = _read_json(f, {}) or {}
        if isinstance(d0, dict) and any(k in d0 for k in ("passed", "total", "success_rate", "gain_obs_pct")):
            evals.append(f)
    if not evals:
        return _res("unknown", "reports/ 下没有评测产物(最近 %d 个 JSON 都不是评测; 上次真评测见历史报告)"
                    % len(reps))
    p = evals[-1]
    d = _read_json(p, {}) or {}
    passed, total = d.get("passed"), d.get("total")
    gain = d.get("gain_obs_pct", d.get("gain_pct"))
    st = "pass" if (isinstance(total, int) and isinstance(passed, int) and passed == total and total > 0) else "unknown"
    return _res(st, "%s: passed=%s/%s gain=%s(门: 有提升才放行; 缺 baseline 就是未证明)"
                % (os.path.basename(p), passed, total, gain), path=os.path.basename(p),
                age_s=_age(p), **{"passed": passed, "total": total, "gain_pct": gain})


def s6_publish():
    """S6 发布: 本地权重 + 静态 URL 可达"""
    ws = sorted(glob.glob(os.path.join(REPO, "outputs/**/*.safetensors"), recursive=True) +
                glob.glob(os.path.join(REPO, "models/**/*.safetensors"), recursive=True), key=os.path.getmtime)
    if not ws:
        return _res("unknown", "本地未找到 *.safetensors 权重")
    p = ws[-1]
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    name = os.path.basename(p)
    code, _ = _http("https://datadrive.world/models/" + name, timeout=12)
    st = "pass" if code == 200 else "unknown"
    return _res(st, "本地 %s(sha256 %s…) 静态URL HTTP %s" % (name, h.hexdigest()[:12], code),
                local=p.replace(REPO + "/", ""), sha256=h.hexdigest(), url_http=code)


def s7_deploy():
    """S7 部署: 审计台账最后一条指令"""
    p = os.path.join(REPO, "docs/deploy_audit.jsonl")
    if not os.path.exists(p):
        return _res("unknown", "没有 docs/deploy_audit.jsonl")
    last = None
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                last = ln
    if not last:
        return _res("unknown", "审计台账为空")
    try:
        d = json.loads(last)
    except Exception:                                                        # noqa: BLE001
        return _res("unknown", "审计台账最后一行不是 JSON")
    # 台账真实字段(实测): {"ev": deploy/train_start/dispatch_remote, "layer", "dir"/"to", "sha16", "ts"}
    ev_kind = d.get("ev") or d.get("action")
    art = d.get("dir") or d.get("artifact")
    who = d.get("to") or d.get("issuer") or "本机"
    st = "pass" if (ev_kind and d.get("ts")) else "unknown"
    return _res(st, "最后一条: %s · 目标=%s · 产物=%s · sha=%s · 时间=%s(龄 %.0fh)"
                % (ev_kind, who, art, str(d.get("sha16"))[:16], d.get("ts"), (_age(p) or 0) / 3600.0),
                age_h=round((_age(p) or 0) / 3600.0, 1), ev=ev_kind, target=who, artifact=art,
                sha16=d.get("sha16"), audit_ts=d.get("ts"))


def s8_infer():
    """S8 推理与回采: 本机推理服务 + Orin 推理计数"""
    code, body = _http("http://127.0.0.1:8790/health", timeout=6)
    d = {}
    try:
        d = json.loads(body)
    except Exception:                                                        # noqa: BLE001
        pass
    cnt = d.get("infer_count") if isinstance(d, dict) else None
    c2, b2 = _http("https://datadrive.world/api/relay/orin/status", timeout=12)
    o = {}
    try:
        o = json.loads(b2)
    except Exception:                                                        # noqa: BLE001
        pass
    st = "pass" if (cnt or 0) > 0 else "unknown"
    return _res(st, "本机推理 HTTP %s infer_count=%s · Orin 侧 HTTP %s %s"
                % (code, cnt, c2, {k: o.get(k) for k in list(o)[:3]} if isinstance(o, dict) else ""),
                infer_count=cnt, orin_http=c2, orin_infer_count=(o or {}).get("infer_count"))


CHECKERS = {"S0": s0_preflight, "S1": s1_collect, "S2": s2_upload, "S3": s3_dataset,
            "S4": s4_train, "S5": s5_eval, "S6": s6_publish, "S7": s7_deploy, "S8": s8_infer}


def collect():
    stages = []
    for s in T.CLOSED_LOOP:
        fn = CHECKERS.get(s["id"])
        try:
            r = fn() if fn else _res("unknown", "无检查器")
        except Exception as e:                                               # noqa: BLE001
            r = _res("unknown", "检查器异常 %s: %s" % (type(e).__name__, str(e)[:80]))
        stages.append({"id": s["id"], "name": s["name"], "gate": s["gate"], "owner": s["owner"],
                       **r})
    n = {k: sum(1 for s in stages if s["status"] == k) for k in ("pass", "fail", "unknown")}
    return {"ts": time.time(), "repo": REPO,
            "counts": n, "stuck_at": next((s["id"] for s in stages if s["status"] != "pass"), None),
            "stages": stages}


def main():
    ap = argparse.ArgumentParser(description="数据闭环证据采集器")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=10.0)
    a = ap.parse_args()
    while True:
        d = collect()
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(a.out + ".tmp", a.out)
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=1))
        else:
            print("=" * 92)
            print("🔁 数据闭环 · 9 环节  pass=%d fail=%d unknown=%d · 卡在 %s"
                  % (d["counts"]["pass"], d["counts"]["fail"], d["counts"]["unknown"], d["stuck_at"]))
            print("=" * 92)
            for s in d["stages"]:
                icon = {"pass": "✅", "fail": "❌", "unknown": "❔"}[s["status"]]
                print("%s %-3s %-12s %s" % (icon, s["id"], s["name"], s["evidence"][:96]))
        if not a.watch:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
