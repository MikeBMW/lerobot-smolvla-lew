#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hil_bridge.py — 🙋 HIL 人机在环桥 (状态空间状态 → ECS web; 人的指示 → 回灌工程)

老倪 (2026-09-26): 「在状态空间工程增加 HIL Human in the loop 节点, 向 ECS web 发送状态空间状态;
我在 ECS 的浏览器上能给出要求; 就用 hermes 的标准浏览器的形式」

职责 (两向):
  ⬆ 上行: 每 N 秒把**真实状态空间状态**发到 ECS 中转 `/api/relay/hil/state`:
      分层健康(L2/L3/L4/L5) · 当前阶段(真机 tap 的 prod_stage) · 6 个事件预测(真调事件头, 输入=真机 obs)
      · 资源(GPU/磁盘/内存) · 核心思想话术(给人类看懂"现在在干什么") · 最近取证
  ⬇ 下行: 轮询 `/api/relay/agent/prompt` 收人的指示 → 映射成**只读/离线**动作并把结果写回 `agent/reply`
      红线: 任何"真机动作类"指示一律拒答 (未授权), 但如实回执"已记录为待授权请求"

用法: python3 tools/hil_bridge.py --once | --watch --interval 5 | --status
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = "/home/ubuntu/zmax_rel"
REPORTS = os.path.join(ROOT, "reports")
RELAY = os.environ.get("ZMAX_RELAY_BASE", "https://datadrive.world/api/relay")
TAP_DIR = "/home/ubuntu/zmax_ss_remote"

# 红线: 动作类关键词 → 拒答 (未授权不下发真机动作)
MOTION_PAT = re.compile(r"(插入|抓取|夹爪|夹紧|移动|运动|下发|示教|拍照|启动产线|回位|抓|插|拔|推|拉|执行动作)")


def _derived_stage(obs7):
    """产线未上报阶段时的**推算**阶段 (明确标注推算, 不冒充产线上报)

    口径 (只用 tap 真值 obs7 = 手位3 + 夹爪1 + 速度3, 为粗略三态划分):
      · 夹爪张开(>=0.5)            → 接近/对位 (未夹持)
      · 夹爪闭合(<0.5) 且 z 下降中 → 下降/插入
      · 夹爪闭合(<0.5)             → 已夹持/转移
    """
    if not obs7 or len(obs7) < 7:
        return ""
    z, grip, vz = float(obs7[2]), float(obs7[3]), float(obs7[6])
    if grip >= 0.5:
        return "接近/对位 (推算)"
    return "下降/插入 (推算)" if vz < -1e-4 else "已夹持/转移 (推算)"


def _sh(cmd, timeout=8):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:                                                        # noqa: BLE001
        return ""


def _post(path, obj, timeout=15):
    req = urllib.request.Request(RELAY + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _get(path, timeout=12):
    with urllib.request.urlopen(RELAY + path, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


# ───────────────────────── 以下: 状态采集 (全部真实) ─────────────────────────
def real_obs():
    """真机只读 tap 最新一帧 (state_*.jsonl) → (obs7, stage, ts, age_s) ; 拿不到 → (None, None, None, -1)"""
    try:
        files = [os.path.join(TAP_DIR, f) for f in os.listdir(TAP_DIR) if f.startswith("state_")]
        if not files:
            return None, None, None, -1
        p = max(files, key=os.path.getmtime)
        age = time.time() - os.path.getmtime(p)
        with open(p, "rb") as f:
            f.seek(max(0, os.path.getsize(p) - 4000))
            last = [x for x in f.read().decode("utf-8", "ignore").splitlines() if x.strip().startswith("{")][-1]
        d = json.loads(last)
        tcp = d.get("tcp") or []
        jv = d.get("jvel") or [0, 0, 0]
        grip = d.get("gripper")
        grip = 1.0 if grip is None else float(grip)
        obs7 = [float(x) for x in (list(tcp[:3]) + [grip] + list(jv[:3]))] if len(tcp) >= 3 else None
        st = d.get("prod_stage") or d.get("stage") or ""
        # ⚠️ 如实: 真机 tap 的 prod_stage 为空 = 产线主程序没在跑 (不是"读失败")
        return obs7, (str(st) if st else ""), d.get("t"), round(age, 1)
    except Exception:                                                        # noqa: BLE001
        return None, None, None, -1


def event_pred(obs7):
    """真调事件级认知头 (同源 ckpt engine_v2) → 6 概率; 不可用 → {}"""
    if not obs7:
        return {}
    try:
        sp = os.path.join(ROOT, "src")
        if sp not in sys.path:
            sys.path.insert(0, sp)
        from lerobot.cognition.event_head import get_event_head
        h = get_event_head()
        if not h.available():
            return {}
        pr, ms = h.predict(obs7)
        out = {k: round(float(v), 4) for k, v in pr.items()}
        out["_ms"] = round(ms, 3)
        out["_ckpt"] = h.source
        return out
    except Exception:                                                        # noqa: BLE001
        return {}


def layer_health():
    """分层(L2/L3/L4/L5)真实健康: 由服务/文件/模型实测判定, 不猜"""
    svc = {s: _sh("systemctl is-active %s" % s) for s in
           ("ss-local-infer", "ss-bypass", "ss-remote-tap", "ss-yolo-bypass")}
    infer = {}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8790/health", timeout=5) as r:
            infer = json.loads(r.read().decode() or "{}")
    except Exception:                                                        # noqa: BLE001
        pass
    head = os.path.isfile("/home/ubuntu/stable-wm-cache/checkpoints/cog_event_head/head_H5_engine_v2.pt")
    return {
        "L2": {"name": "L2 检测反馈/收口", "status": "active" if svc.get("ss-yolo-bypass") == "active" else "offline",
               "detail": "yolo 旁路 %s · 推理服务 %s" % (svc.get("ss-yolo-bypass"), svc.get("ss-local-infer"))},
        "L3": {"name": "L3 状态调度", "status": "active" if os.path.isfile(os.path.join(ROOT, "tools/gui/state_space_sim_real.py")) else "missing",
               "detail": "引擎 state_space_sim_real 在位"},
        "L4": {"name": "L4 认知预测", "status": "active" if infer.get("online") else "offline",
               "detail": "推理 models=%s" % (infer.get("models") or [])},
        "L5": {"name": "L5 大模型/意图", "status": "active" if head else "no-weights",
               "detail": "事件头 engine_v2 %s" % ("已就位" if head else "缺")},
    }


def resources():
    gpu = _sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader")
    return {"gpu": gpu, "disk": _sh("df -h / | tail -1"), "mem": _sh("free -g | sed -n 2p")}


def core_idea(stage, ev, obs7):
    """给人类看懂的'核心思想'话术 (状态空间工程: 上层只给意图, 执行由 L2 收口)"""
    risky = max((v for k, v in ev.items() if isinstance(v, float) and not k.startswith("_")), default=None)
    return {
        "one_liner": "状态空间 = 把机器人作业写成 s(观测)→a(动作) 的转移链: L5 给意图 · L4 预测认知 · L3 调度阶段 · L2 收口执行(势函数兜底)",
        "now": "当前阶段「%s」· 观测(手位/夹爪/速度)=%s" % (stage or "?", [round(x, 3) for x in (obs7 or [])]),
        "watch": "事件头对未来 5/10 帧的预测: 夹爪闭合/AI到位/手在动 (值越高越可能发生); 最高 %.2f"
                 % (risky if risky is not None else -1),
        "ask": "你可以直接说: 解释 / 状态 / 阶段=对位 / 暂停 / 恢复 / 列出 待办",
    }


def build_snapshot():
    obs7, stage, ts, age = real_obs()
    ev = event_pred(obs7)
    if not stage:
        stage = _derived_stage(obs7)
        stage_note = ("真机 tap 的 prod_stage 为空 (产线主程序未运行/未上报) → 上行为**推算阶段**(由夹爪+z 速度导出), "
                      "标注为'推算'以区分产线上报; 帧本身是新鲜的")
    return {
        "from": "zmax_hil", "ts": time.strftime("%F %T"),
        "snapshot": {
            "stage": (stage or "未上报"), "stage_note": stage_note,
            "obs7": obs7, "obs_ts": ts, "frame_age_s": age,
            "events": ev, "layers": layer_health(), "resources": resources(),
            "idea": core_idea(stage, ev, obs7),
            "canvas": _canvas_brief(),
            "evidence": _latest_evidence(),
        },
    }


def _canvas_brief():
    try:
        d = json.load(open(os.path.join(ROOT, "flows/state_space_obs.json"), encoding="utf-8"))
        real = [n for n in d["nodes"] if not ((n.get("params") or {}).get("bg") or (n.get("params") or {}).get("row_bg"))]
        return {"nodes": len(d["nodes"]), "real_nodes": len(real), "links": len(d["links"]),
                "hil_node": any(n["id"] == "n_hil" for n in d["nodes"])}
    except Exception:                                                        # noqa: BLE001
        return {}


def _latest_evidence():
    out = []
    try:
        for f in sorted(os.listdir(REPORTS), reverse=True)[:60]:
            if f.endswith(".json") and any(k in f for k in ("cog_event", "verify", "dds_ss", "preflight")):
                out.append(f)
            if len(out) >= 5:
                break
    except Exception:                                                        # noqa: BLE001
        pass
    return out


# ───────────────────────── 指令处理 (下行) ─────────────────────────
def handle_instruction(text, snap=None):
    """指示 → (reply_text, action_taken)。红线: 动作类一律拒答并记为待授权"""
    t = (text or "").strip()
    low = t.lower()
    if MOTION_PAT.search(t):
        rec = {"ts": time.strftime("%F %T"), "text": t, "verdict": "refused_motion",
               "reason": "未授权不下发真机动作 (现场授权后由 L2 收口执行)"}
        _append_instruction(rec)
        return ("🚫 这条指示涉及真机动作, 我**没有执行**(当前未授权现场操作)。已记为待授权请求; "
                "授权后我会按 L2 收口的顺序执行并回报每步证据。", "refused_motion")
    if low in ("help", "?", "解释", "说明") or "核心思想" in t:
        s = snap or build_snapshot()["snapshot"]
        return ("🧠 %s\n\n%s\n\n%s\n\n%s" % (s["idea"]["one_liner"], s["idea"]["now"], s["idea"]["watch"], s["idea"]["ask"]), "help")
    if low in ("status", "状态", "快照") or "状态" in t:
        s = (snap or build_snapshot()["snapshot"])
        ly = " · ".join("%s:%s" % (k, v["status"]) for k, v in s["layers"].items())
        return ("📊 状态: 阶段=%s · 帧龄=%ss · 分层 %s · 事件 %s"
                % (s["stage"], s["frame_age_s"], ly,
                   {k: v for k, v in (s["events"] or {}).items() if not k.startswith("_")}), "status")
    m = re.match(r"^阶段\s*[=:：]\s*(.+)$", t)
    if m:
        want = m.group(1).strip()
        _append_instruction({"ts": time.strftime("%F %T"), "text": t, "verdict": "stage_request", "stage": want})
        return ("✅ 已记录人工阶段指示「%s」。注: 阶段切换由引擎状态机按几何证据推进, L5/L4 只给意图, "
                "执行由 L2 收口 —— 我会在下一轮引擎运行里把它作为**软先验**带上(不改默认档)。" % want, "stage_request")
    if t in ("暂停", "pause"):
        open(os.path.join(REPORTS, "hil_pause.flag"), "w").write(time.strftime("%F %T"))
        return ("⏸ 已置暂停标 (reports/hil_pause.flag); 引擎/流水线下一轮起读该标自理。", "pause")
    if t in ("恢复", "resume", "继续"):
        p = os.path.join(REPORTS, "hil_pause.flag")
        if os.path.isfile(p):
            os.remove(p)
        return ("▶️ 已清暂停标。", "resume")
    if "待办" in t or "任务" in t:
        return ("📋 待办见 docs/TASK_LEDGER_20260925.md 会话六/七; 离线可做: 事件头可视化接入 · 事件头驱动 L2 收口 · "
                "同源数据扩到 300 段; 现场: Orin 上行清单 · AOI 标注 · 10083 /picture", "todo")
    return ("🤔 收到「%s」, 但我把它归到**未识别指示**。可用: 解释 / 状态 / 阶段=对位 / 暂停 / 恢复 / 待办。"
            "(涉及真机动作的指示一律不执行, 会记为待授权)" % t[:60], "unknown")


def _append_instruction(rec):
    try:
        os.makedirs(REPORTS, exist_ok=True)
        with open(os.path.join(REPORTS, "hil_instructions.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                                        # noqa: BLE001
        pass


def poll_instructions(state_path=os.path.join(REPORTS, "hil_bridge_state.json")):
    """拉 web 指示 (复用既有 /agent/prompt 游标通道), 逐条处理并回 /agent/reply"""
    st = {}
    try:
        st = json.load(open(state_path, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        st = {}
    cur = int(st.get("cursor") or 0)
    try:
        r = _get("/agent/prompt?after=%d" % cur)
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:80]), "handled": 0}
    # 通道隔离: 只处理来自 HIL 网页的指示 (from=hil_web), 别人的提示词只推进游标不回话
    items = [x for x in (r.get("prompts") or []) if str(x.get("from") or "") == "hil_web"]
    handled = []
    snap = None
    for it in items:
        if snap is None:
            snap = build_snapshot()["snapshot"]
        reply, act = handle_instruction(it.get("text", ""), snap)
        try:
            _post("/agent/reply", {"prompt_seq": it.get("seq"), "text": reply, "from": "hil_bridge", "action": act})
        except Exception:                                                    # noqa: BLE001
            pass
        handled.append({"seq": it.get("seq"), "text": (it.get("text") or "")[:40], "action": act})
        cur = max(cur, int(it.get("seq") or 0))
    for x in (r.get("prompts") or []):            # 非 HIL 的提示词: 只推进游标 (不抢别的消费者的活)
        cur = max(cur, int(x.get("seq") or 0))
    try:
        json.dump({"cursor": cur, "ts": time.strftime("%F %T")}, open(state_path, "w", encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        pass
    return {"ok": True, "handled": len(handled), "items": handled, "cursor": cur}


def publish_once():
    snap = build_snapshot()
    r = _post("/hil/state", snap)
    return r, snap


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        s = build_snapshot()["snapshot"]
        print(json.dumps({"stage": s["stage"], "frame_age_s": s["frame_age_s"],
                          "events": s["events"], "layers": {k: v["status"] for k, v in s["layers"].items()},
                          "canvas": s["canvas"],
                          "hil_endpoint": RELAY + "/hil/state"}, ensure_ascii=False, indent=1))
        return 0
    if a.once:
        r, snap = publish_once()
        print("⬆ 已上报:", json.dumps(r, ensure_ascii=False), "| 阶段=%s 帧龄=%ss 事件=%s"
              % (snap["snapshot"]["stage"], snap["snapshot"]["frame_age_s"],
                 {k: v for k, v in (snap["snapshot"]["events"] or {}).items() if not k.startswith("_")}))
        inst = poll_instructions()
        print("⬇ 指示:", json.dumps(inst, ensure_ascii=False)[:300])
        return 0
    print("🙋 HIL 桥常驻: 每 %.0fs 上报状态 + 拉取人的指示 (ESC 退出)" % a.interval)
    while True:
        try:
            r, snap = publish_once()
            inst = poll_instructions()
            print("[%s] ⬆ %s | 阶段=%s 帧龄=%ss | ⬇ 处理 %d 条" %
                  (time.strftime("%H:%M:%S"), r.get("ok"), snap["snapshot"]["stage"],
                   snap["snapshot"]["frame_age_s"], inst.get("handled", 0)), flush=True)
        except Exception as e:                                               # noqa: BLE001
            print("[%s] ❌ %s: %s" % (time.strftime("%H:%M:%S"), type(e).__name__, str(e)[:100]), flush=True)
        time.sleep(max(1.0, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
