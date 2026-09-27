# -*- coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════════════════════
#  粘到工控机那套「表面检测」程序里 (端口必须是 10083), 加一条只读取图路由
#  目的: 让 4060/Orin 能取到表面相机的图 (现在 10083 只有 POST /capture_detect, 取不到图)
#
#  怎么粘 (三步):
#    1. 把下面「① 全局区」那几行放到文件顶部的 import 区之后;
#    2. 找到你们拍照保存的地方(形如  img = camera_grab(); cv2.imwrite(path, img)),
#       在 cv2.imwrite 之后加「② 记一笔内存」那两行(函数里加, 不要放全局);
#    3. 把「③ 路由」整段贴到文件里其它 @app.route 旁边(缩进对齐顶层, 不要放进函数里)。
#
#  安全: 这条路由**只读内存里最近一张照片**, 不会自动拍照;
#        只有显式带 ?grab=1 才会抓一帧(和现在 POST /capture_detect 等价)。
#  自测(在工控机本机, 不拍照也能验):
#        curl -X OPTIONS -D - -o NUL http://127.0.0.1:10083/picture
#        → 必须出现 Allow: OPTIONS, HEAD, POST, GET
#  然后:  curl -X POST http://127.0.0.1:10083/capture_detect
#         curl -o surface.png "http://127.0.0.1:10083/picture?kind=topview"   # 应 >100KB
#  上完 4060 侧零改动: 工位总览那一格会自动出图(它每 4s 就在轮询取图)。
# ══════════════════════════════════════════════════════════════════════════════

# ── ① 全局区 (若已有 _LAST_PIC / _PIC_LOCK 就复用, 不要重复定义) ──────────────
import os
import time
import traceback
from threading import Lock

from flask import Response, jsonify, request

_PIC_LOCK = globals().get("_PIC_LOCK") or Lock()
_LAST_PIC = globals().get("_LAST_PIC") or {}      # {"origin": path, "topview": path, "t": ts}


# ── ② 记一笔内存 (放在你们 cv2.imwrite(path, img) 之后的同一函数里) ───────────
#        cv2.imwrite(path, img)
#        with _PIC_LOCK:
#            _LAST_PIC.update({"origin": path, "topview": path, "t": time.time()})


# ── ③ 路由 (贴到其它 @app.route 旁边; 语义与 10082 那套逐字一致) ─────────────
@app.route("/picture", methods=["GET", "POST"])
def picture_api():
    """读当前照片: ?kind=topview|origin (默认 topview) · ?meta=1 返回 JSON 元数据 · ?grab=1 先抓一帧"""
    try:
        kind = (request.args.get("kind") or "topview").lower()
        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():                       # ← 用你们现有的相机初始化函数名
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            o, tv = GrabAndSaveImage()                    # ← 用你们现有的抓帧函数名
            if o is None and tv is None:
                return jsonify({"code": 500, "msg": "抓帧失败"}), 500
            with _PIC_LOCK:
                _LAST_PIC.update({"origin": o, "topview": tv or o, "t": time.time()})
        with _PIC_LOCK:
            snap = dict(_LAST_PIC)
        path = snap.get("origin") if kind == "origin" else snap.get("topview")
        if not path or not os.path.exists(path):
            return jsonify({"code": 404,
                            "msg": "尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}), 404
        if request.args.get("meta") in ("1", "true", "yes"):
            return jsonify({"code": 200, "kind": kind, "file": os.path.basename(path),
                            "t": snap.get("t", 0), "size": os.path.getsize(path),
                            "origin": os.path.basename(snap.get("origin") or ""),
                            "topview": os.path.basename(snap.get("topview") or ""),
                            "last_result": globals().get("_LAST_RESULT", {})})
        with open(path, "rb") as fp:
            data = fp.read()
        mt = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        return Response(data, mimetype=mt, headers={"Cache-Control": "no-store"})
    except Exception as e:                                # noqa: BLE001
        traceback.print_exc()
        return jsonify({"code": 500, "msg": str(e)}), 500
