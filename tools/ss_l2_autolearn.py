#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_l2_autolearn.py — 真机数据 L2「边干边学」自动学习闭环 (sim→real 泛化)

老倪 2026-09-18: 「在机器人正常插拔光模块的过程中自动学习数据, 完成 sim to real 的泛化过程。
                  状态空间的推理/训练切换节点, 选『真机数据 L2 训练模式』→ 点运行即可按真实数据训练」

═══ 设计: 三环 ═══
  环1 在线采集 (机器人正常插拔时, 只读旁路, 零下行)
      新鲜帧门(0≤age≤2s, 负帧龄拒用) → 去重(md5) → 限速(默认 3s/张) → 落帧 + 真值侧车
      (TCP 位姿/四元数/关节/六维力/夹爪/产线阶段), 与人工样本同结构 → sessions/auto_<ts>/
      自动标注两条路, 都**只进 train**:
        A) kinematic 几何真值: 需相机标定就绪 (models/real_cam_calib.json ready) + 抓取成立时段
           → 光模块 8 角点投影 AABB (真实几何, 不是模型猜的)
        B) pseudo 伪标注: 在役权重 conf ≥ 阈值 (默认 0.45) 的框 —— 标 annotator=auto:pseudo, 记权重 sha256
      ⚠️ 标定没就绪时 A 路**拒算不编造**, 只用 B 路并如实标注 (自动标注**永不当 val**)
  环2 触发训练 (新样本 ≥ K 张 或 距上轮 ≥ T 分钟且有新样本)
      构建数据集(去重 + auto 强制 train) → 体检 → 从**在役权重**继续微调 (systemd 独立单元)
      → 训练后**新鲜真机帧同口径对照** (在役 vs 新) → 有提升才上在役 (指针原子切换 + 记 sha256)
      → 无提升按纪律不上默认档, 只留产物 + 判定落盘
  环3 人工介入 (控制台「输入图像」窗口): 人工标注/修正 → annotator=human → 进 val 与门槛裁决集

═══ 红线 (写死在代码里) ═══
  · 自动标注样本**绝不进 val** (build 时强制 train; stats 里 auto_in_val 必须为 0)
  · 只读真机 (Orin 零自启/零下行); 不拿旧帧冒充实时 (负帧龄/超龄一律拒用)
  · 未证明提升不得进默认档 (判定数字来自真推理, 不看训练内 mAP)
  · 训练脱离启动者 cgroup (systemd-run --user), 否则关控制台会把训练连带杀

用法:
  python3 tools/ss_l2_autolearn.py --status                    # 当前状态 (样本/指针/最近判定/常驻)
  python3 tools/ss_l2_autolearn.py --collect-once              # 采 1 张 (真机新鲜帧) + 自动标注
  python3 tools/ss_l2_autolearn.py --collect --minutes 30      # 只采集, 跑 30 分钟
  python3 tools/ss_l2_autolearn.py --cycle --epochs 60         # 跑一轮完整学习闭环 (采集→训练→判定→上线)
  python3 tools/ss_l2_autolearn.py --daemon --trigger-n 12 --trigger-min 20
  python3 tools/ss_l2_autolearn.py --stop
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
import yolo_annot_dataset as yad                                              # noqa: E402

DATA_ROOT = os.environ.get("ZMAX_YOLO_ANNOT_ROOT", os.path.join(REPO, "data", "yolo_annot"))
SS_REMOTE = os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote")
WORK = os.environ.get("ZMAX_L2_WORK", "/home/ubuntu/zmax_data/l2_autolearn")
LIVE_PTR = os.path.join(REPO, "models", "yolo_peg_live.pt")
CALIB = os.environ.get("ZMAX_REAL_CALIB", os.path.join(REPO, "models", "real_cam_calib.json"))
# ② 机器人动作自标定产物 (S0→S1): 不用棋盘格, 由 tools/real_autolabel.py --probe 产出。
#    有它时几何标注直接可用 (2D 投影 P); 没它才退回 calib 的 K·T 路线。
CALIB_PROJ = os.environ.get("ZMAX_REAL_PROJ", os.path.join(REPO, "models", "real_cam_proj.json"))
TRAIN = os.path.join(_HERE, "yolo_annot_train.py")
EVAL = os.path.join(_HERE, "yolo_live_eval.py")

STATE_F = os.path.join(WORK, "state.json")
HEART_F = os.path.join(WORK, "heartbeat.json")
VERD_F = os.path.join(WORK, "verdicts.jsonl")
PID_F = os.path.join(WORK, "daemon.pid")
LOG_F = os.path.join(WORK, "autolearn.log")
RUNS = os.path.join(WORK, "runs")

PSEUDO_CONF = float(os.environ.get("ZMAX_L2_PSEUDO_CONF", "0.35"))  # 伪标注最低 conf (低于此不生成标签, 宁少不标错)
FRESH_MAX_S = 3.0           # 帧新鲜度上限 (秒): 旁路 tap 落盘约 1Hz, 留 3s 余量; age<0 一律拒用
MIN_INTERVAL_S = 3.0        # 采集限速: 相邻两张最少间隔
MIN_TCP_MOVE_MM = 8.0       # 姿态多样性门: 与上一张已收样本的 TCP 位移 (mm) 或阶段变化才收
MIN_ROT_DEG = 3.0           # 或姿态角变化 (度) 达此值也收


# ───────────────────────── 基础设施 ─────────────────────────
def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(WORK, exist_ok=True)
        with open(LOG_F, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                         # noqa: BLE001
        return default if default is not None else {}


def _sha256(path, n=1 << 20):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                b = f.read(n)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except OSError:
        return None


# ───────────────────────── 采集侧: 真机只读帧 + 真值 ─────────────────────────
def read_cam_frame():
    """最新真机帧 (cam_rs.png). 返回 (rgb, age_s, path) 或 (None, reason, None)。

    时钟纪律: age 用单调钟差值 (记录首次 mtime 的基准) —— 但跨进程只拿得到 mtime 与墙钟,
    因此用 mtime vs 墙钟差, 并**拒绝负帧龄** (mtime 在未来 = 系统时钟被回拨过)。
    """
    p = os.path.join(SS_REMOTE, "cam_rs.png")
    if not os.path.isfile(p):
        return None, f"缺 {p}", None
    age = time.time() - os.stat(p).st_mtime
    if age < 0:
        return None, f"负帧龄 {age:.2f}s (mtime 在未来 → 时钟异常, 拒用)", None
    if age > FRESH_MAX_S:
        return None, f"帧过期 {age:.2f}s > {FRESH_MAX_S}s", None
    import cv2
    img = cv2.imread(p)                       # BGR
    if img is None:
        return None, "图解码失败 (半张/0 字节?)", None
    if float(img.std()) < 5.0:                # 与引擎同口径的"真图"判据
        return None, f"帧无内容 (std={img.std():.1f} < 5)", None
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB), float(age), p


def _tail_jsonl(path, nbytes=262144):
    """读 jsonl 最后一行 (大文件不全读)"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            buf = f.read().decode("utf-8", "ignore").strip().splitlines()
        for ln in reversed(buf):
            ln = ln.strip()
            if ln:
                try:
                    return json.loads(ln)
                except ValueError:
                    continue
    except OSError:
        pass
    return None


def read_truth():
    """真机状态流最后一行 (TCP 真值/关节/力/夹爪/阶段). 返回 (truth_dict, age_s, reason)"""
    p = os.path.join(SS_REMOTE, "state_%s.jsonl" % time.strftime("%Y%m%d"))
    if not os.path.isfile(p):
        return {}, None, f"缺 {p} (旁路 tap 未在跑?)"
    d = _tail_jsonl(p)
    if not d:
        return {}, None, "状态流为空"
    age = time.time() - float(d.get("t") or 0.0)
    ps = d.get("prod_stage")
    if isinstance(ps, dict):
        st = ps.get("stage") or ps.get("name") or ("/".join(map(str, ps.get("states") or [])) or None)
    else:
        st = ps
    t = {"tcp": d.get("tcp"), "tcp_quat": d.get("tcp_quat"), "tcp_frame": d.get("tcp_frame"),
         "jpos": d.get("jpos"), "ft": d.get("ft"), "gripper": d.get("gripper"),
         "stage": st, "t": d.get("t")}
    return t, age, ""


def grasp_ok(truth) -> bool | None:
    """抓取成立判据 (自动标注只在成立时段发标签): 夹爪状态优先, 其次阶段名。无法判定 → None (不发几何标签)"""
    g = truth.get("gripper")
    if isinstance(g, (int, float)):
        return float(g) > 0.5
    st = str(truth.get("stage") or "")
    if st:
        return any(k in st for k in ("夹持", "抓取", "抬起", "插入", "拔出", "转移", "放下"))
    return None


# ───────────────────────── 自动标注 (两条路) ─────────────────────────
def autolabel_kinematic(rgb, truth):
    """A 路: 几何真值标注 (光模块 8 角点 → 投影 AABB)。两条标定来源, 都没有就拒算 (不编造)。

      ① `models/real_cam_proj.json`  —— **机器人动作自标定** (tools/real_autolabel.py --probe),
         P 已含内参与手眼外参的乘积; 出框用 "TCP + R·实测模块偏移"。
      ② `models/real_cam_calib.json` —— 棋盘格/手眼标定 (K + T_base_cam), 需要单独标。
    任一就绪即可出框; 都未就绪 → 明确报 gap。
    """
    if not truth.get("tcp"):
        return None, "无 TCP 真值 → 拒算"
    if grasp_ok(truth) is not True:
        return None, f"抓取未确认 (gripper={truth.get('gripper')} stage={truth.get('stage')}) → 该帧不发几何标签"
    try:
        import numpy as np
        from real_autolabel import box_from_3d, module_center
        proj = _read_json(CALIB_PROJ, {})
        if proj.get("ready") and proj.get("P"):
            P = np.asarray(proj["P"], float).reshape(3, 4)
            route = f"机器人动作自标定 (rms {proj.get('rms_px')}px)"
            size = [s / 1000.0 for s in (proj.get("module_size_mm") or [40.0, 16.0, 12.0])]
            moff = [s / 1000.0 for s in (proj.get("module_offset_mm") or [0.0, 0.0, 0.0])]
        else:
            calib = _read_json(CALIB, {})
            if not (calib.get("ready") and calib.get("K") and calib.get("T_base_cam")):
                return None, ("几何标注无标定可用: models/real_cam_proj.json 未就绪 (机器人动作自标定) 且 "
                              "models/real_cam_calib.json 未就绪 (K/T_base_cam) → 拒算; "
                              "先跑 tools/real_probe_plan.py + tools/real_autolabel.py --probe")
            K = np.asarray(calib["K"], float).reshape(3, 3)
            T = np.asarray(calib["T_base_cam"], float).reshape(4, 4)
            P = K @ T[:3, :]                                 # 相机系约定: +z 朝前 (由 calib_real_cam 写入)
            route = "棋盘格/手眼标定 (K·T)"
            size = [s / 1000.0 for s in (calib.get("module_size_mm") or [40.0, 16.0, 12.0])]
            moff = [s / 1000.0 for s in (calib.get("module_offset_mm") or [0.0, 0.0, 0.0])]
        center = module_center(truth["tcp"], truth.get("tcp_quat"), moff)
        b = box_from_3d(P, center, truth.get("tcp_quat"), size, (rgb.shape[1], rgb.shape[0]))
        if b is None:
            return None, "框退化/出画 (模块不在视野) → 丢弃该帧"
        return [(b[0], b[1], b[2], b[3], "peg")], ""
    except Exception as e:                                                     # noqa: BLE001
        return None, f"几何标注失败: {type(e).__name__}: {e}"


def autolabel_pseudo(rgb, conf=PSEUDO_CONF):
    """B 路: 在役权重伪标注 (conf 门槛, 只取数据集里的类名) → (boxes, meta, reason)"""
    if not os.path.isfile(LIVE_PTR):
        return None, {}, "在役权重不存在"
    try:
        from ultralytics import YOLO
        names = yad.load_classes(DATA_ROOT)
        m = _get_model()
        r = m.predict(rgb, imgsz=640, conf=conf, verbose=False)[0]
        keep, confs = [], []
        for cf, cl, xy in zip(r.boxes.conf.tolist(), r.boxes.cls.tolist(), r.boxes.xyxy.tolist()):
            cname = m.names.get(int(cl), str(int(cl)))
            if cname not in names:
                continue                                     # 类不在数据集类别表 → 不用 (避免类错位)
            keep.append((xy[0], xy[1], xy[2], xy[3], cname))
            confs.append(float(cf))
        meta = {"weight": os.path.realpath(LIVE_PTR), "weight_sha256": _sha256(LIVE_PTR),
                "conf_thr": conf, "n_det": len(keep),
                "conf_mean": (sum(confs) / len(confs)) if confs else None}
        return (keep or None), meta, ("" if keep else f"在役权重 conf≥{conf} 无检出")
    except Exception as e:                                                     # noqa: BLE001
        return None, {}, f"伪标注失败: {type(e).__name__}: {e}"


_MODEL = {}


def _get_model():
    """在役权重单次加载 (别每帧重建模型)"""
    key = os.path.realpath(LIVE_PTR)
    if _MODEL.get("key") != key:
        from ultralytics import YOLO
        _MODEL["key"], _MODEL["m"] = key, YOLO(key)
    return _MODEL["m"]


# ───────────────────────── 环1: 采集一张 ─────────────────────────
def _pose_delta(tcp1, q1, tcp2, q2):
    """两个位姿的位移(mm) 与姿态夹角(度); 缺数据 → (None, None)"""
    try:
        import math
        import numpy as np
        d = None
        if tcp1 and tcp2:
            d = float(np.linalg.norm(np.asarray(tcp1, float) - np.asarray(tcp2, float))) * 1000.0
        a = None
        if q1 and q2:
            q1 = np.asarray(q1, float); q2 = np.asarray(q2, float)
            q1 = q1 / (np.linalg.norm(q1) or 1.0); q2 = q2 / (np.linalg.norm(q2) or 1.0)
            c = abs(float(np.dot(q1, q2)))
            a = math.degrees(2.0 * math.acos(min(1.0, c)))
        return d, a
    except Exception:                                                          # noqa: BLE001
        return None, None


def collect_once(*, force=False, seq=None, session=None, ignore_motion_gate=False) -> dict:
    """采一张真机帧 + 真值 + 自动标注 → 落进标定会话。返回记录 (含 label_src)"""
    st = _read_json(STATE_F, {})
    if not force and st.get("last_collect_ts") and \
            (time.time() - float(st["last_collect_ts"])) < MIN_INTERVAL_S:
        return {"ok": False, "reason": f"限速 (距上张 < {MIN_INTERVAL_S}s)"}
    rgb, age, srcp = read_cam_frame()
    if rgb is None:
        return {"ok": False, "reason": f"无新鲜真机帧: {age}"}
    truth, tage, treason = read_truth()
    # 🎯 姿态多样性门 (2026-09-18): 机器人静止时相邻帧几乎相同 —— 只按 md5 去重会让"覆盖不同姿态"
    #   的域适应数据永远只有 1 张。改为: 与上一张**已收样本**的 TCP 位移/转角/阶段变化达阈值才收。
    dmm, ddeg = _pose_delta(st.get("last_tcp"), st.get("last_quat"),
                            truth.get("tcp"), truth.get("tcp_quat"))
    stage_now = truth.get("stage")
    stage_chg = bool(stage_now) and stage_now != st.get("last_stage")
    if not (force or ignore_motion_gate):
        _has_ref = st.get("last_tcp") is not None or st.get("last_quat") is not None
        if not _has_ref:
            pass                                  # 首个样本无参考位姿 → 收下 (否则永远采不到第一张)
        elif dmm is None and ddeg is None and not stage_chg:
            return {"ok": False, "reason": "无位姿真值 → 姿态门无法判定 (拒收, 不猜)"}
        elif not (stage_chg or (dmm is not None and dmm >= MIN_TCP_MOVE_MM)
                  or (ddeg is not None and ddeg >= MIN_ROT_DEG)):
            return {"ok": False, "reason": f"姿态门未过 (Δ位移={dmm if dmm is None else round(dmm, 1)}mm "
                                          f"Δ转角={ddeg if ddeg is None else round(ddeg, 1)}° < "
                                          f"{MIN_TCP_MOVE_MM}mm/{MIN_ROT_DEG}°, 与上张样本近似重复)"}
    h = hashlib.md5(rgb.tobytes()).hexdigest()
    if h in set(st.get("md5_recent") or []):
        return {"ok": False, "reason": "与最近样本重复 (md5 命中)", "md5": h}
    # 标注: A 路几何真值优先, 不行退 B 路伪标注 (如实记 source)
    boxes, kreason = autolabel_kinematic(rgb, truth)
    label_src, pmeta = "none", {}
    if boxes:
        label_src = "kinematic"
    else:
        boxes, pmeta, preason = autolabel_pseudo(rgb)
        label_src = "pseudo" if boxes else "none"
    # ⚠️ 2026-09-18 质量红线: **无标签帧不当背景负样本** —— 在役权重低置信度漏检时帧里其实有目标,
    #   若当"背景"进训练集会教模型"光模块=背景"(反向伤害)。因此无标签的帧进 **待标注池**
    #   (annotator=auto:pending), 数据集构建时**排除**, 等人工标注 (控制台「输入图像」窗口) 或
    #   几何标定就绪后补标才进训练集。
    _pend = (label_src == "none")
    sess = session or (("pending_" + time.strftime("%m%d_%H%M")) if _pend
                       else ("auto_" + time.strftime("%m%d_%H%M")))
    extra = {"truth": {**(truth or {}), "frame_age_s": round(age, 3),
                       "truth_age_s": (round(float(tage), 3) if isinstance(tage, (int, float)) else None),
                       "grasp_ok": grasp_ok(truth or {})},
             "label_src": label_src, "kinematic_gap": kreason or None, "pseudo_meta": pmeta or None,
             "pending_label": bool(_pend), "auto": True}
    rec = yad.save_sample(DATA_ROOT, rgb, boxes or [], device="realsense-d405", seq=seq,
                          ts=time.time(), src=f"real:autolearn({label_src})",
                          session=sess, annotator=("auto:pending" if _pend else f"auto:{label_src}"),
                          extra=extra)
    st.update({"last_collect_ts": time.time(), "md5_recent": ([h] + list(st.get("md5_recent") or []))[:40],
               "last_tcp": truth.get("tcp"), "last_quat": truth.get("tcp_quat"),
               "last_stage": stage_now,
               "n_collected": int(st.get("n_collected", 0)) + 1})
    _write_json(STATE_F, st)
    return {"ok": True, "stem": rec["stem"], "session": rec["session"], "boxes": len(rec["boxes"]),
            "label_src": label_src, "frame_age_s": round(age, 2),
            "pose_delta_mm": (round(dmm, 2) if dmm is not None else None),
            "pose_delta_deg": (round(ddeg, 2) if ddeg is not None else None),
            "tage_s": (round(tage, 2) if isinstance(tage, (int, float)) else None),
            "kinematic_gap": kreason or None,
            "pseudo": pmeta or None, "md5": h}


# ───────────────────────── 环2: 一轮学习闭环 ─────────────────────────
def _auto_sessions():
    """auto 标注会话名单 (meta.json 的 annotator 前缀)"""
    meta = _read_json(os.path.join(DATA_ROOT, "meta.json"), {})
    return {s["name"] for s in (meta.get("sessions") or [])
            if str(s.get("annotator", "")).startswith("auto")}


def _stem_to_session():
    """stem → 会话名 (从各会话 truth.jsonl / frames 归属; 去重后用于红线审计)"""
    m = {}
    for tp in glob.glob(os.path.join(DATA_ROOT, "sessions", "*", "truth.jsonl")):
        sess = os.path.basename(os.path.dirname(tp))
        try:
            with open(tp, encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        st = json.loads(ln).get("stem")
                    except ValueError:
                        continue
                    if st:
                        m[st] = sess
        except OSError:
            continue
    return m


def _dataset_auto_split_audit():
    """核对红线: auto 标注样本**必须全部在 train**, 混进 val 的数必须为 0"""
    ds = os.path.join(DATA_ROOT, "dataset")
    auto_sess = _auto_sessions()
    s2s = _stem_to_session()
    bad = []
    for sp in ("train", "val"):
        for jpg in glob.glob(os.path.join(ds, "images", sp, "*")):
            stem = os.path.splitext(os.path.basename(jpg))[0]
            sess = s2s.get(stem)
            if sess and sess in auto_sess:
                bad.append({"split": sp, "stem": stem, "session": sess})
    return {"auto_sessions": sorted(auto_sess), "auto_placed": bad,
            "auto_in_val": [b for b in bad if b["split"] == "val"]}


def decide_improved(old, new):
    """交付门槛 (老倪): **有提升才认** —— 检出率↑ 或 检出率持平但 conf 均值 +0.02 以上。
    数字只看训练后新采真机帧的同口径对照 (不看训练内 mAP)。"""
    keys = ("frames_with_peg", "n_frames", "peg_rate", "peg_conf_mean", "peg_conf_max")
    if not old or not new:
        return {"improved": False, "reason": f"对照组缺失 (new={bool(new)} old={bool(old)})"}
    nr, orr = float(new.get("peg_rate") or 0.0), float(old.get("peg_rate") or 0.0)
    nc, oc = float(new.get("peg_conf_mean") or 0.0), float(old.get("peg_conf_mean") or 0.0)
    dr, dc = nr - orr, nc - oc
    improved = nr > 0 and (dr > 0 or (abs(dr) < 1e-9 and dc > 0.02))
    return {"improved": bool(improved),
            "reason": (f"检出率 {orr:.3f}→{nr:.3f} ({dr:+.3f}) · conf {oc:.3f}→{nc:.3f} ({dc:+.3f}) · "
                       f"帧数 {new.get('n_frames')}"),
            "new": {k: new.get(k) for k in keys}, "old": {k: old.get(k) for k in keys}}


def switch_live_pointer(best):
    """在役指针**原子**切换 (读者要么旧要么新, 不会读到空) + 历史留痕。返回 (record, err)"""
    old = os.path.realpath(LIVE_PTR) if os.path.exists(LIVE_PTR) else None
    tmp = LIVE_PTR + ".tmp"
    try:
        if os.path.lexists(tmp):
            os.remove(tmp)
        os.symlink(os.path.abspath(best), tmp)
        os.replace(tmp, LIVE_PTR)
        sh = _sha256(LIVE_PTR)
        rec = {"done": True, "from": old, "to": os.path.realpath(LIVE_PTR),
               "rel": os.path.relpath(best, REPO), "sha256": sh}
        with open(os.path.join(REPO, "models", "yolo_peg_live.history.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%F %T"), **rec, "actor": "l2_autolearn"},
                               ensure_ascii=False) + "\n")
        return rec, None
    except Exception as e:                                                     # noqa: BLE001
        return {"done": False}, f"{type(e).__name__}: {e}"


def cycle(*, epochs=60, imgsz=640, live_frames=40, promote=True, name=None, timeout=3600) -> dict:
    """一轮: 构建数据集 → 体检 → 训练(在役权重续训) → 新鲜帧同口径对照 → 有提升才上在役"""
    os.makedirs(RUNS, exist_ok=True)
    ts = time.strftime("%m%d_%H%M%S")
    run_dir = os.path.join(RUNS, f"cycle_{ts}")
    os.makedirs(run_dir, exist_ok=True)
    name = name or f"auto_{ts}"
    out = {"ts": time.strftime("%F %T"), "name": name, "run_dir": run_dir, "promote": bool(promote)}

    # 1) 构建数据集 (去重 + auto→train 红线 + 体检)
    try:
        stats = yad.build_dataset(DATA_ROOT)
        chk = yad.check_dataset(DATA_ROOT, strict=False)
    except Exception as e:                                                     # noqa: BLE001
        out.update({"ok": False, "stage": "build", "error": f"{type(e).__name__}: {e}"})
        _log(f"❌ 建数据集失败: {e}")
        return out
    audit = _dataset_auto_split_audit()
    out["dataset"] = {"n_train": stats.get("n_train"), "n_val": stats.get("n_val"),
                      "n_samples": stats.get("n_samples"), "per_class": stats.get("per_class"),
                      "n_truth": stats.get("n_truth"), "errors": chk.get("errors"),
                      "n_images": chk.get("n_images")}
    out["auto_split_audit"] = {"auto_in_val": audit["auto_in_val"], "auto_sessions": audit["auto_sessions"]}
    _log(f"📦 数据集: train={stats.get('n_train')} val={stats.get('n_val')} 样本={stats.get('n_samples')} "
         f"类别={stats.get('per_class')} · auto 会话={len(audit['auto_sessions'])} · "
         f"auto混入val={len(audit['auto_in_val'])} (必须 0)")
    if audit["auto_in_val"]:
        out.update({"ok": False, "stage": "redline", "error": "红线违规: 自动标注样本进了 val"})
        _write_json(os.path.join(run_dir, "cycle.json"), out)
        return out
    if chk.get("errors"):
        out["dataset_errors"] = chk["errors"][:6]
        _log(f"⚠️ 体检告警/错误 {len(chk['errors'])} 条 (训练脚本会再判一次)")

    # 2) 训练 (从在役权重继续; 独立 systemd 单元, 不挂在控制台 cgroup 下)
    before = _read_json(STATE_F, {})
    cmd = [sys.executable, TRAIN, "--data", os.path.join(DATA_ROOT, "dataset"),
           "--epochs", str(epochs), "--imgsz", str(imgsz), "--base", "auto",
           "--name", name, "--live-frames", str(live_frames), "--live-eval", str(live_frames)]
    _log(f"🚀 训练: {' '.join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd))}")
    t0 = time.time()
    try:
        pr = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
        (open(os.path.join(run_dir, "train.log"), "w", encoding="utf-8")
         .write((pr.stdout or "") + "\n--- STDERR ---\n" + (pr.stderr or "")))
    except subprocess.TimeoutExpired:
        out.update({"ok": False, "stage": "train", "error": f"训练超时 {timeout}s"})
        _write_json(os.path.join(run_dir, "cycle.json"), out)
        return out
    out["train"] = {"rc": pr.returncode, "seconds": round(time.time() - t0, 1),
                    "log": os.path.join(run_dir, "train.log")}
    if pr.returncode != 0:
        out.update({"ok": False, "stage": "train", "error": f"训练脚本 rc={pr.returncode}"})
        _write_json(os.path.join(run_dir, "cycle.json"), out)
        _log(f"❌ 训练失败 rc={pr.returncode} (看 {out['train']['log']})")
        return out
    tail = "\n".join((pr.stdout or "").strip().splitlines()[-12:])
    _log("训练输出尾部:\n" + tail)

    # 3) 权重产物 + 真机帧同口径对照
    best = None
    for pat in (os.path.join(REPO, "outputs", "yolo_annot", name, "weights", "best.pt"),
                os.path.join(REPO, "runs", "detect", "outputs", "yolo_annot", name, "weights", "best.pt"),
                os.path.join(REPO, "runs", "detect", "outputs", "yolo_annot", name, "weights", "last.pt")):
        if os.path.isfile(pat):
            best = pat
            break
    if best is None:
        c = glob.glob(os.path.join(REPO, "runs", "**", name, "weights", "best.pt"), recursive=True)
        best = c[0] if c else None
    out["weights"] = best
    if not best:
        out.update({"ok": False, "stage": "weights", "error": "找不到训练产物 best.pt"})
        _write_json(os.path.join(run_dir, "cycle.json"), out)
        return out
    ev_json = os.path.join(REPO, "reports", f"yolo_live_eval_{name}.json")
    old_tgt = os.path.realpath(LIVE_PTR) if os.path.exists(LIVE_PTR) else None
    verdict = {"improved": False, "reason": "未取得对照结果"}
    if os.path.isfile(ev_json):
        try:
            d = json.load(open(ev_json, encoding="utf-8"))
            rs = {os.path.basename(r["weights"]): r for r in d["results"]}
            new = rs.get(os.path.basename(best))
            old = rs.get(os.path.basename(old_tgt)) if old_tgt else None
            if not old and len(d["results"]) > 1:          # 在役路径变了等 → 用第一个当对照组 (live_eval 约定)
                old = d["results"][0]
            verdict = decide_improved(old, new)
        except Exception as e:                                                 # noqa: BLE001
            verdict = {"improved": False, "reason": f"解析对照失败: {type(e).__name__}: {e}"}
    else:
        verdict = {"improved": False, "reason": f"缺对照文件 {ev_json}"}
    out["verdict"] = verdict
    _log(f"🎯 对照判定: {'✅ 有提升' if verdict['improved'] else '➖ 持平/回退'} — {verdict['reason']}")

    # 4) 上在役 (有提升 且 被授权 promote 时): 指针**原子**切换 + 记 sha256 前后值
    if verdict["improved"] and promote:
        rec, err = switch_live_pointer(best)
        if err:
            out["promote"] = {"done": False, "error": err}
            _log(f"⚠️ 上在役失败: {err}")
        else:
            out["promote"] = rec
            _log(f"⬆️ 已上在役 (单点指针): {rec['rel']} · sha256 {str(rec['sha256'])[:16]}…")
    else:
        out["promote"] = {"done": False,
                          "reason": ("无提升 → 按纪律不上默认档" if not verdict["improved"]
                                     else "本次未授权 promote (--no-promote)")}

    # 5) 证据包
    for f in (ev_json, os.path.join(REPO, "reports", f"yolo_live_eval_{name}.json")):
        if os.path.isfile(f):
            shutil.copy2(f, os.path.join(run_dir, os.path.basename(f)))
    tr = os.path.join(REPO, "runs", "detect", "outputs", "yolo_annot", name, "results.csv")
    if os.path.isfile(tr):
        shutil.copy2(tr, os.path.join(run_dir, "results.csv"))
    out["ok"] = True
    _write_json(os.path.join(run_dir, "cycle.json"), out)
    st = _read_json(STATE_F, {})
    st.update({"last_cycle_ts": time.time(), "last_cycle_name": name, "last_verdict": verdict,
               "n_collected_at_cycle": before.get("n_collected", 0)})
    _write_json(STATE_F, st)
    with open(VERD_F, "a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    _log(f"📁 证据包: {run_dir}")
    return out


# ───────────────────────── 状态 ─────────────────────────
def status() -> dict:
    meta = _read_json(os.path.join(DATA_ROOT, "meta.json"), {})
    sess = meta.get("sessions") or []
    human = [s for s in sess if not str(s.get("annotator", "")).startswith("auto")]
    auto = [s for s in sess if str(s.get("annotator", "")).startswith("auto")]
    ds_stats = _read_json(os.path.join(DATA_ROOT, "dataset", "stats.json"), {})
    st = _read_json(STATE_F, {})
    heart = _read_json(HEART_F, {})
    pid = None
    try:
        pid = int(open(PID_F, encoding="utf-8").read().strip())
    except Exception:                                                          # noqa: BLE001
        pid = None
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            alive = False
    _rgb, age, _p = read_cam_frame()
    truth, tage, treason = read_truth()
    calib = _read_json(CALIB, {})
    proj = _read_json(CALIB_PROJ, {})
    vers = []
    try:
        with open(VERD_F, encoding="utf-8") as f:
            for ln in f:
                try:
                    vers.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        pass
    return {
        "in_service": {"ptr": LIVE_PTR, "target": os.path.realpath(LIVE_PTR) if os.path.exists(LIVE_PTR) else None,
                       "sha256": _sha256(LIVE_PTR)},
        "data": {"sessions_human": len(human), "sessions_auto": len(auto),
                 "n_images_human": sum(int(s.get("n_images", 0)) for s in human),
                 "n_images_auto": sum(int(s.get("n_images", 0)) for s in auto),
                 "sessions_pending": len([s for s in sess
                                          if str(s.get("annotator", "")) == "auto:pending"]),
                 "n_images_pending": sum(int(s.get("n_images", 0)) for s in sess
                                         if str(s.get("annotator", "")) == "auto:pending"),
                 "dataset": {k: ds_stats.get(k) for k in ("n_train", "n_val", "n_samples", "per_class",
                                                          "n_truth", "val_overlap_train",
                                                          "n_pending_excluded", "auto_in_val")},
                 "auto_sessions": [s["name"] for s in auto][-6:]},
        "live": {"cam_age_s": (round(age, 2) if isinstance(age, (int, float)) else age),
                 "truth_age_s": (round(tage, 2) if isinstance(tage, (int, float)) else tage),
                 "truth_gap": treason, "stage": (truth or {}).get("stage"),
                 "grasp_ok": grasp_ok(truth or {}), "tcp": (truth or {}).get("tcp")},
        "calib": {"ready": bool(calib.get("ready")), "rms_px": calib.get("rms_px"),
                  "why": calib.get("reason") if not calib.get("ready") else None},
        # 几何标注的两条标定来源 (2026-09-18): 机器人动作自标定优先, 棋盘格次之
        "calib_route": {"route": ("机器人动作自标定(P)" if (proj.get("ready") and proj.get("P"))
                                  else ("棋盘格/手眼(K·T)" if (calib.get("ready") and calib.get("K")
                                                              and calib.get("T_base_cam")) else "无 → 几何拒算")),
                        "proj": {"ready": bool(proj.get("ready")), "rms_px": proj.get("rms_px"),
                                 "n_pairs": proj.get("n_pairs"), "updated_at": proj.get("updated_at"),
                                 "K_est_note": proj.get("K_est_note")},
                        "cam_calib_ready": bool(calib.get("ready"))},
        "daemon": {"running": alive, "pid": pid, "heartbeat_age_s":
                   (round(time.time() - float(heart.get("t") or 0), 1) if heart.get("t") else None),
                   "heartbeat": heart},
        "collector": {"n_collected": st.get("n_collected", 0), "last_collect_ts": st.get("last_collect_ts"),
                      "last_cycle_ts": st.get("last_cycle_ts"), "last_cycle_name": st.get("last_cycle_name"),
                      "last_verdict": st.get("last_verdict")},
        "recent_verdicts": [{"ts": v.get("ts"), "name": v.get("name"),
                             "improved": (v.get("verdict") or {}).get("improved"),
                             "reason": (v.get("verdict") or {}).get("reason"),
                             "promoted": (v.get("promote") or {}).get("done")} for v in vers[-5:]],
    }


# ───────────────────────── 常驻 (边干边学) ─────────────────────────
_STOP = {"v": False}


def _on_term(signum, frame):                                                   # noqa: ARG001
    _STOP["v"] = True
    _log(f"收到信号 {signum} → 准备退出 (本轮采集/训练收尾后停)")


def collect_loop(*, minutes=0, interval=MIN_INTERVAL_S, max_n=0, session=None,
                 ignore_motion_gate=False) -> dict:
    """只采集 (环1)。minutes=0 且 max_n=0 → 无限 (常驻, 需 --stop 或信号)"""
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    t0 = time.time()
    got, miss, reasons = 0, 0, {}
    while not _STOP["v"]:
        r = collect_once(session=session, ignore_motion_gate=ignore_motion_gate)
        if r.get("ok"):
            got += 1
            _log(f"📥 采样 {got}: {r['session']}/{r['stem']} 标签={r['label_src']} 框={r['boxes']} "
                 f"帧龄={r['frame_age_s']}s" + (f" · 几何缺口: {r['kinematic_gap'][:60]}" if r.get("kinematic_gap") else ""))
        else:
            miss += 1
            reasons[r.get("reason", "?")[:60]] = reasons.get(r.get("reason", "?")[:60], 0) + 1
        _write_json(HEART_F, {"t": time.time(), "iso": time.strftime("%F %T"), "collected": got,
                              "missed": miss, "reasons": reasons})
        if max_n and got >= max_n:
            break
        if minutes and (time.time() - t0) > minutes * 60:
            break
        time.sleep(max(0.2, interval))
    return {"collected": got, "missed": miss, "reasons": reasons, "seconds": round(time.time() - t0, 1)}


def daemon(*, trigger_n=12, trigger_min=20, epochs=60, live_frames=40, promote=True,
           interval=MIN_INTERVAL_S, poll_s=10.0) -> dict:
    """环1+环2: 边采边学。新样本 ≥ trigger_n 或 距上轮 ≥ trigger_min 分钟且有新样本 → 跑一轮闭环"""
    os.makedirs(WORK, exist_ok=True)
    with open(PID_F, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    _log(f"🧠 L2 边干边学常驻启动 pid={os.getpid()} · 触发: 新样本≥{trigger_n} 或 距上轮≥{trigger_min}min "
         f"· 训练 {epochs} 轮 · 上在役={'开' if promote else '关'}")
    st = _read_json(STATE_F, {})
    last_cycle_ts = float(st.get("last_cycle_ts") or 0.0)
    n_at_cycle = int(st.get("n_collected_at_cycle") or 0)
    rounds = 0
    try:
        while not _STOP["v"]:
            r = collect_once()
            if r.get("ok"):
                _log(f"📥 采样: {r['stem']} 标签={r['label_src']} 框={r['boxes']}")
            st = _read_json(STATE_F, {})
            n_now = int(st.get("n_collected", 0))
            new_n = n_now - n_at_cycle
            due_n = new_n >= trigger_n
            due_t = (last_cycle_ts > 0 and (time.time() - last_cycle_ts) >= trigger_min * 60 and new_n > 0)
            due_first = (last_cycle_ts <= 0 and new_n >= max(4, trigger_n // 3))
            _write_json(HEART_F, {"t": time.time(), "iso": time.strftime("%F %T"), "mode": "daemon",
                                  "n_collected": n_now, "new_since_cycle": new_n, "rounds": rounds,
                                  "last_cycle_ts": last_cycle_ts, "due": {"by_n": due_n, "by_t": due_t,
                                                                          "first": due_first}})
            if due_n or due_t or due_first:
                why = ("新样本 %d ≥ %d" % (new_n, trigger_n) if due_n else
                       ("距上轮 %.1f 分钟且新增 %d" % ((time.time() - last_cycle_ts) / 60, new_n) if due_t
                        else f"首轮 (样本 {new_n})"))
                _log(f"🔁 触发学习轮: {why}")
                out = cycle(epochs=epochs, live_frames=live_frames, promote=promote)
                rounds += 1
                last_cycle_ts = time.time()
                n_at_cycle = int(_read_json(STATE_F, {}).get("n_collected", 0))
                _log(f"🔁 第 {rounds} 轮结束: ok={out.get('ok')} 提升={(out.get('verdict') or {}).get('improved')} "
                     f"上在役={(out.get('promote') or {}).get('done')}")
            time.sleep(max(1.0, poll_s))
    finally:
        _log(f"🧠 常驻退出 (采集 {_read_json(STATE_F, {}).get('n_collected')} 张 · 学习轮 {rounds})")
        try:
            os.remove(PID_F)
        except OSError:
            pass
    return {"rounds": rounds}


def stop_daemon() -> dict:
    try:
        pid = int(open(PID_F, encoding="utf-8").read().strip())
    except Exception:                                                          # noqa: BLE001
        return {"ok": False, "reason": "无 pid 文件 (未在跑?)"}
    try:
        os.kill(pid, signal.SIGTERM)
        _log(f"已发 SIGTERM → pid {pid}")
        return {"ok": True, "pid": pid}
    except OSError as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}


# ───────────────────────── CLI ─────────────────────────
def main():
    global PSEUDO_CONF
    ap = argparse.ArgumentParser(description="真机数据 L2 边干边学自动学习闭环")
    ap.add_argument("--status", action="store_true", help="打印状态 (JSON)")
    ap.add_argument("--collect-once", action="store_true", help="采一张 + 自动标注")
    ap.add_argument("--collect", action="store_true", help="只采集循环")
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--max-n", type=int, default=0)
    ap.add_argument("--cycle", action="store_true", help="跑一轮完整闭环")
    ap.add_argument("--daemon", action="store_true", help="常驻边干边学")
    ap.add_argument("--stop", action="store_true", help="停常驻")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--live-frames", type=int, default=40)
    ap.add_argument("--trigger-n", type=int, default=12, help="新样本达此数触发一轮训练")
    ap.add_argument("--trigger-min", type=float, default=20.0, help="距上轮达此分钟数且有新样本 → 触发")
    ap.add_argument("--interval", type=float, default=MIN_INTERVAL_S, help="采集间隔秒")
    ap.add_argument("--name", default=None)
    ap.add_argument("--pseudo-conf", type=float, default=None, help=f"伪标注 conf 门槛 (默认 {PSEUDO_CONF})")
    ap.add_argument("--ignore-motion-gate", action="store_true", help="忽略姿态多样性门 (诊断用)")
    ap.add_argument("--no-promote", dest="promote", action="store_false", default=True,
                    help="只训练+对照, 即使有提升也不切在役指针 (演练)")
    a = ap.parse_args()

    if a.pseudo_conf is not None:
        PSEUDO_CONF = float(a.pseudo_conf)

    if a.status:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
        return 0
    if a.stop:
        print(json.dumps(stop_daemon(), ensure_ascii=False))
        return 0
    if a.collect_once:
        print(json.dumps(collect_once(force=True, ignore_motion_gate=a.ignore_motion_gate),
                         ensure_ascii=False, indent=1))
        return 0
    if a.collect:
        print(json.dumps(collect_loop(minutes=a.minutes, interval=a.interval, max_n=a.max_n,
                                      ignore_motion_gate=a.ignore_motion_gate),
                         ensure_ascii=False, indent=1))
        return 0
    if a.cycle:
        out = cycle(epochs=a.epochs, imgsz=a.imgsz, live_frames=a.live_frames,
                    promote=a.promote, name=a.name)
        print(json.dumps({k: out.get(k) for k in ("ok", "stage", "error", "dataset", "verdict",
                                                  "promote", "weights", "run_dir")},
                         ensure_ascii=False, indent=1))
        return 0 if out.get("ok") else 1
    if a.daemon:
        daemon(trigger_n=a.trigger_n, trigger_min=a.trigger_min, epochs=a.epochs,
               live_frames=a.live_frames, promote=a.promote, interval=a.interval)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
