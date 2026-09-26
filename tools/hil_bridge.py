#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hil_bridge.py (CLI) — 🙋 HIL 人机在环桥 命令行/常驻入口 (画布 n_hil 节点的执行体)

用法:
  python3 tools/hil_bridge.py --status              # 只看本机要上报的状态 (不发送)
  python3 tools/hil_bridge.py --once                # 上报一次 + 处理一轮人的指示
  python3 tools/hil_bridge.py --watch --interval 5  # 常驻 (systemd zmax-hil-bridge)
网页: https://datadrive.world/hil.html (hermes 形式聊天界面)
"""
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/src")
sys.path.insert(0, "/home/ubuntu/zmax_rel/src/lerobot/policies/left_right/state_space")
from lerobot.policies.left_right.state_space.hil_bridge import main  # noqa: E402

if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
