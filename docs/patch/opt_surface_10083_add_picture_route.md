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

---

## 追加: 曝光问题 (2026-09-24 老倪现场发现, 10082 金手指同样需要)

**症状 (真拍实测)**: 工控机给的拉伸图 `?kind=topview` **73% 是死白** —— y≥255 起逐行亮度恒在
238.5±0.5、饱和像素(≥250)占 **61.5%**、死白行 532/960、最差列饱和 **100%**, 细节能量 Tenengrad 仅 2300。
老倪原话: 「灰度信息丢失(过曝), 底线到 255 纯白, 明暗细节/纹理/衬度完全消失; 底部出现急剧亮度抬升
(Cliff edge), 不自然的强光边缘」。

**4060 侧已做的补救 (无需工控机改动, 已上线)**: 不用工厂拉伸图 → **从 `?kind=origin` 原始图自裁**:
切掉过曝带(sat>40% 的 213 行) + 左右死白列(裁到 x[433,2056]), 只保留金手指条 →
判据图实测 **饱和 61.5%→5.6%、死白行 532→0、最差列 100%→31.2%、Tenengrad 2300→29394 (×12.8)**。
代码: `tools/aoi_exposure_fix.py` (`clean_judge_frame`), 窗口勾选「过曝切除」(默认开)。

**建议工控机侧根治 (曝光/增益)**: 那套程序里已有 `set_exposure(exposure_us)` / `set_gain(gain_db)`
(或 config.yaml 的曝光项), 建议**降低曝光时间或增益**, 把金手指条内的饱和像素压下来。
验收判据 (4060 侧一条命令即可量):
```bash
cd ~/lerobot-smolvla-lew && ./gui-venv311/bin/python tools/aoi_exposure_fix.py <origin.png>
# 目标: 金手指条 sat ≤ 5%, 无任何列 sat > 60%, 且条内可分辨焊盘/间隙纹理
```
> 为什么不是"越小越好": 金面镜反光本身会有少量 255 (实测条内 5.6%), 属正常; 当前 35% 才叫过曝。
