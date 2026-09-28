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
  D. 🌈 深度源: 容器 ss-remote-tap 里的 ros_depth_stream.py 不在, 或宿主读到的 depth_raw.npy 龄 >20s
     → 深度格会一直显示**旧图**(2026-09-28 实测冻了 26.6h / frames_served=1, 慢层拼图一直拿它扣分)
     ⇒ 按脚本官方用法在容器内拉起 `python3 /repo/tools/ros_depth_stream.py --hz 5`
  E. 🦾 TCP 真值: 容器 rokae_tcp_sampler 的 SDK 直采 latest.json 龄 >10s (或读不到)
     → 叠加里**所有 3D 框都会集体消失**(只剩大模型的 2D 框), 老倪会当成"框丢了"
     → 重启该采样容器; 宿主读法见 scene_overlay.read_tcp (SDK 文件优先, 死掉的 tcp_pose.json 只作回退)
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
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("ZMAX_STREAM_PORT", "8791"))
RGB_KEY = "Integrated RGB"          # 笔记本彩色相机的卡名关键字
TOP_KEY = "MAXHUB"                  # 顶视相机
# 🌈 深度源: 由**容器内常驻**的 ros_depth_stream.py 落盘 (宿主只读它的 npy)
DEPTH_NPY = "/home/ubuntu/zmax_ss_remote/zmax_scene/depth_raw.npy"
DEPTH_DEAD_S = float(os.environ.get("ZMAX_DEPTH_DEAD_S", "20"))
DEPTH_CONTAINER = os.environ.get("ZMAX_TAP_CONTAINER", "ss-remote-tap")
# 🦾 TCP 真值源: 容器 rokae_tcp_sampler 里 tcp_direct_sampler.py 5Hz 写 latest.json (珞石 SDK 直采,
#   口径 endInRef = 与产线 /robot/tcp_pose 同口径)。宿主挂载见下。
TCP_LATEST = "/home/ubuntu/zmax_data/rokae_sdk/tcp_out/latest.json"
TCP_DEAD_S = float(os.environ.get("ZMAX_TCP_DEAD_S", "10"))
TCP_CONTAINER = os.environ.get("ZMAX_TCP_CONTAINER", "rokae_tcp_sampler")


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


def depth_age():
    """深度源文件龄(s); 读不到返回 None"""
    try:
        return time.time() - os.path.getmtime(DEPTH_NPY)
    except OSError:
        return None


def depth_proc():
    """容器里 ros_depth_stream.py 还在不在 → True/False/None(查不了)"""
    try:
        r = subprocess.run(["sudo", "-n", "docker", "exec", DEPTH_CONTAINER, "bash", "-lc",
                            "ps -eo cmd 2>/dev/null | grep -c '[r]os_depth_stream.py'"],
                           capture_output=True, text=True, timeout=20)
    except Exception:                                                            # noqa: BLE001
        return None
    # 注意: grep -c 命中 0 条时退出码是 1(不是错误) ⇒ 只看 stdout, 别被 returncode 误导
    try:
        return int((r.stdout or "").strip().splitlines()[-1]) > 0
    except Exception:                                                            # noqa: BLE001
        return None


def start_depth():
    """按脚本官方用法把常驻深度流拉进容器(分离运行)"""
    try:
        r = subprocess.run(["sudo", "-n", "docker", "exec", "-d", DEPTH_CONTAINER, "bash", "-lc",
                            "source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=0 && "
                            "python3 /repo/tools/ros_depth_stream.py --hz 5 >> /tmp/depth_stream.log 2>&1"],
                           capture_output=True, text=True, timeout=40)
        return r.returncode == 0
    except Exception:                                                            # noqa: BLE001
        return False


def tcp_stale():
    """TCP 真值文件龄 → (是否失效, 说明)。读不到也判失效(3D 框会集体消失)。"""
    try:
        d = json.load(open(TCP_LATEST, encoding="utf-8"))
        age = time.time() - float(d.get("ts", 0))
        return (age > TCP_DEAD_S), "SDK 直采 latest.json 龄 %.1fs (阈 %.0fs, 值=(%.4f,%.4f,%.4f))" % (
            age, TCP_DEAD_S, d.get("x", 0), d.get("y", 0), d.get("z", 0))
    except Exception as e:                                                        # noqa: BLE001
        return True, "读不到 TCP 真值 %s: %s" % (TCP_LATEST, str(e)[:80])


def start_tcp_sampler():
    """重启 SDK 直采容器 (只读采样, 不发动作) —— 它自带 Restart=unless-stopped, 这是最后一道"""
    try:
        r = subprocess.run(["sudo", "-n", "docker", "restart", TCP_CONTAINER],
                           capture_output=True, text=True, timeout=40)
        return r.returncode == 0
    except Exception:                                                             # noqa: BLE001
        return False


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

    # 🌈 深度格自愈 (2026-09-28 现场): 深度源 = **容器内常驻** ros_depth_stream.py 落的 npy。
    #    重启/容器重建后没人拉它 ⇒ 宿主只读到 09-27 的旧图: 深度格冻结 26.6h(frames_served=1),
    #    慢层拼图里那份深度一直是旧的, 一直在给"画面异常"扣分。这里连"文件龄"和"容器进程"一起兜。
    d_age, d_proc = depth_age(), depth_proc()
    d_bad = (d_proc is False) or (d_age is None) or (d_age > DEPTH_DEAD_S)
    if d_bad:
        if a.dry_run:
            print("🌈 深度源守护(dry-run): 容器进程=%s · 源文件龄=%s → 需要拉起"
                  % (d_proc, ("%.0fs" % d_age) if d_age is not None else "读不到"))
            return 3
        if start_depth():
            time.sleep(8)
            d2 = depth_age()
            print("🌈 深度源守护: 容器内 ros_depth_stream 不在(进程=%s) 或源文件龄过大(%s) → 已按官方用法拉起"
                  "\n   复核: 源文件龄 %s%s"
                  % (d_proc, ("%.0fs" % d_age) if d_age is not None else "读不到",
                     ("%.1fs" % d2) if d2 is not None else "读不到",
                     " ✅" if (d2 is not None and d2 <= DEPTH_DEAD_S) else " ❌ 仍不新鲜, 需看容器日志 /tmp/depth_stream.log"))
            return 0 if (d2 is not None and d2 <= DEPTH_DEAD_S) else 1
        print("🌈 深度源守护: 拉起失败(sudo -n docker exec 返回非 0) — 需人工看容器 %s" % DEPTH_CONTAINER)
        return 1

    t_bad, t_note = tcp_stale()
    if t_bad:
        if a.dry_run:
            print("🦾 TCP 真值守护(dry-run): %s → 需要拉起容器 %s" % (t_note, TCP_CONTAINER))
            return 3
        if start_tcp_sampler():
            time.sleep(6)
            t_bad2, t_note2 = tcp_stale()
            print("🦾 TCP 真值守护: %s → 已重启容器 %s\n   复核: %s %s"
                  % (t_note, TCP_CONTAINER, t_note2,
                     "✅" if not t_bad2 else "❌ 仍不新鲜, 看 sudo docker logs " + TCP_CONTAINER))
            return 0 if not t_bad2 else 1
        print("🦾 TCP 真值守护: 重启 %s 失败 — 需人工看容器" % TCP_CONTAINER)
        return 1

    if ok:
        return 0                                                 # 全正常: 静默
    if a.dry_run:
        print("🛰 工位推流守护(dry-run): %s — 需要重启纠正" % why)
        return 3
    return restart(why)


if __name__ == "__main__":
    sys.exit(main())
