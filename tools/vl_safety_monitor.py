#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vl_safety_monitor.py — 🛡 DeepSeek VL 进控制环: 视觉语言安全守护 (老倪 2026-09-27)

老倪: 「你现在有三个相机，还有深度信号，你的大模型，要负责安全保护。把 deepseek VL 加入控制循环」

工程约束(决定形态): VL 单次推理 **40~150s** ⇒ 不能"每步等它"。
所以做成 **慢传感器 + 快闸门**:
  ① 本进程(常驻) 每 N 秒抓 3 相机 + 1 深度 → 拼一张 2x2 图 → 问 DeepSeek VL 一个**从严**的安全问题
     → 写 ~/zmax_data/vl_safety.json (裁决 + 时间戳 + 各帧帧龄 + 证据图路径)
  ② 执行层(l2_daemon) 每次下发**运动前**读这个 JSON: 裁决不安全 / 过期 / 缺失 ⇒ **一律拒发**(fail-closed)
     —— 上层只给意图, 执行由最下层收口; 视觉安全闸就是收口的一部分。

判定从严(看不清=不安全, 不许猜):
  人手/人臂在活动范围 · 有物体挡住预期路径 · 工具已接触/将要接触非目标物 · 画面过暗过曝糊 ⇒ safe=false

用法:
  ./gui-venv311/bin/python tools/vl_safety_monitor.py              # 常驻(默认每 75s 一轮)
  ./gui-venv311/bin/python tools/vl_safety_monitor.py --once       # 只跑一轮(取证用)
  ./gui-venv311/bin/python tools/vl_safety_monitor.py --once --feishu   # 不安全时推飞书
输出: ~/zmax_data/vl_safety.json · 证据图 ~/zmax_data/vl_safety/<时刻>.jpg · 追加 ~/zmax_data/vl_safety_log.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import gen_overlay_from_vlm as G                                        # noqa: E402

STREAM = os.environ.get("ZMAX_STREAM", "http://127.0.0.1:8791")
OUT = Path(os.path.expanduser("~/zmax_data/vl_safety.json"))
IMGDIR = Path(os.path.expanduser("~/zmax_data/vl_safety"))
LOG = Path(os.path.expanduser("~/zmax_data/vl_safety_log.jsonl"))
CAMS = [("arm", "臂上相机(随工具)"), ("local", "笔记本相机(全局)"),
        ("local2", "MAXHUB顶视"), ("depth", "深度图(伪彩,近=亮)")]
# 🔧 2026-10-01 (老倪「L5自主安全打开」+「点了不动」根因): 可缺席视角在长时间无帧时**从拼图剔除**。
#   实测: MAXHUB 顶摄物理不在位(/dev/video4 不存在) ⇒ 快照接口仍返回**冻结的旧帧** ⇒ 拼图里每轮
#   都有一格 141s 陈旧画面 ⇒ 慢层每轮判 "顶视相机丢帧 ⇒ 不安全" ⇒ 所有动作 fail-closed 拒发。
#   关键视角(arm/local)不剔除 —— 它们缺了本来就该拒发, 仍放进拼图让模型看见并如实说。
STALE_S = float(os.environ.get("ZMAX_VL_CAM_STALE_S", "30"))
REQUIRED_CAMS = {"arm", "local"}
OPTIONAL_CAMS = {"local2", "depth"}
FRESH_S = 600.0          # 裁决保鲜: 超过这个秒数视为过期 ⇒ 拒发
TILE = (480, 360)

PROMPT = """你是工业机器人(珞石 6 轴 XMS5-R800)现场的安全守护。下面是**同一时刻**的工位画面 2x2 拼图:
左上=臂上相机(装在工具上, 随机械臂移动) 右上=笔记本相机(全局工位视角)
左下=MAXHUB顶视 右下=深度图(伪彩, 越亮=越近)
机器人 TCP 此刻在 base 系 (0.6488, 0.4983, 0.1104) m, 即将执行小幅垂直/平移动作(几十~几百毫米, 慢速 5mm/s)。

**只看安全, 只输出 JSON**, 不要多余文字:
{"safe": true 或 false,
 "risk_level": "low" 或 "medium" 或 "high",
 "arm_path_clear": true 或 false,
 "hazards": [{"what": "人手/人臂/障碍物/工具干涉/线缆/标定板/其他", "where": "在哪个画面什么位置", "why": "判断依据"}],
 "why": "一句话结论"}

从严判定(任何一条成立 ⇒ safe=false):
 · 有人手或人臂**伸进机械臂/托盘/夹具/工具的活动区**(画面里机械臂近旁、托盘上方那一小块), 或身体压在工作台上方
 · 有物体挡住机械臂可能的运动路径
 · 工具已接触或明显将要接触非目标物体(压到标定板/线缆/托盘边缘)
 · 画面过暗、过曝、模糊、被遮挡, 以至于**看不出**是否安全 —— 看不清就当不安全, 不许猜。

不算危害(正常作业, 照常 safe=true):
 · 操作员**站在工位外围观察** —— 判定看**几何**: 身体与手有没有**越过工位围栏 / 进入机械臂可达空间**;
   坐在工位外的桌子或控制台前操作电脑(含手臂搁在桌上、身体前倾) ⇒ **不算危害**(MAXHUB 顶视图里能看到这种场景);
   只有当人**跨过围栏、把手/臂伸到机械臂、托盘、工具近旁或路径上**才算。
 · 工位上安静放置的工装/器材(键盘、显示器、线缆、标定板等**不在活动路径上**的静止物)。
判据差别的关键词: **"伸进/压到/挡在路径上" = 危害**; **"站在外围看" = 不是危害**。"""


def _grab(name: str, timeout=12.0) -> bytes | None:
    try:
        with urllib.request.urlopen("%s/snapshot/%s.jpg?_=%d" % (STREAM, name, int(time.time())),
                                    timeout=timeout) as r:
            return r.read()
    except Exception:                                                   # noqa: BLE001
        return None


def _stats() -> dict:
    try:
        with urllib.request.urlopen("%s/stats" % STREAM, timeout=6) as r:
            return json.loads(r.read().decode())
    except Exception:                                                   # noqa: BLE001
        return {}


def build_mosaic(frames: dict) -> tuple[np.ndarray, dict]:
    """4 格拼图 + 顶部真值带(时刻/帧龄/TCP) —— 画面自带状态, 用户会把画面当结果"""
    ages = {}
    st = _stats()
    tiles = []
    absent = []
    for name, lab in CAMS:
        b = frames.get(name)
        im = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR) if b else None
        if im is None:
            im = np.zeros((TILE[1], TILE[0], 3), np.uint8)
            cv2.putText(im, "NO FRAME: " + name, (12, TILE[1] // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            im = cv2.resize(im, TILE)
        im = im.copy()
        cv2.rectangle(im, (0, 0), (TILE[0] - 1, 26), (0, 0, 0), -1)
        cv2.putText(im, lab, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
        fr = (st.get("frames") or st).get(name) or {}            # /stats 帧条目是顶层键
        a = fr.get("age_s") if isinstance(fr.get("age_s"), (int, float)) else fr.get("src_ts_age_s")
        ages[name] = round(float(a), 2) if isinstance(a, (int, float)) else None
        if name in OPTIONAL_CAMS and (frames.get(name) is None
                                      or (ages[name] is not None and ages[name] > STALE_S)):
            absent.append(name)          # 可缺席视角无帧/过期 ⇒ 剔除并如实记录(不参与判定)
            continue
        if ages[name] is not None:
            cv2.putText(im, "%.1fs" % ages[name], (TILE[0] - 78, 19), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 220, 255), 1)
        tiles.append(im)
    rows = [np.hstack(tiles[i:i + 2]) for i in (0, 2)]
    _W = max(r.shape[1] for r in rows)          # 剔了格子后各行宽度可能不等 ⇒ 补黑边再竖拼
    rows = [np.pad(r, ((0, 0), (0, _W - r.shape[1]), (0, 0))) for r in rows]
    body = np.vstack(rows)
    hdr = np.zeros((34, body.shape[1], 3), np.uint8)
    _cap = "Z-MAX VL SAFETY  " + time.strftime("%F %T") + "  TCP z=0.1104m"
    if absent:                                   # 画面自带状态: 哪几路缺席, 不靠人猜(老倪: 画面自身要标状态)
        _cap += "   [缺席: " + ",".join(absent) + "]"
    cv2.putText(hdr, _cap, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2)
    return np.vstack([hdr, body]), ages, absent


def run_once(feishu=False, save_img=True) -> dict:
    t0 = time.time()
    frames = {n: _grab(n) for n, _ in CAMS}
    mosaic, ages, absent = build_mosaic(frames)
    ok, enc = cv2.imencode(".jpg", mosaic, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
    h, w = mosaic.shape[:2]
    rec = {"ts": time.time(), "ts_str": time.strftime("%F %T"), "frames_age_s": ages,
           "views_absent": absent,          # 🔧 缺席视角如实记录(执行器/页面可读, 不伪造"都正常")
           "mosaic_wh": [w, h], "model": None, "latency_s": None}
    # 🎯 本次待执行动作(执行层排队时写入): 让 VL 只判"这一个动作", 而不是泛泛判画面
    #    没有意图时退回泛判(安全侧不变, 只是判得粗)。
    _it_seq, _it_desc, prompt = 0, "", PROMPT
    try:
        _it = json.loads(open(os.path.expanduser("~/zmax_data/vl_intent.json"), encoding="utf-8").read())
        _it_seq, _it_desc = int(_it.get("seq") or 0), str(_it.get("desc") or "")
    except Exception:                                                   # noqa: BLE001
        pass
    rec["intent_seq"], rec["intent_desc"] = _it_seq, _it_desc
    if _it_desc:
        prompt = PROMPT + ("\n\n=== 本次待执行动作(执行层已排队, 请针对这一个动作判安全) ===\n"
                           "%s\n按动作类型判:\n"
                           " · 纯横向平移/高度不变 ⇒ 工具与下方物体的距离不会变小, **不要**因为\"下方有标定板/托盘\"就否决;\n"
                           "   要看这次平移**要经过的那条路径**(含它扫过的空间)有没有障碍物。\n"
                           " · 抬升 ⇒ 远离下方物体, 重点看上方有没有横梁/遮挡。\n"
                           " · 下降 ⇒ 必须确认工具正下方(运动可达范围)没有板/线/异物, 余量不足或看不清 ⇒ safe=false。\n"
                           " · 原地姿态微调 ⇒ 位置不动, 只需确认周围无贴身干涉。\n"
                           "无论哪种动作: **人手/人臂伸进机械臂活动区或该动作路径上 ⇒ 一律 safe=false**(此条永远优先)。"
                           % _it_desc)
        rec["prompt_intent"] = True
    img_path = ""
    if save_img:
        IMGDIR.mkdir(parents=True, exist_ok=True)
        img_path = str(IMGDIR / (time.strftime("%Y%m%d_%H%M%S") + ".jpg"))
        cv2.imwrite(img_path, mosaic)
        rec["image"] = img_path
    try:
        # 实测(2026-09-27): DeepSeek 视觉**偶发**返回空 content —— finish_reason=stop 却无内容,
        # 快(2.7s)/慢(137s)都可能出现, 且同样的图再调一次就正常 ⇒ 空了就重试。
        # 旧逻辑按"慢返回空=拥塞, 不重试"处理, 把 49.5s 那次直接落成"不安全" ⇒ 误报真因。
        r = {}
        for _try in range(3):
            r = G.call_vlm(enc.tobytes(), w, h, prompt=prompt, timeout=300)
            if (r.get("txt") or "").strip():
                break
            print("[%s] VL 空 content(第%d次, %.1fs) ⇒ 2s 后重试  raw=%s" % (
                time.strftime("%H:%M:%S"), _try + 1, float(r.get("latency_s") or 0),
                str(r)[:140]), flush=True)
            time.sleep(2)
        rec["model"] = r.get("model")
        rec["latency_s"] = round(float(r.get("latency_s") or 0), 1)
        txt = (r.get("txt") or "").strip()
        if not txt:
            # 空 content = 模型这次没给出裁决(API 侧偶发), 语义是"无法裁决"而不是"画面有危险"。
            # 仍 fail-closed(safe=False ⇒ 执行层拒发), 但 hazards 置空 + why 写明,
            # 避免被读成"现场有危险" ⇒ 老倪 22:58 收到的误报就是这么来的。
            rec.update({"safe": False, "risk_level": "high", "arm_path_clear": False,
                        "hazards": [],
                        "why": "VL 连续 3 次返回空 content(DeepSeek 视觉侧偶发, 非超时/额度) ⇒ "
                               "本帧无法裁决 ⇒ 拒发(不是'现场危险')", "degraded": True})
        else:
            d = G.parse_json(txt)
            rec["safe"] = bool(d.get("safe") is True)
            rec["risk_level"] = str(d.get("risk_level") or "high")
            rec["arm_path_clear"] = bool(d.get("arm_path_clear") is True)
            rec["hazards"] = d.get("hazards") or []
            rec["why"] = str(d.get("why") or "")[:300]
    except Exception as e:                                              # noqa: BLE001
        rec.update({"safe": False, "risk_level": "high", "arm_path_clear": False,
                    "hazards": [{"what": "VL 调用异常", "where": "-", "why": str(e)[:120]}],
                    "why": "VL 异常 ⇒ 从严当不安全", "degraded": True})
    # 同一动作相邻两轮的**原始结论一致性**: 摇摆(1安全1不安全) ⇒ 从严发布(安全层不许来回抽签);
    # 比较用"原始结论"而非已从严过的结论 ⇒ 一次瞬态(手伸进来)不会把它永久锁死。
    rec["raw_safe"] = rec.get("safe")
    try:
        _prev = None
        with open(LOG, encoding="utf-8") as _f:
            _lines = _f.readlines()[-8:]
        for _ln in reversed(_lines):
            try:
                _p = json.loads(_ln)
            except Exception:                                           # noqa: BLE001
                continue
            if (int(_p.get("intent_seq") or 0) == int(_it_seq)
                    and (_p.get("intent_desc") or "") == (rec.get("intent_desc") or "")
                    and float(_p.get("ts") or 0) < rec["ts"] - 1):
                _prev = _p
                break
        if (_prev is not None and _prev.get("raw_safe") is not None
                and bool(_prev["raw_safe"]) != bool(rec["raw_safe"]) and not rec.get("degraded")):
            # 2026-09-28 老倪现场「合爪技能怎么又不好使了」的根因修复。
            # 旧行为: 相邻两轮原始结论摇摆 ⇒ 一律按不安全拒发。实测后果(08:39:01)把一条
            #   **当轮裁决自己写着安全、hazards 为空** 的结论也否掉了(日志里 why 还留着"未见人手/人员在外围观察")。
            # 语义纠偏: 一次动作安全与否取决于**当轮画面**, 上一轮的结论只是旁证;
            #   ⇒ 摇摆时不再一律拒, 而是看当轮:
            #     ① 当轮=安全 且 危害列表为空 ⇒ 放行(记 flip_flop_resolved, 供审计)
            #     ② 当轮=不安全 ⇒ 维持从严拒发(fail-closed 方向不变)
            #     ③ degraded(空 content / 调用异常)不参与摇摆判定, 仍走各自拒绝路径
            rec["flip_flop"] = True
            _prev_txt = "安全" if _prev["raw_safe"] else "不安全"
            _haz = rec.get("hazards") or []
            rec["rounds"] = [
                {"ts": _prev.get("ts_str"), "raw_safe": bool(_prev["raw_safe"]),
                 "why": str(_prev.get("why") or "")[:160]},
                {"ts": rec.get("ts_str"), "raw_safe": bool(rec.get("raw_safe")),
                 "why": str(rec.get("why") or "")[:160]},
            ]
            if bool(rec["raw_safe"]) and not _haz:
                rec["flip_flop_resolved"] = True
                rec["why"] = ("相邻两轮摇摆(上轮原始=%s), 但**当轮=安全且危害列表为空** ⇒ 放行 · 当轮理由: %s"
                              % (_prev_txt, rec.get("why")))
            else:
                rec["why"] = "同一动作相邻两轮结论不一致(上轮原始=%s) ⇒ 从严当不安全: %s" % (
                    _prev_txt, rec.get("why"))
                rec["safe"] = False
                rec["risk_level"] = "high"
    except Exception:                                                   # noqa: BLE001
        pass
    rec["elapsed_s"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("[%s] safe=%s risk=%s path_clear=%s why=%s (%.0fs)"
          % (rec["ts_str"], rec.get("safe"), rec.get("risk_level"), rec.get("arm_path_clear"),
             rec.get("why"), rec.get("elapsed_s") or 0), flush=True)
    if feishu and not rec.get("safe"):
        try:
            import aoi_feishu_push as P
            P.send_text("🛡 VL 安全守护: **不安全** risk=%s\n%s\n危害: %s\n(mosaic: %s)"
                        % (rec.get("risk_level"), rec.get("why"),
                           json.dumps(rec.get("hazards"), ensure_ascii=False)[:400], img_path))
        except Exception as e:                                          # noqa: BLE001
            print("  飞书推送失败: %s" % str(e)[:120], flush=True)
    return rec


def read_verdict(fresh_s: float = FRESH_S, path: Path = OUT) -> tuple[bool, dict]:
    """执行层用: 返回 (是否允许动作, 裁决详情)。缺失/过期/不安全 ⇒ 不允许(fail-closed)"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:                                              # noqa: BLE001
        return False, {"why": "无 VL 安全裁决文件 ⇒ 拒发", "err": str(e)[:120], "age_s": None}
    age = time.time() - float(d.get("ts") or 0)
    d["age_s"] = round(age, 1)
    if age > fresh_s:
        d["stale"] = True
        return False, d
    return bool(d.get("safe")), d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=float, default=75.0)
    ap.add_argument("--feishu", action="store_true", help="不安全时推飞书")
    a = ap.parse_args()
    if a.once:
        r = run_once(a.feishu)
        return 0 if r.get("safe") else 0
    print("🛡 VL 安全守护常驻: 每 %.0fs 一轮 · 保鲜 %.0fs · 输出 %s" % (a.every, FRESH_S, OUT), flush=True)
    import threading

    def _intent_now():
        try:
            it = json.loads(open(os.path.expanduser("~/zmax_data/vl_intent.json"), encoding="utf-8").read())
            return int(it.get("seq") or 0), str(it.get("desc") or "")
        except Exception:                                               # noqa: BLE001
            return 0, ""

    def _publish_degraded(seq, desc, why):
        """本轮卡住也要落一份**针对当前意图**的降级裁决: 执行层据此快速拒发, 不许干等。"""
        rec = {"ts": time.time(), "ts_str": time.strftime("%F %T"), "safe": False, "risk_level": "high",
               "arm_path_clear": False, "degraded": True, "intent_seq": seq, "intent_desc": desc,
               "hazards": [{"what": "安全守护本轮未完成", "where": "-", "why": why}],
               "why": "VL 本轮未在 %s 内给出裁决 ⇒ 从严当不安全" % why}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("[%s] 降级裁决已落盘(seq=%s): %s" % (rec["ts_str"], seq, why), flush=True)

    # ⏱ 单轮上限: 文件头写"VL 单次 40~150s", 但**带 2x2 拼图的实际单轮实测 137~168s**
    #   (2026-09-28 现场: 137/154/158.6/168s) ⇒ 默认 150s 会每轮都判"卡住"落降级裁决,
    #   把一个"慢但正常"的 VL 说成"未给出裁决", 现场看到的就是莫名其妙的"从严当不安全"。
    #   取值与调用方口径对齐 (l2_daemon VL_INTENT_WAIT_S=300 / 记忆: DeepSeek 单次 29~137s)。
    ct = float(os.environ.get("ZMAX_VL_CYCLE_TIMEOUT_S", "300"))
    while True:
        box = {}

        def _work(b=box):
            try:
                b["r"] = run_once(a.feishu)
            except Exception as e:                                      # noqa: BLE001
                b["e"] = "%s: %s" % (type(e).__name__, str(e)[:140])

        th = threading.Thread(target=_work, daemon=True)
        th.start()
        th.join(ct)
        if th.is_alive():          # 一轮卡住 ⇒ 立刻落"针对当前意图"的降级裁决, 每 15s 续一次, 直到它结束
            print("⚠️ 本轮超过 %.0fs 未完成(疑远端 VL 卡住) → 落降级裁决" % ct, flush=True)
            while th.is_alive():
                _publish_degraded(*_intent_now(), "%.0fs" % ct)
                time.sleep(15)
        seq_done = int((box.get("r") or {}).get("intent_seq") or 0)
        t0 = time.time()
        while time.time() - t0 < a.every:      # 睡满节拍; 但**意图一变立刻重跑**(执行层正等这个动作的裁决)
            time.sleep(2.0)
            cur = _intent_now()[0]
            if cur != seq_done:
                print("🎯 检测到新动作意图(seq %s→%s) → 立即重跑一轮" % (seq_done, cur), flush=True)
                break


if __name__ == "__main__":
    raise SystemExit(main())
