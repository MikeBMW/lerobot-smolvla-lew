#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_hil_chain.py — 🙋 HIL 人机在环 全链取证 (画布→接线→上行→下行→红线→网页→服务)

判据:
  ① 画布: n_hil 存在 · 在 L5 行带 · DeepSeek 右侧 · 零重叠 · 1 入线 1 出线且全前向
  ② 接线: node_logic 注册命中 + _EXTERNAL_LOC 指向真源码且文件在
  ③ 上行: build_snapshot() 全真值 (obs7/帧龄/6 事件/4 分层/画布含 hil_node) → POST relay ok → 云端回读一致
  ④ 下行: 发 from=hil_web 指示 → 处理 → 云端回执 from='hil_bridge' 可见
  ⑤ 红线: 动作类指示 → refused_motion + 落审计 reports/hil_instructions.jsonl
  ⑥ 网页: hil.html 200 且含关键元素 (hil/state · agent/prompt · 核心思想)
  ⑦ 服务: zmax-hil-bridge active (常驻上报)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src/lerobot/policies/left_right/state_space"))
RELAY = "https://datadrive.world/api/relay"
ok = []


def chk(n, c, d=""):
    ok.append(bool(c))
    print("  %s %s%s" % ("✅" if c else "❌", n, (" — " + d) if d else ""), flush=True)


def _get(p, t=15):
    with urllib.request.urlopen(RELAY + p, timeout=t) as r:
        return json.loads(r.read().decode() or "{}")


def _post(p, o, t=15):
    req = urllib.request.Request(RELAY + p, data=json.dumps(o).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.loads(r.read().decode() or "{}")


print("① 画布")
d = json.load(open(os.path.join(ROOT, "flows/state_space_obs.json"), encoding="utf-8"))
by = {n["id"]: n for n in d["nodes"]}
chk("节点 n_hil 存在", "n_hil" in by, "画布 %d 节点 / %d 连线" % (len(d["nodes"]), len(d["links"])))
if "n_hil" in by:
    h, dsv = by["n_hil"], by["n_dsvl"]
    chk("在 L5 行带且 DeepSeek 右侧", h["y"] == dsv["y"] and h["x"] >= dsv["x"] + dsv["w"],
        "hil x=%d y=%d · DeepSeek 右边界 %d" % (h["x"], h["y"], dsv["x"] + dsv["w"]))
    ov = [n["id"] for n in d["nodes"] if n["id"] != "n_hil"
          and not ((n.get("params") or {}).get("bg") or (n.get("params") or {}).get("row_bg"))
          and h["x"] < n["x"] + n["w"] and n["x"] < h["x"] + h["w"] and h["y"] < n["y"] + n["h"] and n["y"] < h["y"] + h["h"]]
    chk("与全图零重叠", not ov, "重叠=%s" % ov)
    li = [l for l in d["links"] if l.get("t") == "n_hil"]
    lo = [l for l in d["links"] if l.get("f") == "n_hil"]
    fwd = all(by.get(l["f"], h if l["f"] == "n_hil" else {}).get("x", 0) < by.get(l["t"], h if l["t"] == "n_hil" else {}).get("x", 1)
              for l in li + lo)
    chk("1 入线 + 1 出线且全前向", len(li) == 1 and len(lo) == 1 and fwd,
        "入=%s 出=%s 前向=%s" % ([l["id"] for l in li], [l["id"] for l in lo], fwd))

print("② 运行时接线")
import node_logic as NL                                                   # noqa: E402
reg = NL.match_node("HIL 人机在环") if hasattr(NL, "match_node") else None
reg2 = NL.match_node("人机在环") if hasattr(NL, "match_node") else None
chk("_reg 注册命中 (搜索'HIL'/'人机在环')", bool(reg) and bool(reg2), "命中=%s" % (reg or reg2))
loc = NL.get_node_external_symbol("n_hil") if hasattr(NL, "get_node_external_symbol") else None
src = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/hil_bridge.py")
chk("_EXTERNAL_LOC 指向真源码且在盘", bool(loc) and os.path.isfile(src), "symbol=%s · 文件%s" % (loc, "在" if os.path.isfile(src) else "缺"))

print("③ 上行 (状态真实 + 云端回读)")
import hil_bridge as HB                                                   # noqa: E402
snap = HB.build_snapshot()
s = snap["snapshot"]
ev = {k: v for k, v in (s.get("events") or {}).items() if not k.startswith("_")}
chk("快照含真值 (obs7 / 帧龄 / 6 事件 / 4 分层)", bool(s.get("obs7")) and s.get("frame_age_s", -1) >= 0
    and len(ev) == 6 and len(s.get("layers") or {}) == 4,
    "obs7=%s 帧龄=%ss 事件=%d 分层=%d" % (s.get("obs7"), s.get("frame_age_s"), len(ev), len(s.get("layers") or {})))
chk("画布简况含 hil_node", bool((s.get("canvas") or {}).get("hil_node")), json.dumps(s.get("canvas"), ensure_ascii=False))
pub = _post("/hil/state", snap)
chk("上报成功 (relay ok)", bool(pub.get("ok")), json.dumps(pub, ensure_ascii=False))
back = _get("/hil/state")
chk("云端回读一致 (阶段/事件同源)", (back.get("snapshot") or {}).get("stage") == s.get("stage")
    and len([k for k in (back.get("snapshot") or {}).get("events", {}) if not k.startswith("_")]) == 6,
    "回读 _total=%s 阶段=%s" % (back.get("_total"), (back.get("snapshot") or {}).get("stage")))

print("④ 下行 (浏览器指示 → 回执)")
n0 = _get("/agent/reply?after=0").get("replies") or []
seq0 = max([int(x.get("seq") or 0) for x in n0], default=0)
p = _post("/agent/prompt", {"text": "解释", "from": "hil_web", "meta": {"page": "hil.html"}})
inst = HB.poll_instructions()
time.sleep(1)
reps = _get("/agent/reply?after=%d" % seq0).get("replies") or []
mine = [x for x in reps if str(x.get("from")) == "hil_bridge"]
chk("指示被处理 (handled≥1)", inst.get("handled", 0) >= 1, json.dumps(inst.get("items"), ensure_ascii=False)[:120])
chk("云端可见 HIL 回执 (from='hil_bridge')", bool(mine), "回执数=%d 例: %s" % (len(mine), (mine[-1].get("text") or "")[:80] if mine else ""))

print("⑤ 红线 (动作类必须拒答)")
audit = os.path.join(ROOT, "reports/hil_instructions.jsonl")
n_a = len(open(audit, encoding="utf-8").read().splitlines()) if os.path.isfile(audit) else 0
_post("/agent/prompt", {"text": "用夹爪把光模块插入治具", "from": "hil_web"})
inst2 = HB.poll_instructions()
n_b = len(open(audit, encoding="utf-8").read().splitlines()) if os.path.isfile(audit) else 0
act = [x.get("action") for x in (inst2.get("items") or [])]
chk("动作类指示 → refused_motion", "refused_motion" in act, "actions=%s" % act)
chk("拒答已落审计 (jsonl 增加)", n_b > n_a, "%d → %d 行" % (n_a, n_b))

print("⑥ 网页")
url = "https://datadrive.world/hil.html"
code, body = 0, ""
try:
    with urllib.request.urlopen(url, timeout=15) as r:
        code, body = r.status, r.read().decode("utf-8", "ignore")
except Exception as e:                                                    # noqa: BLE001
    body = str(e)
chk("hil.html 可访问", code == 200, "HTTP %s · %d 字节" % (code, len(body)))
chk("页面含关键元素 (hil/state · agent/prompt · 核心思想)",
    all(k in body for k in ("hil/state", "agent/prompt", "核心思想")), "命中 3/3" if all(k in body for k in ("hil/state", "agent/prompt", "核心思想")) else "缺元素")

print("⑦ 服务")
st = subprocess.run(["systemctl", "is-active", "zmax-hil-bridge"], capture_output=True, text=True).stdout.strip()
chk("zmax-hil-bridge 常驻 active", st == "active", "state=%s" % st)

out = {"ts": time.strftime("%F %T"), "judges_pass": "%d/%d" % (sum(ok), len(ok)),
       "snapshot_keys": sorted(s.keys()), "events": ev, "pub": pub}
dst = os.path.join(ROOT, "reports", "hil_chain_verify_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n判据通过: %d/%d · 取证: %s" % (sum(ok), len(ok), dst))
sys.exit(0 if all(ok) else 3)
