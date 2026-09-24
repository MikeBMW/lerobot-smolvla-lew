# 补丁: 10083 表面相机加 `/picture` 路由 (交工控机侧) — 2026-09-24

## 为什么需要
现场要求「外观质量检测窗口能看**两台 OPT 相机**的图并标定/训练」。实测（`OPTIONS` 零副作用探路由）：

| 端口 | 相机 | 现有路由 | 能否取图 |
|---|---|---|---|
| 10082 | 金手指 OPT-CC1-GG50 (SN D265250070) | `/picture`(类/原图/抓帧) · `/crop_info` · `/region` · `/last_result` · `/capture_detect` | ✅ 能 |
| 10083 | 表面 OPT-CC1-C050-GG3-00 (SN D265250099) | **只有 `/capture_detect`** | ❌ **只能触发拍照, 拿不到图** |

⇒ 10083 那套 Flask（表面检测 AOI 程序）需要补一条**只读** `/picture` 路由，语义与 10082 **完全一致**，
这样 4060 侧的 `tools/opt_camera_client.py` 不改一行代码就能取到表面相机图。

## 补丁（直接粘进表面程序，约 30 行）

```python
# ── 加在文件顶部的全局区（若已存在 _LAST_PIC/_PIC_LOCK 则复用，不要重复定义）──
import time, os, traceback
from threading import Lock
from flask import request, jsonify, Response
_PIC_LOCK = globals().get("_PIC_LOCK") or Lock()
_LAST_PIC = globals().get("_LAST_PIC") or {}      # {"origin": path, "topview": path, "t": ts}
_TARGET_CROP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "surface_images")

# ── 在拍照函数里补两行（关键：把每次拍到的原图记进内存，供 /picture 取）──
#   现有写法类似:  image = camera_grab(); cv2.imwrite(path, image)
#   改成:
#        cv2.imwrite(path, image)
#        with _PIC_LOCK:
#            _LAST_PIC.update({"origin": path, "topview": path, "t": time.time()})
#   （表面相机无"规整拉长"需求 → topview 与 origin 同一条路径即可）

# ── 追加路由（与 10082 v3 逐字同语义）──
@app.route("/picture", methods=["GET", "POST"])
def picture_api():
    """读取当前照片: ?kind=topview|origin (默认 topview) · ?meta=1 返回 JSON 元数据 · ?grab=1 先抓一帧"""
    try:
        kind = (request.args.get("kind") or "topview").lower()
        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            o, tv = GrabAndSaveImage()               # ← 用你们现有的抓帧函数名
            if o is None and tv is None:
                return jsonify({"code": 500, "msg": "抓帧失败"}), 500
            with _PIC_LOCK:
                _LAST_PIC.update({"origin": o, "topview": tv or o, "t": time.time()})
        with _PIC_LOCK:
            snap = dict(_LAST_PIC)
        path = snap.get("origin") if kind == "origin" else snap.get("topview")
        if not path or not os.path.exists(path):
            return jsonify({"code": 404, "msg": "尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}), 404
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
    except Exception as e:
        traceback.print_exc()
        return jsonify({"code": 500, "msg": str(e)}), 500
```

## 上线与验证（现场 4 步）
1. **端口必须仍是 10083**（产线 HMI/PLC 打的就是它）；**同一台相机 SN D265250099 只能被一个进程打开**
   → 是"热替换"不是"并行跑"：先停旧进程（`netstat -ano | findstr :10083` + `taskkill /PID <pid> /F`），再起新版。
2. 起新版后先在工控机本机自测（**不拍照也能验**，零副作用）：
   `curl -X OPTIONS -D - -o NUL http://127.0.0.1:10083/picture` → 必须出现 `Allow: OPTIONS, HEAD, POST, GET`。
3. 自测取图：`curl -X POST http://127.0.0.1:10083/capture_detect` → 等 1s →
   `curl -o surface.png http://127.0.0.1:10083/picture?kind=topview` （文件应 >100KB 且不是 0 字节）。
4. 4060 侧验收（一条命令，只读+取图各一）：
   ```bash
   cd ~/lerobot-smolvla-lew && ./gui-venv311/bin/python tools/opt_camera_client.py --health          # 路由表应变 True
   ./gui-venv311/bin/python tools/opt_camera_client.py --cam 2 --grab --out /tmp/surface.png          # ⚠️ 真拍
   ```
   通过判据：`has_picture=True`、返回图 `shape` 正常、`mean_gray` 有内容（不是 <5 的黑帧）。

## 备注
- 4060 侧已就绪：`tools/opt_camera_client.py`（客户端）+ 外观质量检测窗口「源=🏭 OPT 相机 → 表面 10083」；
  10083 补齐前，窗口会如实提示"表面相机在工控机侧无 /picture 路由 → 只能触发拍照"，不伪造图。
- 若表面相机也想走"规整拉长"供 YOLO（与金手指同口径），在路由里给出 `topview` 独立路径即可（本补丁已预留）。
- 判决通道：10082 有 `/last_result`（已用于窗口"📋 工控机判决"）。10083 若要显示自家判决，同样可在
  检测 worker 里把最近结果存 `_LAST_RESULT` 并加一条 `/last_result` 路由（与 10082 一致）。
