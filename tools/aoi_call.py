#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_call.py — 调用产线 AOI 检测服务 (192.168.23.23 工控机)

用法:
  python3 tools/aoi_call.py gold     # 金手指检测 (10082, 模型 gf)
  python3 tools/aoi_call.py surface  # 表面检测   (10083, 模型 housing)
  python3 tools/aoi_call.py 10081    # 直接给端口

说明: 服务是**异步**的 —— 返回 success 只代表"已拍照并投递检测";
       YOLO 结果打印在工控机终端, API 不返回判决。详见技能 zmax-aoi-service。
"""
import json
import sys
import time
import urllib.request

HOST = "192.168.23.23"
PORTS = {"gold": 10082, "gf": 10082, "surface": 10083, "housing": 10083}


def main():
    key = (sys.argv[1] if len(sys.argv) > 1 else "gold").lower()
    port = PORTS.get(key, None) or (int(key) if key.isdigit() else None)
    if not port:
        print("用法: aoi_call.py [gold|surface|10081|10082|10083]")
        return 2
    url = "http://%s:%d/capture_detect" % (HOST, port)
    req = urllib.request.Request(url, data=b"", method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "ignore")
            code = r.status
    except Exception as e:
        print("调用失败: %s" % e)
        return 1
    dt = (time.time() - t0) * 1000
    print("POST %s → HTTP %s (%.0f ms)" % (url, code, dt))
    print(body)
    try:
        j = json.loads(body)
    except Exception:
        return 0
    if j.get("code") == 200:
        print("✅ 已触发拍照+检测投递 (注意: 判决在工控机终端, 本接口不返回结果)")
        return 0
    print("⚠️ 服务返回: %s" % j.get("msg"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
