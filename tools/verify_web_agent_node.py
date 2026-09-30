#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_web_agent_node.py — 🌐 L5「Web 智能体桥」离线+真通道取证 (2026-09-25)

判据 (全部真断言, 不是"跑通即过"):
  ① 画布: 节点存在 · 在 DeepSeek 左侧 · 与 DeepSeek 同行带
  ② 画布: 与全图零重叠 (排除行带背景)
  ③ 画布: 两条连线存在且全前向 (工程记忆→桥→DeepSeek)
  ④ 节点声明: state_space/web_agent/readonly/source/source_symbol 齐 + 源码文件存在
  ⑤ 运行时注册: match_node(画布名) → n_web_agent · _EXTERNAL_LOC 指向真源码
  ⑥ 离线派发(只读功能): 状态/画布/记忆/技能 四类提示词都返回**真数据**
  ⑦ 红线: 动作类提示词 → 拒答(refused) + 审计落盘, 且回执文字说明原因
  ⑧ **真通道端到端**: POST /agent/prompt → 本地 poll_once 拉到 → 派发 → POST /agent/reply → web 侧 GET 读到
  ⑨ 游标幂等: 再次 poll_once 不重复处理 (不重放)
  ⑩ 节点执行器: node_web_agent(ctx) 真调用桥 (日志含轮询/处理)
  ⑪ 只读红线字段: 真机只读功能明确标注 readonly=True / actuation=禁止
  ⑫ 常驻服务: zmax-web-agent-bridge.service enabled (以后开机即到岗)

用法: ./gui-venv311/bin/python tools/verify_web_agent_node.py [--no-e2e]   (--no-e2e 跳过公网往返)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
SS = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space")
AUDIT = os.path.join(ROOT, "reports", "web_agent_bridge_audit.jsonl")
sys.path.insert(0, SS)

OK: list = []
NG: list = []


def chk(name: str, cond: bool, detail: str = ""):
    (OK if cond else NG).append(f"{name}{(' — ' + detail) if detail else ''}")
    print(f"  {'✅' if cond else '❌'} {name}{(' — ' + detail) if detail else ''}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-e2e", action="store_true")
    a = ap.parse_args()

    d = json.load(open(FLOW, encoding="utf-8"))
    ns = {n["id"]: n for n in d["nodes"]}
    ls = d["links"]
    node = ns.get("n_web_agent")
    dsvl = ns.get("n_dsvl", {})
    mem = ns.get("n_eng_mem", {})

    print("① 画布位置")
    chk("节点 n_web_agent 存在", node is not None)
    if not node:
        return 1
    chk("在 DeepSeek 左侧 (x+w < dsvl.x)", node["x"] + node["w"] < dsvl["x"],
        f"桥 {node['x']}+{node['w']}={node['x']+node['w']} < DeepSeek {dsvl['x']}")
    chk("与 DeepSeek 同行带 (y 相同)", node["y"] == dsvl["y"], f"y={node['y']}")

    print("② 零重叠 (排除行带背景)")
    real = [n for n in d["nodes"] if not (n.get("params", {}).get("bg") or n.get("params", {}).get("row_bg"))]
    ov = [n["id"] for n in real if n["id"] != "n_web_agent"
          and node["x"] < n["x"] + n["w"] and n["x"] < node["x"] + node["w"]
          and node["y"] < n["y"] + n["h"] and n["y"] < node["y"] + node["h"]]
    chk("与全图实节点零重叠", not ov, f"重叠={ov or '无'} (比对 {len(real)} 节点)")

    print("③ 连线")
    byid = {l["id"]: l for l in ls}
    l1, l2 = byid.get("lkwa_mem"), byid.get("lkwa_dsvl")
    chk("入线 工程记忆→桥", bool(l1) and l1["f"] == "n_eng_mem" and l1["t"] == "n_web_agent")
    chk("出线 桥→DeepSeek 场景理解", bool(l2) and l2["f"] == "n_web_agent" and l2["t"] == "n_dsvl")
    chk("两线全前向", all(ns[l["f"]]["x"] < ns[l["t"]]["x"] for l in (l1, l2) if l))

    print("④ 节点声明与源码")
    p = node.get("params", {})
    chk("params 声明齐 (state_space/web_agent/readonly/source)", all(
        k in p for k in ("state_space", "web_agent", "readonly", "source", "source_symbol", "funcs")))
    src = os.path.join(ROOT, p.get("source", ""))
    chk("源码文件存在", os.path.isfile(src), p.get("source", ""))

    print("⑤ 运行时注册")
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import node_logic as NL
    key = NL.match_node(node["name"])
    chk("match_node(画布名) → n_web_agent", key == "n_web_agent", f"实际 {key}")
    ext = NL.get_node_external_symbol("n_web_agent") if hasattr(NL, "get_node_external_symbol") else None
    loc = NL.get_node_location("n_web_agent") if hasattr(NL, "get_node_location") else None
    chk("_EXTERNAL_LOC 符号 = class WebAgentBridge", "WebAgentBridge" in str(ext), str(ext)[:80])
    chk("_EXTERNAL_LOC 指向 web_agent_bridge.py", "web_agent_bridge.py" in str(loc), str(loc)[:100])

    print("⑥ 离线派发 (只读功能返回真数据)")
    from web_agent_bridge import WebAgentBridge
    b = WebAgentBridge()
    for prompt, need_key in [("状态空间服务状态", "services"), ("画布有多少节点", "nodes"),
                             ("记忆层情况", "eng_memory_md"), ("技能库条数", "hermes_skills_dirs")]:
        r = b.dispatch(prompt)
        ok = bool(r.get("ok")) and isinstance(r.get("data"), dict) and need_key in json.dumps(r.get("data"), ensure_ascii=False)
        chk(f"派发[{prompt}] → {r.get('func')} 含真实字段 {need_key}", ok, r["text"][:40])

    print("⑦ 红线 (动作类拒答)")
    n0 = sum(1 for _ in open(AUDIT, encoding="utf-8")) if os.path.isfile(AUDIT) else 0
    r = b.dispatch("用机械臂把光模块插入治具并夹紧")
    n1 = sum(1 for _ in open(AUDIT, encoding="utf-8")) if os.path.isfile(AUDIT) else 0
    chk("动作提示词被拒答", r.get("refused") is True and r["ok"] is False, r["text"][:50])
    chk("拒答写入审计", n1 > n0, f"审计 {n0}→{n1}")

    print("⑧ 真通道端到端 (web→本地→web)")
    if a.no_e2e:
        print("  ⏭ 跳过 (--no-e2e)")
    else:
        # ⚠️ 常驻服务每 5s 也在轮询同一个队列 → 会抢走取证用的提示词 (自己的 poll 就"看不到")
        #    → 取证期间停常驻, 取证完恢复 (与真机无关, 只是本机服务启停)
        subprocess.run("sudo systemctl stop zmax-web-agent-bridge.service", shell=True, capture_output=True)
        try:
            import urllib.request
            def post(path, obj):
                req = urllib.request.Request(b.relay + path, data=json.dumps(obj).encode(),
                                            headers={"Content-Type": "application/json"}, method="POST")
                return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
            def get(path):
                return json.loads(urllib.request.urlopen(b.relay + path, timeout=15).read().decode())
            # ⚠️ 别用 after=1e9 跳队尾: seq 是小整数(1,2,3…), after>seq 会让本轮新提示词也被过滤掉
            #    正确做法 = 读 /agent/status 的 last_prompt.seq 当游标
            tail = get("/agent/status").get("last_prompt") or {}
            b.cursor = int(tail.get("seq", 0) or 0)
            sent = post("/agent/prompt", {"text": "画布有多少节点 (端到端取证)", "from": "verify_web_agent_node"})
            chk("web 侧 POST 提示词成功", sent.get("ok") is True, f"seq={sent.get('seq')}")
            out = b.poll_once(timeout=15)
            got = [x for x in out.get("processed", []) if x["seq"] == sent.get("seq")]
            chk("本地桥拉到并派发", bool(got) and got[0]["ok"] is True, f"处理={out.get('processed')}")
            reps = get("/agent/reply?after=0").get("replies", [])
            mine = [x for x in reps if x.get("prompt_seq") == sent.get("seq")]
            chk("web 侧 GET 读到回执", bool(mine), f"回执条数={len(mine)}")
            if mine:
                chk("回执含真实数据 (节点数)", "nodes" in json.dumps(mine[-1].get("data"), ensure_ascii=False),
                    str(mine[-1].get("data"))[:70])
            print("⑨ 游标幂等")
            out2 = b.poll_once(timeout=15)
            chk("重复 poll 不重放", not out2.get("processed"), f"processed={out2.get('processed')}")
        finally:
            subprocess.run("sudo systemctl start zmax-web-agent-bridge.service", shell=True, capture_output=True)

    print("⑩ 节点执行器真调用")
    logs = []
    okx = b and NL_web_agent_run(logs, NL)
    chk("node_web_agent(ctx) 返回 True", okx is True)
    chk("执行日志含轮询动作", any("轮询" in x for x in logs), str(logs[:2])[:90])

    print("⑪ 只读红线字段")
    rr = b.dispatch("真机只读信号")["data"]
    chk("真机只读功能标注 readonly=True", rr.get("readonly") is True and "禁止" in str(rr.get("actuation")), str(rr)[:80])

    print("⑫ 常驻服务")
    st = subprocess.run("systemctl is-enabled zmax-web-agent-bridge.service 2>/dev/null; systemctl is-active zmax-web-agent-bridge.service 2>/dev/null",
                        shell=True, capture_output=True, text=True).stdout.split()
    chk("zmax-web-agent-bridge enabled+active", len(st) == 2 and st[0] == "enabled" and st[1] == "active", f"{st}")

    print(f"\n判据通过: {len(OK)}/{len(OK)+len(NG)}")
    if NG:
        print("❌ 未过:")
        for x in NG:
            print("   -", x)
    return 0 if not NG else 3


def NL_web_agent_run(logs: list, NL):
    """用 node_logic 的注册表真跑一次执行器 (ctx 注入日志收集)"""
    ctx = {"log": logs.append, "node": {"name": "🌐 Web 智能体桥 · 远程提示词", "params": {}},
           "module": None, "trace": None}
    fn = NL.NODE_LOGIC.get("n_web_agent", {}).get("fn")
    if fn is None:
        return False
    return fn(ctx) is True


if __name__ == "__main__":
    raise SystemExit(main())
