#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_opt_camera.py — 工控机 OPT 相机链路取证 (2026-09-24)

判据:
  ① 零副作用只读: 路由探针 (OPTIONS) 双相机 + 工控机判决通道 (本机直连)
  ② 双通道等价: 本机直连 vs 经 Orin (ssh → curl) 都能拿到 10082 /last_result (同一判决)
  ③ 真拍取图 (需 --authorize): POST /capture_detect + GET /picture?kind=topview&grab=1
     → 断言 拿到真图 (非黑帧 mean_gray>5) + 尺寸 + 耗时 + 审计落盘
  ④ 任务头在真图上的识别: AoiQualityHead.inspect() → 判决表行数>0 且来源可辨
  ⑤ 表面相机 10083 如实报缺口 (无 /picture 路由 → 不能取图)
用法: ./gui-venv311/bin/python tools/verify_opt_camera.py --authorize   # --authorize 才真拍
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui"),
           os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("ZMAX_ANNOT_ROOT_AOI", os.path.join(ROOT, "data", "yolo_aoi_annot"))
import opt_camera_client as optc                                          # noqa: E402
from aoi_head import AoiQualityHead                                       # noqa: E402
import yolo_annot_dataset as yad                                          # noqa: E402

CHECKS, RES = {}, {}


def ck(n, c, d=""):
    CHECKS[n] = bool(c)
    print(f"  {'✅' if c else '❌'} {n}" + (f" — {d}" if d else ""))


def main():
    auth = "--authorize" in sys.argv
    print(f"🏭 工控机 OPT 相机链路取证 (真拍={'是' if auth else '否 (只读)'})")

    # ① 只读探针
    h = optc.health(via="local")
    r82 = h["cams"]["金手指"]["routes"]
    r83 = h["cams"]["表面"]["routes"]
    RES["health"] = h
    ck("① 10082 有 /picture 路由", "GET" in r82.get("/picture", "") or "POST" in r82.get("/picture", ""),
       str(r82.get("/picture")))
    ck("① 10082 有 /last_result 判决通道", "GET" in r82.get("/last_result", ""), str(r82.get("/last_result")))
    ck("① 10083 只有 /capture_detect (如实标注无 /picture)",
       "路由不存在" in r83.get("/picture", "") and "POST" in r83.get("/capture_detect", ""),
       f"/picture={r83.get('/picture')} /capture_detect={r83.get('/capture_detect')}")
    lr_local = optc.last_result(1, via="local")
    RES["last_result_local_before"] = lr_local
    # ⚠️ 判据: /last_result 通道"可达且结构化"即可 —— 两种合法形态:
    #    code=200 + verdict/count (有检测记录) | code=404 + msg (服务内存空, 拍照后才有)
    #    断言 code==200 会误报服务刚重启的情况; 断言必须带 msg 会在 200 时误报。
    _struct = (lr_local.get("code") == 200 and ("verdict" in lr_local or "count" in lr_local)) or \
              (lr_local.get("code") == 404 and "msg" in lr_local)
    ck("① /last_result 通道可达且结构化", bool(_struct),
       f"code={lr_local.get('code')} verdict={lr_local.get('verdict')} count={lr_local.get('count')} "
       f"msg={lr_local.get('msg')}")
    lr_orin0 = optc.last_result(1, via="orin")
    ck("② 经 Orin 通道可达 (ssh→curl 同一条通道)", lr_orin0.get("code") in (200, 404),
       f"orin code={lr_orin0.get('code')} msg={str(lr_orin0.get('msg'))[:60]}")

    head = AoiQualityHead()
    RES["head"] = {"weights": head.weights, "ready": head.model_ready, "note": head._load_err}

    if auth:
        # ③ 真拍 + 取图 (产线台会真拍一张)
        t0 = time.time()
        # 真拍一次 (与产线同为 POST /capture_detect) → 再取图 (不重复抓帧, 省产线节拍)
        cap = optc.capture_detect(1, via="local")
        time.sleep(1.0)                       # 等工控机异步落盘 (其自家检测 ~1.5s)
        rgb, meta = optc.fetch_frame(1, kind="topview", grab=False, via="local")
        RES["capture"] = {"capture_detect": cap, "fetch_meta": meta, "wall_s": round(time.time() - t0, 1)}
        ok = rgb is not None
        ck("③ 真拍拿到图 (非黑帧)", ok and meta.get("mean_gray", 0) > 5,
           f"{meta.get('shape')} 灰度均值={meta.get('mean_gray')} {meta.get('ms')}ms "
           f"{meta.get('bytes', 0)//1024}KB HTTP={meta.get('http')}")
        if ok:
            # ④ 任务头在真图上识别
            res = head.inspect(rgb, roi="gold_finger", zoom=2.0)
            n_rows = len(res["verdict"]["items"])
            srcs = sorted({it.get("source") for it in res["verdict"]["items"]})
            RES["head_on_real"] = {"rows": n_rows, "sources": srcs, "loc": len(res["loc"]),
                                   "defects": len(res["defects"]), "elapsed_ms": res["elapsed_ms"],
                                   "roi_meta": res["roi_meta"]}
            ck("④ 任务头在真图上出判决表", n_rows > 0, f"{n_rows} 行 来源={srcs} "
                                                        f"定位={len(res['loc'])} 缺陷={len(res['defects'])}")
            # 真图结构断言 (不是空白/占位): 灰度 std + Tenengrad + 非均匀性
            import cv2
            g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            gx = cv2.Sobel(g, cv2.CV_32F, 1, 0); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
            ten = float((gx * gx + gy * gy).mean())
            RES["real_image_stats"] = {"std": round(float(g.std()), 1), "tenengrad": round(ten, 1),
                                      "mean_gray": round(float(g.mean()), 1)}
            ck("④ 真图有真实结构 (非空白帧)", float(g.std()) > 8 and ten > 20,
               f"std={g.std():.1f} Tenengrad={ten:.1f} mean={g.mean():.1f}")
            # ②b 判决对照: 拍照后工控机自家模型判决应新鲜, 且本机/Orin 读到的**必须是同一条**
            lr_l = optc.last_result(1, via="local")
            lr_o = optc.last_result(1, via="orin")
            RES["last_result_after"] = {"local": lr_l, "orin": lr_o}
            ck("② 双通道读到同一条工控机判决 (t 一致)",
               lr_l.get("code") == 200 and lr_l.get("t") == lr_o.get("t"),
               f"local code={lr_l.get('code')} t={lr_l.get('t')} verdict={lr_l.get('verdict')} | "
               f"orin t={lr_o.get('t')}")
            # 落盘为标定素材 (直接可进数据集)
            p = os.path.join(ROOT, "reports", f"opt_capture_{time.strftime('%Y%m%d_%H%M%S')}.png")
            import cv2
            cv2.imwrite(p, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            RES["saved_png"] = p
            try:
                yad.save_sample(head.root, rgb, [], device="opt-10082", src="real",
                                annotator="verify")
                RES["sample_saved"] = True
            except Exception as e:                                        # noqa: BLE001
                RES["sample_saved"] = f"{type(e).__name__}: {e}"
            ck("④ 真图落盘 + 可入标定库", os.path.isfile(p) and RES.get("sample_saved") is True,
               f"{p} · sample={RES.get('sample_saved')}")

        # ⑤ 表面相机缺口
        rgb2, meta2 = optc.fetch_frame(2, kind="topview", grab=False, via="local")
        RES["surface_gap"] = meta2
        ck("⑤ 10083 取图如实报缺口 (无 /picture)",
           rgb2 is None and "/picture" in str(meta2.get("err", "")), str(meta2.get("err"))[:90])
    else:
        print("  ⏭ 跳过 ③④⑤ (未加 --authorize; 真拍产线台需授权)")

    out = os.path.join(ROOT, "reports", f"opt_camera_verify_{time.strftime('%Y%m%d_%H%M%S')}.json")
    RES["checks"] = CHECKS
    RES["checks_pass"] = f"{sum(CHECKS.values())}/{len(CHECKS)}"
    json.dump(RES, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n" + "=" * 78)
    print(f"  判据通过: {RES['checks_pass']}\n  证据: {out}")
    print(f"  审计流水: {os.path.join(ROOT, 'reports', 'opt_capture_log.jsonl')}")
    return 0 if all(CHECKS.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
