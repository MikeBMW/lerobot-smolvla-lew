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
import json
import os
import platform
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROLE = os.environ.get("ZMAX_HW_ROLE", "mac")


def _ws_dds_payload(machine: str = "mac") -> dict:
    """采集本机硬件 → **ECS DDS 网关期望的 payload 格式**
    (2026-09-25 从 /root/dds_ws_gateway.py + /api/train/hardware 实测反推)
    字段: machine/gpu/gpu_load/gpu_vram/gpu_vram_total/load1..15/
          mem_total(MB)/mem_used(MB)/disk_total(GB)/disk_used(GB)/cpu_cores/cpu_mhz/time
    """
    from hw_monitor import probe
    d = probe(measure=False)
    g = d["gpu"]
    gpu_name = f"{g.get('name') or 'Apple GPU'} (MPS)" if g.get("backend") == "mps" else (g.get("name") or "未知")
    vram_used = g.get("mem_used_gb")
    vram_total = g.get("mem_total_gb")
    mem = d["mem"]
    disk = d["disk"]
    return {
        "machine": machine,
        "os": platform.system(),
        "gpu": gpu_name,
        "gpu_load": int(g["util_pct"]) if g.get("util_pct") is not None else None,
        "gpu_vram": round(vram_used, 2) if vram_used is not None else None,
        "gpu_vram_total": round(vram_total, 2) if vram_total is not None else None,
        "load1": d["cpu"].get("load1"),
        "load5": d["cpu"].get("load5"),
        "load15": d["cpu"].get("load15"),
        "cpu_percent": d["cpu"].get("percent"),
        "mem_total": int(round((mem.get("total_gb") or 0) * 1024)),
        "mem_used": int(round((mem.get("used_gb") or 0) * 1024)),
        "disk_total": int(round(disk.get("total_gb") or 0)),
        "disk_used": int(round(disk.get("used_gb") or 0)),
        "cpu_cores": d["cpu"].get("cores"),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "notes": "on MPS (Apple Silicon 统一内存, 显存=系统内存)",
    }


def _ws_dds_loop(machine: str = "mac", interval: float = 5.0):
    """**真 DDS 通道**: WebSocket(TCP443) → ECS DDS 网关 → DDS 总线(ZMAX.Msg)
    这是 APP 读取的路径 (/api/train/hardware 由该总线喂数据)。
    用 WebSocket 是因为 DDS 组播过不了公网, 网关在 ECS 侧把它发布到真 DDS 总线。
    """
    try:
        from websockets.sync.client import connect
    except Exception as e:
        print(f"❌ 需要 websockets 库: pip install websockets ({e})", flush=True)
        return 1
    url = os.environ.get("ZMAX_DDS_WS", "wss://datadrive.world/ws/dds/")
    print(f"🛰  DDS 通道启动 · {machine} → {url} (每 {interval:.0f}s)", flush=True)
    n = 0
    while True:
        try:
            with connect(url, open_timeout=15) as ws:
                print(f"🛰  已接入 DDS 总线 ({time.strftime('%H:%M:%S')})", flush=True)
                while True:
                    hw = _ws_dds_payload(machine)
                    ws.send(json.dumps({"type": "hardware", "payload": hw}, ensure_ascii=False))
                    n += 1
                    if n % 6 == 0:
                        print(f"🛰  已上报 {n} 次 | GPU {hw['gpu']} "
                              f"{hw['gpu_vram']}/{hw['gpu_vram_total']}GB "
                              f"负载 {hw['gpu_load']}% ({time.strftime('%H:%M:%S')})", flush=True)
                    try:
                        ws.recv(timeout=1.0)
                    except TimeoutError:
                        pass
                    time.sleep(interval)
        except Exception as e:
            print(f"⚠️  DDS 通道断开, 3s 后重连: {type(e).__name__}: {str(e)[:110]}", flush=True)
            time.sleep(3)


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
        # --dds = 真 DDS 通道 (WebSocket → ECS DDS 网关 → DDS 总线) ← APP 读这条
        if a.cloud:
            import threading
            from hw_upload import brief, collect, upload

            def _cloud_loop():
                while True:
                    try:
                        p = collect(measure_tflops=a.measure_tflops)
                        r = upload(p)
                        print(f"☁️  上云(副本) ok={r.get('ok')} | {brief(p)}", flush=True)
                    except Exception as e:
                        print(f"⚠️  上云失败: {type(e).__name__}: {str(e)[:90]}", flush=True)
                    time.sleep(10)

            threading.Thread(target=_cloud_loop, daemon=True).start()
        return _ws_dds_loop(ROLE, a.hz if a.hz > 1 else 5.0)

    if a.dds:
        # 单次: 走 DDS 网关发一包
        try:
            from websockets.sync.client import connect
            url = os.environ.get("ZMAX_DDS_WS", "wss://datadrive.world/ws/dds/")
            with connect(url, open_timeout=15) as ws:
                hw = _ws_dds_payload(ROLE)
                ws.send(json.dumps({"type": "hardware", "payload": hw}, ensure_ascii=False))
                try:
                    print("  DDS 网关回应:", ws.recv(timeout=3.0)[:200])
                except TimeoutError:
                    print("  (无回应, 已发送)")
            print(f"  ✅ 已通过 DDS 通道上报一次: {hw['machine']} GPU={hw['gpu']} "
                  f"{hw['gpu_vram']}/{hw['gpu_vram_total']}GB")
        except Exception as e:
            print(f"  ❌ DDS 上报失败: {type(e).__name__}: {str(e)[:150]}")
            return 1
        return 0

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
