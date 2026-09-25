#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_web_agent.py (CLI) — 🌐 L5 Web 智能体桥 命令行/常驻入口

老倪 2026-09-25: 「开通一个状态空间 L5 的新节点, 用于与 web 的 agent 交换信息 … 远程通过提示词操纵
状态空间的功能」→ 本 CLI 就是那个节点的**执行体** (画布节点 = 🌐 Web 智能体桥 · 远程提示词)。

⚠️ 命名坑: 本文件**不能**叫 web_agent_bridge.py —— 与真源模块同名会让 `import web_agent_bridge`
导到自己 (shadow) → 报 "Module is not callable"。所以 CLI 用 ss_web_agent.py。

用法:
  python tools/ss_web_agent.py --ask "状态空间现在什么情况"   # 本地直接派发 (离线排障/演示)
  python tools/ss_web_agent.py --list                        # 能力清单 (远程可调功能)
  python tools/ss_web_agent.py --once                        # 拉一轮 web 提示词 → 派发 → 回执
  python tools/ss_web_agent.py --watch --interval 5          # 常驻 (systemd 用)
  python tools/ss_web_agent.py --status                      # 通道两侧计数
红线: 只读白名单; 动作类提示词拒答; 绝不触发真机动作与产线拍照。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SS = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space")
sys.path.insert(0, SS)

import web_agent_bridge as W  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", default="", help="本地派发一条提示词 (离线)")
    ap.add_argument("--list", action="store_true", help="能力清单")
    ap.add_argument("--once", action="store_true", help="拉一轮 web 提示词")
    ap.add_argument("--watch", action="store_true", help="常驻监听")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--seconds", type=float, default=0.0)
    ap.add_argument("--status", action="store_true", help="通道计数")
    a = ap.parse_args()

    b = W.WebAgentBridge()
    print(f"🌐 L5 Web 智能体桥 · 中转={W.RELAY} · 游标={b.cursor} (只读白名单)", flush=True)

    if a.list:
        print(json.dumps(b.f_help(""), ensure_ascii=False, indent=1))
        return 0
    if a.ask:
        r = b.dispatch(a.ask)
        print(json.dumps(r, ensure_ascii=False, indent=1)[:2000])
        return 0 if r.get("ok") else 1
    if a.status:
        print(json.dumps(W._get("/agent/status"), ensure_ascii=False, indent=1)[:1200])
        return 0
    if a.watch:
        b.watch(a.interval, a.seconds)
        return 0
    r = b.poll_once()                    # 默认 = --once
    print(json.dumps(r, ensure_ascii=False, indent=1)[:1500])
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
