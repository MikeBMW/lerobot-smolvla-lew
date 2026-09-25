#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mac_hw_report.py — Mac 硬件上报入口 (APP 约定的脚本名)
=========================================================
手机 APP / web 控制平台按这个脚本名和参数来判断"小芳是否在上报"。
界面文案: "Mac 未上报（小芳需跑 mac_hw_report.py --dds）"

用法:
    python3 mac_hw_report.py --dds                  # 只走 DDS 播报 (APP 要求)
    python3 mac_hw_report.py --dds --loop           # 常驻 (默认 1Hz)
    python3 mac_hw_report.py --cloud                # 只上云 (ECS relay)
    python3 mac_hw_report.py --dds --cloud --loop   # 双通道常驻 (推荐)
    python3 mac_hw_report.py --once                 # 打一次快照看数据

环境变量:
    ZMAX_HW_ROLE      本机角色 (默认 mac)
    ZMAX_HW_HZ        DDS 播报频率 (默认 1)
    ZMAX_RELAY_URL    ECS 上传地址
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROLE = os.environ.get("ZMAX_HW_ROLE", "mac")


def _publish_dds(hz: float = 1.0, measure: bool = False, stop_after: float | None = None):
    """走 DDS 播报本机硬件 (APP 的 --dds 模式)"""
    from hw_dds import HwPublisher
    pub = HwPublisher(role=ROLE, measure_tflops=measure)
    print(f"🛰  DDS 播报启动 · role={ROLE} · 话题 zmax/hw/metrics · {hz}Hz", flush=True)
    pub.tick()   # 立刻发第一包, APP 不用等
    period = 1.0 / max(0.05, hz)
    t0 = time.time()
    n = 1
    while True:
        time.sleep(period)
        try:
            pub.tick()
            n += 1
            if n % max(1, int(hz) * 10) == 0:
                print(f"🛰  DDS 已播报 {n} 包 ({time.strftime('%H:%M:%S')})", flush=True)
        except Exception as e:
            print(f"⚠️  DDS 播报异常: {type(e).__name__}: {str(e)[:100]}", flush=True)
        if stop_after and (time.time() - t0) >= stop_after:
            return n


def _upload_cloud(measure: bool = False):
    """走 ECS relay 上云"""
    from hw_upload import brief, collect, upload
    payload = collect(measure_tflops=measure)
    r = upload(payload)
    print(f"☁️  上云 ok={r.get('ok')} name={r.get('name')} | {brief(payload)}", flush=True)
    return r


def main():
    ap = argparse.ArgumentParser(description="Mac 硬件上报 (DDS / 云)")
    ap.add_argument("--dds", action="store_true", help="DDS 播报 (APP 要求的模式)")
    ap.add_argument("--cloud", action="store_true", help="上传到 ECS relay")
    ap.add_argument("--loop", action="store_true", help="常驻循环")
    ap.add_argument("--hz", type=float, default=float(os.environ.get("ZMAX_HW_HZ", "1")))
    ap.add_argument("--measure-tflops", action="store_true", help="含算力实测 (较慢)")
    ap.add_argument("--once", action="store_true", help="打一次快照")
    ap.add_argument("--seconds", type=float, default=None, help="跑多久后退出 (自检用)")
    a = ap.parse_args()

    if not (a.dds or a.cloud or a.once):
        # 默认按 APP 约定: --dds
        a.dds = True

    # 快照模式
    if a.once:
        from hw_monitor import fmt, probe
        d = probe(measure=a.measure_tflops)
        print(fmt(d))
        print(f"\n  gpu.mem_total_gb = {d['gpu'].get('mem_total_gb')}  "
              f"gpu.mem_used_gb = {d['gpu'].get('mem_used_gb')}")
        return 0

    if a.dds and a.loop:
        # 双通道: DDS 播报 + 定时上云
        if a.cloud:
            import threading
            from hw_upload import brief, collect, upload

            def _cloud_loop():
                while True:
                    try:
                        p = collect(measure_tflops=a.measure_tflops)
                        r = upload(p)
                        print(f"☁️  上云 ok={r.get('ok')} | {brief(p)}", flush=True)
                    except Exception as e:
                        print(f"⚠️  上云失败: {type(e).__name__}: {str(e)[:90]}", flush=True)
                    time.sleep(10)

            threading.Thread(target=_cloud_loop, daemon=True).start()
        return _publish_dds(a.hz, a.measure_tflops, a.seconds) and 0

    if a.dds:
        return _publish_dds(a.hz, a.measure_tflops, a.seconds or 2.0) and 0

    if a.cloud:
        if a.loop:
            from hw_upload import main as _up
            sys.argv = ["hw_upload", "--loop", "--interval", "10"]
            if a.measure_tflops:
                sys.argv.append("--measure-tflops")
            return _up()
        _upload_cloud(a.measure_tflops)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
