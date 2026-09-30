#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_v9_960_nofile.py — 离线验证 v9「模型直接吃判据图 + 只落一张图」(不接真相机)。

老倪 2026-09-30: 「Finger_ModelIn_W960_H960_No_26549.png 工控机检测的这个就不要了;
                  模型用的是这个图片, 保留下面的 Finger_TopView_W900_H332_No_26549.png;
                  你确定一下模型使用的是不是 topview」

断言(全部要"硬证据", 不接受"看起来差不多"):
  ① POST /capture_detect → 200
  ② 落盘的只有判据图: `Finger_TopView_*`(900x332) 存在, **`Finger_ModelIn_*` 不再产出**
  ③ **模型喂的是同帧派生的 960x960(不落盘)**: 桩记录到的第一个路径在 %TEMP% 且 zmax_main_960_*, 跑完已删;
     v8 那条"直接吃判据图"的路在工控机 app 里会卡死(实测), 故 v9 不走
  ④ 老遗留的 Finger_ModelIn_* 会被自动清掉(keep=0)
  ⑤ 影子对照(老口径 960 方图)在 %TEMP% 里跑, 跑完**临时图必须删掉**(goldfinger_images 里不留第二张)
  ⑥ /last_result: model_input = 判据图; shadow 单列; verdict 取并集(任一 NG 即 NG ⇒ 不漏判)
  ⑦ /picture?kind=crop 仍是判据图口径 + grab 不落盘(老规矩未破)

用法: AOI_REF_JUDGE=... AOI_ORIGIN_PNG=... gui-venv311/bin/python test_v8_topview_input.py
"""
import glob
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
os.environ["AOI_AB_PAIRS"] = "2"                     # 影子对照只跑 2 张
TMP = os.path.join(HERE, "_v9test_tmp")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
os.environ["TEMP"] = TMP                             # 影子临时图落这里(便于断言"跑完就删")
os.environ["TMP"] = TMP

import test_v5_offline as T5            # noqa: E402  复用它的桩(SciCam 底层 + 合成图机制)

import cv2                              # noqa: E402

CALLS = []                              # 桩: 记录**模型被喂了哪张文件**(硬证据)
yd = types.ModuleType("yolo_detector")


class YoloDetector:
    def detect(self, path, detect_type=None):
        CALLS.append(path)
        # 第一个调用(topview 口径)= 有缺陷; 第二个调用(影子 960 口径)= 无缺陷
        #   ⇒ 用来验证"并集判决"确实起作用(单跑 topview 会 NG, 影子带不出 NG)
        dets = [{"class_name": "scratch", "confidence": 0.7, "bbox": [1, 2, 3, 4]}] if len(CALLS) == 1 else []
        return {"detections": dets, "saved_incoming": "_stub.png"}


yd.YoloDetector = YoloDetector
sys.modules["yolo_detector"] = yd

import cam_finger_10082_work_v9 as M     # noqa: E402

ROOT = os.path.join(HERE, "_v9test_finger")
REF = os.environ.get("AOI_REF_JUDGE", "/tmp/aoi_cmp/page_judge.jpg")
ORIGIN = os.environ.get("AOI_ORIGIN_PNG", "/tmp/aoi_cmp/gk_origin.png")
ok = True


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
        print("❌ 缺参考原图 %s" % ORIGIN)
        return 1
    # 预埋一张"老 v7 遗留"的 ModelIn 文件 ⇒ 验证会被自动清掉
    legacy = os.path.join(ROOT, "Finger_ModelIn_W960_H960_No_1.png")
    cv2.imwrite(legacy, np.zeros((960, 960, 3), np.uint8))
    print("══ 桩相机喂入工控机真实原图 %s (%dx%d) ; 版本=%s ; 影子张数=%d ══"
          % (os.path.basename(ORIGIN), bgr.shape[1], bgr.shape[0], M.VERSION, M._AB_LEFT))
    T5._wire(M, bgr)

    class _A:
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
    try:
        M.PORT_TO_DETECT_TYPE["80"] = list(M.PORT_TO_DETECT_TYPE.values())[0]
    except Exception:                                     # noqa: BLE001
        pass
    cli = M.app.test_client()

    r = cli.post("/capture_detect")
    chk("① POST /capture_detect → 200", r.status_code == 200, r.get_json())
    for _ in range(100):                                  # 等检测线程跑完(两次桩推理 + 落盘)
        if len(CALLS) >= 2:
            break
        time.sleep(0.1)
    time.sleep(0.5)

    tops = sorted(glob.glob(os.path.join(ROOT, "Finger_TopView_*_No_*.png")), key=os.path.getmtime)
    mis = glob.glob(os.path.join(ROOT, "Finger_ModelIn_*_No_*.png"))
    chk("② 落了 Finger_TopView_*(判据图口径)", bool(tops), [os.path.basename(p) for p in tops])
    chk("② 不再产出 Finger_ModelIn_*", not mis, mis)
    chk("④ 预埋的老 Finger_ModelIn_* 已被自动清掉(keep=0)", not os.path.exists(legacy))
    if not tops:
        return 1
    tv = cv2.imread(tops[-1])
    chk("② 判据图口径 900x332", tv.shape[1] == 900 and tv.shape[0] == 332, "%dx%d" % (tv.shape[1], tv.shape[0]))

    chk("③ 主口径喂的是 %TEMP% 里的 960 方图(zmax_main_960_*)",
        bool(CALLS) and "zmax_main_960" in os.path.basename(CALLS[0])
        and os.path.abspath(CALLS[0]).startswith(os.path.abspath(TMP)) and not os.path.exists(CALLS[0]),
        os.path.basename(CALLS[0]) if CALLS else "无调用")

    # ⑤ 影子对照: 在 %TEMP% 里跑, 跑完删
    chk("⑤ 影子对照跑了第二遍(老口径 960)", len(CALLS) >= 2, "调用数=%d" % len(CALLS))
    if len(CALLS) >= 2:
        sp = CALLS[1]
        chk("⑤ 影子图是 %TEMP% 下的临时文件(zmax_ab_judge960_*)",
            "zmax_ab_judge960" in os.path.basename(sp) and os.path.abspath(sp).startswith(os.path.abspath(TMP)),
            os.path.basename(sp))
        chk("⑤ 影子临时图跑完已删除", not os.path.exists(sp))
    left = [f for f in glob.glob(os.path.join(TMP, "*")) if f]
    chk("⑤ %TEMP% 里不留残图", not left, left)

    # ⑥ /last_result
    lr = cli.get("/last_result").get_json()
    chk("⑥ /last_result.topview = 判据图", os.path.basename(lr.get("topview", "")) == os.path.basename(tops[-1]),
        lr.get("topview"))
    chk("⑥ /last_result.model_input = 960 同帧派生图 + 有 kind 说明",
        os.path.basename(lr.get("model_input", "")).startswith("zmax_main_960") and "960x960" in str(lr.get("model_input_kind")),
        "%s | %s" % (lr.get("model_input"), lr.get("model_input_kind")))
    sh = lr.get("shadow") or {}
    chk("⑥ /last_result.shadow 单列老口径结果",
        sh.get("count") == 0 and sh.get("verdict") == "OK", sh.get("input_file"))
    chk("⑥ verdict 取并集(topview=NG ⇒ 并集 NG, 不漏判)",
        lr.get("verdict_topview") == "NG" and lr.get("verdict_shadow") == "OK" and lr.get("verdict") == "NG",
        "topview=%s shadow=%s 并集=%s" % (lr.get("verdict_topview"), lr.get("verdict_shadow"), lr.get("verdict")))

    # ⑦ 内存帧 / 不落盘规矩未破
    n0 = len(glob.glob(os.path.join(ROOT, "*.png")))
    r = cli.get("/picture?grab=1&kind=crop")
    n1 = len(glob.glob(os.path.join(ROOT, "*.png")))
    chk("⑦ GET /picture?grab=1&kind=crop → 200 有图", r.status_code == 200 and len(r.data) > 5000, "%d bytes" % len(r.data))
    chk("⑦ grab 不落盘(张数不变)", n0 == n1, "%d→%d" % (n0, n1))
    jp = cv2.imdecode(np.frombuffer(r.data, np.uint8), cv2.IMREAD_COLOR)
    chk("⑦ grab 出图也是判据图口径 900x332", jp is not None and jp.shape[1] == 900 and jp.shape[0] == 332,
        "%dx%d" % (jp.shape[1], jp.shape[0]) if jp is not None else "解码失败")

    # ⑧ 与 4060 网页判据图逐像素同源(几何没改坏)
    ref = cv2.imread(REF)
    if ref is not None:
        def _r(x, y):
            a = cv2.cvtColor(cv2.resize(x, (450, 166)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            b = cv2.cvtColor(cv2.resize(y, (450, 166)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            return float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        chk("⑧ 桩路: 与网页判据图相关 r≥0.70(几何未被改坏)", _r(tv, ref) >= 0.70, "r=%.4f" % _r(tv, ref))

    ci = cli.get("/crop_info").get_json()
    chk("⑧ /crop_info.model_input_file 指向判据图", str(ci.get("model_input_file", "")).startswith("Finger_TopView_"),
        ci.get("model_input_file"))
    chk("⑧ /storage 仍 200", cli.get("/storage").status_code == 200)

    print("\n落盘清单: " + ", ".join(sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.png")))))
    print("\n" + ("✅ v9 全部通过: 只落判据图一张; 模型吃 960 同帧派生图(不落盘); 影子对照跑通" if ok else "❌ 有断言失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
