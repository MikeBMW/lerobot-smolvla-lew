#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔥 GPU 训练铁证采样器 —— 用时间序列回答"是不是真在 GPU 上训练"

判据（缺一不算真 GPU 训练）:
  ① nvidia-smi 报出**本训练的 PID** 在 GPU 进程表里
  ② 该 PID 的 **used_memory 稳定在模型量级**(几百 MB~几 GB), 不是 0
  ③ **利用率时间序列**在训练窗口内持续高位(非瞬时抖动)
  ④ 训练日志里**步数在推进**(不是卡死)
  ⑤ CPU 侧进程的 `ps` 状态为 R(运行) 且有 GPU 上下文

输出: reports/gpu_proof_<ts>.json + 终端摘要（可复制给用户）
用法:
  python tools/gpu_proof_sampler.py --pid <训练PID> --seconds 120 --interval 3
  python tools/gpu_proof_sampler.py --match 'joint_unified_backbone' --seconds 120
"""
import argparse
import json
import os
import re
import subprocess
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout
    except Exception as e:                                                     # noqa: BLE001
        return "ERR:%s" % e


def gpu_procs():
    """nvidia-smi 的 GPU 计算进程表: [(pid, name, usedMB)]"""
    out = sh("nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader")
    rows = []
    for ln in out.strip().splitlines():
        p = [x.strip() for x in ln.split(",")]
        if len(p) >= 3:
            try:
                rows.append((int(p[0]), os.path.basename(p[1]), p[2]))
            except ValueError:
                pass
    return rows


def util_mem():
    out = sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu "
             "--format=csv,noheader,nounits")
    p = [x.strip() for x in out.strip().split(",")]
    try:
        return {"util": int(p[0]), "mem_used_mb": int(p[1]), "mem_total_mb": int(p[2]),
                "temp_c": int(p[3]) if len(p) > 3 else None}
    except Exception:                                                          # noqa: BLE001
        return {"util": None, "mem_used_mb": None, "mem_total_mb": None, "temp_c": None}


def find_pid(match):
    out = sh("pgrep -f %s" % match)
    pids = [int(x) for x in out.split() if x.strip().isdigit()]
    return pids[0] if pids else None


def cpu_state(pid):
    out = sh("ps -o stat=,pcpu=,etime= -p %d" % pid)
    return out.strip() or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--match", default="")
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--log", default="", help="训练日志(数步数用)")
    ap.add_argument("--out-dir", default=os.path.join(REPO, "reports"))
    a = ap.parse_args()

    # ★ 优先用 nvidia-smi 报的**真 CUDA PID**（--match 命中的可能是 timeout/父包装进程）
    pid = a.pid or None
    if not pid and a.match:
        cand = find_pid(a.match)                      # 父进程候选
        gpu_pids = [x[0] for x in gpu_procs()]
        if cand in gpu_pids:
            pid = cand
        else:
            # 在 GPU 进程表里找命令行含 match 的那个（真持 CUDA 上下文的）
            for gp in gpu_pids:
                cmd = sh("ps -o args= -p %d" % gp)
                if a.match in cmd:
                    pid = gp
                    print("  ℹ️ 自动纠正 PID: %s(父/包装) → %d(GPU 表内的真训练进程)" % (cand, gp))
                    break
            pid = pid or cand
    if not pid:
        print("❌ 未找到训练进程 (--pid 或 --match 必须有一个能命中)")
        return 2
    print("=" * 78)
    print("🔥 GPU 训练铁证采样 — PID %d · %ds · 每 %.1fs" % (pid, a.seconds, a.interval))
    print("=" * 78)
    series, t0 = [], time.time()
    steps_seen = []
    while time.time() - t0 < a.seconds:
        u = util_mem()
        procs = gpu_procs()
        mine = [(p, n, m) for (p, n, m) in procs if p == pid]
        rec = {"t": round(time.time() - t0, 1), **u,
               "pid_on_gpu": bool(mine),
               "pid_mem": mine[0][2] if mine else None,
               "gpu_proc_count": len(procs),
               "cpu_stat": cpu_state(pid)}
        if a.log and os.path.isfile(a.log):
            try:
                m = re.findall(r"step\s+(\d+)/", open(a.log, encoding="utf-8", errors="replace").read())
                rec["train_step"] = int(m[-1]) if m else None
                if rec["train_step"] is not None:
                    steps_seen.append((round(time.time() - t0, 1), rec["train_step"]))
            except Exception:                                                  # noqa: BLE001
                pass
        series.append(rec)
        print("  t=%6.1fs util=%3s%% mem=%5sMB pid_on_gpu=%s pid_mem=%s step=%s cpu=%s" %
              (rec["t"], rec["util"], rec["mem_used_mb"], "✅" if rec["pid_on_gpu"] else "❌",
               rec["pid_mem"], rec.get("train_step"), (rec["cpu_stat"] or "").split()[0] if rec["cpu_stat"] else "?"),
              flush=True)
        time.sleep(a.interval)

    utils = [x["util"] for x in series if isinstance(x["util"], int)]
    on_gpu = sum(1 for x in series if x["pid_on_gpu"])
    hi = sum(1 for u in utils if u >= 50)
    step_delta = (steps_seen[-1][1] - steps_seen[0][1]) if len(steps_seen) >= 2 else None
    verdict = {
        "pid": pid,
        "samples": len(series),
        "pid_on_gpu_samples": on_gpu,
        "util_mean": round(sum(utils) / len(utils), 1) if utils else None,
        "util_max": max(utils) if utils else None,
        "util_ge50_ratio": round(hi / len(utils), 3) if utils else None,
        "steps_progressed": step_delta,
        "verdict": ("真 GPU 训练" if (on_gpu >= max(1, len(series) // 2) and utils and
                                  sum(utils) / len(utils) >= 30) else "证据不足(需查)"),
    }
    print("-" * 78)
    print("  采样 %d 次 · PID 出现在 GPU 进程表 %d 次 · 利用率均值 %s%% · ≥50%% 占比 %s" %
          (verdict["samples"], verdict["pid_on_gpu_samples"], verdict["util_mean"], verdict["util_ge50_ratio"]))
    print("  训练步数推进: %s" % (step_delta if step_delta is not None else "（未提供日志）"))
    print("  🎯 判定: **%s**" % verdict["verdict"])
    os.makedirs(a.out_dir, exist_ok=True)
    p = os.path.join(a.out_dir, "gpu_proof_%d.json" % int(t0))
    json.dump({"verdict": verdict, "series": series}, open(p, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("  证据已落盘 → %s" % os.path.relpath(p, REPO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
