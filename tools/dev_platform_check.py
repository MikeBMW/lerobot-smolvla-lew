#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dev_platform_check.py — 状态空间工程开发控制平台 · 全景体检 (只读, 为 L5 审视提供真实输入)

五段体检 (全部真实命令/文件, 拿不到就写 None 不编):
  ① 控制台 (开发平台本体): 进程/版本/画布规模/页面/定时器/在役窗口
  ② 数据 pipeline (采集→中转→落盘→训练→部署): 逐段取证
  ③ 资源: GPU/磁盘/内存/服务/cron
  ④ 功能面: 画布节点分层统计 + 注册执行率 (档位级审计摘要)
  ⑤ 验证器清单与最近结果 (工程完整落地程度)
输出: 控制台摘要 + JSON 落盘 reports/dev_platform_check_<ts>.json
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time

ROOT = "/home/ubuntu/zmax_rel"
REPORTS = os.path.join(ROOT, "reports")
SWM = "/home/ubuntu/stable-wm-cache"


def sh(cmd, timeout=12):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:                                                        # noqa: BLE001
        return ""


def jload(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        return None


out = {"ts": time.strftime("%F %T %Z")}

# ── ① 控制台 ──
console = {}
pid = sh("pgrep -f 'gui-venv311/bin/python studio.py' | head -1")
console["running"] = bool(pid)
if pid:
    console["pid"] = int(pid)
    console["cwd"] = os.path.realpath("/proc/%s/cwd" % pid) if os.path.exists("/proc/%s/cwd" % pid) else ""
    console["cpu_pct"] = sh("ps -o %%cpu= -p %s" % pid)
    console["rss_mb"] = sh("ps -o rss= -p %s" % pid)
st = os.path.join(ROOT, "tools/gui/studio.py")
src = open(st, encoding="utf-8", errors="ignore").read() if os.path.isfile(st) else ""
console["version"] = (re.search(r'Z-MAX v(\d+\.\d+\.\d+)', src).group(1) if re.search(r'Z-MAX v(\d+\.\d+\.\d+)', src) else "")
console["studio_kb"] = round(len(src) / 1024)
console["modules"] = {m: len(re.findall(r"class \w*%s\w*" % m, src)) for m in ("Widget", "Dialog", "Window")}
console["pages"] = sorted(set(re.findall(r'view_targets\s*=|\(\"([^"]{2,10})\",\s*\"(?:home|dataset|training|evaluation|hardware|config|monitor|plugging|version)\"\)', src)))
cv = jload(os.path.join(ROOT, "flows/state_space_obs.json"))
if cv:
    rows = {}
    for n in cv["nodes"]:
        p = n.get("params") or {}
        if p.get("bg") or p.get("row_bg"):
            rows[int(n.get("y", 0))] = n.get("name", "")
    console["canvas"] = {"nodes": len(cv["nodes"]), "links": len(cv["links"]),
                         "rows": len(rows), "real_nodes": sum(1 for n in cv["nodes"]
                                                              if not ((n.get("params") or {}).get("bg") or (n.get("params") or {}).get("row_bg")))}
out["console"] = console

# ── ② 数据 pipeline 五段 ──
pipe = {}
tap = sorted(glob.glob("/home/ubuntu/zmax_ss_remote/state_*.jsonl"), key=os.path.getmtime)
if tap:
    p = tap[-1]
    pipe["collect_orin_tap"] = {"file": os.path.basename(p), "mb": round(os.path.getsize(p) / 1e6, 1),
                                "age_s": round(time.time() - os.path.getmtime(p), 1)}
relay = sh("curl -s -m 8 https://datadrive.world/api/relay/status")
pipe["relay_ecs"] = (json.loads(relay) if relay.startswith("{") else {"raw": relay[:120]})
pipe["relay_latest"] = sh("curl -s -m 8 https://datadrive.world/api/relay/latest")[:160]
dsets = sorted(glob.glob(os.path.join(SWM, "datasets", "*.h5")), key=os.path.getmtime, reverse=True)[:5]
pipe["datasets"] = [{"f": os.path.basename(d), "gb": round(os.path.getsize(d) / 1e9, 2),
                     "age_h": round((time.time() - os.path.getmtime(d)) / 3600, 1)} for d in dsets]
pipe["training_running"] = sh("pgrep -af 'lerobot_train|train\\.py' | grep -v grep | head -2")
pipe["gpu"] = sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader")
ck = sorted(glob.glob(os.path.join(SWM, "checkpoints", "**", "*.pt"), recursive=True), key=os.path.getmtime, reverse=True)[:5]
pipe["checkpoints"] = [{"f": os.path.relpath(c, os.path.join(SWM, "checkpoints")),
                        "age_h": round((time.time() - os.path.getmtime(c)) / 3600, 1)} for c in ck]
pipe["deploy_links"] = {l: os.path.basename(os.path.realpath(l)) for l in
                        glob.glob(os.path.join(ROOT, "models", "*.pt")) if os.path.islink(l)}
out["pipeline"] = pipe

# ── ③ 资源 ──
out["resources"] = {
    "disk": sh("df -h / | tail -1"),
    "mem": sh("free -g | sed -n 2p"),
    "services": {s: sh("systemctl is-active %s" % s).strip() for s in
                 ("ss-local-infer", "ss-bypass", "ss-remote-tap", "ss-yolo-bypass",
                  "zmax-dds-ss", "zmax-dds-pub", "zmax-dds-agg", "aoi-feishu-push",
                  "zmax-web-agent-bridge", "zmax-net-optimize")},
    "cron_count": len(json.load(open(os.path.expanduser("~/.hermes/cron/jobs.json"), encoding="utf-8")).get("jobs", {})),
    "infer_health": sh("curl -s -m 5 http://127.0.0.1:8790/health")[:200],
}

# ── ④ 功能面 (画布分层 + 审计) ──
audit = ""
for cand in sorted(glob.glob(os.path.join(REPORTS, "canvas_level_audit*")), reverse=True)[:1]:
    audit = cand
out["functions"] = {"last_level_audit": os.path.basename(audit) if audit else "",
                    "audit_tail": sh("python3 %s 2>/dev/null | tail -6" % audit.replace(".json", ".py")) if audit.endswith(".py") else ""}

# ── ⑤ 验证器与最近结果 ──
verifiers = sorted(os.path.basename(v) for v in glob.glob(os.path.join(ROOT, "tools/verify_*.py")))
res_recent = sorted(glob.glob(os.path.join(REPORTS, "*verify*.log")), key=os.path.getmtime, reverse=True)[:6]
out["verification"] = {"verifiers": verifiers, "n_verifiers": len(verifiers),
                       "recent_evidence": [os.path.basename(x) for x in res_recent]}

os.makedirs(REPORTS, exist_ok=True)
dst = os.path.join(REPORTS, "dev_platform_check_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ── 打印 ──
print("═" * 78)
print("状态空间工程 · 开发控制平台体检  %s" % out["ts"])
print("═" * 78)
print("① 控制台: 运行=%s pid=%s cwd=%s | v%s | studio %dKB | 画布 %s" %
      (console["running"], console.get("pid"), console.get("cwd", "").replace("/tools/gui", ""),
       console["version"], console["studio_kb"], console.get("canvas")))
print("② 数据 pipeline:")
for k, v in pipe.items():
    print("   %-18s %s" % (k, json.dumps(v, ensure_ascii=False)[:150]))
print("③ 资源: %s | %s" % (out["resources"]["disk"], out["resources"]["mem"]))
print("   服务: %s" % json.dumps(out["resources"]["services"], ensure_ascii=False))
print("   推理: %s" % out["resources"]["infer_health"][:120])
print("④ 功能面: 验证器 %d 个 | 最近取证 %s" % (out["verification"]["n_verifiers"], out["verification"]["recent_evidence"][:3]))
print("⑤ 取证 JSON: %s" % dst)
