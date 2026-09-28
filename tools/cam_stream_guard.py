#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🛰 工位总览推流守护 —— ①没跑就拉起 ②跑着但**相机映射错了**就按解析结果重启 ③正常静默

为什么需要 (2026-09-28 现场): 控制台按钮拉流时设备号写死过 `--local-dev 2 --local2-dev 0` ⇒
  · /dev/video2 = 笔记本相机的 GREY(IR) 那一路 → 那一格近全黑(实测 mean=3.7 / 95.8% 像素近黑);
  · /dev/video0 = 笔记本**彩色**那一路, 却被当成 MAXHUB → 两格串线(实测两格 label 都是 Integrated RGB Camera)。
老倪原话:「笔记本内置摄像头太黑了, 而且 MAXHUB 的摄像头显示的不对, 跟笔记本摄像头串线了」。
   代码侧已改(控制台两个按钮 + tools/start_station_stream.sh 都走 tools/cam_dev_resolve.py 实测解析);
   本守护是**兜底**: 不管谁用错参数拉起的流, 5 分钟内都会被按实测判据纠正。

判据(全部可核, 不猜):
  A. 8791 不可达                              → 用 tools/start_station_stream.sh 拉起
  B. 进程 cmdline 的 --local-dev/--local2-dev ≠ 解析结果 → 映射错, 重启纠正  (抓"选了 IR 路/串线"这一类)
  C. /stats 里 local 的 label 不含 "Integrated RGB" 或 local2 的 label 不含 "MAXHUB" → 同上
正常时 **一个字都不打**(老倪 2026-09-27: 没请求不要刷屏); 只有动作/失败才输出。

用法:
  python3 tools/cam_stream_guard.py                          # 真守护 (cron 每 5 分钟)
  python3 tools/cam_stream_guard.py --cmdline "a b --local-dev 2 --local2-dev 0" --expect 0,4 --stats-json f
                                                             # 自测: 用给定输入只判不动手
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("ZMAX_STREAM_PORT", "8791"))
RGB_KEY = "Integrated RGB"          # 笔记本彩色相机的卡名关键字
TOP_KEY = "MAXHUB"                  # 顶视相机


def resolve_devs():
    """按卡名+能力解析本机两路相机 (与 tools/start_station_stream.sh / 控制台按钮同一个真源)"""
    try:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "cam_dev_resolve.py")],
                           capture_output=True, text=True, timeout=25)
    except Exception:                                                            # noqa: BLE001
        return None
    lo, l2 = None, None
    for ln in (r.stdout or "").splitlines():
        k, _, v = ln.partition("=")
        v = v.strip()
        if v.lstrip("-").isdigit():
            if k == "LOCAL":
                lo = int(v)
            elif k == "LOCAL2":
                l2 = int(v)
    return (lo, l2) if lo is not None else None


def proc_cmdline():
    """跑着的 cam_live_stream 进程自己声明的设备号 (读 /proc, 不靠 pkill/grep 名字)"""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        argv = [a.decode("utf-8", "ignore") for a in argv if a]
        if not any("cam_live_stream.py" in a for a in argv):
            continue
        out = {}
        for i, a in enumerate(argv):
            if a in ("--local-dev", "--local2-dev") and i + 1 < len(argv):
                out[a.lstrip("-")] = int(argv[i + 1]) if argv[i + 1].lstrip("-").isdigit() else None
        if out:
            return out
    return None


def stats(timeout=6):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/stats" % PORT, timeout=timeout) as r:
            return json.load(r)
    except Exception:                                                            # noqa: BLE001
        return None


def judge(cmd_devs, expect, st):
    """→ (ok, reason) 纯函数, 可用给定输入自测"""
    if cmd_devs is None and st is None:
        return False, "8791 不可达且没有推流进程(推流没跑)"
    if expect:
        lo_e, l2_e = expect
        if cmd_devs is None:
            return False, "进程不在(推流没跑)"
        if cmd_devs.get("local-dev") != lo_e or cmd_devs.get("local2-dev") != l2_e:
            return False, ("进程用的是 local-dev=%s local2-dev=%s, 实测解析应为 local=%s local2=%s"
                           % (cmd_devs.get("local-dev"), cmd_devs.get("local2-dev"), lo_e, l2_e))
    if st:
        lo = (st.get("local") or {}).get("label", "")
        l2 = (st.get("local2") or {}).get("label", "")
        if lo and RGB_KEY.lower() not in lo.lower():
            return False, "local 那一格不是笔记本彩色相机(实测 label=%r)" % lo
        if l2 and TOP_KEY.lower() not in l2.lower():
            return False, "local2 那一格不是 MAXHUB(实测 label=%r) — 串线" % l2
    return True, "ok"


def restart(reason):
    s = os.path.join(ROOT, "tools", "start_station_stream.sh")
    r = subprocess.run(["bash", s], capture_output=True, text=True, timeout=180)
    tail = "\n".join((r.stdout or "").strip().splitlines()[-4:])
    print("🛰 工位推流守护: %s → 已按解析结果重启\n%s" % (reason, tail))
    ok, why = judge(proc_cmdline(), resolve_devs(), stats())
    print("   复核: %s (%s)" % ("✅ 映射正确" if ok else "❌ 仍不对", why))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmdline", default="", help="自测: 假装的进程命令行")
    ap.add_argument("--expect", default="", help="自测: 'local,local2'")
    ap.add_argument("--stats-json", default="", help="自测: /stats 快照文件")
    ap.add_argument("--dry-run", action="store_true", help="只判不动手")
    a = ap.parse_args()

    if a.cmdline or a.stats_json or a.expect:
        cd = {}
        for i, tok in enumerate(a.cmdline.split()):
            if tok in ("--local-dev", "--local2-dev"):
                cd[tok.lstrip("-")] = int(a.cmdline.split()[i + 1])
        exp = tuple(int(x) for x in a.expect.split(",")) if a.expect else None
        stj = json.load(open(a.stats_json, encoding="utf-8")) if a.stats_json else None
        ok, why = judge(cd or None, exp, stj)
        print("判定: %s — %s" % ("✅ 映射正确(不需要动手)" if ok else "❌ 需要纠正", why))
        return 0 if ok else 3

    cd, exp, st = proc_cmdline(), resolve_devs(), stats()
    ok, why = judge(cd, exp, st)
    if ok:
        return 0                                                 # 正常: 静默
    if a.dry_run:
        print("🛰 工位推流守护(dry-run): %s — 需要重启纠正" % why)
        return 3
    return restart(why)


if __name__ == "__main__":
    sys.exit(main())
