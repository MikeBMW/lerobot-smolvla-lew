#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vpc_*.py — 感知链单条判据入口 (文件名决定查哪条: vpc_<check>.py)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_perception_chain import CHECKS

name = os.path.basename(__file__)[4:-3]
ok, detail = CHECKS[name]()
print(("✅ " if ok else "❌ ") + name + " · " + str(detail))
sys.exit(0 if ok else 1)
