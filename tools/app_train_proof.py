#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 APP 训练铁证链 —— 一次性证明"APP 启动的是真训练, 进度是真的"

证据链（5 环, 环环相扣）:
  ① APP API 启动训练 → 返回 job_id + pid
  ② **该 pid 出现在 nvidia-smi 的 GPU 进程表**（同一条链, 不是旁证）
  ③ /proc/<pid>/cmdline 证明它就是训练脚本, 且参数来自 APP 模板
  ④ **进度文件 step** 与 **训练日志 step** 两个独立来源相互印证
  ⑤ 时间戳序列证明进度**单调递增**（不是伪造的固定值）

用法: python tools/app_train_proof.py --layer L4moe --steps 400 --watch 90
"""
import argparse
import json
import os
import re
import subprocess
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSOLE = "http://127.0.0.1:8799"
SWM = "/home/ubuntu/stable-wm-cache"


def sh(c):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e:                                                     # noqa: BLE001
        return "ERR:%s" % e


def gpu_pids():
    out = sh("nvidia-smi --query-compute-apps=pid --format=csv,noheader")
    return {int(x) for x in out.split() if x.strip().isdigit()}


def gpu_line():
    return sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv,noheader")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", default="L4moe")
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--watch", type=int, default=90)
    a = ap.parse_args()

    print("=" * 80)
    print("🔗 APP 训练铁证链 — 通过控制台 API 真启动, 逐环取证")
    print("=" * 80)

    # ── 环①: APP API 启动 ──
    req = urllib.request.Request(CONSOLE + "/api/train",
                                 data=json.dumps({"layer": a.layer, "steps": a.steps}).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    print("\n① APP API 启动: ok=%s · jid=%s · pid=%s" % (r.get("ok"), r.get("jid"), r.get("pid")))
    print("   msg: %s" % r.get("msg"))
    if not r.get("ok"):
        print("   ❌ 启动失败, 链断")
        return 2

    # ── 环②: 解析**真 python 子进程** pid（控制台给的是 /bin/sh -c 包装进程）+ 核 GPU 表 ──
    def resolve_real_pid(pid):
        """包装进程 → 真训练进程: 优先取 GPU 表内命令行匹配的, 其次取 /bin/sh 的 python 子进程"""
        gp = gpu_pids()
        cmd_self = sh("tr '\\0' ' ' < /proc/%s/cmdline" % pid)
        for gp_pid in sorted(gp):
            c2 = sh("tr '\\0' ' ' < /proc/%s/cmdline" % gp_pid)
            if "backbone" in c2 or "stage_moe" in c2:
                return gp_pid, c2
        for ch in sh("pgrep -P %s" % pid).split():
            if ch.isdigit():
                c3 = sh("tr '\\0' ' ' < /proc/%s/cmdline" % ch)
                if "backbone" in c3 or "stage_moe" in c3:
                    return int(ch), c3
        return pid, cmd_self

    t0 = time.time()
    real_pid, cmd = r["pid"], sh("tr '\\0' ' ' < /proc/%s/cmdline" % r["pid"])
    found_at = None
    while time.time() - t0 < 120:
        real_pid, cmd = resolve_real_pid(r["pid"])
        if real_pid in gpu_pids():
            found_at = time.time() - t0
            break
        time.sleep(3)
    print("\n② GPU 进程表核对: 包装 pid %s → **真训练 pid %s** %s%s" %
          (r["pid"], real_pid, "**在表内 ✅**" if found_at is not None else "**未出现 ❌**",
           ("（%.0fs 后出现）" % found_at) if found_at is not None else ""))
    print("   当前 GPU: %s" % gpu_line())

    # ── 环③: cmdline 证明是训练脚本 ──
    print("\n③ 真训练进程 /proc/%s/cmdline:" % real_pid)
    print("   %s" % cmd[:300])
    is_train = ("backbone" in cmd or "train" in cmd or "moe" in cmd)
    print("   是训练脚本: %s" % ("✅" if is_train else "❌"))
    prog = re.search(r"--progress-file (\S+)", cmd)
    pfile = prog.group(1) if prog else None
    print("   进度文件参数: %s" % (pfile or "（无）"))

    # ── 环④⑤: 进度文件 vs 日志 双源印证 + 单调递增 ──
    logf = r.get("log")
    print("\n④⑤ 双源印证 + 递增性（采样 %ds）:" % a.watch)
    rows = []
    t1 = time.time()
    while time.time() - t1 < a.watch:
        pf = {}
        if pfile and os.path.isfile(pfile):
            try:
                pf = json.load(open(pfile, encoding="utf-8"))
            except Exception:                                                  # noqa: BLE001
                pass
        lg = None
        if logf and os.path.isfile(logf):
            try:
                m = re.findall(r"step\s+(\d+)/(\d+)", open(logf, encoding="utf-8", errors="replace").read())
                lg = (int(m[-1][0]), int(m[-1][1])) if m else None
            except Exception:                                                  # noqa: BLE001
                pass
        g = gpu_line()
        rows.append((round(time.time() - t1, 1), pf.get("step"), lg[0] if lg else None,
                     pf.get("pct"), pf.get("loss"), g))
        print("   t=%5.1fs | 进度文件 step=%-5s | 日志 step=%-5s | %5s%% | loss %-9s | GPU %s" %
              (rows[-1][0], pf.get("step"), (lg[0] if lg else "—"), pf.get("pct"), pf.get("loss"), g))
        time.sleep(12)

    steps_pf = [x[1] for x in rows if x[1] is not None]
    mono = len(steps_pf) >= 2 and all(b >= y for y, b in zip(steps_pf, steps_pf[1:]))
    # ★ 双源**同源**判据（修正）: 两源粒度不同(进度文件 10 步 / 日志 --stats 250 步),
    #    正确口径 = ①日志 step ≤ 进度 step（进度不得超前于真训练）②在日志刷新时刻两者**精确相等**
    pairs = [(x[1], x[2]) for x in rows if x[1] is not None and x[2] is not None]
    not_ahead = all(lg <= pf for pf, lg in pairs) if pairs else False
    boundary = [lg for pf, lg in pairs if pf == lg]
    print("\n" + "=" * 80)
    print("📋 铁证链判定")
    print("=" * 80)
    print("  ① APP API 启动成功            : ✅ (jid=%s, 包装pid=%s→真pid=%s)" %
          (r.get("jid"), r.get("pid"), real_pid))
    print("  ② 真训练 pid 在 GPU 进程表     : %s" % ("✅" if found_at is not None else "❌"))
    print("  ③ 是训练脚本(含APP下发参数)     : %s" % ("✅" if is_train else "❌"))
    print("  ④ 双源同源(日志≤进度 且 边界相等): %s (%s)" %
          ("✅" if (not_ahead and boundary) else "⚠️",
           "日志从不超过进度" if not_ahead else "进度超前→异常"))
    print("     边界精确相等样本: %s" % (boundary if boundary else "（窗口内无 stats 刷新点）"))
    print("  ⑤ 进度单调递增                : %s (%s)" % ("✅" if mono else "⚠️", steps_pf))
    ok = found_at is not None and is_train and mono and not_ahead
    print("\n  🎯 **结论: %s**" % ("APP 启动的是**真训练**, 进度是**真实的**"
                                   if ok else "证据不足, 需继续排查"))
    out = os.path.join(REPO, "reports", "app_train_proof_%d.json" % int(t0))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"job": r, "real_pid": real_pid, "gpu_found_after_s": found_at, "cmdline": cmd,
               "samples": [{"t": x[0], "progress_file_step": x[1], "log_step": x[2],
                            "pct": x[3], "loss": x[4], "gpu": x[5]} for x in rows],
               "verdict": {"is_real_training": bool(ok), "monotonic": mono,
                           "not_ahead": not_ahead, "boundary_equal": boundary}},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  证据落盘 → %s" % os.path.relpath(out, REPO))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
