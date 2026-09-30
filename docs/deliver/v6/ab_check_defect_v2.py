# -*- coding: utf-8 -*-
"""离线复核(在工控机本机跑, 不改任何文件): 用同一套 yolo_detector 对最新一帧的三种图各跑一遍。

老倪的问题: 光模块摆好了, 眼睛能看到缺陷, YOLO 到底看到没有?
只 new 一个检测器读图, 不占 10082 端口、不动在役进程。
用法(程序目录下):  venv/Scripts/python.exe ab_check_defect_v2.py
"""
import glob, json, os, time

from yolo_detector import YoloDetector


def newest(pat):
    f = sorted(glob.glob(pat), key=os.path.getmtime)
    return f[-1] if f else None


out = {"host": os.environ.get("COMPUTERNAME", "?"), "t": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": []}
targets = []
_j = newest(os.path.join("goldfinger_images", "Finger_TopView_*.png"))
if _j:
    targets.append(("judge_topview_900x332", _j))
_o = newest(os.path.join("goldfinger_images", "Finger_Image_*.png"))
if _o:
    targets.append(("origin_2448x2048", _o))
_t = newest(os.path.join(os.environ.get("TEMP", "C:" + os.sep + "Windows" + os.sep + "TEMP"), "zmax_main_960_*.png"))
if _t:
    targets.append(("modelin_960_temp", _t))

det = YoloDetector()
for label, p in targets:
    rec = {"label": label, "file": os.path.basename(p), "bytes": os.path.getsize(p)}
    try:
        t0 = time.time()
        r = det.detect(p, detect_type="gf")
        d = r.get("detections", []) or []
        rec.update({"ms": round((time.time() - t0) * 1000, 1), "count": len(d),
                    "verdict": "NG" if d else "OK",
                    "defects": [{"cls": x.get("class_name", x.get("name")),
                                 "conf": round(float(x.get("confidence", x.get("conf", 0))), 3),
                                 "bbox": x.get("bbox", x.get("box"))} for x in d[:12]],
                    "result_keys": sorted(r.keys())})
    except Exception as e:                                                   # noqa: BLE001
        rec["error"] = str(e)[:200]
    out["runs"].append(rec)

print(json.dumps(out, ensure_ascii=False, indent=1))
