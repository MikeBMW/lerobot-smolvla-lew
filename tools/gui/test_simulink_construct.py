#!/usr/bin/env python3
"""本机实测 SimulinkModule 构造 — 定位 Mac 黑屏是否代码问题 (2026-08-26)
用法: gui-venv311/bin/python test_simulink_construct.py
"""
import os, sys, time, traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_OPENGL"] = "software"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui"))
# gui 目录
GUI_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, GUI_DIR)

LOG = "/tmp/zmax_simulink_init.log"
def mk(m):
    with open(LOG, "a") as f:
        f.write(f"{time.time():.1f} {m}\n")
    print(f"[{time.time():.1f}] {m}", flush=True)

mk("TEST START")
try:
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    mk("QApplication OK")
except Exception as e:
    mk(f"QApplication FAIL: {e!r}")
    traceback.print_exc()
    sys.exit(1)

try:
    mk("import simulink_module")
    import simulink_module
    mk("import OK")
except Exception as e:
    mk(f"import FAIL: {e!r}")
    traceback.print_exc()
    sys.exit(1)

try:
    mk("SimulinkModule() 构造开始")
    sim = simulink_module.SimulinkModule()
    mk("SimulinkModule() 构造完成 ✅")
    print("✅ 构造成功! 节点数:", len(sim.nodes))
except Exception as e:
    mk(f"SimulinkModule() 构造 FAIL: {e!r}")
    traceback.print_exc()
    sys.exit(1)
