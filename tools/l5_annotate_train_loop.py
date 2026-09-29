#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_annotate_train_loop.py — L5 档「视觉语言自动标注 → L2/L3/L4 监督 → 自动训练」闭环编排

老倪需求 (2026-09-28): 「能力档位节点增加 L5 档位; 选 L5 + 点运行 → 通过大模型的视觉语言能力
自动标注, 为 L2 L3 L4 模型提供监督标注数据, 同时自动启动训练流程。
L2 是全量训练 YOLO; L3 和 L4 是通过 LoRA 适配训练。」

本脚本 = **编排层** (不重写任何算法, 全部复用既有件):

  ① 标注 (annotate)   tools/auto_annotate.py (L5 视觉语言: 6 路实拍 → DeepSeek-V4-Flash →
                      场景描述 + 边界框 + 标注图; 单次 ~120s ⇒ **后台异步**跑, 不占 GUI 线程)
  ② 监督 (supervision) 标注结果 → L2/L3/L4 三份监督口径产物:
                      · L2: YOLO 格式数据集 (复用 tools/yolo_annot_dataset.py 的会话契约 +
                        build_dataset 的**红线** "自动标注样本绝不进 val"), 根 = data/yolo_annot_l5vlm
                      · L3/L4: 逐帧监督 manifest (jsonl) —— 场景文本 + 框 + 图像; 训练进程通过
                        env ZMAX_L5_SUPERVISION 拿到它 (作为监督/条件侧车, 可追溯)
  ③ 训练 (serial)     · L2 = **全量训练** YOLO: tools/yolo_annot_train.py --base none (从 COCO 重训)
                      · L3 = SmolVLA LoRA: tools/joint_train_all.py --only L3 --lora-l3 (自研 lora_inject)
                      · L4 = INTACT LoRA:  tools/joint_train_all.py --only L4 --lora-l4
                      · merge: 训完必 merge —— tools/merge_lora_ckpt.py 把包装键折叠回可部署命名
                        (不 merge 时官方加载器 Missing key → trained=False → **零动作伪装成"没提升"**)
  ④ 取证 (evidence)   每阶段: 子进程 pid + `ps -o lstart` + 日志前几行 + 产物路径/大小 + 判据;
                      全过程状态落  ~/zmax_data/l5_loop/state.json (GUI 徽章/双击读它)

红线 (写死在代码里):
  · 8GB 卡同刻只跑一个模型进程 → 全部阶段**串行**; 每阶段前查 GPU 空闲并记录
  · 自动标注样本**绝不进 val** (复用 yad.build_dataset 的 auto 会话规则; stats 里 auto_in_val 必须 0)
  · 未证明提升**不切在役指针** (只落 candidates; 上线由 model_autoload.py --promote 显式执行)
  · LoRA 产物**必须 merge** 才报告"可部署"; 不 merge 的产物一律标 unmerged

用法:
  ./gui-venv311/bin/python tools/l5_annotate_train_loop.py --run          # 全链 (后台)
  ./gui-venv311/bin/python tools/l5_annotate_train_loop.py --dry-run      # 只打印计划
  ./gui-venv311/bin/python tools/l5_annotate_train_loop.py --status       # 当前状态 (GUI 徽章同源)
  ./gui-venv311/bin/python tools/l5_annotate_train_loop.py --run --only annotate,supervision
  ./gui-venv311/bin/python tools/l5_annotate_train_loop.py --run --cams arm,local --yolo-epochs 5
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
PY_INTACT = "/home/ubuntu/INTACT-JEPA/.venv/bin/python"
WORK = os.environ.get("ZMAX_L5_WORK", "/home/ubuntu/zmax_data/l5_loop")
STATE = os.path.join(WORK, "state.json")
ANNOT_ROOT = os.path.join(os.path.expanduser("~/zmax_data/auto_annotate"))
SUP_ROOT = os.environ.get("ZMAX_L5_SUP_ROOT", "/home/ubuntu/zmax_data/l5_supervision")
L2_ROOT = os.environ.get("ZMAX_L5_L2_ROOT", os.path.join(ROOT, "data", "yolo_annot_l5vlm"))        # L2 监督数据集根 (与在役根隔离)
CLASSES_SRC = os.path.join(ROOT, "data", "yolo_annot", "classes.txt")
STAGES = ("interact", "annotate", "supervision", "slots", "L2_full", "L3_lora", "L4_lora", "merge", "verify")

# VLM 自由文本标签 → 本工程类别名 (关键词映射; 未命中一律**跳过并计数**, 不硬塞类别)
LABEL_MAP = [
    ("OPT_Gold", ("金手指", "gold", "opt_gold", "opt-gold", "optgold", "卡缘", "金指",
                  "连接器", "connector", "edge")),
    ("peg", ("光模块", "模块", "peg", "optical", "插芯", "插针", "光纤", "module",
             "sma", "mpo", "跳线")),
]


# ─────────────────────────── 状态/日志 ───────────────────────────
def _now() -> str:
    return time.strftime("%F %T")


def load_state() -> dict:
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:                                                       # noqa: BLE001
        return {}


def _atomic_json(path: str, obj) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:                                                       # noqa: BLE001
        pass


LOCK = os.path.join(WORK, "loop.lock")


def acquire_lock() -> tuple:
    """🔒 单实例闸门 (2026-09-28 现场急需): 老倪演示时点 ▶运行, GUI 可能再 spawn 一个编排进程
    → 两个编排同时跑 = 抢 8GB 卡 + 互相覆盖 state.json (现场不可再生数据绝不能这样)。
    按 pid 判活; 拿不到锁就**什么都不做直接退出**, 绝不碰别人的 state。"""
    try:
        os.makedirs(WORK, exist_ok=True)
        if os.path.isfile(LOCK):
            try:
                old = json.load(open(LOCK, encoding="utf-8"))
                opid = int(old.get("pid") or 0)
                os.kill(opid, 0)
                return (False, "已有编排在跑 (pid %s · 起于 %s · 阶段 %s)"
                        % (opid, old.get("started"), old.get("stage")))
            except ProcessLookupError:
                pass
            except Exception:                                                   # noqa: BLE001
                pass
        _atomic_json(LOCK, {"pid": os.getpid(), "started": time.strftime("%F %T"), "argv": sys.argv[1:]})
        return (True, "lock ok pid=%d" % os.getpid())
    except Exception as e:                                                       # noqa: BLE001
        return (True, "lock 异常(放行): %s" % e)


def refresh_lock(stage: str, started: str = "") -> None:
    _atomic_json(LOCK, {"pid": os.getpid(), "started": started or _now(), "stage": stage,
                        "argv": sys.argv[1:]})


def release_lock() -> None:
    try:
        cur = json.load(open(LOCK, encoding="utf-8"))
        if int(cur.get("pid") or 0) == os.getpid():
            os.remove(LOCK)
    except Exception:                                                       # noqa: BLE001
        pass


def save_state(st: dict) -> None:
    os.makedirs(WORK, exist_ok=True)
    st["updated"] = _now()
    st["pid"] = os.getpid()          # 🧿 编排自身 pid (GUI 判活优先看这个, 不是子进程 pid)
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def _tail(p: str, n: int = 12) -> list:
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return [ln.rstrip("\n") for ln in f.readlines()[-n:]]
    except Exception:                                                       # noqa: BLE001
        return []


def gpu_free() -> int:
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True,
                           text=True, timeout=10).stdout.strip().splitlines()[0]
        u, t = [int(x) for x in o.split(",")]
        return t - u
    except Exception:                                                       # noqa: BLE001
        return -1


def run_stage_cmd(name: str, cmd: list, log_path: str, cwd: str = ROOT,
                  env_extra: dict | None = None, st: dict | None = None,
                  timeout: float | None = None) -> dict:
    """起一个**独立会话**(setsid)的子进程, 记录 pid/lstart + 日志; 返回判据字典。"""
    env = {**os.environ, **(env_extra or {})}
    env.setdefault("PYTHONUNBUFFERED", "1")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write("[%s] [%s] $ %s\n" % (_now(), name, " ".join(cmd)))
        lf.flush()
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=lf, stderr=subprocess.STDOUT,
                             start_new_session=True)
        lstart = ""
        try:
            lstart = subprocess.run(["ps", "-o", "lstart=", "-p", str(p.pid)], capture_output=True,
                                    text=True).stdout.strip()
        except Exception:                                                   # noqa: BLE001
            pass
        if st is not None:
            st["stage_detail"] = {"name": name, "pid": p.pid, "lstart": lstart,
                                  "cmd": cmd, "log": log_path, "started": _now()}
            st["gpu_free_mb_before"] = gpu_free()
            save_state(st)
        try:
            rc = p.wait(timeout=timeout) if timeout else p.wait()
        except Exception:                                                   # noqa: BLE001
            try:
                p.kill()
            except Exception:                                               # noqa: BLE001
                pass
            rc = 124
        secs = round(time.time() - t0, 1)
    out = {"stage": name, "pid": p.pid, "lstart": lstart, "rc": rc, "secs": secs,
           "log": log_path, "cmd": cmd, "head": _tail(log_path, 25), "tail": _tail(log_path, 8)}
    return out


# ─────────────────── ⓪ 人机交互模式 (复用既有 HIL 通道, 不另造) ───────────────────
INTERACT_STATE = os.path.join(WORK, "interact_state.json")
HIL_API_PORT = int(os.environ.get("ZMAX_HIL_LOCAL_PORT", "8795"))


def _hil_import():
    """既有 HIL 大脑 (画布 n_hil 节点同一份): hil_bridge.build_snapshot/handle_instruction"""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, os.path.join(ROOT, "src/lerobot/policies/left_right/state_space"))
    import hil_bridge as HB                                                     # noqa: N812
    return HB


def _port_up(port: int, timeout=1.0) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:                                                       # noqa: BLE001
        return False


def _http(path: str, obj=None, timeout=15):
    import urllib.request
    url = "http://127.0.0.1:%d%s" % (HIL_API_PORT, path)
    if obj is None:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def stage_interact(st: dict, ts: str) -> dict:
    """⓪ 自动进入【人机交互模式】(老倪 L5 定义第一条) —— **复用既有 HIL 通道, 不另造一套**:
      · 大脑: hil_bridge.build_snapshot / handle_instruction (与画布 n_hil 节点同一份状态与指示处理)
      · 本地接口: tools/hil_local_api.py (0.0.0.0:8795, /health | /hil/state | /hil/say)
      · 人的提示词从飞书/APP/现场页 http://<工位机>:8791/room 进来, 走同一个 POST /hil/say
    🚨 只读: 本模式只读 TCP / 抓图 / 记录 / 标注 —— **任何真机动作不在这里**, 演示由老倪驱动。
    三处证据: ①状态文件 ②接口返回 ③快照内容。
    """
    r = {"stage": "interact", "ok": False, "redline": "只读: 读TCP/抓图/记录/标注; 不动臂"}
    HB = _hil_import()
    snap = None
    try:
        snap = HB.build_snapshot()
        r["snapshot_ok"] = True
        r["snapshot_keys"] = sorted(list(snap.keys()))[:14]
    except Exception as e:                                                       # noqa: BLE001
        r["snapshot_err"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    # 本地接口: 在听就用现成的 (既有通道), 不在听才拉起 (后台, 不阻塞 GUI)
    api = {"port": HIL_API_PORT, "listening_before": _port_up(HIL_API_PORT), "spawned": False}
    if not api["listening_before"]:
        api_py = os.path.join(ROOT, "tools", "hil_local_api.py")
        if os.path.isfile(api_py):
            p = subprocess.Popen([PY, api_py], cwd=ROOT, start_new_session=True,
                                 stdout=open(os.path.join(WORK, "hil_local_api.log"), "a"),
                                 stderr=subprocess.STDOUT)
            api["spawned"] = True
            api["pid"] = p.pid
            for _ in range(20):
                time.sleep(0.4)
                if _port_up(HIL_API_PORT):
                    break
    api["listening_after"] = _port_up(HIL_API_PORT)
    r["api"] = api
    # 接口返回 (证据②): /health + /hil/state
    try:
        r["health"] = _http("/health", timeout=8)
        hs = _http("/hil/state", timeout=20)
        r["hil_state"] = {"ok": hs.get("ok"), "ts": hs.get("ts"), "pause": hs.get("pause"),
                          "snapshot_keys": sorted(list((hs.get("snapshot") or {}).keys()))[:14],
                          "instructions": len(hs.get("instructions") or [])}
    except Exception as e:                                                       # noqa: BLE001
        r["hil_state"] = {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}
    # 用**同一个指示处理链**跑一次 "进入 L5 标注模式" 的指示 (证据: reply/verdict 是真大脑回的)
    txt = env_extra_demo_prompt()
    try:
        say = _http("/hil/say", {"text": txt}, timeout=60)
        r["instruction"] = {"text": txt, "reply": str(say.get("reply"))[:300],
                            "verdict": str(say.get("verdict"))[:120], "ok": bool(say.get("ok"))}
    except Exception as e:                                                       # noqa: BLE001
        r["instruction"] = {"text": txt, "ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}
    r["slots_reg"] = os.path.relpath(SLOT_REG, ROOT) if os.path.isfile(SLOT_REG) else None
    r["ts"] = _now()
    r["ok"] = bool(r.get("snapshot_ok") and (r.get("hil_state") or {}).get("ok")
                   and (r.get("instruction") or {}).get("ok"))
    try:
        os.makedirs(WORK, exist_ok=True)
        json.dump(r, open(INTERACT_STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:                                                       # noqa: BLE001
        pass
    r["state_file"] = INTERACT_STATE
    return r


def env_extra_demo_prompt() -> str:
    """老倪的提示词 (从 HIL 通道进来的原话) —— 原样送进同一套指示处理链"""
    return ("进入 L5 标注模式: 我能通过手臂相机看到黑色治具, 右上角有一个光模块, 一共 14 个槽位; "
            "我演示每个光模块放进槽位的位置, 你要记住位置、理解光模块边沿、标注槽位角点, "
            "并自动进入 L2 YOLO 训练流程; 只读记录, 不要动机器人。")


# ─────────────────── ④ 槽位数据集 (TCP 真值 + 标定链角点投影 → 14 类) ───────────────────
SLOT_REG = os.path.join(ROOT, "models", "l5_slots.json")
SLOT_TOOL = os.path.join(ROOT, "tools", "l5_slot_tool.py")
SLOT_DS = os.environ.get("ZMAX_L5_SLOT_DS", os.path.join(ROOT, "data", "yolo_annot_l5slots"))


def stage_slots(st: dict, ts: str) -> dict:
    """④ 槽位数据集: 已记录的槽位 (TCP 真值 + 角点投影) → 14 类 YOLO 数据集。
    ⚠️ 未演示的槽位如实留白 (绝不补假数据); 深度那路未上线如实标。"""
    r = {"stage": "slots", "ok": False, "mode": "TCP真值位置 + 标定链角点投影 → 14 类 (每槽位一类)"}
    stt = run_stage_cmd("slots_status", [PY, SLOT_TOOL, "--status"], os.path.join(WORK, "slots_status.log"),
                        st=None, timeout=120)
    r["status_log"] = os.path.join(WORK, "slots_status.log")
    r["status_head"] = (stt.get("head") or [])[:8]
    try:
        reg = json.load(open(SLOT_REG, encoding="utf-8"))
        sl = reg.get("slots") or {}
        rec = [k for k, v in sl.items() if v.get("status") == "已记录"]
        r["slots"] = {"total": reg.get("n_slots"), "recorded": len(rec), "recorded_ids": rec,
                      "undemoed": [k for k, v in sl.items() if v.get("status") == "未演示"],
                      "pending": [k for k, v in sl.items() if v.get("status") == "待确认"],
                      "depth": reg.get("depth")}
    except Exception as e:                                                       # noqa: BLE001
        r["slots"] = {"err": "%s: %s" % (type(e).__name__, e)}
    b = run_stage_cmd("slots_dataset", [PY, SLOT_TOOL, "--build-dataset"],
                      os.path.join(WORK, "slots_dataset.log"), st=None, timeout=600)
    r["dataset_log"] = os.path.join(WORK, "slots_dataset.log")
    r["dataset_head"] = (b.get("head") or [])[:10]
    try:
        rep = json.load(open(os.path.join(WORK, "dataset_report.json"), encoding="utf-8"))
        r["dataset"] = {k: rep.get(k) for k in ("n_box", "classes", "dataset_root", "data_yaml",
                                                "build", "check")}
        r["labels"] = (rep.get("labels") or [])[:6]
    except Exception as e:                                                       # noqa: BLE001
        r["dataset"] = {"err": "%s: %s" % (type(e).__name__, e)}
    n = ((r.get("dataset") or {}).get("n_box") or 0)
    r["ok"] = bool(n > 0 and (r.get("slots") or {}).get("recorded", 0) > 0)
    if not r["ok"]:
        r["reason"] = ("尚无已记录槽位 (等老倪逐个演示; 记录器: python tools/l5_slot_tool.py "
                       "--record --slot N --size W,H,T)" if not ((r.get("slots") or {}).get("recorded"))
                       else "槽位数据集为空")
        # 🐛 2026-09-29 修 (编排"模型拉不通"的第二个卡点): 槽位是**可选输入** ——
        #   没演示槽位时 stage_L2 本来就有明确退路 (退回 L5 监督标注数据集, 见 stage_L2 的
        #   mode="L5 监督标注"), 但原编排一律 `break` ⇒ 后面的 L2_full/L3_lora/L4_lora/merge
        #   全不启动 (实测: interact✅ annotate✅ supervision✅ slots❌ → 整链 failed)。
        #   现把"尚未演示槽位"标为 non_fatal: 仍如实 ok=False + 写 reason (绝不补假数据),
        #   但主循环只告警继续 → 训练阶段照跑 (L2 自动退到监督数据集, 各阶段自己的红线不变)。
        #   数据/代码类错误 (槽位记录了却建不出数据集) 仍按致命处理。
        r["non_fatal"] = not ((r.get("slots") or {}).get("recorded"))
    return r


# ─────────────────────────── ① 标注 ───────────────────────────
TARGET_PROMPT = """你是产线视觉标注工程师。图中**需要标注的目标类别**只有这些: {classes}。
逐类判断是否可见; 可见就给出**像素边界框**(左上角为原点, 整数, 保证 x2>x1, y2>y1)。
不要标类别表以外的物体(其它物体一律忽略, 不写进 objects)。
只输出 JSON, 不要解释/markdown:
{{"objects":[{{"label":"<上面类别之一>","bbox":[x1,y1,x2,y2],"conf":0.0-1.0,"why":"<20字依据>"}}]}}
图尺寸: {W}x{H} 像素。
"""


def _targeted_sources():
    """目标类别 = data/yolo_annot/classes.txt (与 L2 训练类别表同源, 不另立口径)。"""
    try:
        return [ln.strip() for ln in open(CLASSES_SRC, encoding="utf-8")
                if ln.strip() and not ln.strip().startswith("#")]
    except Exception:                                                       # noqa: BLE001
        return []


def targeted_pass(batch_dir: str, cams, log=None) -> dict:
    """定向标注 pass: 按 L2 **目标类别表**问一次 VLM (复用 gen_overlay_from_vlm.call_vlm)。

    与 auto_annotate 的通用场景理解互补: 通用 pass 给场景级标签 (标定板/托盘/手...),
    定向 pass 只问"peg/OPT_Gold 在哪" → 才可能产出可用的检测监督框。
    产物写进同批目录 <cam>_target.json + summary_targeted.json (绝不覆盖通用 pass 产物)。
    """
    import concurrent.futures as _cf
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import gen_overlay_from_vlm as G                                        # noqa: E402
    import auto_annotate as AA                                              # noqa: E402
    import cv2                                                              # noqa: E402
    import numpy as np                                                      # noqa: E402
    classes = _targeted_sources()
    out = {"classes": classes, "cams": {}, "ok": False, "model": None}
    if not classes:
        out["reason"] = "类别表为空: %s" % CLASSES_SRC
        return out

    def _one(cam):
        rec = {"cam": cam, "ok": False, "objects": [], "ts": time.strftime("%F %T")}
        try:
            raw = AA.grab(cam)
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                rec["err"] = "取到的不是图片"
                return rec
            H, W = img.shape[:2]
            k = min(1.0, float(AA.SEND_W) / max(W, H))
            sm = cv2.resize(img, (int(W * k), int(H * k)), interpolation=cv2.INTER_AREA) if k < 1.0 else img
            h2, w2 = sm.shape[:2]
            ok, enc = cv2.imencode(".jpg", sm, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            pr = TARGET_PROMPT.format(classes=" / ".join(classes), W=w2, H=h2)
            r = G.call_vlm(enc.tobytes(), w2, h2, timeout=300, prompt=pr)
            txt = (r.get("txt") or "").strip()
            if not txt:
                rec["err"] = "content 空 · model=%s · %.0fs" % (r.get("model"), r.get("latency_s") or 0)
                return rec
            d = G.parse_json(txt)
            for o in (d.get("objects") or []):
                b = o.get("bbox")
                if not (isinstance(b, (list, tuple)) and len(b) == 4):
                    continue
                x1, y1, x2, y2 = [float(v) / k for v in b]
                x1, x2 = sorted((max(0.0, min(W - 1, x1)), max(0.0, min(W - 1, x2))))
                y1, y2 = sorted((max(0.0, min(H - 1, y1)), max(0.0, min(H - 1, y2))))
                if (x2 - x1) < 4 or (y2 - y1) < 4:
                    continue
                rec["objects"].append({"label": str(o.get("label") or "?")[:20],
                                       "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                                       "conf": o.get("conf"), "why": str(o.get("why") or "")[:40]})
            rec.update({"ok": True, "n_obj": len(rec["objects"]), "model": r.get("model"),
                        "latency_s": round(float(r.get("latency_s") or 0), 1),
                        "w": W, "h": H, "scene": str(d.get("scene") or "")[:200],
                        "prompt_classes": classes, "raw_txt": txt[:800]})
        except Exception as e:                                              # noqa: BLE001
            rec["err"] = "%s: %s" % (type(e).__name__, str(e)[:180])
        return rec

    cams = list(cams)
    with _cf.ThreadPoolExecutor(max_workers=max(1, len(cams))) as ex:
        recs = list(ex.map(_one, cams))
    for rec in recs:
        out["cams"][rec["cam"]] = {k: rec.get(k) for k in ("ok", "n_obj", "model", "latency_s", "err")}
        out["model"] = rec.get("model") or out.get("model")
        try:
            with open(os.path.join(batch_dir, "%s_target.json" % rec["cam"]), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
        except Exception as e:                                              # noqa: BLE001
            rec["err"] = (rec.get("err") or "") + " 写盘失败:%s" % e
    out["ok"] = any(len(c.get("objects") or []) >= 0 and c.get("ok") for c in recs)
    out["n_frames"] = sum(1 for c in recs if c.get("ok"))
    out["n_boxes"] = sum(len(c.get("objects") or []) for c in recs)
    try:
        with open(os.path.join(batch_dir, "summary_targeted.json"), "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in out.items() if k != "cams"} | {"cams": out["cams"]},
                      f, ensure_ascii=False, indent=1)
    except Exception:                                                       # noqa: BLE001
        pass
    if log:
        log("🎯 定向标注 pass: %d/%d 路回 OK · 共 %d 框 · 类别表 %s"
            % (out["n_frames"], len(cams), out["n_boxes"], classes))
    return out


def stage_annotate(st: dict, cams: str, push_overlay: bool, targeted: bool = True) -> dict:
    before = set(os.listdir(ANNOT_ROOT)) if os.path.isdir(ANNOT_ROOT) else set()
    cmd = [PY, os.path.join(ROOT, "tools", "auto_annotate.py")]
    if cams:
        cmd += ["--cams", cams]
    if push_overlay:
        cmd += ["--push-overlay"]
    r = run_stage_cmd("annotate", cmd, os.path.join(WORK, "annotate.log"), st=st)
    after = set(os.listdir(ANNOT_ROOT)) if os.path.isdir(ANNOT_ROOT) else set()
    new = sorted(x for x in (after - before) if x.startswith("batch_"))
    if not new and after:                       # 同秒覆盖/复用最近批次
        new = [sorted(after)[-1]]
    r["new_batches"] = new
    if new:
        b = os.path.join(ANNOT_ROOT, new[-1])
        try:
            r["summary"] = json.load(open(os.path.join(b, "summary.json"), encoding="utf-8"))
        except Exception as e:                                              # noqa: BLE001
            r["summary_err"] = str(e)
        r["batch_dir"] = b
    r["ok"] = bool(new) and r["rc"] == 0
    if not r["ok"]:
        r["reason"] = ("auto_annotate 退出码 %s; 无新批次" % r["rc"]) if r["rc"] else "无新批次目录"
        return r
    # 定向 pass: 按 L2 目标类别表再问一次 VLM (通用 pass 的标签是场景级, 目标类别命中率低)
    if targeted and r.get("batch_dir"):
        try:
            _cams = [c.strip() for c in cams.split(",") if c.strip()] if cams else None
            if not _cams:
                sys.path.insert(0, os.path.join(ROOT, "tools"))
                import auto_annotate as _AA                                     # noqa: E402
                _cams = list(_AA.CAMS)
            r["targeted"] = targeted_pass(r["batch_dir"], _cams)
        except Exception as e:                                              # noqa: BLE001
            r["targeted"] = {"ok": False, "reason": "%s: %s" % (type(e).__name__, e)}
    return r


# ─────────────────────────── ② 监督数据 ───────────────────────────
def _map_label(lab: str) -> str | None:
    s = str(lab or "").lower()
    for cls, kws in LABEL_MAP:
        for k in kws:
            if k in s:
                return cls
    return None


def stage_supervision(st: dict, batch_dir: str) -> dict:
    """标注结果 → L2 YOLO 数据集 (会话契约 + build_dataset) + L3/L4 监督 manifest。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import yolo_annot_dataset as yad                                       # noqa: E402
    import cv2                                                             # noqa: E402
    import numpy as np                                                     # noqa: E402

    r = {"stage": "supervision", "batch": batch_dir}
    batch = os.path.basename(batch_dir.rstrip("/"))
    supdir = os.path.join(SUP_ROOT, batch)
    os.makedirs(supdir, exist_ok=True)
    sess = "l5vlm_" + batch.replace("batch_", "")
    names = [ln.strip() for ln in open(CLASSES_SRC, encoding="utf-8")
             if ln.strip() and not ln.strip().startswith("#")]
    yad.ensure_layout(L2_ROOT, classes=names)        # classes.txt 缺失才写; 已有不动
    sd = os.path.join(L2_ROOT, "sessions", sess)
    os.makedirs(os.path.join(sd, "frames"), exist_ok=True)
    os.makedirs(os.path.join(sd, "labels"), exist_ok=True)

    recs = []
    # 权威来源 = 本批目录内每路的 <cam>.json (auto_annotate 逐路落盘, 带 objects/scene/ts);
    # 若同批有定向 pass 的 <cam>_target.json (只问 L2 目标类别) → **定向优先**, 通用 pass 保留为对照
    for fn in sorted(os.listdir(batch_dir)):
        if not fn.endswith(".json") or fn == "summary.json":
            continue
        if fn.endswith("_ann.json") or fn.endswith("_target.json"):
            continue
        p = os.path.join(batch_dir, fn)
        try:
            d = dict(json.load(open(p, encoding="utf-8")))
        except Exception:                                                   # noqa: BLE001
            continue
        if not d.get("ok"):
            continue
        cam = d.get("cam") or os.path.splitext(fn)[0]
        tgt = {}
        tp = os.path.join(batch_dir, "%s_target.json" % cam)
        if os.path.isfile(tp):
            try:
                tgt = json.load(open(tp, encoding="utf-8"))
            except Exception:                                               # noqa: BLE001
                tgt = {}
        d["objects_std"] = d.get("objects") or []
        d["objects_targeted"] = (tgt.get("objects") or []) if tgt.get("ok") else []
        d["objects"] = d["objects_targeted"] or d["objects_std"]
        d["objects_src"] = ("targeted(按类别表定向问)" if d["objects_targeted"]
                            else "std(通用场景理解)")
        if not d.get("scene") and tgt.get("scene"):
            d["scene"] = tgt.get("scene")
        recs.append(d)
    if not recs:            # 兜底: 从追加流水里按 _batch 字段挑 (老记录无该字段 → 不强取)
        jl = os.path.join(ANNOT_ROOT, "annotations.jsonl")
        if os.path.isfile(jl):
            for ln in open(jl, encoding="utf-8", errors="replace"):
                try:
                    d = json.loads(ln.strip() or "{}")
                except Exception:                                           # noqa: BLE001
                    continue
                if d.get("ok") and str(d.get("_batch")) == batch:
                    recs.append(d)
    r["n_frames"] = len(recs)
    r["recs_source"] = "batch_dir/*.json" if recs else "none"
    rows_l3, rows_l4 = [], []
    stat = {"mapped_boxes": 0, "skipped_boxes": 0, "skipped_labels": {},
            "per_class": {}, "images_written": 0, "frames_no_box": 0}
    for i, d in enumerate(recs):
        cam = d.get("cam") or "cam%d" % i
        src = os.path.join(batch_dir, "%s.jpg" % cam)
        if not os.path.isfile(src):
            continue
        img = cv2.imread(src)
        if img is None:
            continue
        H, W = img.shape[:2]
        lines, kept = [], []
        for o in (d.get("objects") or []):
            cls = _map_label(o.get("label"))
            b = o.get("bbox")
            if cls is None or not (isinstance(b, (list, tuple)) and len(b) == 4):
                stat["skipped_boxes"] += 1
                stat["skipped_labels"][str(o.get("label"))] = stat["skipped_labels"].get(str(o.get("label")), 0) + 1
                continue
            x1, y1, x2, y2 = [float(v) for v in b]
            ln_ = yad.to_yolo_line((x1, y1, x2, y2), W, H, names.index(cls))
            lines.append(ln_)
            kept.append({**o, "class": cls})
            stat["mapped_boxes"] += 1
            stat["per_class"][cls] = stat["per_class"].get(cls, 0) + 1
        if not lines:
            stat["frames_no_box"] += 1
            continue
        stem = "%s_%02d" % (cam, i)
        shutil.copy2(src, os.path.join(sd, "frames", stem + ".jpg"))
        open(os.path.join(sd, "labels", stem + ".txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
        stat["images_written"] += 1
        row = {"cam": cam, "image": os.path.join(sd, "frames", stem + ".jpg"),
               "image_src": src, "ts": d.get("ts"), "scene": d.get("scene"),
               "boxes": kept, "objects_src": d.get("objects_src"),
               "labels_raw": [o.get("label") for o in (d.get("objects") or [])],
               "labels_std": [o.get("label") for o in (d.get("objects_std") or [])],
               "model": d.get("model"), "latency_s": d.get("latency_s"),
               "origin": "L5:auto_annotate(VLM)", "batch": batch}
        rows_l3.append(row)
        rows_l4.append({**row, "supervision_role": "L4 场景-意图监督 (动作 chunk 的语义侧车)"})
    for nm, rows in (("l3_supervision.jsonl", rows_l3), ("l4_supervision.jsonl", rows_l4)):
        with open(os.path.join(supdir, nm), "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # 会话登记 (annotator 前缀 auto ⇒ build_dataset 的红线: 自动样本只进 train)
    meta_p = os.path.join(L2_ROOT, "meta.json")
    meta = yad._read_json(meta_p, {}) or {"version": 1, "sessions": []}
    meta["sessions"] = [s for s in (meta.get("sessions") or []) if s.get("name") != sess]
    meta["sessions"].append({"name": sess, "created": _now(),
                             "n_images": stat["images_written"],
                             "device": "auto_annotate(6路实拍)", "w": 0, "h": 0,
                             "annotator": "auto:vlm-l5", "src": "vlm:%s" % batch,
                             "updated": _now()})
    meta["n_images"] = sum(int(s.get("n_images") or 0) for s in meta["sessions"])
    yad._write_json(meta_p, meta)

    build = yad.build_dataset(L2_ROOT, val_ratio=0.15, seed=0)
    chk = yad.check_dataset(L2_ROOT, strict=False)
    # 🚨 2026-09-28 老倪红线: **标注产出 0 框必须明确判失败并说清原因**, 不许当成功继续往下训。
    #   0 框的常见原因要分开报: ①VLM 没识别出目标(全 其它/未命中类别表) ②VLM 返回空 content
    #   (max_tokens<3000 或图太暗) ③帧取不到 ④类别映射全未命中。
    _n_map = int((stat or {}).get("mapped_boxes") or 0)
    _zero_reason = None
    if _n_map <= 0:
        _tgt = (r.get("targeted") or {})
        _cams_ok = int((r.get("summary") or {}).get("n_ok") or 0) if isinstance(r.get("summary"), dict) else 0
        _n_tgt = int(_tgt.get("n_boxes") or 0)
        _lat = [_c.get("latency_s") for _c in (_tgt.get("cams") or {}).values() if _c.get("latency_s")]
        if _cams_ok == 0:
            _zero_reason = "①所有相机都没拿到帧 (流没起/相机离线) → 0 框"
        elif _n_tgt == 0 and _lat and max(_lat) > 60:
            _zero_reason = ("②VLM 返回空/超时 (单片 %.0fs) —— 多半是 max_tokens<3000 导致 content 为空, "
                            "或图过暗/无目标 → 0 框" % max(_lat))
        else:
            _zero_reason = ("③VLM 识别了但都不是目标类别 (未命中类别表 %s; 见 skipped_labels) → 0 框"
                            % ("/".join((stat or {}).get("classes") or [])))
    r.update({"supdir": supdir, "l2_root": L2_ROOT, "session": sess, "stats": stat,
              "build": {k: build.get(k) for k in ("n_train", "n_val", "n_boxes", "classes",
                                                  "auto_in_val", "n_auto_train", "val_overlap_train",
                                                  "n_pending_excluded", "note") if k in build},
              "check": {k: chk.get(k) for k in ("n_images", "n_labels", "n_boxes", "n_empty_label",
                                                "errors", "per_class") if k in chk},
              "zero_box_reason": _zero_reason,
              "ok": bool(_n_map > 0 and build.get("n_train", 0) > 0 and chk.get("n_images", 0) > 0
                         and int(chk.get("n_empty_label") or 0) == 0
                         and not [e for e in (chk.get("errors") or [])
                                  if "超出类别表" in e or "不在 [0,1]" in e])})
    if not r["ok"]:
        r["reason"] = (_zero_reason or "数据集体检未过或零样本") + " → 判失败, 不继续训练"
    r["auto_in_val_note"] = ("自动标注会话按 yad.build_dataset 规则只进 train; val 允许为空/回落 train "
                            "(stats 显式标注) —— 自动标注永不当裁决集")
    json.dump(r, open(os.path.join(supdir, "supervision.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return r


# ─────────────────────────── ③ 训练 ───────────────────────────
def _ensure_val_split(data: str) -> dict:
    """val 拆分为空时补上 val —— ultralytics 硬要求, 且不破「自动标注样本绝不进 val」红线。

    ① 优先: 既有**真机人工留出集** data/yolo_annot/dataset/{images,labels}/val → 软链过来
       (单一真源; 样本是人工标注, 不是 L5 自动样本 ⇒ 红线不破、指标口径诚实)
    ② 都没有: 退化为 val=train, 并**如实标注"指标偏乐观"** (不静默假报)
    """
    img_val = os.path.join(data, "images", "val")
    lab_val = os.path.join(data, "labels", "val")
    os.makedirs(img_val, exist_ok=True)
    os.makedirs(lab_val, exist_ok=True)
    for _c in ("val.cache", os.path.join("..", "labels", "val.cache")):
        _cp = os.path.join(img_val, _c) if not _c.startswith("..") else os.path.join(data, "labels", "val.cache")
        if os.path.isfile(_cp):
            try:
                os.remove(_cp)
            except OSError:
                pass
    n_img = len([f for f in glob.glob(os.path.join(img_val, "*")) if not f.endswith(".cache")])
    n_lab0 = len([f for f in glob.glob(os.path.join(lab_val, "*")) if not f.endswith(".cache")])
    # ⚠️ 两个都要有才算"已有 val": 图像有、标签没有 = val 全是背景图 (评估失效), 必须补标签。
    if n_img > 0 and n_lab0 > 0:
        return {"need": False, "n_img": n_img, "n_label": n_lab0, "source": "已有 val"}
    src_root = os.path.join(ROOT, "data", "yolo_annot", "dataset")
    src_img, src_lab = os.path.join(src_root, "images", "val"), os.path.join(src_root, "labels", "val")
    cands = [f for f in glob.glob(os.path.join(src_img, "*")) if os.path.isfile(f)]
    if cands:
        # ⚠️ 修 (2026-09-29 实测踩到): 图像是 .jpg / 标签是 .txt —— 原来两路都用同一个
        #   basename b, 于是标签侧永远找不到源文件 ⇒ images/val 有 5 张而 labels/val **0 个**
        #   (val 全变背景图 = 评估失去意义)。这里按 stem 分别映射扩展名。
        n_img = n_lab = 0
        for f in cands:
            b = os.path.basename(f)
            stem = os.path.splitext(b)[0]
            for p, t, _kind in ((os.path.join(src_img, b), os.path.join(img_val, b), "img"),
                                (os.path.join(src_lab, stem + ".txt"), os.path.join(lab_val, stem + ".txt"), "lab")):
                if not os.path.exists(p) or os.path.exists(t):
                    continue
                try:
                    os.symlink(p, t)
                except OSError:
                    shutil.copy2(p, t)          # 跨设备/无权限 → 退化为拷贝
                if _kind == "img":
                    n_img += 1
                else:
                    n_lab += 1
        return {"need": True, "n_img": n_img, "n_label": n_lab, "n_src": len(cands),
                "source": "真机人工留出集 data/yolo_annot/dataset/{images,labels}/val (软链)",
                "honest": "L5 自动标注样本仍不进 val"}
    n2 = 0
    for f in glob.glob(os.path.join(data, "images", "train", "*")):
        b = os.path.basename(f)
        t = os.path.join(img_val, b)
        if not os.path.exists(t):
            try:
                os.symlink(f, t)
            except OSError:
                shutil.copy2(f, t)
            n2 += 1
        lp = os.path.join(data, "labels", "train", os.path.splitext(b)[0] + ".txt")
        lt = os.path.join(lab_val, os.path.basename(lp))
        if os.path.isfile(lp) and not os.path.exists(lt):
            try:
                os.symlink(lp, lt)
            except OSError:
                shutil.copy2(lp, lt)
    return {"need": True, "n_img": n2, "source": "train (无独立留出集)",
            "honest": "⚠️ val=train → 指标偏乐观, 仅用于跑通链路, 不可作为泛化判据"}


def stage_L2(st: dict, sup: dict, epochs: int, ts: str) -> dict:
    """L2 = **全量训练** YOLO (从 COCO 预训练重训, --base none)。

    数据集选择 (老倪 2026-09-28 L5 定义: "14 个槽位 = 14 类; L2 层要进行训练并更新"):
      ① 有已记录槽位 (models/l5_slots.json + data/yolo_annot_l5slots 有框) → 用**槽位 14 类数据集**
         (位置来自 TCP 真值, 角点来自标定链投影);
      ② 没有 → 退回 L5 监督标注数据集 (VLM 场景理解 → L2 监督), 如实写 mode 说明。
    """
    slot_yaml = os.path.join(SLOT_DS, "dataset", "data.yaml")
    slot_n = 0
    try:
        rep = json.load(open(os.path.join(WORK, "dataset_report.json"), encoding="utf-8"))
        slot_n = int(rep.get("n_box") or 0)
    except Exception:                                                       # noqa: BLE001
        slot_n = 0
    use_slot = bool(slot_n > 0 and os.path.isfile(slot_yaml))
    root = SLOT_DS if use_slot else L2_ROOT
    data = os.path.join(root, "dataset")
    # 🐛 2026-09-29 修 (编排"模型拉不通"的第三个卡点): val 空 → ultralytics 直接
    #   `AssertionError: val: No images found` → L2 全量训练起不来 (实测 l5vlm 集 val=0 张:
    #   红线要求自动标注样本**绝不进 val**, 所以新集天然没有 val 拆分)。
    #   正解: 训练用 L5 自动标注集, **val 用既有真机留出集**(data/yolo_annot/dataset/images/val,
    #   人工标注、非自动样本) —— 红线不破且指标口径诚实。软链而非拷贝 (单一真源)。
    #   若真机留出集也不存在 → 退化为 val=train 并**如实标注指标偏乐观** (不静默)。
    #   ⚠️ 必须在下面的 labels_assert 之前做: 断言/日志要报**补完之后**的真实拆分。
    _vs = _ensure_val_split(data)
    # 🚨 2026-09-28 老倪红线: **训练前断言数据集非空** (train/val 的 labels 数 > 0),
    #   否则拒绝启动 —— 空数据集上"8 epochs completed"= 训了个空模型却报成功 (绝对不能发生)。
    _lab = {}
    for _sp in ("train", "val"):
        _fs = glob.glob(os.path.join(data, "labels", _sp, "*.txt"))
        _n = sum(1 for f in _fs if os.path.getsize(f) > 0)
        _lab[_sp] = {"files": len(_fs), "nonzero": _n}
    if not (_lab["train"]["nonzero"] > 0 or _lab["val"]["nonzero"] > 0):
        return {"stage": "L2_full", "ok": False, "rc": None, "secs": 0.0,
                "labels_assert": _lab, "dataset_used": {"root": root, "mode": "槽位" if use_slot else "监督"},
                "reason": ("数据集为空 (labels train=%s val=%s 全 0) → **拒绝启动训练** "
                           "(避免在空集上训出空模型还报成功); 先修标注/映射" % (_lab["train"], _lab["val"]))}
    r = run_stage_cmd("L2_full", [
        PY, os.path.join(ROOT, "tools", "yolo_annot_train.py"),
        "--root", root, "--data", data, "--base", "none",
        "--epochs", str(epochs), "--imgsz", "640", "--batch", "8", "--workers", "2",
        "--name", "l5full_%s" % ts, "--project", "outputs/yolo_annot_l5",
        "--live-eval", "0", "--verify", "4",
    ], os.path.join(WORK, "L2_full.log"), st=st,
        env_extra={"ZMAX_L5_SUPERVISION": os.path.join(sup.get("supdir") or SUP_ROOT,
                                                       "l3_supervision.jsonl")})
    r["dataset_used"] = {"root": root, "n_boxes": slot_n if use_slot else None,
                         "mode": ("槽位 14 类 (TCP真值+标定链投影)" if use_slot
                                  else "L5 监督标注 (VLM 场景理解; 无槽位记录时的退路)")}
    r["val_split"] = _vs
    # 🔎 best.pt 落地位置不止一处: yolo_annot_train 的 project 会挂到 RUNS_DIR(runs/detect) 下
    #   → 原只查 ROOT/outputs/... 会假阴性 (2026-09-28 实测: 训练真跑完 rc=0/8轮, 却报 best.pt 不在位)。
    #   口径: 解析日志里的「权重路径」行 + 多根 glob 兜底, 命中即真产物。
    name = "l5full_%s" % ts
    cands = [os.path.join(ROOT, "outputs", "yolo_annot_l5", name, "weights", "best.pt"),
             os.path.join(ROOT, "runs", "detect", "outputs", "yolo_annot_l5", name, "weights", "best.pt")]
    for _ln in (r.get("tail") or []) + (r.get("head") or []):
        if "权重路径" in _ln or "best.pt" in _ln:
            for _tok in _ln.replace("(", " ").replace(")", " ").split():
                if _tok.endswith("best.pt"):
                    cands.append(_tok if os.path.isabs(_tok) else os.path.join(ROOT, _tok))
    best = next((c for c in cands if os.path.isfile(c)), cands[0])
    r["best"] = best
    r["artifact_ok"] = os.path.isfile(best)
    r["labels_assert"] = _lab
    # 🚨 2026-09-28 老倪红线: 训完的**真推理验证若 0 框** → 明确判"不算成功"(不能给他"训练完成"的假结果):
    #   "训练在极小样本上跑完但权重零检出" ≠ 可用模型 (更不能上在役)。
    _vtxt = "\n".join((r.get("tail") or []) + (r.get("head") or []))
    _vlines = [l for l in _vtxt.splitlines() if "真推理验证" in l or "框 (无检出)" in l or "→ " in l]
    _n_box_verify = None
    for l in _vlines:
        if "真推理验证" in l and "→" in l:
            try:
                _n_box_verify = int(l.split("→")[1].strip().split()[0])
            except Exception:                                               # noqa: BLE001
                pass
    r["post_train_verify"] = {"n_boxes": _n_box_verify, "lines": _vlines[:6]}
    r["ok"] = bool(r["rc"] == 0 and r["artifact_ok"] and (_n_box_verify or 0) > 0)
    r["mode"] = "全量训练 (--base none → 从 COCO 预训练重训, 非域适应微调)"
    if not r["ok"]:
        if r["rc"] != 0 or not r["artifact_ok"]:
            r["reason"] = "rc=%s · best.pt 在位=%s" % (r["rc"], r["artifact_ok"])
        else:
            r["reason"] = ("训练跑完但**真推理验证 0 框** → **不算成功**: 样本太少/未收敛, "
                           "权重不可用 (明确标注, 不上在役); 需要更多标注样本 (当前 labels %s)"
                           % json.dumps(_lab, ensure_ascii=False))
            # 🐛 2026-09-29 (编排"模型拉不通"的第四个卡点): 上面这条是**数据量**问题, 不是链路问题
            #   —— 训练本身机械跑通 (rc=0 + best.pt 落地)。原逻辑一律 break ⇒ L3/L4 LoRA 与
            #   merge 也不启动, 后面两个模型同样"拉不通"。现标 non_fatal: 主循环告警继续
            #   (权重仍是"未过闸、不可上在役"的诚实状态, 绝不悄悄上线)。
            r["non_fatal"] = True
    return r


def stage_LoRA(st: dict, layer: str, steps: int, ts: str, sup: dict, batch: int) -> dict:
    """L3/L4 = LoRA 适配训练 (复用 tools/joint_train_all.py, 自研 lora_inject 引擎)"""
    cmd = [PY, os.path.join(ROOT, "tools", "joint_train_all.py"),
           "--only", layer, "--steps", str(steps), "--gpu-wait", "120"]
    if layer == "L3":
        cmd += ["--lora-l3", "--l3-lora-engine", "local", "--l3-batch", str(batch),
                "--l3-tag", "_l5%s" % ts]
    else:
        cmd += ["--lora-l4", "--lora-r", "8"]
    r = run_stage_cmd("L%s_lora" % layer, cmd, os.path.join(WORK, "L%s_lora.log" % layer), st=st,
                      env_extra={"ZMAX_L5_SUPERVISION": os.path.join(sup.get("supdir") or SUP_ROOT,
                                                                     "%s_supervision.jsonl" % layer.lower())})
    r["ok"] = r["rc"] == 0
    r["mode"] = "LoRA 适配 (r=8 · α=16 · 基座冻结, 只训 lora_A/B)"
    if not r["ok"]:
        r["reason"] = "rc=%s (见日志尾部)" % r["rc"]
    # 产物定位
    try:
        mroot = None
        for ln in reversed(r["tail"]):
            if "汇总:" in ln:
                mroot = ln.split("汇总:")[-1].strip()
                break
        r["report_dir"] = mroot
        if mroot:
            r["report_dir_abs"] = os.path.join(ROOT, mroot) if not os.path.isabs(mroot) else mroot
            sj = os.path.join(r["report_dir_abs"], "summary.json")
            if os.path.isfile(sj):
                r["summary"] = json.load(open(sj, encoding="utf-8"))
    except Exception:                                                       # noqa: BLE001
        pass
    return r


def stage_merge(st: dict, l4: dict, l3: dict, ts: str) -> dict:
    """LoRA **必须 merge** —— 不 merge 的产物加载即 Missing key → trained=False → 零动作伪装。
    复用 tools/merge_lora_ckpt.py (W = W_base + (α/r)·B@A), 绝不覆盖原产物。"""
    out = {"stage": "merge", "items": [], "ok": True}
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib.util as _iu

    def _find_l4_ckpt() -> str | None:
        cache = "/home/ubuntu/stable-wm-cache/checkpoints"
        cands = [os.path.join(cache, d) for d in sorted(os.listdir(cache))
                 if d.startswith("intact_goal_optical_insert_v6lora")]
        cands = [d for d in cands if os.path.isdir(d)]
        if not cands:
            return None
        d = max(cands, key=os.path.getmtime)
        pts = sorted(f for f in os.listdir(d) if f.endswith(".pt") and "merged" not in f)
        return os.path.join(d, pts[-1]) if pts else None

    def _find_l3_sf() -> str | None:
        """L3 (lerobot) ckpt 布局: <run>/checkpoints/<step>/pretrained_model/model.safetensors
        (也有直接 <run>/checkpoints/<step>/model.safetensors 的老布局) —— 两种都查,
        ⚠️ 2026-09-28 实测第一版只查后者 → 明明训出来了却报"未找到 L3 训练 ckpt"。"""
        base = os.path.join(ROOT, "outputs", "train")
        if not os.path.isdir(base):
            return None
        try:
            ds = [d for d in sorted(os.listdir(base)) if d.startswith("smolvla_lew_lora_")
                  and d.endswith("_l5%s" % ts)]
        except Exception:                                                   # noqa: BLE001
            ds = []
        if not ds:
            try:
                ds = [d for d in sorted(os.listdir(base), key=lambda x: os.path.getmtime(
                    os.path.join(base, x))) if d.startswith("smolvla_lew_lora_")]
                ds = ds[-1:]
            except Exception:                                               # noqa: BLE001
                ds = []
        for d in reversed(ds):
            ck = os.path.join(base, d, "checkpoints")
            if not os.path.isdir(ck):
                continue
            steps = sorted(os.listdir(ck), key=lambda x: (x == "last", x))
            for s in reversed(steps):
                for _rel in ("pretrained_model/model.safetensors", "model.safetensors"):
                    sf = os.path.join(ck, s, _rel)
                    if os.path.isfile(sf):
                        return sf
        return None

    # L4: 走 merge_lora_ckpt.py 原命令 (intact venv 的 torch)
    p4 = _find_l4_ckpt()
    item4 = {"layer": "L4", "src": p4}
    if not p4:
        item4.update({"ok": False, "reason": "未找到本次 LoRA 产物 (checkpoints/intact_goal_optical_insert_v6lora*)"})
    else:
        dst = p4.replace(".pt", "_merged.pt")
        cmd = [PY_INTACT if os.path.isfile(PY_INTACT) else PY,
               os.path.join(ROOT, "tools", "merge_lora_ckpt.py"),
               "--in", p4, "--out", dst, "--r", "8", "--alpha", "16"]
        rr = run_stage_cmd("merge_L4", cmd, os.path.join(WORK, "merge_L4.log"), st=st)
        item4.update({"dst": dst, "rc": rr["rc"], "log": rr["log"],
                      "exists": os.path.isfile(dst),
                      "head": rr["head"][-4:], "ok": rr["rc"] == 0 and os.path.isfile(dst)})
        if not item4["ok"]:
            item4["reason"] = "merge 失败 (rc=%s)" % rr["rc"]
    out["items"].append(item4)
    out["ok"] = out["ok"] and item4.get("ok", False)

    # L3: lerobot ckpt (safetensors) —— 有 lora_* 键才折叠, 无键如实报"框架内无 LoRA 包装键"
    p3 = None
    try:
        p3 = _find_l3_sf()
    except Exception:                                                       # noqa: BLE001
        p3 = None
    item3 = {"layer": "L3", "src": p3}
    if not p3:
        item3.update({"ok": False, "reason": "未找到 L3 训练 ckpt (model.safetensors)"})
    else:
        try:
            spec = _iu.spec_from_file_location("merge_lora_ckpt", os.path.join(ROOT, "tools", "merge_lora_ckpt.py"))
            mlc = _iu.module_from_spec(spec)
            spec.loader.exec_module(mlc)
            from safetensors import safe_open
            keys = []
            with safe_open(p3, framework="pt", device="cpu") as f:
                keys = list(f.keys())
            n_lora = sum(1 for k in keys if k.endswith(".lora_A") or k.endswith(".lora_B"))
            item3["n_tensors"] = len(keys)
            item3["n_lora_tensors"] = n_lora
            if n_lora == 0:
                item3.update({"ok": True, "merge": "not_needed",
                              "reason": "ckpt 内无 lora_A/B 包装键 (自研 lora_inject 训练时已按低秩注入, "
                                        "保存的就是合并后的可部署命名) → 无需二次 merge; 已核键名"})
            else:
                import torch
                sd = {}
                with safe_open(p3, framework="pt", device="cpu") as f:
                    for k in keys:
                        sd[k] = f.get_tensor(k)
                merged, stt = mlc.merge(sd, 8, 16.0)
                dst = p3.replace("model.safetensors", "model_merged.safetensors")
                try:
                    from safetensors.torch import save_file
                    save_file({k: v.contiguous() for k, v in merged.items()}, dst)
                except Exception:                                           # noqa: BLE001
                    torch.save(merged, dst.replace(".safetensors", ".pt"))
                    dst = dst.replace(".safetensors", ".pt")
                bad = [k for k in merged if "lora" in k.lower() or ".base." in k]
                item3.update({"dst": dst, "exists": os.path.isfile(dst), "stats": stt,
                              "residual_wrapped_keys": len(bad),
                              "ok": os.path.isfile(dst) and not bad})
        except Exception as e:                                              # noqa: BLE001
            import traceback
            item3.update({"ok": False, "reason": "%s: %s" % (type(e).__name__, e),
                          "tb": traceback.format_exc().strip().splitlines()[-3:]})
    out["items"].append(item3)
    out["ok"] = out["ok"] and item3.get("ok", False)
    return out


# ─────────────────────────── ④ 验证/指针 ───────────────────────────
def stage_verify(st: dict, res: dict, ts: str) -> dict:
    """产物登记为 candidates + 真加载验证 (不切在役指针 —— 未证明提升不上线)"""
    import importlib.util as _iu
    spec = _iu.spec_from_file_location("model_autoload", os.path.join(ROOT, "tools", "model_autoload.py"))
    ma = _iu.module_from_spec(spec)
    sys.modules["model_autoload"] = ma
    spec.loader.exec_module(ma)
    reg = ma.load_registry(create=True)
    cands = reg.setdefault("candidates", {})
    l2 = res.get("L2_full") or {}
    l3m = next((i for i in ((res.get("merge") or {}).get("items") or []) if i["layer"] == "L3"), {})
    if l2.get("artifact_ok"):
        cands["L2"] = {"path": os.path.relpath(l2["best"], ROOT), "ts": ts,
                       "mode": l2.get("mode"), "sha16": ma._sha16(l2["best"]),
                       "note": "L5 全量训练产物 · **未切在役指针** (上线需同口径对照证明提升: "
                               "tools/yolo_live_eval.py + model_autoload.py --promote L2)"}
    if l3m.get("dst") and l3m.get("exists"):
        cands["L3"] = {"path": l3m["dst"], "ts": ts, "merge": l3m.get("merge") or "merged",
                       "sha16": ma._sha16(l3m["dst"]),
                       "note": "L5 LoRA 适配产物 (已按可部署口径处理)"}
    ma.write_registry(reg)
    r = {"stage": "verify", "registry": os.path.relpath(ma.REG_PATH, ROOT),
         "candidates": {k: v.get("path") for k, v in cands.items()},
         "resolve": {}, "ok": True}
    for k, v in cands.items():
        path = v["path"] if os.path.isabs(v["path"]) else os.path.join(ROOT, v["path"])
        ent = {"kind": {"L2": "yolo", "L3": "smolvla", "L4": "intact"}.get(k), "path": path}
        r["resolve"][k] = ma.resolve_layer(k, ent)
    return r


# ─────────────────────────── 编排 ───────────────────────────
def planned(a) -> list:
    return [s for s in STAGES if (not a.only or s in a.only.split(","))]


def main() -> int:
    ap = argparse.ArgumentParser(description="L5 标注→训练闭环编排器")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--only", default="", help="逗号分隔: interact,annotate,supervision,slots,L2_full,L3_lora,L4_lora,merge,verify")
    ap.add_argument("--cams", default="", help="auto_annotate 的相机 (默认 6 路)")
    ap.add_argument("--push-overlay", action="store_true")
    ap.add_argument("--yolo-epochs", type=int, default=10)
    ap.add_argument("--steps", type=int, default=40, help="L3/L4 LoRA 有界步数")
    ap.add_argument("--l3-batch", type=int, default=2)
    ap.add_argument("--batch-dir", default="", help="复用已有标注批次 (跳过 annotate 阶段重跑)")
    a = ap.parse_args()

    if a.status:
        st = load_state()
        print(json.dumps({k: st.get(k) for k in ("status", "stage", "stages_done", "started",
                                                 "updated", "last_result", "stage_detail")},
                         ensure_ascii=False, indent=1))
        return 0

    ts = time.strftime("%y%m%d_%H%M%S")

    # 🔒 单实例闸门: 老倪演示时点 ▶运行, GUI 可能再 spawn 一个编排 → 明确拒绝, 不碰别人的 state
    if a.run and os.environ.get("ZMAX_L5_IGNORE_LOCK") != "1":
        _ok, _why = acquire_lock()
        if not _ok:
            print("⛔ L5 闭环未启动: %s" % _why)
            print("   (保护现场: 不抢 GPU / 不覆盖 state.json; 要强制并行设 ZMAX_L5_IGNORE_LOCK=1)")
            return 3
    todo = planned(a)
    print("🧿 L5 标注→训练闭环 · 阶段 %s" % ",".join(todo))
    print("   真源: 标注 tools/auto_annotate.py · 训练 tools/joint_train_all.py/yolo_annot_train.py"
          " · merge tools/merge_lora_ckpt.py")
    print("   红线: 串行(8GB 单模型) · 自动标注不进 val · 未证明提升不切在役指针 · LoRA 必 merge")
    print("   GPU 空闲 %s MB" % gpu_free())
    if a.dry_run or not a.run:
        print("\n(--dry-run/未加 --run: 只打印计划, 不执行)")
        return 0

    os.makedirs(WORK, exist_ok=True)
    st = load_state()
    st.update({"status": "running", "started": _now(), "run_ts": ts, "stages_done": [],
               "last_result": {}, "only": todo})
    save_state(st)
    res = st.setdefault("results", {})
    logf = os.path.join(WORK, "run_%s.log" % ts)

    def _say(s):
        print(s, flush=True)
        with open(logf, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (_now(), s))

    _say("=== L5 闭环开始 (%s) ===" % ts)
    sup = res.get("supervision") or {}
    try:
        for s in todo:
            st["stage"] = s
            save_state(st)
            refresh_lock(s, st.get("started") or "")
            if s == "interact":
                r = stage_interact(st, ts)
            elif s == "slots":
                r = stage_slots(st, ts)
            elif s == "annotate":
                r = stage_annotate(st, a.cams, a.push_overlay)
            elif s == "supervision":
                bd = a.batch_dir or (res.get("annotate") or {}).get("batch_dir")
                if not bd:
                    r = {"stage": "supervision", "ok": False, "reason": "无标注批次 (先跑 annotate)"}
                else:
                    r = stage_supervision(st, bd)
            elif s == "L2_full":
                r = stage_L2(st, sup, a.yolo_epochs, ts)
            elif s == "L3_lora":
                r = stage_LoRA(st, "L3", a.steps, ts, sup, a.l3_batch)
            elif s == "L4_lora":
                r = stage_LoRA(st, "L4", a.steps, ts, sup, a.l3_batch)
            elif s == "merge":
                r = stage_merge(st, res.get("L4_lora") or {}, res.get("L3_lora") or {}, ts)
            elif s == "verify":
                r = stage_verify(st, res, ts)
            else:
                r = {"stage": s, "ok": False, "reason": "未知阶段"}
            res[s] = r
            if s == "supervision":
                sup = r
            st["stages_done"] = list(res.keys())
            st["last_result"] = {k: v for k, v in r.items() if k not in ("head", "tail", "cmd")}
            save_state(st)
            _say("%s %s · %s" % ("✅" if r.get("ok") else "❌", s,
                                 r.get("reason") or ("rc=%s %.1fs" % (r.get("rc"), r.get("secs") or 0))))
            for ln in (r.get("head") or [])[:6]:
                _say("     | " + ln[-160:])
            if not r.get("ok") and os.environ.get("ZMAX_L5_CONTINUE_ON_FAIL") != "1":
                if r.get("non_fatal"):
                    # 🐛 2026-09-29: 可选输入的缺口 (如"尚未演示槽位") 只告警, 不掐断整链 ——
                    #   后面的训练阶段各有自己的退路与红线 (L2 退监督数据集; 空集仍拒绝启动)。
                    _say("⚠️ 阶段 %s 未过 (non_fatal: 可选输入缺口) → 继续后续阶段: %s"
                         % (s, r.get("reason") or ""))
                    continue
                _say("⛔ 阶段 %s 未过 → 停止后续 (设 ZMAX_L5_CONTINUE_ON_FAIL=1 可强跑)" % s)
                break
        # 终态口径: 有致命阶段未过 = failed; 只有 non_fatal 缺口 (如"尚未演示槽位"/"L2 零检出")
        # = done_with_gaps —— 链路本身跑通, 缺口如实记录 (不因缺口把整链报成"失败", 也不掩盖)。
        _gaps = [k for k in todo if not (res.get(k) or {}).get("ok")]
        st["gaps"] = _gaps
        st["status"] = ("done" if not _gaps
                        else ("done_with_gaps" if all((res.get(k) or {}).get("non_fatal") for k in _gaps)
                              else "failed"))
    except Exception as e:                                                  # noqa: BLE001
        import traceback
        st["status"] = "failed"
        st["error"] = "%s: %s" % (type(e).__name__, e)
        st["tb"] = traceback.format_exc().strip().splitlines()[-6:]
        _say("💥 编排异常: %s" % st["error"])
    st["finished"] = _now()
    save_state(st)
    _say("=== L5 闭环结束 · status=%s · 状态文件 %s ===" % (st.get("status"), STATE))
    return 0 if st.get("status") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
