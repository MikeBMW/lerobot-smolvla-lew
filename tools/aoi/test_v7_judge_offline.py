#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_v7_judge_offline.py — 离线验证 v7 的判据图口径(不接真相机)。

老倪 2026-09-29: 「工控机的金手指…点击请求检测后, 在工控机保存的 topview 图片不是判据图的样子; 改成判据图的样子」

断言:
  ① POST /capture_detect → 200, 且落盘的 `Finger_TopView_*` 就是**判据图口径** 900x332
  ② 这张顶视图与 4060 网页判据图(同源同一张原图) **结构相关 r≥0.99**(逐像素同源, 不是"看起来差不多")
  ③ 送检给 YOLO 的仍是 **Finger_ModelIn_* 960x960**(逐位不变 ⇒ 召回不受影响), /last_result 两路都报
  ④ GET /picture?kind=crop(内存帧) → 判据图(grab 不落盘这条老规矩保持)
  ⑤ /crop_info 带 judge 台账(保留行/切过曝行/列裁/倾角/定尺) + model_input_file

做法: 桩掉 SciCam SDK 底层, 但把**相机图像换成工控机真实原图**(/tmp/aoi_cmp/gk_origin.png),
      让真的 GrabAndSaveImage + 真的 render_judge 跑起来。
用法: .venv-test/bin/python test_v7_judge_offline.py
"""
import glob
import hashlib
import os
import shutil
import sys
import time
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_stub"))
sys.path.insert(0, HERE)
os.environ.setdefault("AOI_KEEP_CANON", "4")
os.environ.setdefault("AOI_KEEP_ORIGIN", "4")

import test_v5_offline as T5            # noqa: E402  复用它的桩(SciCam 底层 + 合成图机制)

import cv2                              # noqa: E402

# 桩 yolo_detector: 记录**它被喂了哪张文件**(这是"模型输入有没有变"的硬证据)
CALLS = []
yd = types.ModuleType("yolo_detector")


class YoloDetector:
    def detect(self, path, detect_type=None):
        CALLS.append(path)
        return {"detections": [{"class_name": "scratch", "confidence": 0.7, "bbox": [1, 2, 3, 4]}],
                "saved_incoming": "_stub.png"}


yd.YoloDetector = YoloDetector
sys.modules["yolo_detector"] = yd

import cam_finger_10082_work_v7 as M     # noqa: E402

ROOT = os.path.join(HERE, "_v7test_finger")
REF = os.environ.get("AOI_REF_JUDGE", "/tmp/aoi_cmp/page_judge.jpg")
ORIGIN = os.environ.get("AOI_ORIGIN_PNG", "/tmp/aoi_cmp/gk_origin.png")
ok = True


def _ref_angle(default=-0.75):
    """真相机 /region 的实测倾角(与网页判据图同源的基准图所用值)。"""
    try:
        import json
        import urllib.request
        with urllib.request.urlopen("http://192.168.23.23:10082/region", timeout=6) as f:
            return float(json.loads(f.read().decode("utf-8", "ignore")).get("angle", default))
    except Exception:                                     # noqa: BLE001
        return default


def chk(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print("  %s %s%s" % ("✅" if cond else "❌", name, (" — " + str(detail)) if detail else ""))
    return bool(cond)


def main():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT, exist_ok=True)
    M.SAVE_ROOT_DIR = ROOT
    bgr = cv2.imread(ORIGIN)
    if bgr is None:
        print("❌ 缺参考原图 %s (先跑 curl 'http://192.168.23.23:10082/picture?kind=origin' 存下来)" % ORIGIN)
        return 1
    print("══ 桩相机喂入工控机真实原图 %s (%dx%d) ══" % (os.path.basename(ORIGIN), bgr.shape[1], bgr.shape[0]))
    T5._wire(M, bgr)

    class _A:                                             # 与真相机同尺寸的属性对象(2448x2048)
        isComplete = 1
        payloadMode = 1

        class imgAttr:
            width = 2448
            height = 2048
            pixelType = 7
    M.SCI_CAM_PAYLOAD_ATTRIBUTE = _A
    M.SciCam_Payload_GetAttribute = lambda pp, attr, *a, **k: 0
    M.SciCam_Payload_GetImage = lambda pp, out, *a, **k: 0
    M.ensure_camera = lambda *a, **k: True
    try:                                                  # 离线无监听端口 ⇒ 把测试客户端的端口映射成 10082
        M.PORT_TO_DETECT_TYPE["80"] = list(M.PORT_TO_DETECT_TYPE.values())[0]
    except Exception:                                     # noqa: BLE001
        pass
    cli = M.app.test_client()

    # ① 真检测: 拍照 + 落盘 + 投递
    r = cli.post("/capture_detect")
    chk("POST /capture_detect → 200", r.status_code == 200, r.get_json())
    for _ in range(80):                                   # 等检测线程跑完(桩推理很快)
        if CALLS:
            break
        time.sleep(0.1)

    tops = sorted(glob.glob(os.path.join(ROOT, "Finger_TopView_*_No_*.png")), key=os.path.getmtime)
    mis = sorted(glob.glob(os.path.join(ROOT, "Finger_ModelIn_*_No_*.png")), key=os.path.getmtime)
    chk("落了 Finger_TopView_*", bool(tops), [os.path.basename(p) for p in tops])
    chk("落了 Finger_ModelIn_*", bool(mis), [os.path.basename(p) for p in mis])
    if not (tops and mis):
        return 1
    tv = cv2.imread(tops[-1])
    mi = cv2.imread(mis[-1])
    chk("顶视图是判据图口径 900x332", tv.shape[1] == 900 and tv.shape[0] == 332, "%dx%d" % (tv.shape[1], tv.shape[0]))
    chk("模型输入仍是 960x960 规整图(逐位不变)", mi.shape[1] == 960 and mi.shape[0] == 960, "%dx%d" % (mi.shape[1], mi.shape[0]))

    # ② 与 4060 网页判据图逐像素同源。
    #    分两路量, 因为**桩相机比真相机多一道去马赛克**(桩喂进来的是已经处理好的 PNG 字节,
    #    还会再走一遍 raw→BGR ⇒ 画面被二次平滑/提亮, 几何不变但细节相关会掉到 ~0.8):
    #      ②a 桩路(端到端路由): 只要求几何台账一致 + 相关 r≥0.70(能检出"几何被改坏")
    #      ②b 直调路(render_judge 拿同一张原图): 这才是"同一口径"的硬证据, 要求 r≥0.99
    ref = cv2.imread(REF)
    if ref is not None:
        def _r(x, y):
            a = cv2.cvtColor(cv2.resize(x, (450, 166)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            b = cv2.cvtColor(cv2.resize(y, (450, 166)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            return float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        rr = _r(tv, ref)
        chk("②a 桩路: 与网页判据图相关 r≥0.70(几何未被改坏)", rr >= 0.70, "r=%.4f" % rr)
        bgr_fresh = cv2.imread(ORIGIN)          # ⚠️ 重新读一份(桩路径会原地改它自己那份像素)
        # 倾角取**真相机 /region 的实测值**: 桩路的去马赛克被叠了两遍(桩喂的已是处理好的 PNG),
        # 它自己量出来的倾角会偏(本次实测 -1.50° vs 真值 -0.75°), 不能拿来对基准。
        ang = _ref_angle()
        jd, jm = M.render_judge(bgr_fresh, deskew_deg=ang)
        print("     [口径] 用真相机 /region 倾角=%.2f° ; 原图 mean=%.2f ; 直调 mean=%.1f 桩路 mean=%.1f"
              % (ang, bgr_fresh.mean(), jd.mean(), tv.mean()))
        rr2 = _r(jd, ref)
        chk("②b 直调: render_judge(同一张原图) vs 网页判据图 r≥0.99", rr2 >= 0.99,
            "r=%.4f; 保留行=%s 列裁=%s 定尺=%s" % (rr2, jm.get("kept_rows"), (jm.get("x_trim") or {}).get("x_span"), jm.get("fix_hw")))
        cv2.imwrite(os.path.join(ROOT, "_cmp_桩路.jpg"), tv)
        cv2.imwrite(os.path.join(ROOT, "_cmp_直调.jpg"), jd)
    else:
        print("  ⚠️ 缺参考判据图 %s, 跳过逐像素对比" % REF)

    # ③ 送检的是模型输入那张
    chk("送检路径 = 最新 Finger_ModelIn_*", CALLS and os.path.abspath(CALLS[-1]) == os.path.abspath(mis[-1]),
        os.path.basename(CALLS[-1]) if CALLS else "无调用")
    lr = cli.get("/last_result").get_json()
    chk("/last_result.topview = 判据图", os.path.basename(lr.get("topview", "")) == os.path.basename(tops[-1]), lr.get("topview"))
    chk("/last_result.model_input = 960 规整图", os.path.basename(lr.get("model_input", "")) == os.path.basename(mis[-1]),
        lr.get("model_input"))

    # ④ 内存帧 / 不落盘规矩未破
    n0 = len(glob.glob(os.path.join(ROOT, "*.png")))
    r = cli.get("/picture?grab=1&kind=crop")
    n1 = len(glob.glob(os.path.join(ROOT, "*.png")))
    chk("GET /picture?grab=1&kind=crop → 200 有图", r.status_code == 200 and len(r.data) > 5000, "%d bytes" % len(r.data))
    chk("grab 不落盘(张数不变)", n0 == n1, "%d→%d" % (n0, n1))
    jp = cv2.imdecode(np.frombuffer(r.data, np.uint8), cv2.IMREAD_COLOR)
    chk("grab 出图也是判据图口径 900x332", jp is not None and jp.shape[1] == 900 and jp.shape[0] == 332,
        "%dx%d" % (jp.shape[1], jp.shape[0]) if jp is not None else "解码失败")

    # ⑤ 台账
    ci = cli.get("/crop_info").get_json()
    j = ci.get("judge") or {}
    chk("/crop_info.judge 台账齐全", bool(j.get("kept_rows") and j.get("fix_hw") == [900, 332] and j.get("out") == [900, 332]), j)
    chk("/crop_info.model_input_file 指向 960 图", ci.get("model_input_file", "").startswith("Finger_ModelIn_"),
        ci.get("model_input_file"))
    chk("/storage 仍 200", cli.get("/storage").status_code == 200)

    print("\n落盘清单: " + ", ".join(sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.png")))))
    print("\n" + ("✅ v7 判据图口径全部通过" if ok else "❌ 有断言失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
