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
    def _n_real_shots(path):
        """只数**真拍** (成功 capture_detect / fetch_grab); 失败记录不算。"""
        n = 0
        if os.path.isfile(path):
            for _l in open(path, encoding="utf-8"):
                try:
                    _d = json.loads(_l)
                except Exception:                                      # noqa: BLE001
                    continue
                if _d.get("action") in ("capture_detect", "fetch_grab") and str(_d.get("http")) == "200":
                    n += 1
        return n

    log_before = 0
    _lg = os.path.join(ROOT, "reports", "opt_capture_log.jsonl")
    log_before = _n_real_shots(_lg)
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
    _log_after = _n_real_shots(_lg)
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

    # ⑩b 定时器 tick 不得把切除结果冲掉 (老倪: "闪一下就变回坏图" = 500ms tick 重塞工厂图)
    _before = np.array_equal
    snap = w._last_rgb.copy()
    for _ in range(3):
        w._tick(); app.processEvents(); time.sleep(0.15)
    ck("⑩ 定时器 tick 不冲掉过曝切除结果 (跨 3 跳画面逐位不变)",
       np.array_equal(snap, w._last_rgb),
       f"shape {w._last_rgb.shape} · 与 tick 前逐位相同={bool(np.array_equal(snap, w._last_rgb))}")

    # ⑪ 手动框选拉伸 (老倪: "我鼠标拖出边界框圈出矩形, 你来将圈选矩形对应拉伸")
    good = [433, 948, 2056, 1074]          # 金手指条
    bad = [433, 640, 2056, 900]            # 过曝死白带
    w.cmb_src.setCurrentIndex(3)
    for _ in range(25):
        app.processEvents(); time.sleep(0.05)
    w.chk_roi_pick.setChecked(True)
    app.processEvents()
    w.wid_orig.add_box_px(good)            # 等价于用户拖出这个框
    for _ in range(20):
        app.processEvents(); time.sleep(0.05)
    m1 = dict(w._roi_meta)
    RES["roi_good"] = {"roi": w._manual_roi, "judge_shape": list(w._last_rgb.shape), "meta": m1,
                       "lbl": w.lbl_v_crop.text()}
    ck("⑪ 拖框 → 判据图 = 该矩形拉伸 (尺寸=任务头输入)",
       w._manual_roi == tuple(good) and list(w._last_rgb.shape[:2]) == [w.head.imgsz, w.head.imgsz],
       f"框 {w._manual_roi} → 判据图 {list(w._last_rgb.shape)}")
    ck("⑪ 好框: 框内饱和低 + 数字如实显示",
       m1.get("sat_in_rect", 1) < 0.15 and "框选拉伸" in w.lbl_v_crop.text(),
       f"框内饱和 {m1.get('sat_in_rect', 0)*100:.1f}% 死白行 {m1.get('deadwhite_rows_in_rect')} "
       f"Tenengrad {m1.get('tenengrad_in_rect')} · {w.lbl_v_crop.text()}")
    snap2 = w._last_rgb.copy()
    for _ in range(3):
        w._tick(); app.processEvents(); time.sleep(0.15)
    ck("⑪ 框选拉伸结果不被 tick 冲掉 (曾'闪一下变回坏图')", np.array_equal(snap2, w._last_rgb),
       f"tick 后仍为手选框拉伸结果={bool(np.array_equal(snap2, w._last_rgb))}")
    w.wid_orig.clear_boxes()
    w.wid_orig.add_box_px(bad)
    for _ in range(20):
        app.processEvents(); time.sleep(0.05)
    m2 = dict(w._roi_meta)
    RES["roi_bad"] = m2
    ck("⑪ 坏框(过曝带): 如实告警'拉伸后仍会一片白'",
       m2.get("sat_in_rect", 0) > 0.40 and "过曝" in str(m2.get("warning", "")),
       f"框内饱和 {m2.get('sat_in_rect', 0)*100:.1f}% · warning={m2.get('warning')}")
    w._on_roi_keep()
    app.processEvents()
    roi_file = os.path.join(ROOT, "reports", "aoi_roi.json")
    ck("⑪ 记住此框 → 落盘 ROI 文件", os.path.isfile(roi_file),
       f"{roi_file} → {open(roi_file, encoding='utf-8').read()[:90]}")
    w2 = aic.AoiInspectConsole(source="real")          # 新实例应读回记住的 ROI
    w2._timer.stop()
    ck("⑪ 新开窗口自动读回记住的 ROI", tuple(w2._manual_roi or ()) == tuple(bad), f"{w2._manual_roi}")
    w2.close()
    w._on_roi_clear()
    app.processEvents(); time.sleep(0.3)
    ck("⑪ 清除框 → ROI 清空 + 文件删除 (回到自动裁切)",
       w._manual_roi is None and not os.path.isfile(roi_file), f"roi={w._manual_roi}")
    w.close()


    # ⑧ UI 级断言 (不依赖工控机在线): 服务接口按钮 + 拍照时间 + 自动刷新
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import time as _t
    from PyQt5 import QtWidgets as _QW                                    # noqa: E402
    import aoi_inspect_console as _aic                                    # noqa: E402
    _app = _QW.QApplication.instance() or _QW.QApplication([])
    _w = _aic.AoiInspectConsole(source="real")
    _w._timer.stop(); _w.show()
    for _ in range(12):
        _app.processEvents()
    _want = ["capture_detect", "picture_origin", "picture_topview", "region", "crop_info",
             "last_result", "picture_meta"]
    _miss = [k for k in _want if k not in _w.api_btns]
    _bad = [k for k, b in _w.api_btns.items() if not (b.isVisible() and b.isEnabled())]
    _bad83 = [k for k, b in _w.api83_btns.items() if not (b.isVisible() and b.isEnabled())]
    RES["api_btns"] = {"n": len(_w.api_btns), "missing": _miss, "disabled": _bad,
                       "surface": list(_w.api83_btns.keys()), "bad_surface": _bad83}
    ck("⑧ 10082 七个接口按钮 + 10083 两个 全部可达 (点一下就能用)",
       not _miss and not _bad and not _bad83 and len(_w.api_btns) == 7, str(RES["api_btns"]))
    # 点一个只读接口: 无论工控机在不在线, 都必须**返回结果**(图或如实报错)而不崩
    _before_lines = len(_w.term_json.toPlainText().splitlines())
    _w.api_btns["crop_info"].click()
    for _ in range(30):
        _app.processEvents(); _t.sleep(0.1)
    _after_lines = len(_w.term_json.toPlainText().splitlines())
    _log_txt = _w.txt_log.toPlainText()
    RES["svc_click"] = {"lines_before": _before_lines, "lines_after": _after_lines,
                        "log_tail": _log_txt.strip().splitlines()[-1][:120]}
    ck("⑧ 服务按钮点一下就出结果 (JSON/curl 进终端页; 失败也如实记)",
       _after_lines > _before_lines, f"{_before_lines}→{_after_lines} · {RES['svc_click']['log_tail']}")
    # 拍照时间标签 (注入快照时间验证显示口径)
    _w._update_shot({"ms": 16, "http": "200", "bytes": 731000, "shape": [960, 960, 3]},
                    t=_t.time() - 3.2, action="真拍")
    _lbl = _w.lbl_shot.text()
    RES["shot_label"] = {"text": _lbl, "extra": _w.lbl_shot_extra.text()}
    ck("⑧ 拍照时间可见 (拍照 HH:MM:SS + 帧龄 + 取图耗时/码)",
       _lbl.startswith("拍照 ") and "s 前" in _lbl and "真拍" in _lbl and "16ms" in _w.lbl_shot_extra.text(),
       f"{_lbl} | {_w.lbl_shot_extra.text()}")
    # 自动刷新 开/关
    _w.chk_auto.setChecked(True)
    _app.processEvents(); _t.sleep(0.1)
    _on = _w._auto_timer.isActive()
    _w.chk_auto.setChecked(False)
    _app.processEvents(); _t.sleep(0.1)
    _off = _w._auto_timer.isActive()
    RES["auto_refresh"] = {"on": _on, "off": _off, "mode": _w.cmb_auto_mode.currentText()}
    ck("⑧ 自动刷新 开/关可控 (默认关)",
       _on and not _off, str(RES["auto_refresh"]))
    _w.close()

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
