#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_v5.py — 把 aoi_v4 的两个 v4 程序生成成 v5 (内存取图 + 按需落盘 + 保留上限)。

老倪 2026-09-27: 「不检测的时候, 不用保存那么多图片；升级到 v5。」
设计 (不改服务通道, 不改产线调用口径):
  · POST /capture_detect (真检测) —— 照旧落盘(模型要读文件), 但落盘后按保留上限清旧图;
  · GET /picture?grab=1 (只看一眼 / 我们页面的「拍帧」) —— **不落盘**, 图留在内存里直接回;
  · GET /picture (不带 grab) —— 优先回内存帧(不再读盘), 没有才回磁盘上最近一张;
  · 诊断图(标注图/legacy)默认不写, 要写设 AOI_SAVE_DEBUG=1;
  · 新增 GET /storage(用了多少/有多少张) 与 POST /prune(手动清);
  · 端口/路由/回执语义全部不变。
用法: python3 make_v5.py   (在 aoi_v4 目录下; 幂等: 已改过会跳过)
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

SHARED = '''

# ───────────────────── v5: 内存帧 + 按需落盘 + 保留上限 ─────────────────────
# 老倪 2026-09-27: 「不检测的时候, 不用保存那么多图片」⇒
#   · 只"看一眼/取图"(GET /picture?grab=1) 一律**不落盘**, 图只留内存(编码后几百 KB);
#   · 只有真检测(POST /capture_detect, 模型要读文件)才落盘, 落完按上限清旧图;
#   · 诊断用的额外图(标注图/legacy)默认不写, 要写设 AOI_SAVE_DEBUG=1;
#   · GET /storage 看占用/张数, POST /prune 手动清。
AOI_SAVE_DEBUG = os.environ.get("AOI_SAVE_DEBUG", "0").strip().lower() in ("1", "true", "yes")
KEEP_CANON = int(os.environ.get("AOI_KEEP_CANON", "400"))
KEEP_ORIGIN = int(os.environ.get("AOI_KEEP_ORIGIN", "120"))
_MEM = {"crop": None, "origin": None, "natural": None, "ts": 0.0}
_MEM_LOCK = threading.Lock()
_TL = threading.local()          # 每次抓帧的落盘开关(线程安全: /capture_detect 与 /picture?grab=1 可能并发)


def _enc_jpg(bgr, quality=90):
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else b""


def _mem_put(crop=None, origin=None, natural=None):
    """把当前这帧编码进内存 (取图走内存, 磁盘就不需要那么多文件)。"""
    with _MEM_LOCK:
        if crop is not None:
            _MEM["crop"] = _enc_jpg(crop, 92)
        if origin is not None:
            _MEM["origin"] = _enc_jpg(origin, 88)
        if natural is not None:
            _MEM["natural"] = _enc_jpg(natural, 92)
        _MEM["ts"] = time.time()


def _mem_get(kind, t0=0.0):
    """取内存帧: kind=origin/raw 要原图, 其余要规范图; 没有就退回另一张。"""
    with _MEM_LOCK:
        b = _MEM.get(kind) or _MEM.get("crop") or _MEM.get("origin")
        ts = _MEM.get("ts", 0.0)
    return b, ts


def _iw(path, img, *a, **kw):
    """落盘开关: 只有真检测(或 AOI_SAVE_DEBUG 下的诊断图)才写盘。"""
    save = getattr(_TL, "save", True)
    p = str(path)
    if save or (AOI_SAVE_DEBUG and ("Anno" in p or "Legacy" in p)):
        return cv2.imwrite(path, img, *a, **kw)
    return True


def _prune_dir(patterns=None):
    """按保留上限删最旧的图; patterns=[(glob, keep_n), ...] (keep_n=0 表示这类全清)。"""
    patterns = patterns if patterns is not None else _PRUNE_PATTERNS
    removed = 0
    for pat, keep in patterns:
        try:
            files = sorted(glob.glob(os.path.join(SAVE_ROOT_DIR, pat)), key=os.path.getmtime)
        except OSError:
            continue
        if keep >= 0 and len(files) > keep:
            for f in files[:len(files) - keep]:
                try:
                    os.remove(f)
                    removed += 1
                except OSError:
                    pass
    return removed


def _dir_stat():
    out = {"dir": os.path.abspath(SAVE_ROOT_DIR), "groups": {}}
    total = n_total = 0
    for pat, keep in _PRUNE_PATTERNS:
        files = glob.glob(os.path.join(SAVE_ROOT_DIR, pat))
        sz = 0
        for f in files:
            try:
                sz += os.path.getsize(f)
            except OSError:
                pass
        out["groups"][pat] = {"count": len(files), "mb": round(sz / 1048576.0, 1), "keep": keep}
        total += sz
        n_total += len(files)
    out["files_total"] = n_total
    out["mb_total"] = round(total / 1048576.0, 1)
    out["save_debug"] = AOI_SAVE_DEBUG
    return out
'''

STORAGE_ROUTES = '''

@app.route("/storage", methods=["GET"])
def storage_api():
    """看存了多少图 / 占多少磁盘, 以及保留上限 (老倪: 不检测时别存那么多)。"""
    try:
        d = _dir_stat()
        d["code"] = 200
        d["keep_canon"] = KEEP_CANON
        d["keep_origin"] = KEEP_ORIGIN
        d["mem"] = {"crop_kb": round(len(_MEM.get("crop") or b"") / 1024.0, 1),
                    "origin_kb": round(len(_MEM.get("origin") or b"") / 1024.0, 1),
                    "age_s": round(time.time() - (_MEM.get("ts") or 0), 1)}
        return jsonify(d)
    except Exception as e:                                                    # noqa: BLE001
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/prune", methods=["POST", "GET"])
def prune_api():
    """清旧图: POST 真删(按保留上限), GET 只报告会删多少(不删)。"""
    try:
        before = _dir_stat()
        if request.method == "GET":
            return jsonify({"code": 200, "dry": True, "before": before})
        n = _prune_dir()
        after = _dir_stat()
        print("  【清理】删除 %d 张旧图; 现在 %d 张 / %.1fMB" % (n, after["files_total"], after["mb_total"]))
        return jsonify({"code": 200, "removed": n, "before": before, "after": after})
    except Exception as e:                                                    # noqa: BLE001
        return jsonify({"code": 500, "msg": str(e)}), 500
'''


def patch_surface(path):
    s = open(path, encoding="utf-8").read()
    if "_mem_put(" in s:
        print("  跳过(已是 v5): %s" % path)
        return False
    # 1) 版本号
    assert 'VERSION = "v4"' in s, "surface: 找不到 VERSION"
    s = s.replace('VERSION = "v4"', 'VERSION = "v5"', 1)
    s = s.replace('"""Z-MAX 表面检测 AOI 程序 · 优化版 v4 (端口 10083)',
                  '"""Z-MAX 表面检测 AOI 程序 · 优化版 v5 (端口 10083)', 1)
    # 2) 内存/落盘/清理 基础设施 (插在 _LAST_PIC 之后)
    anchor = '_LAST_PIC = {"origin": None, "topview": None, "t": 0.0}\n'
    assert anchor in s, "surface: 找不到 _LAST_PIC"
    s = s.replace(anchor, anchor + SHARED, 1)
    # 3) 保留上限的分组
    s = s.replace('SAVE_ROOT_DIR = r"./surface_images"',
                  'SAVE_ROOT_DIR = r"./surface_images"\n'
                  '_PRUNE_PATTERNS = [("Surface_Letterbox_W*_No_*.png", KEEP_CANON),\n'
                  '                   ("Surface_Image_W*_No_*.png", KEEP_ORIGIN)]', 1)
    # 4) GrabAndSaveImage: 加 save 开关 + 内存帧
    assert "def GrabAndSaveImage():" in s, "surface: 找不到 GrabAndSaveImage"
    s = s.replace("def GrabAndSaveImage():", "def GrabAndSaveImage(save: bool = True):", 1)
    s = s.replace('''    """抓一帧 → 存原图 + 规范图(letterbox1280) → 返回 (origin_path, topview_path)"""
    global global_img_count''',
                  '''    """抓一帧 → 规范图(letterbox1280) + 原图 → 返回 (origin_path, topview_path)。

    v5: 图**总是**进内存(取图走内存); `save=True`(真检测)才落盘, `save=False`(只看一眼)不落盘。
    """
    global global_img_count
    _TL.save = bool(save)''', 1)
    s = s.replace('    canvas, ratio, off = letterbox_square(bgr)',
                  '    canvas, ratio, off = letterbox_square(bgr)\n'
                  '    _mem_put(crop=canvas, origin=bgr)          # v5: 内存帧(取图不用读盘)', 1)
    # 5) 落盘走 _iw (受 _TL.save 控制)
    s = s.replace("cv2.imwrite(topview_path, canvas)", "_iw(topview_path, canvas)")
    s = s.replace("cv2.imwrite(origin_path, bgr)", "_iw(origin_path, bgr)")
    # 6) /capture_detect: 明确 save=True 并在投递后清旧图
    s = s.replace("        o, tv = GrabAndSaveImage()\n        if o is None or tv is None:\n"
                  "            print(\"⚠️ 抓帧失败, 重连相机后重试…\")",
                  "        o, tv = GrabAndSaveImage(save=True)      # 真检测: 落盘(模型要读文件)\n"
                  "        if o is None or tv is None:\n"
                  "            print(\"⚠️ 抓帧失败, 重连相机后重试…\")", 1)
    s = s.replace("        _enqueue_detect(tv, o, detect_type)",
                  "        _enqueue_detect(tv, o, detect_type)\n"
                  "        _prune_dir()                             # v5: 按保留上限清旧图(不检测时不再堆图)", 1)
    # 7) /picture: grab 默认不落盘 + 优先回内存帧
    s = s.replace('''        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            o, tv = GrabAndSaveImage()''',
                  '''        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            # v5: 取图默认**不落盘**(加 &save=1 才写盘) —— 不检测时不再堆图
            _sv = str(request.args.get("save", "")).lower() in ("1", "true", "yes")
            o, tv = GrabAndSaveImage(save=_sv)''', 1)
    s = s.replace('''        if request.args.get("meta") in ("1", "true", "yes"):
            return jsonify({"code": 200, "kind": kind, "file": os.path.basename(path),''',
                  '''        mem, mts = _mem_get(kind)
        if mem and not request.args.get("file"):
            return Response(mem, mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store",
                                     "X-Frame-Source": "memory", "X-Frame-Age-S": "%.3f" % (time.time() - mts)})
        if request.args.get("meta") in ("1", "true", "yes"):
            return jsonify({"code": 200, "kind": kind, "file": os.path.basename(path),''', 1)
    # 8) /storage + /prune (插在启动段之前)
    anchor2 = "# ───────────────────────── 启动 ─────────────────────────"
    assert anchor2 in s, "surface: 找不到启动段"
    s = s.replace(anchor2, STORAGE_ROUTES.strip() + "\n\n\n" + anchor2, 1)
    # 9) 头部说明补一段 v5
    s = s.replace("相对 V2 的升级点 (把金手指 v4 的成熟做法搬到表面通道):",
                  "v5 相对 v4: 取图走**内存**(GET /picture 不再读盘) · GET /picture?grab=1 默认**不落盘**\n"
                  "  (要存加 &save=1) · 真检测才落盘且按上限清旧图(AOI_KEEP_CANON/AOI_KEEP_ORIGIN) ·\n"
                  "  诊断图默认不写(AOI_SAVE_DEBUG=1 才写) · 新增 GET /storage 与 POST /prune。\n\n"
                  "相对 V2 的升级点 (把金手指 v4 的成熟做法搬到表面通道):", 1)
    open(path, "w", encoding="utf-8").write(s)
    print("  已生成 v5: %s (%d 字节)" % (path, len(s)))
    return True


def patch_finger(path):
    s = open(path, encoding="utf-8").read()
    if "_mem_put(" in s:
        print("  跳过(已是 v5): %s" % path)
        return False
    s = s.replace('VERSION = "v4"', 'VERSION = "v5"', 1)
    anchor = '_LAST_PIC = {"origin": None, "topview": None, "t": 0.0}\n'
    assert anchor in s, "finger: 找不到 _LAST_PIC"
    s = s.replace(anchor, anchor + SHARED, 1)
    s = s.replace('SAVE_ROOT_DIR = r"./goldfinger_images"',
                  'SAVE_ROOT_DIR = r"./goldfinger_images"\n'
                  '_PRUNE_PATTERNS = [("Finger_TopView_W*_H*_No_*.png", KEEP_CANON),\n'
                  '                   ("Finger_Image_W*_H*_No_*.png", KEEP_ORIGIN),\n'
                  '                   ("Finger_CropNatural_W*_No_*.png", KEEP_CANON),\n'
                  '                   ("Finger_CropAnno_No_*.png", KEEP_ORIGIN if AOI_SAVE_DEBUG else 0),\n'
                  '                   ("Legacy_TopView_No_*.png", KEEP_ORIGIN if AOI_SAVE_DEBUG else 0)]', 1)
    assert "def GrabAndSaveImage():" in s, "finger: 找不到 GrabAndSaveImage"
    s = s.replace("def GrabAndSaveImage():", "def GrabAndSaveImage(save: bool = True):", 1)
    s = s.replace('''    """抓一帧 → 存原图 → 模板法规整裁剪 → 存裁剪图 + 标注图(取证)"""
    global global_img_count''',
                  '''    """抓一帧 → 原图 → 模板法规整裁剪 → 裁剪图(+标注图取证)。

    v5: 图**总是**进内存(取图走内存); `save=True`(真检测)才落盘, `save=False`(只看一眼)不落盘。
    """
    global global_img_count
    _TL.save = bool(save)''', 1)
    # 内存帧: 在裁剪出 crop 之后
    s = s.replace('''            q = info.get("quality", {}) or {}''',
                  '''            q = info.get("quality", {}) or {}
            _mem_put(crop=crop, origin=bgr, natural=_LAST_NATURAL)   # v5: 内存帧''', 1)
    # 落盘全部改走 _iw
    n_iw = s.count("cv2.imwrite(")
    s = s.replace("cv2.imwrite(", "_iw(")
    # /capture_detect
    s = s.replace("""            o, tv = GrabAndSaveImage()""",
                  """            o, tv = GrabAndSaveImage(save=True)      # 真检测: 落盘(模型要读文件)""", 1)
    s = s.replace("""            _enqueue_detect(""", """            _prune_dir()                             # v5: 按保留上限清旧图
            _enqueue_detect(""", 1)
    # /picture: grab 默认不落盘 + 内存优先
    s = s.replace('''        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            o, tv = GrabAndSaveImage()''',
                  '''        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            # v5: 取图默认**不落盘**(加 &save=1 才写盘)
            _sv = str(request.args.get("save", "")).lower() in ("1", "true", "yes")
            o, tv = GrabAndSaveImage(save=_sv)''', 1)
    s = s.replace('''        if request.args.get("meta") in ("1", "true", "yes"):
            return jsonify({"code": 200, "kind": kind, "file": os.path.basename(path),''',
                  '''        mem, mts = _mem_get(kind)
        if mem and not request.args.get("file"):
            return Response(mem, mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store",
                                     "X-Frame-Source": "memory", "X-Frame-Age-S": "%.3f" % (time.time() - mts)})
        if request.args.get("meta") in ("1", "true", "yes"):
            return jsonify({"code": 200, "kind": kind, "file": os.path.basename(path),''', 1)
    anchor2 = "# ───────────────────────── 启动 ─────────────────────────"
    if anchor2 not in s:
        anchor2 = "def main("
    s = s.replace(anchor2, STORAGE_ROUTES.strip() + "\n\n\n" + anchor2, 1)
    open(path, "w", encoding="utf-8").write(s)
    print("  已生成 v5: %s (%d 字节, cv2.imwrite→_iw %d 处)" % (path, len(s), n_iw))
    return True


if __name__ == "__main__":
    ok = True
    for f, fn in (("surface_10083_work_v5.py", patch_surface),
                  ("cam_finger_10082_work_v5.py", patch_finger)):
        p = os.path.join(HERE, f)
        if not os.path.exists(p):
            print("缺文件: %s" % p)
            ok = False
            continue
        try:
            fn(p)
        except AssertionError as e:
            print("❌ %s: %s" % (f, e))
            ok = False
    sys.exit(0 if ok else 1)
