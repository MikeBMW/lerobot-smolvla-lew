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

    # ── ⑥ 窗口级断言 (不需真拍: 用相机的最近一张图) ──
    # ⑥ 窗口"选相机源即显示该相机实际图" (离线 GUI 断言; 只取最近图, **不拍照**)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import cv2                                                       # noqa: E402
    from PyQt5 import QtWidgets                                      # noqa: E402
    import aoi_inspect_console as aic                                # noqa: E402
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    log_before = 0
    _lg = os.path.join(ROOT, "reports", "opt_capture_log.jsonl")
    if os.path.isfile(_lg):
        log_before = sum(1 for _ in open(_lg, encoding="utf-8"))
    w = aic.AoiInspectConsole(source="real")
    w._timer.stop()
    w.cmb_src.setCurrentIndex(3)                                     # 📷 10082 金手指
    for _ in range(25):
        app.processEvents(); time.sleep(0.05)
    r1 = w._opt_rgb
    std = float(cv2.cvtColor(r1, cv2.COLOR_RGB2GRAY).std()) if r1 is not None else 0.0
    RES["gui_src_10082"] = {"tag": w._opt_tag, "std": round(std, 1),
                            "meta_keys": sorted(w._opt_meta.keys())[:8]}
    ck("⑥ 选『📷 10082 金手指』即显示该相机实际图", r1 is not None and std > 8 and "金手指" in w._opt_tag,
       f"tag={w._opt_tag} std={std:.1f}")
    # 原始图同屏 (老倪: "原始图片也要有显示")
    o = w._orig_rgb
    ost = float(cv2.cvtColor(o, cv2.COLOR_RGB2GRAY).std()) if o is not None else 0.0
    RES["gui_orig"] = {"shape": list(o.shape) if o is not None else None, "std": round(ost, 1),
                       "lbl_orig": w.lbl_v_orig.text(), "lbl_crop": w.lbl_v_crop.text()}
    ck("⑥ 同屏显示原始图 (2048x2448 有结构)", o is not None and list(o.shape)[:2] == [2048, 2448] and ost > 8,
       f"shape={list(o.shape) if o is not None else None} std={ost:.1f} · {w.lbl_v_orig.text()}")
    ck("⑥ 两幅画面都有帧 + 尺寸标注", w.wid_orig.frame_rgb() is not None and w.wid.frame_rgb() is not None
       and "原始图" in w.lbl_v_orig.text() and "判据图" in w.lbl_v_crop.text(),
       f"orig='{w.lbl_v_orig.text()}' crop='{w.lbl_v_crop.text()}'")
    # 标定基准可切 (可编辑只开在选中画面)
    w.chk_label.setChecked(True)
    w.rb_basis_orig.setChecked(True)
    app.processEvents()
    orig_ed, crop_ed = w.wid_orig._editable, w.wid._editable
    w.rb_basis_crop.setChecked(True)
    app.processEvents()
    ck("⑥ 标定基准可切到原始图 (可编辑只开在选中画面)",
       orig_ed is True and crop_ed is False and w.wid_orig._editable is False and w.wid._editable is True,
       f"基准=原始图: orig_ed={orig_ed} crop_ed={crop_ed} → 切回判据图后 orig={w.wid_orig._editable} crop={w.wid._editable}")
    w.cmb_src.setCurrentIndex(4)                                     # 📷 10083 表面
    for _ in range(25):
        app.processEvents(); time.sleep(0.05)
    RES["gui_src_10083"] = {"rgb_is_none": w._opt_rgb is None, "meta": w._opt_meta}
    ck("⑥ 选『📷 10083 表面』如实报缺口 (不伪造图)",
       w._opt_rgb is None and "picture" in str(w._opt_meta.get("err", "")),
       str(w._opt_meta.get("err"))[:80])
    _log_after = sum(1 for _ in open(_lg, encoding="utf-8")) if os.path.isfile(_lg) else 0
    ck("⑥ 切源取图**不新增真拍** (审计流水未增长)", _log_after == log_before,
       f"{log_before} → {_log_after}")

    # ⑦ curl 命令可见 + 可复制 (老倪: "把 curl 命令显示在窗口, 可以复制后在 4060 终端执行")
    w.cmb_src.setCurrentIndex(3)
    for _ in range(25):
        app.processEvents(); time.sleep(0.05)
    txt = w.term_cmd.toPlainText().strip()
    last = txt.splitlines()[-1] if txt else ""
    RES["term_cmd"] = {"n_lines": len(txt.splitlines()), "last": last,
                       "json_lines": len(w.term_json.toPlainText().splitlines())}
    ck("⑦ 窗口显示 curl 命令 (含目标 URL, 可直接执行)",
       last.startswith("curl ") and "192.168.23.23" in last and "10082" in last, last[:110])
    w._copy_text(w.term_cmd)
    app.processEvents()
    cb = QtWidgets.QApplication.clipboard().text()
    ck("⑦ 复制命令 → 剪贴板内容与命令框一致", cb.strip() == txt, f"剪贴板 {len(cb)} 字符")
    jtxt = w.term_json.toPlainText()
    ck("⑦ 终端有服务反馈 JSON 原文", "http" in jtxt and "{" in jtxt,
       f"{len(jtxt.splitlines())} 行; 片段: {jtxt.strip().splitlines()[-1][:90]}")
    w._copy_text(w.term_json)
    app.processEvents()
    ck("⑦ 复制反馈 → 剪贴板拿到 JSON", len(QtWidgets.QApplication.clipboard().text()) > 20)

    # ⑧ 每个技能"点击即可执行得到结果"
    skill_res = {}
    for k in ("gold_finger", "module_body", "optical_port", "full"):
        w.skill_btns[k].click()
        app.processEvents(); time.sleep(0.05)
        skill_res[k] = {"rows": w.tbl_verdict.rowCount(), "has_res": w._last_res is not None}
    j_before = len(w.term_json.toPlainText())
    svc = {}
    for name, b in (("crop_info", w.btn_opt_crop), ("region", w.btn_opt_region),
                    ("pic_meta", w.btn_opt_meta), ("last_result", w.btn_opt_verd),
                    ("fetch_recent", w.btn_opt_recent)):
        b.click()
        app.processEvents(); time.sleep(0.35)
        svc[name] = len(w.term_json.toPlainText()) > j_before
        j_before = len(w.term_json.toPlainText())
    RES["skill_click"] = {"inference": skill_res, "service": svc}
    ck("⑧ 四个推理技能点击即出判决表", all(v["rows"] > 0 and v["has_res"] for v in skill_res.values()),
       str({k: v["rows"] for k, v in skill_res.items()}))
    ck("⑧ 五个服务技能点击即得 JSON 反馈", all(svc.values()), str(svc))

    # ⑨ 图片右键可复制到剪贴板 (老倪: "显示的图片, 右键即可复制, 可粘贴到别的地方")
    from aoi_inspect_console import CopyImageView                    # noqa: E402
    from yolo_label_widget import YoloLabelWidget                    # noqa: E402
    w.cmb_src.setCurrentIndex(3)
    for _ in range(25):
        app.processEvents(); time.sleep(0.05)
    ok_copy = w.wid.copy_image()
    app.processEvents()
    img = QtWidgets.QApplication.clipboard().image()
    ok_o = w.wid_orig.copy_image()
    app.processEvents()
    img_o = QtWidgets.QApplication.clipboard().image()
    RES["img_copy"] = {"crop": [img.width(), img.height()], "orig": [img_o.width(), img_o.height()],
                       "has_ctxmenu": CopyImageView.contextMenuEvent is not YoloLabelWidget.contextMenuEvent,
                       "widgets": [type(w.wid).__name__, type(w.wid_orig).__name__],
                       "crop_path": w.wid._path, "orig_path": w.wid_orig._path}
    ck("⑨ 判据图右键复制 → 剪贴板拿到同尺寸图", ok_copy and img.width() == w._last_rgb.shape[1]
       and img.height() == w._last_rgb.shape[0], f"{img.width()}x{img.height()}")
    ck("⑨ 原始图右键复制 → 剪贴板拿到 2448x2048",
       ok_o and img_o.width() == 2448 and img_o.height() == 2048, f"{img_o.width()}x{img_o.height()}")
    ck("⑨ 两幅画面都装了右键复制菜单 (非编辑态不误删框)",
       isinstance(w.wid, CopyImageView) and isinstance(w.wid_orig, CopyImageView)
       and RES["img_copy"]["has_ctxmenu"], str(RES["img_copy"]["widgets"]))
    ck("⑨ 画面有本地副本路径 (可复制路径贴到别处)",
       bool(w.wid._path) and os.path.isfile(w.wid._path) and os.path.isfile(w.wid_orig._path),
       f"{w.wid._path} | {w.wid_orig._path}")

    # ⑩ 过曝切除 (老倪: "要把原始图过曝光的部分去掉")
    def _img_stats(rgb):
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        ten = float((cv2.Sobel(g, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(g, cv2.CV_32F, 0, 1) ** 2).mean())
        return {"sat_pct": round(float((g >= 250).mean() * 100), 1),
                "deadwhite_rows": int((g.mean(axis=1) > 235).sum()),
                "row_var": round(float(g.mean(axis=1).std()), 1),
                "worst_col_sat_pct": round(float(((g >= 250).mean(axis=0)).max() * 100), 1),
                "tenengrad": round(ten, 0)}

    w.cmb_src.setCurrentIndex(3)
    for _ in range(25):
        app.processEvents(); time.sleep(0.05)
    w.chk_expfix.setChecked(False)
    app.processEvents(); time.sleep(0.6)
    raw_top = w._last_rgb
    w.chk_expfix.setChecked(True)
    app.processEvents(); time.sleep(0.8)
    fixed = w._last_rgb
    s_raw, s_fix = _img_stats(raw_top), _img_stats(fixed)
    RES["expfix"] = {"raw_factory_topview": s_raw, "after_crop": s_fix, "meta": w._expfix_meta}
    ck("⑩ 切除前(工厂拉伸图)确认过曝: 死白行>0 且饱和>40%",
       s_raw["deadwhite_rows"] > 0 and s_raw["sat_pct"] > 40, str(s_raw))
    ck("⑩ 切除后: 死白行=0 且饱和<15% 且细节能量显著提升",
       s_fix["deadwhite_rows"] == 0 and s_fix["sat_pct"] < 15
       and s_fix["tenengrad"] > max(3000, s_raw["tenengrad"] * 2),
       f"{s_raw} → {s_fix}")
    ck("⑩ 左右死白列也切了 (最差列饱和从 100% 降下来)",
       s_raw["worst_col_sat_pct"] > 90 and s_fix["worst_col_sat_pct"] < 60,
       f"最差列饱和 {s_raw['worst_col_sat_pct']}% → {s_fix['worst_col_sat_pct']}%")
    ck("⑩ 切除台账 (裁掉多少行/列 + cliff 位置) 如实记录",
       bool(w._expfix_meta.get("ok")) and w._expfix_meta.get("dropped_sat_rows", 0) > 0
       and w._expfix_meta.get("cliff", {}).get("y", -1) >= 0,
       f"裁掉 {w._expfix_meta.get('dropped_sat_rows')} 行 · 保留 {w._expfix_meta.get('kept_rows')} · "
       f"列裁 {w._expfix_meta.get('x_trim')} · cliff y={w._expfix_meta.get('cliff', {}).get('y')}")
    w.close()

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
