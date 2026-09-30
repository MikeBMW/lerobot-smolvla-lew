#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""box3d_live_box.py — **实时**: 真机 YOLO 2D 框 → 3D 边界框 (中心 + 姿态 + 尺寸 + 8 角点)

老倪 2026-09-18 晚: 「镜头里已经有一个光模块, YOLO 也检测出了。完善策略: 如何根据当前的
                 光模块 2D 检测, 推算出 3D 边界框。」

链路 (每一环都是真数据, 没有仿真白送的几何):
  Orin 只读落盘  ~/zmax_ss_remote/cam_rs.png   ← D405 彩色 640x480 (与 L2 旁路同源)
  Orin 只读落盘  state_YYYYMMDD.jsonl          ← 同一行的 tcp/tcp_quat (编码器 50Hz, base_link)
                  ↑ 用**同一行**取 (tcp, quat, image) → 天然同刻配对, 不是"读最新两文件"那种错配
  YOLO 在役权重  models/yolo_peg_live.pt       ← 真机域微调 (单类 peg = 光模块)
  → Box3DSolver.predict_box3d(框, tcp, quat)   ← 自监督标定的相机模型 P + 夹持偏移 off
  → 3D 边界框: center / R / size / corners8 / 反投影框自检 IoU / σ / gaps

三档 (策略的核心: 有多少信息就说多少话):
  ① 夹持态 + 已标定 (最准)  中心 = TCP + R(q)·off (FK 锚定), 姿态 = R(q)·R_rel, 反投影自检
  ② 非夹持态 + 已标定      框跨度 + 姿态 → 反解投影模型定距离 → 视线求交 (σ ∝ 距离²)
  ③ 未标定 / 无位姿        诚实降级: 只给 FK 锚定框并写清缺什么, 或直接拒绝出 3D (宁缺勿假)

用法:
  gui-venv311/bin/python tools/box3d_live_box.py                       # 单帧出一次 3D 框 (现场看一眼)
  ... --loop --interval 0.5 --collect                                  # 常驻: 攒数据 + 自监督标定 + 出框
  ... --json ~/zmax_data/box3d_live_box.json --log                     # 落盘 + 逐帧打印
  ... --min-conf 0.35 --imgsz 640
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "src", "lerobot", "policies", "yolo_3d"))
from box3d_solver import Box3DSolver, iou_2d                                  # noqa: E402

REMOTE = os.environ.get("ZMAX_SS_REMOTE_DIR", os.path.expanduser("~/zmax_ss_remote"))
OUTDIR = os.path.expanduser(os.environ.get("ZMAX_BOX3D_DIR", "~/zmax_data"))
STATE = os.path.join(_REPO, "models", "box3d_state.json")
OBS_LOG = os.path.join(OUTDIR, "box3d_live_obs.jsonl")
LIVE_JSON = os.path.join(OUTDIR, "box3d_live_box.json")
WEIGHTS = os.environ.get("SS_YOLO_WEIGHTS") or os.path.join(_REPO, "models", "yolo_peg_live.pt")
IMG_WH = (640, 480)


# ───────────────────────── 同刻配对: 一行的 tcp + 该行落盘的图 ─────────────────────────
def newest_state_line(max_age_s=3.0):
    """最新旁路真值行 (含 tcp/tcp_quat + image{t,age,path}); 返回 (dict, 帧龄s) 或 (None, why)"""
    files = sorted(glob.glob(os.path.join(REMOTE, "state_*.jsonl")), key=os.path.getmtime)
    if not files:
        return None, f"{REMOTE} 下没有 state_*.jsonl (Orin 旁路没在落盘?)"
    path = files[-1]
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 40000))
            tail = f.read().decode("utf-8", "ignore").strip().split("\n")
    except Exception as e:                                                     # noqa: BLE001
        return None, f"读 {path} 失败: {e}"
    for ln in reversed(tail):
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except Exception:                                                      # noqa: BLE001
            continue
        if d.get("tcp") and d.get("tcp_quat"):
            age = time.time() - float(d.get("t", 0))
            if age > max_age_s:
                return None, f"最新行已经 {age:.1f}s 前 (旁路停了?) — file={os.path.basename(path)}"
            return d, age
    return None, f"{os.path.basename(path)} 尾部没有可用行"


def frame_for(state_line):
    """把旁路行里记的图路径映射到本机文件 + 帧龄"""
    p = ((state_line.get("image") or {}).get("path") or "").split("/")[-1]
    if not p:
        return None, None, "旁路行里没有 image.path"
    fp = os.path.join(REMOTE, p)
    if not os.path.exists(fp):
        return None, None, f"帧文件不存在: {fp}"
    age = time.time() - os.path.getmtime(fp)
    img_age = ((state_line.get("image") or {}).get("age"))
    return fp, age, (f"行内 image.age={img_age}" if img_age is not None else "")


def detect(frame_path, conf, imgsz, weights=WEIGHTS):
    """YOLO 在役权重 → 最大 conf 的 光模块 框 (BGR: ultralytics 吃 BGR, 2026-08-07 实测坑)"""
    import cv2
    from PIL import Image
    from ultralytics import YOLO
    img = np.array(Image.open(frame_path).convert("RGB"))
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    m = _MODELS.setdefault(weights, YOLO(weights))
    r = m.predict(bgr, imgsz=int(imgsz), conf=float(conf), verbose=False)[0]
    best = None
    for b in r.boxes:
        nm = r.names[int(b.cls[0])]
        if str(nm).lower() not in ("peg", "光模块", "optical_module"):
            continue
        c = float(b.conf[0])
        xy = [float(v) for v in b.xyxy[0].tolist()]
        if best is None or c > best[1]:
            best = (xy, c, nm)
    if best is None:
        return None, None, None, img.shape[:2]
    return best[0], best[1], best[2], img.shape[:2]


_MODELS = {}


# ───────────────────────── 解算器 (载入已标定状态 / 新建并攒数据) ─────────────────────────
CALIB = os.path.join(_REPO, "models", "real_cam_calib.json")


def load_K():
    """真机内参 (出厂标定, 由 tools/calib_fetch_realsense_intrinsics.py 从
    /realsense/color/camera_info 落进 models/real_cam_calib.json)。
    有 K → 拟合只解手眼 (米制锚定); 没有 → 退回 11 自由度投影 P。"""
    try:
        d = json.load(open(CALIB, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return None, None
    K = d.get("K")
    return (np.asarray(K, float).reshape(3, 3) if K else None), d


def ensure_solver(log=False):
    K, calib = load_K()
    st = Box3DSolver.load(STATE) if os.path.exists(STATE) else None
    if st is not None and st.fitted:
        if st.K is None and K is not None:
            st.K = K                        # 旧状态没有 K → 补上 (下次拟合就用米制手眼模式)
        if log:
            print(f"📐 解算器: 载入已标定 {STATE} (off={[round(float(v)*1000,1) for v in st.off]}mm · "
                  f"留出 {st.holdout_px}px · 尺寸 {[round(s*1000,1) for s in st.size]}mm/{st.size_src}"
                  f" · 内参={'已知' if st.K is not None else '未知'})")
        return st
    size_mm = [float(v) for v in os.environ.get("SS_BOX3D_SIZE_MM", "40,16,12").split(",")]
    fo = os.environ.get("SS_BOX3D_FIX_OFF_MM")
    fix = [float(v) / 1000.0 for v in fo.split(",")] if fo else None
    if log:
        print(f"📐 解算器: 新建 (未标定) → 收 (框, TCP位姿) 攒到 ≥10 帧不同位姿自动自监督标定 "
              f"(尺寸先按 {size_mm}mm{', 工具零点已知只解P' if fix else ''}"
              f" · 内参{'已知 (fx=%.1f)' % K[0, 0] if K is not None else '未知 → 解 11 自由度投影 P'})")
    return Box3DSolver(size_mm=size_mm, img_wh=IMG_WH, fix_off=fix, K=K)


def try_fit(slv, log=True, min_holdout_iou=0.45, max_holdout_px=3.0):
    """自监督拟合 + **前提自证** (残差/留出 IoU 只在『中心=TCP+R·off』成立时才可能这么好)

    未知量按 2026-09-18 可辨识性实验的结论取:
      · **R_rel 必估** (夹持歪斜不建模 → off 被吸收, 中心实测偏 76mm)
      · **尺寸不联合解** (尺寸自由会和 off/R_rel 退化: 实测中心偏 65mm; 尺寸必须来自图纸/一次量测)
      · 有内参 K 时只解手眼 (米制锚定, 最稳)
    """
    div = slv.diversity()
    if not div["ok"]:
        return {"ok": False, "why": div["why"], "diversity": div}
    res = slv.fit(use_rrel=True, use_scale=(slv.K is None))
    if not res.get("ok"):
        return res
    # 前提自证: 留出帧上把 FK 框反投影, 与检测框比 IoU
    ious, errs = [], []
    for o in slv.obs[-max(5, len(slv.obs) // 5):]:
        b = slv.projected_box_for(o["box"], o["tcp"], o["quat"])
        if b is not None:
            ious.append(iou_2d(b, o["box"]))
    res["holdout_iou_median"] = round(float(np.median(ious)), 3) if ious else None
    res["premise_ok"] = bool(res["holdout_iou_median"] is not None
                             and res["holdout_iou_median"] >= float(min_holdout_iou)
                             and float(res.get("holdout_rms_px") or 9e9) <= float(max_holdout_px))
    if log:
        print(f"📐 自监督拟合: 内参{'已知(手眼模式)' if slv.K is not None else '未知(投影P模式)'} · "
              f"rms={res.get('rms_px')}px 留出={res.get('holdout_rms_px')}px "
              f"off={res.get('off_mm')}mm R_rel={res.get('rrel_deg')}° · "
              f"前提自证 IoU={res['holdout_iou_median']} "
              f"→ {'成立 (夹持假设与相机模型自洽)' if res['premise_ok'] else '不成立, 不落盘'}")
    if res["premise_ok"]:
        if slv.K is None:
            sz = slv.calibrate_size()
            if log:
                print(f"📐 尺寸自监督: " + (f"采用 {sz.get('size_mm')}mm (留出 {sz.get('holdout_before_px')}"
                                          f"→{sz.get('holdout_after_px')}px)" if sz.get("ok")
                                          else f"保留标称 → {sz.get('why')}"))
            res["size_calib"] = sz
        d = slv.save(STATE, extra={"src": "box3d_live_box.py (真机 2D框+FK 自监督标定)",
                                   "img_wh": list(IMG_WH), "weights": WEIGHTS,
                                   "handeye": slv.T_cam_from_base})
        if log:
            print(f"📐 已落盘 {STATE} (rms {d.get('rms_px')}px · off {res.get('off_mm')}mm · "
                  f"尺寸 {d.get('size_mm')}mm/{d.get('size_src')}"
                  + (" · 手眼已解出" if slv.T_cam_from_base else "") + ")")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--collect", action="store_true", help="攒 (框, 位姿) 用于自监督标定")
    ap.add_argument("--min-conf", type=float, default=float(os.environ.get("SS_YOLO_CONF", "0.4")))
    ap.add_argument("--imgsz", type=int, default=int(os.environ.get("SS_YOLO_IMGSZ", "640")))
    ap.add_argument("--json", default=LIVE_JSON)
    ap.add_argument("--log", action="store_true")
    ap.add_argument("--held", choices=["auto", "on", "off"], default="auto",
                    help="模块是否在夹爪上 (auto=已标定后由反投影自检判定; 未标定时按 on 攒数据)")
    ap.add_argument("--seconds", type=float, default=0.0, help="--loop 时限 (0=无限)")
    args = ap.parse_args()

    slv = ensure_solver(log=True)
    t_end = (time.time() + args.seconds) if args.seconds else None
    n_seen = n_acc = 0
    last_fit_n = len(slv.obs)
    while True:
        n_seen += 1
        line, info = newest_state_line()          # 成功: info=帧龄s · 失败: line=None, info=原因
        age = None if line is None else info
        if line is None:
            print(f"⚠️ {info}")
            out = {"ok": False, "t": time.time(), "reason": info}
        else:
            fp, fage, note = frame_for(line)
            if fp is None:
                print(f"⚠️ {note}")
                out = {"ok": False, "t": line.get("t"), "reason": note}
            else:
                box, conf, cls, shp = detect(fp, args.min_conf, args.imgsz)
                tcp = [float(v) for v in line["tcp"]]
                quat = [float(v) for v in line["tcp_quat"]]
                held = None if args.held == "auto" else (args.held == "on")
                if box is None:
                    out = {"ok": False, "t": line.get("t"), "reason": f"本帧没检出光模块 (conf<{args.min_conf})",
                           "frame": os.path.basename(fp), "frame_age_s": round(fage, 2), "tcp": tcp}
                else:
                    r = slv.predict_box3d(box, tcp=tcp, quat=quat, held=held)
                    out = dict(r)
                    out.update({"t": line.get("t"), "pose_age_s": round(float(age), 2),
                                "frame": os.path.basename(fp), "frame_age_s": round(fage, 2),
                                "frame_wh": [int(shp[1]), int(shp[0])], "box_conf": round(float(conf), 3),
                                "cls": cls, "tcp": [round(v, 5) for v in tcp],
                                "quat": [round(v, 5) for v in quat],
                                "scope": "readonly · 只用 YOLO 框 + 机器人自身位姿 (无深度/无手眼/无仿真真值)",
                                "solver": slv.status()})
                    # 攒数据 (前提: 模块被夹持 → 由拟合的前提自证兜底)
                    if args.collect and (held is not False):
                        a = slv.add(box, tcp, quat, meta={"frame": os.path.basename(fp), "conf": conf,
                                                          "src": "box3d_live_box", "t": line.get("t")})
                        if a.get("ok"):
                            n_acc += 1
                            with open(OBS_LOG, "a", encoding="utf-8") as f:
                                f.write(json.dumps({"t": line.get("t"), "box": box, "tcp": tcp, "quat": quat,
                                                    "conf": conf, "frame": os.path.basename(fp)},
                                                   ensure_ascii=False) + "\n")
                        elif args.log:
                            print(f"   (未收: {a.get('why')})")
                    if args.log or not args.loop:
                        _print_report(out)
                    if args.collect and not slv.fitted and (n_acc - last_fit_n) >= 10:
                        last_fit_n = n_acc
                        try_fit(slv, log=True)
                        if slv.fitted:
                            out2 = slv.predict_box3d(box, tcp=tcp, quat=quat, held=held)
                            out2.update({k: out[k] for k in ("t", "frame", "frame_age_s", "box_conf", "cls")})
                            out2["solver"] = slv.status()
                            out = out2
                            _print_report(out, tag="标定后本帧")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
            tmp = args.json + ".tmp"
            json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, args.json)
        except Exception as e:                                                 # noqa: BLE001
            print(f"⚠️ 写 {args.json} 失败: {e}")
        if not args.loop:
            return 0
        if t_end and time.time() >= t_end:
            print(f"\n收工: 采 {n_seen} 帧 · 收下 {n_acc} 帧 · 解算器 {slv.status()['fitted']}")
            return 0
        time.sleep(max(0.05, args.interval))


def _print_report(o, tag=""):
    print(f"\n───── 2D 检测 → 3D 边界框 {tag} (t={o.get('t')}, 帧龄 {o.get('frame_age_s')}s) ─────")
    print(f"  YOLO: {o.get('cls')} conf={o.get('box_conf')} 框={o.get('box2d_obs')} "
          f"({o.get('span_px')}px 跨度) · 位姿源=编码器(同一行) TCP={o.get('tcp')}")
    if not o.get("ok"):
        print(f"  ❌ 本帧不出 3D (mode={o.get('mode')}) — 缺什么:")
        for g in o.get("gaps", []):
            print(f"     · {g}")
        return
    c = o["center"]
    print(f"  档位: {o['mode']} · {o['method']}")
    print(f"  中心: [{c[0]:.4f} {c[1]:.4f} {c[2]:.4f}]m  尺寸: {o['size_mm']}mm ({o['size_src']}) "
          f"· 距相机 {o.get('dist_m')}m")
    cs = np.asarray(o["corners8"], float)
    print(f"  8 角点 base 范围: x[{cs[:,0].min():.4f},{cs[:,0].max():.4f}] "
          f"y[{cs[:,1].min():.4f},{cs[:,1].max():.4f}] z[{cs[:,2].min():.4f},{cs[:,2].max():.4f}]")
    if o.get("box2d_reproj"):
        print(f"  反投影框 {o['box2d_reproj']} vs 检测框 {o['box2d_obs']} → IoU {o.get('iou')} "
              f"(最大边残差 {o.get('resid_px')}px)")
    if o.get("sigma_mm"):
        print(f"  σ: 中心 ±{o['sigma_mm'].get('total')}mm (残差折算 {o['sigma_mm'].get('center')} + "
              f"夹持重复性 {o['sigma_mm'].get('repeat')})")
    for g in o.get("gaps", []):
        print(f"  gap: {g}")


if __name__ == "__main__":
    sys.exit(main())
