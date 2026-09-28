#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
l5_hil_agent.py — Hermes(我) 与老倪的 **HIL 人机在环互动 + 引擎 L5 自动标注环**
════════════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 「我会从手动控制台控制机器人, 运行 L5 功能; 你从**人机在环节点**与我互动,
                  你自己调用**状态空间工程的 L5 视觉语言大模型能力**, 一边理解, 一边自动标注,
                  根据与我的互动, 完成场景理解与适配。」

链路 (全部真实, 只读):
  老倪(hil.html / 画布 n_hil 节点) ──指示──▶ ECS relay /api/relay/agent/prompt (seq 游标)
        ⇩ 本工具轮询 ?after=N (幂等)
  触发 → 抓 arm 实帧 → **引擎 L5** (state_space/scene_vlm.py :: SceneVLM.ask)
        → 复用 tools/gen_overlay_from_vlm.py 的提示词/解析/落盘 (框写到 overlay vlm 层 = 自动标注)
        → 回执 POST /agent/reply {prompt_seq, from:"hermes-L5"} (老倪在同一个界面上看到我的答复)
  另一个触发源: reports/moveit/pause_points.jsonl 新参考点 P_n (他停顿时自动理解那个视角)

红线(与 n_hil/hil_bridge 一致): 动作类指示一律**不派发、不真动**, 只回执"只记账待授权;
真动走 /ctl/* 两步授权"。本工具只读帧、只写标注与回执。

用法:
  ./gui-venv311/bin/python tools/l5_hil_agent.py --self-test          # 引擎 L5 连通性(不出动作)
  ./gui-venv311/bin/python tools/l5_hil_agent.py --once               # 处理一轮(有指示才跑 L5)
  ./gui-venv311/bin/python tools/l5_hil_agent.py --watch --interval 3 --seconds 7200
  ./gui-venv311/bin/python tools/l5_hil_agent.py --ask-hint "看光模块的朝向, 标出 3D 长方体"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))

RELAY = os.environ.get("ZMAX_RELAY_BASE", "https://datadrive.world/api/relay")
STATE = os.path.join(ROOT, "reports", "l5_hil_agent_state.json")
LOG = os.path.join(ROOT, "reports", "l5_hil_interact.jsonl")
PAUSES = os.path.join(ROOT, "reports", "moveit", "pause_points.jsonl")
MOTION_PAT = re.compile(r"(插入|抓取|夹爪|夹紧|移动|运动|下发|示教|拍照|启动产线|回位|抓|插|拔|推|拉|执行动作|动一下|伸过去)")
# 实测坑(2026-09-29): 机器自己的桥每 ~60s 往同一个队列发一条 "status 状态空间" (from=web-hw-bridge)
# ⇒ 若不过滤, 会把它当成"人的指示", 每分钟白跑一次 L5 并往队列刷回执。
MACHINE_FROM = {"web-hw-bridge", "L5 状态空间节点", "hil_bridge", "hermes-L5", "ss_web_agent", "L5 节点"}
# 只过滤"整条就是一个裸探询词"(宁松勿严: 老倪真说的话不能被吃掉, 例如 "状态: 看光模块" 必须放行)
PROBE_PAT = re.compile(r"^\s*(status|状态|状态空间|画布|节点数|仿真|aoi|net|help|能力清单|自检)\s*[?？。!！,，]*\s*$", re.I)


# ───────────────────────────── 中转通道 (只读轮询 / 回执) ──────────────────
def _get(path, timeout=20):
    with urllib.request.urlopen(RELAY + path, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _post(path, obj, timeout=30):
    req = urllib.request.Request(RELAY + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def load_state() -> dict:
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        return {"cursor": 0, "last_pause": 0, "n": 0, "t0": time.time()}


def save_state(s: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def reply(text: str, prompt_seq=None, action=None) -> dict:
    """回执给老倪(他用的那个界面会显示; from 标明是我)"""
    body = {"prompt_seq": prompt_seq, "text": text, "from": "hermes-L5", "action": action}
    try:
        return _post("/agent/reply", body)
    except Exception as e:                                                   # noqa: BLE001
        print("  ⚠️ 回执失败: %s: %s" % (type(e).__name__, e), flush=True)
        return {"ok": False, "why": str(e)}


# ───────────────────────────── 引擎 L5 (状态空间工程的能力) ────────────────
_ENGINE = {"vlm": None, "err": None, "calls": 0, "ms": []}


def engine_vlm():
    if _ENGINE["vlm"] is None and _ENGINE["err"] is None:
        try:
            from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM
            _ENGINE["vlm"] = SceneVLM.get()
            print("  🧠 引擎 L5 就绪: %s" % json.dumps(_ENGINE["vlm"].health()
                                                    if hasattr(_ENGINE["vlm"], "health") else
                                                    {"provider": _ENGINE["vlm"].provider,
                                                     "model": _ENGINE["vlm"].model}, ensure_ascii=False)[:160],
                  flush=True)
        except Exception as e:                                               # noqa: BLE001
            _ENGINE["err"] = "%s: %s" % (type(e).__name__, e)
            print("  ⚠️ 引擎 L5 加载失败: %s" % _ENGINE["err"], flush=True)
    return _ENGINE["vlm"]


def patch_gen_overlay_to_engine() -> bool:
    """把 gen_overlay_from_vlm 的**模型调用**换成引擎 L5(其余提示词/解析/落盘全复用)。

    这样"自动标注"用的是**状态空间工程的 L5 能力**, 而不是另开一条自留地。
    """
    import gen_overlay_from_vlm as G
    if getattr(G, "_engine_patched", False):
        return True
    orig = G.call_vlm

    def call_vlm_engine(jpg_bytes, w, h, timeout=300, prompt=None):
        vlm = engine_vlm()
        if vlm is None:                                    # 引擎不可用 ⇒ 如实回退(并标明)
            r = orig(jpg_bytes, w, h, timeout=timeout, prompt=prompt)
            r["via"] = "fallback:gen_overlay_from_vlm (引擎 L5 不可用)"
            return r
        fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="l5hil_")
        os.write(fd, jpg_bytes)
        os.close(fd)
        try:
            t0 = time.time()
            r = vlm.ask(tmp, prompt if prompt is not None else G.PROMPT.format(W=w, H=h),
                        max_tokens=int(os.environ.get("SS_VLM_MAXTOK_AGENT", G.MAXTOK)))
            _ENGINE["calls"] += 1
            _ENGINE["ms"].append(int((time.time() - t0) * 1000))
            if not r.get("ok"):
                raise RuntimeError("引擎 L5 未返回: %s" % r.get("why"))
            return {"txt": (r.get("text") or "").strip(), "reasoning": "",
                    "model": r.get("src"), "usage": None,
                    "latency_s": round(time.time() - t0, 1), "via": "engine:SceneVLM"}
        except Exception as e:                                               # noqa: BLE001
            r = orig(jpg_bytes, w, h, timeout=timeout, prompt=prompt)
            r["via"] = "fallback:gen_overlay_from_vlm (引擎报错 %s)" % type(e).__name__
            return r
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    G.call_vlm = call_vlm_engine
    G._engine_patched = True
    return True


def l5_annotate(cam: str, hint: str, negatives=None, keep=None) -> dict:
    """跑一次「引擎 L5 理解 + 自动标注」: 抓帧 → L5 → 框写 overlay vlm 层。返回结果摘要。"""
    import gen_overlay_from_vlm as G
    patch_gen_overlay_to_engine()
    t0 = time.time()
    txt = G.main_cli(cam=cam, hint=hint, negatives=negatives, keep=keep)
    import scene_overlay as SO
    spec = SO.load_spec()
    els = [b for b in (spec["cameras"][cam].get("boxes") or []) if b.get("origin") == "vlm"]
    return {"hint": hint, "cam": cam, "secs": round(time.time() - t0, 1),
            "n_boxes": len(els),
            "labels": [str(b.get("label"))[:24] for b in els][:12],
            "summary": str(txt)[:300] if txt else ""}


def l5_correct(cam: str = "arm", hint: str = "") -> dict:
    """让**引擎 L5 负责判定「哪里不对、该怎么样」**并校正叠加:
    overlay 里已有框 ⇒ 逐框判 keep/junk/fix + 找漏检 → 应用(台账+spec备份, 可回退);
    没有框 ⇒ 退回「标注」模式(先标再说)。"""
    import l5_overlay_correct as C
    import scene_overlay as SO
    spec = SO.load_spec()
    if not (spec["cameras"][cam].get("boxes") or []):
        r = l5_annotate(cam, hint)
        return {"mode": "annotate", **r}
    neg = list((spec.get("deleted") or {}).get(cam) or [])
    os.environ["L5CORR_THINK"] = "1"                     # 判定要细 ⇒ 开思考(慢层)
    t0 = time.time()
    r = C.ask_l5(cam, hint, neg)
    out = {"mode": "correct", "ok": bool(r.get("ok")), "secs": round(time.time() - t0, 1),
           "why": r.get("why"), "hint": hint}
    v = r.get("verdict") or {}
    if r.get("ok") and v:
        out["counts"] = {"junk": len(v.get("junk") or []), "fix": len(v.get("fix") or []),
                         "missing": len(v.get("missing") or []), "ok": len(v.get("ok") or [])}
        out["reasons"] = [str(x.get("why"))[:90] for x in ((v.get("junk") or []) + (v.get("missing") or []))][:4]
        out["applied"] = C.apply_verdict(cam, v)
        with open(os.path.join(os.path.dirname(LOG), "l5_overlay_corrections.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%F %T"), "cam": cam, "hint": hint,
                                "verdict": v, "secs": out["secs"], "applied": out["applied"],
                                "via": "hil_loop"}, ensure_ascii=False) + "\n")
    return out


def _correct_msg(pfx: str, r: dict) -> str:
    if r.get("mode") == "annotate":
        return ("%s · L5 标注(叠加里原本没有框) · %.0fs · 框 %d 个%s\n   场景: %s"
                % (pfx, r.get("secs") or 0, r.get("n_boxes") or 0,
                   ("[" + ", ".join(r.get("labels") or []) + "]") if r.get("labels") else "",
                   (r.get("summary") or "")[:200]))
    if not r.get("ok"):
        return "%s · L5 校正未出判定: %s" % (pfx, r.get("why"))
    c = r.get("counts") or {}
    ap = r.get("applied") or {}
    return ("%s · L5 校正 %.0fs · 判定 删%d 改%d 补%d 保留%d → 应用 删%d 改%d 补%d\n   %s"
            % (pfx, r.get("secs") or 0, c.get("junk", 0), c.get("fix", 0), c.get("missing", 0),
               c.get("ok", 0), ap.get("junk", 0), ap.get("fix", 0), ap.get("missing", 0),
               " | ".join(r.get("reasons") or [])[:260]))


# ───────────────────────────── 触发源 ─────────────────────────────────────
_SEEN_SKIP = set()
_MAX_SEEN = [0]          # 本进程见过的最大 seq(含被过滤的; 用于推进游标, 否则每次轮询重读)


def new_instructions(cur: int) -> list:
    """拉人的指示(只读游标)"""
    try:
        d = _get("/agent/prompt?after=%d" % int(cur))
    except Exception as e:                                                   # noqa: BLE001
        print("  ⚠️ 拉指示失败: %s: %s" % (type(e).__name__, e), flush=True)
        return []
    items = [it for it in (d.get("items") or d.get("prompts") or []) if it.get("seq")]
    for it in items:                                  # 见过的都记(过滤掉的也要推游标)
        _MAX_SEEN[0] = max(_MAX_SEEN[0], int(it.get("seq") or 0))
    keep = []
    for it in items:
        src = str(it.get("from") or "")
        txt = str(it.get("text") or "")
        if src in MACHINE_FROM or PROBE_PAT.match(txt):
            if it.get("seq") not in _SEEN_SKIP:            # 同一条只报一次, 不刷屏
                _SEEN_SKIP.add(it.get("seq"))
                print("  ↷ 跳过(机器来源/探询词) seq=%s from=%s %r"
                      % (it.get("seq"), src or "-", txt[:24]), flush=True)
            continue
        keep.append(it)
    return keep


def new_pause_points(after: int) -> list:
    if not os.path.isfile(PAUSES):
        return []
    out = []
    try:
        for i, line in enumerate(open(PAUSES, encoding="utf-8")):
            if not line.strip():
                continue
            if i >= after:
                d = json.loads(line)
                d["_idx"] = i + 1
                out.append(d)
    except Exception:                                                        # noqa: BLE001
        return []
    return out


def handle_instruction(it: dict, st: dict) -> str:
    text = str(it.get("text") or "")
    print("\n[%s] 📩 老倪: %s" % (time.strftime("%H:%M:%S"), text), flush=True)
    if MOTION_PAT.search(text):
        msg = ("🙋 收到(只读红线): 「%s」属于**动作类**指示 —— 我不代发任何真机动作, 已记账为**待授权**; "
               "要真动请在手动控制台走 /ctl/* 两步授权(现场由你确认)。"
               "我可以同时做的: 对这个视角跑一次 L5 理解 + 自动标注(不出动作)。" % text[:60])
        rec = {"ts": time.strftime("%F %T"), "kind": "motion_refused", "text": text}
    else:
        r = l5_correct("arm", hint=text)
        msg = _correct_msg("📩 按你说的校正(你的话=最高优先级)", r)
        rec = {"ts": time.strftime("%F %T"), "kind": "l5_correct", "text": text, "result": r}
    rep = reply(msg, prompt_seq=it.get("seq"))
    rec["reply_ok"] = bool(rep.get("ok"))
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("  ↳ 已回执(seq=%s ok=%s): %s" % (it.get("seq"), rec["reply_ok"], msg[:150]), flush=True)
    return msg


def handle_pause(p: dict, st: dict) -> str:
    n = p.get("id") or ("P%d" % len(new_pause_points(0)))
    hint = ("现场示教停顿点 %s: 机械臂停在这个位姿(关节 %s, TCP %s)。"
            "请理解此刻臂上相机里看到什么: 有哪些工件/槽位/标记, 光模块在哪、朝向如何, "
            "并把能确认的东西标出来。" % (n, p.get("joints"), p.get("tcp")))
    r = l5_correct("arm", hint=hint)
    msg = _correct_msg("📍 参考点 %s" % n, r)
    rep = reply(msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%F %T"), "kind": "pause_annotate",
                            "pause": n, "result": r, "reply_ok": bool(rep.get("ok"))},
                           ensure_ascii=False) + "\n")
    print("  ↳ 参考点 %s 已理解并回执: %s" % (n, msg[:150]), flush=True)
    return msg


def main() -> int:
    ap = argparse.ArgumentParser(description="HIL 互动 + 引擎 L5 自动标注环 (只读)")
    ap.add_argument("--self-test", action="store_true", help="只验引擎 L5 连通性")
    ap.add_argument("--ask-hint", default="", help="直接对当前 arm 帧跑一次 L5 (给的提示词)")
    ap.add_argument("--say", default="", help="只回一条消息给老倪(不跑 L5)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=7200.0)
    ap.add_argument("--cam", default="arm")
    a = ap.parse_args()

    if a.say:
        r = reply(a.say)
        print("  回执: %s" % json.dumps(r, ensure_ascii=False)[:200])
        return 0
    if a.self_test:
        vlm = engine_vlm()
        if vlm is None:
            print("  ❌ 引擎 L5 不可用: %s" % _ENGINE["err"]); return 2
        import auto_annotate as AA
        fd, tmp = tempfile.mkstemp(suffix=".jpg"); os.write(fd, AA.grab(a.cam)); os.close(fd)
        t0 = time.time()
        r = vlm.ask(tmp, "一句话回答: 这张机械臂末端相机的图里主要有什么?", max_tokens=300)
        print("  → ok=%s %.1fs %s" % (r.get("ok"), time.time() - t0,
                                     (r.get("text") or r.get("why") or "")[:200]))
        os.unlink(tmp)
        return 0 if r.get("ok") else 3
    if a.ask_hint:
        print(json.dumps(l5_annotate(a.cam, a.ask_hint), ensure_ascii=False, indent=1)[:900])
        return 0

    st = load_state()
    print("🌐 HIL↔L5 环启动: 中转=%s · 游标=%s · 停顿点游标=%s · 日志=%s"
          % (RELAY, st.get("cursor"), st.get("last_pause"), os.path.relpath(LOG, ROOT)), flush=True)
    t0 = time.time()
    while True:
        st = load_state()
        # ① 人的指示
        _items = new_instructions(int(st.get("cursor") or 0))
        _maxseq = max([int(st.get("cursor") or 0), int(_MAX_SEEN[0])])
        for it in _items:
            try:
                handle_instruction(it, st)
            except Exception as e:                                           # noqa: BLE001
                print("  ⚠️ 处理指示异常: %s: %s" % (type(e).__name__, e), flush=True)
            st["n"] = int(st.get("n") or 0) + 1
            st["cursor"] = max(int(st.get("cursor") or 0), int(it.get("seq") or 0))
            save_state(st)
        if _maxseq > int(st.get("cursor") or 0):           # 跳过的条目也要推游标(=已看过)
            st["cursor"] = _maxseq
            save_state(st)
        # ② 新参考点
        for p in new_pause_points(int(st.get("last_pause") or 0)):
            try:
                handle_pause(p, st)
            except Exception as e:                                           # noqa: BLE001
                print("  ⚠️ 处理参考点异常: %s: %s" % (type(e).__name__, e), flush=True)
            st["last_pause"] = int(p.get("_idx") or st.get("last_pause") or 0)
            save_state(st)
        if a.once:
            break
        if not a.watch:
            break
        if time.time() - t0 > a.seconds:
            print("  ⏹ 到时退出(%.0fs)" % a.seconds, flush=True)
            break
        time.sleep(max(1.0, a.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
