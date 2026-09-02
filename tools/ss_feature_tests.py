#!/usr/bin/env python3
"""🧪 ss_feature_tests.py — 状态空间系统验证 CLI (薄封装, 真源 verification_layer.py)

用法 (gui-venv311):
  gui-venv311/bin/python tools/ss_feature_tests.py --list            # feature 清单
  gui-venv311/bin/python tools/ss_feature_tests.py --only F-A01      # 单用例
  gui-venv311/bin/python tools/ss_feature_tests.py                   # 全量 (含 YOLO 慢用例)
  gui-venv311/bin/python tools/ss_feature_tests.py --skip-slow       # 全量跳过 YOLO
  echo $?   # 0=全过 1=有 FAIL

YOLO 感知用例 (F-C01/C02) 需要 DISPLAY (metaworld 渲染); 无显示环境自动报 FAIL 提示。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_P = os.path.join(ROOT, "src", "lerobot", "verification", "verification_layer.py")
_spec = importlib.util.spec_from_file_location("lerobot.verification.verification_layer", _P)
_vl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vl)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="🧪 状态空间验证层 CLI")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--skip-slow", action="store_true")
    a = ap.parse_args()
    v = _vl.VerificationLayer()
    if a.list:
        v.list_features()
        sys.exit(0)
    if a.only:
        sys.exit(0 if v.run(a.only)[0] else 1)
    sys.exit(0 if v.run_all(skip_slow=a.skip_slow) else 1)
