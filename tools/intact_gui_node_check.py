# -*- coding: utf-8 -*-
"""GUI 节点层回归: node_intact / node_intact_dec 是否还能真跑 (重构后 = 瘦调用 policy 层服务)。

用法: INTACT_DEVICE=cpu INTACT_POLICY=<name> QT_QPA_PLATFORM=offscreen \
        gui-venv311/bin/python tools/intact_gui_node_check.py
判据: 关键字匹配 + 两节点真跑返回 True + 面板 mod._intact_dec 挂上 (u_ff 4D) + 未标定诚实标记。
"""
import os
import sys
import types

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
import node_logic                                             # noqa: E402

print("① 关键字匹配:", node_logic.match_node("INTACT 意图解码器"), node_logic.match_node("INTACT 策略"))
mod = types.SimpleNamespace()
ctx = {"log": lambda s: print(s, flush=True), "root": ROOT, "module": mod, "stage": ""}

print("\n② node_intact_dec (L4→L3 解码器)")
ok = node_logic.node_intact_dec(ctx)
print("   返回:", ok)
panel = getattr(mod, "_intact_dec", None)
print("   面板 mod._intact_dec:", {k: (list(v) if hasattr(v, "__len__") and not isinstance(v, (str, dict)) else v)
                                  for k, v in (panel or {}).items()})

print("\n③ node_intact (策略节点)")
ok2 = node_logic.node_intact(ctx)
print("   返回:", ok2)

checks = {
    "关键字能匹配到节点": node_logic.match_node("INTACT 意图解码器") in ("intact_dec", "intact"),
    "解码器节点真跑 (True)": ok is True,
    "面板已挂 _intact_dec": isinstance(panel, dict) and "u_ff" in panel,
    "面板 u_ff 4 维非空": bool(panel) and len(panel["u_ff"]) == 4,
    "面板 cond_ready=False (未标定诚实)": panel is not None and panel["cond_ready"] is False,
    "策略节点真跑 (True)": ok2 is True,
}
print()
for k, v in checks.items():
    print(("  ✅ " if v else "  ❌ ") + k)
print("verdict:", "PASS" if all(checks.values()) else "FAIL")
