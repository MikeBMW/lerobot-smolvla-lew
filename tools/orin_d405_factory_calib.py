#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orin_d405_factory_calib.py — 【在 Orin 上跑, 只读设备元数据】读 D405 出厂标定

⚠️ 红线: **不启动任何 pipeline、不流、不写文件、不起服务** —— 只 query_devices() 读元数据,
   不干扰已经在跑的 ROS realsense 驱动 (同一个设备开第二条流有风险, 一律不做)。

输出: 彩色/深度 内参 (fx,fy,cx,cy) + 畸变 + **depth→color 外参** (平移/旋转) → JSON
用途: 有了内参 + 深度 → color 像素 ↔ depth 像素映射 → 框内深度 → 相机系 3D (米制, 不需要尺寸先验)。

用法 (Orin): python3 orin_d405_factory_calib.py > /tmp/d405_calib.json
"""
from __future__ import annotations

import json
import sys

def main():
    try:
        import pyrealsense2 as rs
    except Exception as e:                                                     # noqa: BLE001
        print(json.dumps({"ok": False, "why": f"无 pyrealsense2: {e}"}, ensure_ascii=False))
        return 1
    ctx = rs.context()
    devs = list(ctx.query_devices())
    out = {"ok": False, "n_devices": len(devs), "devices": []}
    for d in devs:
        info = {"name": d.get_info(rs.camera_info.name), "serial": d.get_info(rs.camera_info.serial_number),
                "fw": (d.get_info(rs.camera_info.firmware_version)
                       if d.supports(rs.camera_info.firmware_version) else None), "sensors": []}
        try:
            prof_color = d.first_color_sensor().get_stream_profiles() if d.first_color_sensor() else []
            prof_depth = d.first_depth_sensor().get_stream_profiles() if d.first_depth_sensor() else []
            # 取 640x480 (或最大) 的 profile 读内参
            def pick(profs, w=640, h=480):
                cand = [p for p in profs if p.as_video_stream_profile().width() == w
                        and p.as_video_stream_profile().height() == h]
                return (cand or profs or [None])[0]
            pc, pd = pick(prof_color), pick(prof_depth)
            if pc is not None:
                v = pc.as_video_stream_profile()
                ic = v.get_intrinsics()
                info["color"] = {"format": str(pc.format()), "fps": pc.fps(),
                                 "w": v.width(), "h": v.height(),
                                 "fx": ic.fx, "fy": ic.fy, "ppx": ic.ppx, "ppy": ic.ppy,
                                 "model": str(ic.model), "coeffs": list(ic.coeffs)}
            if pd is not None:
                v = pd.as_video_stream_profile()
                idd = v.get_intrinsics()
                info["depth"] = {"format": str(pd.format()), "fps": pd.fps(),
                                 "w": v.width(), "h": v.height(),
                                 "fx": idd.fx, "fy": idd.fy, "ppx": idd.ppx, "ppy": idd.ppy,
                                 "model": str(idd.model), "coeffs": list(idd.coeffs)}
            if pc is not None and pd is not None:
                ex = pd.get_extrinsics_to(pc.as_video_stream_profile())     # depth → color
                info["depth_to_color"] = {"rotation": list(ex.rotation), "translation_m": list(ex.translation)}
                ey = pc.get_extrinsics_to(pd.as_video_stream_profile())     # color → depth
                info["color_to_depth"] = {"rotation": list(ey.rotation), "translation_m": list(ey.translation)}
            for s in d.sensors:
                sn = {"name": s.get_info(rs.camera_info.name), "streams": []}
                for p in s.get_stream_profiles():
                    try:
                        v = p.as_video_stream_profile()
                        sn["streams"].append(f"{p.stream_type()}/{p.format()}/{v.width()}x{v.height()}@{p.fps()}")
                    except Exception:                                          # noqa: BLE001
                        sn["streams"].append(f"{p.stream_type()}/{p.format()}@{p.fps()}")
                info["sensors"].append(sn)
            out["ok"] = ("color" in info and "depth" in info)
        except Exception as e:                                                 # noqa: BLE001
            info["err"] = f"{type(e).__name__}: {e}"
        out["devices"].append(info)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
