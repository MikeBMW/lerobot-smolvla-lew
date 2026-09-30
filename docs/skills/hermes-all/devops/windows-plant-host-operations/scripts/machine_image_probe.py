# -*- coding: utf-8 -*-
"""只读图像探针(在 Windows 产线机上跑): 量图上"有没有真结构", 而不是"看起来像不像"。

为什么需要: 服务刚卡过/刚重启时, 它的**内存帧**路由会给一张陈旧/雾面帧 —— 拿它判图像内容结论必错。
这个脚本只看**落盘文件**(或你指定的文件), 不改任何东西、不占端口。

用法:
    venv\Scripts\python.exe machine_image_probe.py <文件或 glob> [<文件或 glob> ...]
    venv\Scripts\python.exe machine_image_probe.py --detect <glob>     # 可选: 再喂真模型跑一遍(需目标程序的 detector 可用)

输出: 纯 ASCII key 的 JSON(产线控制台是 GBK, 不打印中文)。
判读: block16_std_mean 高(>15) = 有细结构; <6 = 离焦/雾面; pct_gt240 高 = 过曝会吃掉低对比度缺陷;
      col_ac_peak 高 + 固定 lag = 周期性结构(节距 = col_ac_lag)。
"""
import glob
import json
import os
import sys
import time

import cv2
import numpy as np


def image_stats(p):
    im = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    if im is None:
        return {"error": "imread failed"}
    h, w = im.shape
    hh, ww = (h // 16) * 16, (w // 16) * 16
    blk = im[:hh, :ww].reshape(hh // 16, 16, ww // 16, 16).transpose(0, 2, 1, 3).reshape(-1, 16, 16)
    c = im.astype(np.float32)
    c = c - c.mean(axis=0, keepdims=True)
    ac = [float((c[:, :-k] * c[:, k:]).mean() / (c.std() ** 2 + 1e-6)) for k in range(1, 160)]
    return {"h": h, "w": w, "mean": round(float(im.mean()), 1), "std": round(float(im.std()), 1),
            "block16_std_mean": round(float(blk.std(axis=(1, 2)).mean()), 2),
            "pct_gt240": round(float((im > 240).mean() * 100), 2),
            "pct_gt250": round(float((im > 250).mean() * 100), 2),
            "col_ac_peak": round(max(ac), 3), "col_ac_lag": int(np.argmax(ac) + 1)}


def main():
    argv = [a for a in sys.argv[1:] if a != "--detect"]
    det = None
    if "--detect" in sys.argv:
        from yolo_detector import YoloDetector                  # 目标程序自带的检测器
        det = YoloDetector()
    files = []
    for a in argv or ["*.png"]:
        hit = sorted(glob.glob(a), key=os.path.getmtime)
        files.extend(hit[-3:] if hit else [a])
    out = {"host": os.environ.get("COMPUTERNAME", "?"), "t": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": []}
    for p in files:
        if not os.path.isfile(p):
            out["runs"].append({"file": p, "error": "not found"})
            continue
        rec = {"file": os.path.basename(p), "bytes": os.path.getsize(p),
               "mtime": time.strftime("%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p)))}
        rec.update(image_stats(p))
        if det is not None:
            try:
                t0 = time.time()
                r = det.detect(p)
                d = (r.get("detections") or r.get("defects") or []) if isinstance(r, dict) else []
                rec.update({"ms": round((time.time() - t0) * 1000, 1), "count": len(d),
                            "verdict": "NG" if d else "OK"})
            except Exception as e:                              # noqa: BLE001
                rec["detect_error"] = str(e)[:200]
        out["runs"].append(rec)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
