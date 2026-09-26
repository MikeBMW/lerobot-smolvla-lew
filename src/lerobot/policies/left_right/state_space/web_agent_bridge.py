# -*- coding: utf-8 -*-
"""web_agent_bridge.py — 🌐 L5 · Web 智能体桥 (与 web 上的 agent 交换信息, 2026-09-25 老倪)

老倪需求: 「开通一个状态空间 L5 的新节点, 用于与 web 的 agent 交换信息, 即你可以通过 web 上的
hermes agent, 远程通过提示词操纵状态空间的功能」

架构 (三层, 与本机既有链路同构):
  web agent (浏览器/datadrive.world)  --POST /api/relay/agent/prompt-->  ECS 中转(游标式 jsonl)
                                                                          ↓ 本机 5s 轮询 GET ?after=N
  本机 L5 桥 (本类)  --提示词→功能-->  **只读功能白名单**  (状态/画布/记忆/仿真/网络/AOI/真机只读)
                                                                          ↓
  web agent  <--GET /api/relay/agent/reply?after=N--  ECS 中转  <--POST /api/relay/agent/reply--

红线 (老倪: 「不要动真机, 但可以访问读取真机的信号」):
  · 白名单里**没有任何下发动作的功能**; 提示词命中动作类关键词 → **拒答 + 记审计**, 不做任何转发
  · 全部功能为只读查询 / 仿真内触发 / 飞书通知; 真机侧只读 (ROS tap 订阅 + 工控机 /last_result)
  · 拒答也要回执 (web 侧要看得见"为什么没执行"), 不留静默

与 /command 通道的区别 (为什么另开): /command 是**单槽覆盖**的采集指令 (Mac 守护用), 后一条会盖掉
前一条; agent 消息要**不丢/可重放** → 用游标式 append-only jsonl + ?after=N 只读拉取 (幂等)。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

def _find_repo_root(start: str) -> str:
    """向上找到仓库根 (以 flows/state_space_obs.json 或 tools/ 为标记) — 别用 dirname 数层数(数错过)"""
    p = os.path.abspath(start)
    for _ in range(8):
        if os.path.isfile(os.path.join(p, "flows", "state_space_obs.json")) or \
           os.path.isdir(os.path.join(p, "tools")):
            return p
        np_ = os.path.dirname(p)
        if np_ == p:
            break
        p = np_
    return os.path.abspath(os.path.join(start, "..", "..", "..", "..", "..", ".."))


REPO = _find_repo_root(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO, "src", "lerobot")
RELAY = os.environ.get("SS_WEB_RELAY", "https://datadrive.world/api/relay")
STATE = os.path.join(REPO, "reports", "web_agent_bridge_state.json")
AUDIT = os.path.join(REPO, "reports", "web_agent_bridge_audit.jsonl")

# ── 🔴 硬红线: 命中即拒答 (不做任何转发/解释性执行) ─────────────────────────
BLOCKED = [
    r"插(入|装)", r"抓(取|住|起)", r"夹(爪|紧|住)", r"移动|运动|回位|归位", r"下电|上电|使能|解锁",
    r"goto|move_|movej|movel|rt_|servo", r"拍照|连拍|采集指令", r"示教|记录点位",
    r"启动.*(臂|机器人)|停止.*(臂|机器人)", r"写|下发|部署|切换档位|改配置",
]


def _now():
    return time.strftime("%F %T")


def _post(path: str, obj: dict, timeout: float = 12.0) -> dict:
    req = urllib.request.Request(RELAY + path, data=json.dumps(obj, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _get(path: str, timeout: float = 12.0) -> dict:
    with urllib.request.urlopen(RELAY + path, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _sh(cmd: str, timeout: int = 25) -> str:
    try:
        r = subprocess.run(["bash", "-lc", cmd], capture_output=True, timeout=timeout, cwd=REPO)
        return (r.stdout or b"").decode(errors="replace").strip() or (r.stderr or b"").decode(errors="replace").strip()
    except Exception as e:                                     # noqa: BLE001
        return f"<执行失败 {type(e).__name__}: {e}>"


def _sysctl_services() -> dict:
    names = ["ss-local-infer", "ss-bypass", "ss-remote-tap", "ss-yolo-bypass", "zmax-data-mount",
             "zmax-net-optimize", "aoi-feishu-push"]
    out = {}
    for n in names:
        out[n] = _sh(f"systemctl is-active {n} 2>/dev/null || true", 8).strip() or "unknown"
    return out


class WebAgentBridge:
    """L5 桥: 提示词 → 只读功能派发 → 回执。"""

    def __init__(self, relay: str | None = None):
        self.relay = relay or RELAY
        self.cursor = 0
        self._load_state()

    # ── 游标持久化 (重启不重放已处理提示) ──
    def _load_state(self):
        try:
            d = json.load(open(STATE, encoding="utf-8"))
            self.cursor = int(d.get("cursor", 0))
        except Exception:
            self.cursor = 0

    def _save_state(self, extra: dict | None = None):
        d = {"cursor": self.cursor, "ts": _now()}
        d.update(extra or {})
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(d, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    def _audit(self, rec: dict):
        rec = dict(rec, ts=_now())
        os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ── ① 功能白名单 (全部只读/仿真内/通知; 命名=能力语义, 非算法词) ──
    def f_status(self, arg: str = "") -> dict:
        """系统与链路状态: 在役服务 + 推理服务 + 帧龄"""
        svc = _sysctl_services()
        inf = _sh("curl -s -m 5 http://127.0.0.1:8790/health", 10)
        try:
            infd = json.loads(inf)
        except Exception:
            infd = {"raw": inf[:200]}
        age = _sh("find /home/ubuntu/zmax_ss_remote -name '*.jsonl' -newermt '-10 minutes' 2>/dev/null | wc -l", 8)
        return {"services": svc, "infer_8790": infd, "tap_jsonl_fresh_10min": age.strip()}

    def f_canvas(self, arg: str = "") -> dict:
        """画布结构: 节点/连线数 + 指定节点是否存在"""
        p = os.path.join(REPO, "flows", "state_space_obs.json")
        d = json.load(open(p, encoding="utf-8"))
        ns, ls = d.get("nodes", []), d.get("links", [])
        key = (arg or "").strip()
        hit = [{"id": n["id"], "name": n["name"], "x": n.get("x"), "y": n.get("y")}
               for n in ns if key and key in str(n.get("name", "")) + str(n.get("id", ""))]
        return {"nodes": len(ns), "links": len(ls), "match": hit[:8], "query": key}

    def f_reports(self, arg: str = "") -> dict:
        """最近报告台账: 最新 N 份 + 指定关键字命中"""
        pat = (arg or "").strip()
        cmd = ("ls -t reports/*.json reports/*.md 2>/dev/null | head -40"
               + (f" | grep -i -- {json.dumps(pat)} | head -8" if pat else ""))
        files = [x for x in _sh(cmd, 12).splitlines() if x.strip()][:8]
        return {"pattern": pat, "files": files,
                "count_all": _sh("ls reports/ | wc -l", 8).strip()}

    def f_memory(self, arg: str = "") -> dict:
        """记忆层: Hermes 记忆/用户档 + 工程记忆(md) 条数与最新时间"""
        mem = os.path.expanduser("~/.hermes/memories")
        md = sorted([f for f in os.listdir(os.path.join(REPO, "docs", "memory"))
                     if f.endswith(".md")]) if os.path.isdir(os.path.join(REPO, "docs", "memory")) else []
        out = {"hermes_memory_files": sorted(os.listdir(mem))[:5] if os.path.isdir(mem) else [],
               "eng_memory_md": len(md), "eng_memory_latest": md[-3:]}
        try:
            p = os.path.join(mem, "MEMORY.md")
            out["memory_chars"] = len(open(p, encoding="utf-8").read())
        except Exception:
            pass
        return out

    def f_skills(self, arg: str = "") -> dict:
        """技能库: Hermes 技能清单 + L2 可执行技能 (真源文件/计数)"""
        sk = _sh("ls -d ~/.hermes/skills/*/*/ 2>/dev/null | wc -l", 10)
        l2 = _sh("grep -c '\"skill\"' ~/zmax_data/l2_daemon.log 2>/dev/null | head -1", 10)
        last = _sh("grep -o 'L2\\.[a-z_0-9]*' ~/zmax_data/l2_daemon.log 2>/dev/null | tail -5", 10)
        return {"hermes_skills_dirs": sk.strip(), "l2_log_skill_lines": l2.strip(),
                "l2_recent_skills": last.splitlines()[-5:]}

    def f_sim(self, arg: str = "") -> dict:
        """仿真自检 (不出真机动作): 跑 light rollout / 读最近仿真证据"""
        n = 60
        m = re.search(r"(\d+)", arg or "")
        if m:
            n = max(10, min(300, int(m.group(1))))
        out = _sh(f"cd {REPO} && timeout 120 ./gui-venv311/bin/python tools/rollout_peg_check.py --steps {n} 2>&1 | tail -6", 140)
        return {"steps": n, "tail": out.splitlines()[-6:]}

    def f_net(self, arg: str = "") -> dict:
        """网络性能自检 (只读): 走开机优化脚本的体检段"""
        out = _sh(f"bash {REPO}/tools/zmax_net_optimize.sh --no-throughput 2>&1 | tail -4", 90)
        return {"tail": out.splitlines()[-4:]}

    def f_aoi(self, arg: str = "") -> dict:
        """看 AOI 现场只读信号: 工控机 /last_result 判决 + 裁减指标 (绝不触发拍照)"""
        lr = _sh("curl -s -m 8 http://192.168.23.23:10082/last_result", 14)
        ci = _sh("curl -s -m 8 http://192.168.23.23:10082/crop_info", 14)
        def _j(s):
            try:
                return json.loads(s)
            except Exception:
                return {"raw": s[:160]}
        return {"last_result": _j(lr), "crop_info_method": _j(ci).get("method"), "note": "只读, 未触发拍照"}

    def f_robot_read(self, arg: str = "") -> dict:
        """真机只读信号: Orin 可达性 + 中转 tap 最新帧时间 (不下发任何动作)"""
        ping = _sh("ping -c2 -W2 192.168.23.66 2>/dev/null | tail -1", 12)
        tap = _sh("ls -lt /home/ubuntu/zmax_ss_remote/*.jsonl 2>/dev/null | head -3", 10)
        return {"orin_ping": ping, "tap_files": tap.splitlines()[:3],
                "readonly": True, "actuation": "禁止 (老倪红线)"}

    def f_feishu(self, arg: str = "") -> dict:
        """推一条文本到飞书群 (自换 token, 兜底通道)"""
        text = (arg or "").strip()[:800] or "🌐 Web 智能体桥: 空消息自检"
        out = _sh(f"python3 ~/.hermes/scripts/feishu_notify.py --text {json.dumps(text)}", 40)
        return {"sent_text": text, "tail": out.splitlines()[-3:]}

    def f_help(self, arg: str = "") -> dict:
        """能力清单: 远程可调功能 + 用法"""
        return {"functions": {k: (self.FUNCS[k][1].__doc__ or "").strip().splitlines()[0] for k in self.FUNCS},
                "usage": "提示词里带功能名或关键词即可, 例: '状态' / '画布节点数' / '仿真 60' / 'AOI 判决' / '推飞书: 现场已就绪'"}

    # key → (匹配关键词, 函数)
    FUNCS: dict = {}

    def dispatch(self, text: str) -> dict:
        """提示词 → 功能。红线优先: 动作类一律拒答。"""
        t = (text or "").strip()
        if not t:
            return {"ok": False, "func": None, "text": "空提示词", "data": {}}
        low = t.lower()
        for pat in BLOCKED:
            if re.search(pat, low):
                self._audit({"kind": "refused", "prompt": t, "rule": pat})
                return {"ok": False, "func": None, "refused": True,
                        "text": f"🚫 拒答: 提示词命中动作红线 `{pat}` — 本节点只读 (老倪红线: 不动真机)。"
                                f"如需现场动作, 请人工授权后在控制台执行。",
                        "data": {"rule": pat, "readonly": True}}
        for key, (kws, fn) in self.FUNCS.items():
            if any(k in low for k in kws):
                arg = t
                try:
                    data = fn(self, arg)
                    return {"ok": True, "func": key, "text": f"✅ {key}: 已执行 (只读)", "data": data}
                except Exception as e:                          # noqa: BLE001
                    return {"ok": False, "func": key, "text": f"❌ {key} 执行异常: {type(e).__name__}: {e}", "data": {}}
        return {"ok": True, "func": "help", "text": "未匹配到功能名 → 返回能力清单", "data": self.f_help(self)}

    # ── ② 通道: 拉取 → 派发 → 回执 (幂等, 游标持久化) ──
    def poll_once(self, timeout: float = 12.0) -> dict:
        got = _get(f"/agent/prompt?after={self.cursor}", timeout)
        items = got.get("prompts", []) or []
        # 🐛 2026-09-26: 跳过 HIL 网页专属指示 (from=hil_web) → 由 n_hil/hil_bridge 处理, 避免同一个问题两处回答
        items = [x for x in items if str((x or {}).get("from") or "") != "hil_web"]
        done = []
        for it in items:
            r = self.dispatch(it.get("text", ""))
            rec = {"prompt_seq": it.get("seq"), "ok": r["ok"], "text": r["text"],
                   "data": r.get("data") or {}}
            if r.get("refused"):
                rec["refused"] = True
            try:
                _post("/agent/reply", rec, timeout)
            except Exception as e:                              # noqa: BLE001
                self._audit({"kind": "reply_failed", "seq": it.get("seq"), "err": str(e)})
                return {"ok": False, "error": f"回执失败: {e}", "processed": done}
            self.cursor = max(self.cursor, int(it.get("seq", 0)))
            self._audit({"kind": "handled", "seq": it.get("seq"), "prompt": it.get("text"),
                         "func": r.get("func"), "ok": r["ok"]})
            done.append({"seq": it.get("seq"), "func": r.get("func"), "ok": r["ok"], "text": r["text"][:120]})
        self._save_state({"last_batch": len(done)})
        return {"ok": True, "processed": done, "cursor": self.cursor, "pending": got.get("pending", 0)}

    def watch(self, interval: float = 5.0, seconds: float = 0.0):
        t0 = time.time()
        print(f"🌐 L5 Web 智能体桥 监听中 (每 {interval:.0f}s · {self.relay}/agent/prompt · 只读功能白名单)",
              flush=True)
        while True:
            try:
                r = self.poll_once()
                for p in r.get("processed", []):
                    print(f"  ← #{p['seq']} [{p['func']}] {'✅' if p['ok'] else '🚫'} {p['text'][:90]}", flush=True)
            except Exception as e:                              # noqa: BLE001
                print(f"  ⚠️ 轮询异常: {type(e).__name__}: {e}", flush=True)
            if seconds and time.time() - t0 >= seconds:
                return
            time.sleep(interval)


# 注册表 (函数名 → 关键词) — 关键词是**能力语义**, 便于自然语言提示词命中
WebAgentBridge.FUNCS = {
    "help":         (["help", "帮助", "能干什么", "能力", "用法"], WebAgentBridge.f_help),
    "status":       (["状态", "健康", "服务", "链路", "status"], WebAgentBridge.f_status),
    "canvas":       (["画布", "节点", "连线", "构图", "canvas"], WebAgentBridge.f_canvas),
    "reports":      (["报告", "台账", "最近产物", "reports"], WebAgentBridge.f_reports),
    "memory":       (["记忆", "memory", "工程记忆"], WebAgentBridge.f_memory),
    "skills":       (["技能", "skill", "技能库"], WebAgentBridge.f_skills),
    "sim":          (["仿真", "sim", "rollout", "自检"], WebAgentBridge.f_sim),
    "net":          (["网络", "带宽", "dns", "延迟"], WebAgentBridge.f_net),
    "aoi":          (["aoi", "外观", "金手指", "判决", "裁减"], WebAgentBridge.f_aoi),
    "robot_read":   (["真机", "orin", "位姿", "只读信号"], WebAgentBridge.f_robot_read),
    "feishu":       (["飞书", "推消息", "通知"], WebAgentBridge.f_feishu),
}
