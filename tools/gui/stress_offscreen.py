#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offscreen 压测: 模拟用户操作 10 分钟, 验证 Segfault 是否 X11/VcXsrv 相关
(offscreen 平台无 X11 → 若不崩 = X11 层问题; 若崩 = 纯 Qt/代码问题)
"""
import sys, os, json
# 解析 --minutes 后还原 argv (simulink_module 可能读 sys.argv)
_minutes = 10
for _i, _a in enumerate(sys.argv):
    if _a == "--minutes" and _i + 1 < len(sys.argv):
        try:
            _minutes = max(1, min(int(sys.argv[_i + 1]), 60))
        except ValueError:
            pass
sys.argv = ["x"]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ⚠️ 压测会触发模式开关持久化写回 (a72bb04 起) → 污染画布 JSON
# 启动时全量备份 flows/, atexit 恢复 (崩溃时由调用方 git checkout 兜底)
import atexit, shutil, tempfile
_flows_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "flows")
_flow_backup = tempfile.mkdtemp(prefix="flow_backup_")
if os.path.isdir(_flows_dir):
    for _f in os.listdir(_flows_dir):
        if _f.endswith(".json"):
            shutil.copy2(os.path.join(_flows_dir, _f), os.path.join(_flow_backup, _f))

def _restore_flows():
    if os.path.isdir(_flows_dir):
        for _f in os.listdir(_flow_backup):
            shutil.copy2(os.path.join(_flow_backup, _f), os.path.join(_flows_dir, _f))
    print(f"[stress] 画布 JSON 已从备份恢复: {_flow_backup}")

atexit.register(_restore_flows)

from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtCore import QTimer, Qt
app = QApplication([])

import simulink_module as sm
from feature_list import FeatureListDialog

m = sm.SimulinkModule()
win = QMainWindow()
win.setCentralWidget(m)
win.resize(1400, 900)
win.show()

FLOWS = {
    "state_space": "/root/lerobot-smolvla-lew/flows/state_space_obs.json",
    "z700": "/root/lerobot-smolvla-lew/flows/z700_flow.json",
}
import glob
flow_files = sorted(glob.glob("/root/lerobot-smolvla-lew/flows/*.json"))
print("可用画布:", len(flow_files))

step = {"n": 0}
dlg_ref = {"d": None}

def _sim_user():
    """每 2s 模拟一次用户操作"""
    s = step["n"]
    try:
        if s % 6 == 0:
            # 切画布 (状态空间 ↔ 其他)
            p = FLOWS["state_space"] if s % 12 == 0 else flow_files[s % len(flow_files)]
            m.load_flow_file(p, confirm=False)
        elif s % 6 == 1:
            # 双击模式开关
            md = next((n for n in m.nodes if n.get("type") == "mode_switch"), None)
            if md:
                m.on_node_activated(md)
        elif s % 6 == 2:
            # 双击数据源 (on_run_env → 但只走日志分支, 不真训练)
            src = next((n for n in m.nodes if n.get("params", {}).get("run_env")), None)
            if src:
                m._log(f"模拟双击数据源: {src['name']}")
        elif s % 6 == 3:
            # 打开 FeatureList 弹窗 → 关闭
            if dlg_ref["d"] is None or not dlg_ref["d"].isVisible():
                d = FeatureListDialog(module=m)
                dlg_ref["d"] = d
                d.show()
            else:
                dlg_ref["d"].close()
                dlg_ref["d"] = None
        elif s % 6 == 4:
            # 强制重绘 (滚动路径)
            m.canvas.viewport().repaint()
            m.canvas._scene.update()
        elif s % 6 == 5:
            # 模式切换 + 画布更新
            md = next((n for n in m.nodes if n.get("type") == "mode_switch"), None)
            if md:
                m._toggle_mode(md)
        app.processEvents()
        step["n"] += 1
    except Exception as ex:
        print(f"模拟步骤 {s} 异常(可忽略): {ex}")

_t = QTimer()
_t.timeout.connect(_sim_user)
_t.start(2000)

def _report():
    print(f"✅ offscreen 压测存活: {step['n']} 步 × 2s = {step['n']*2}s, 无崩溃")
    app.quit()

QTimer.singleShot(_minutes * 60 * 1000, _report)  # 默认 10 分钟
print(f"offscreen 压测启动 ({_minutes}分钟, 每2s模拟操作)...")
app.exec_()
print("压测结束")
