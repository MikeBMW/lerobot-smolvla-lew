#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""img_content_diff.py — 直接比内容: 样本图之间到底变了多少 (像素级)

现场困惑: 工具动了 34mm/转过 8°, 而"板在相机里的位姿"只变了 1.4mm/0.4° → 画面没跟着动?
本脚本给出**像素级**证据 (比任何位姿推理都硬):
  · 两两样本: 灰度平均绝对差 (0=完全一样) · 变化像素占比 (>10 灰度差) · 板质心位移
用法: gui-venv311/bin/python tools/img_content_diff.py [--session DIR]
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import os
import sys

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
from handeye_solve_ls import detect   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    a = ap.parse_args()
    sess = a.session or sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
    rows = [json.loads(l) for l in open(os.path.join(sess, "poses.jsonl"), encoding="utf-8") if l.strip()]
    imgs, cens, tcps = {}, {}, {}
    for r in rows:
        g = cv2.cvtColor(cv2.imread(r["img"]), cv2.COLOR_BGR2GRAY)
        imgs[r["idx"]] = g
        cs, _ = detect(g)
        cens[r["idx"]] = None if cs is None else cs.mean(axis=0)
        tcps[r["idx"]] = np.array(r["tcp"], float)
    print(f"会话 {os.path.basename(sess.rstrip('/'))} · 样本 {rows[0]['idx']}..{rows[-1]['idx']}\n")
    print("两两对比: 灰度平均差 · 变化>10灰度的像素占比 · 板质心位移(px) · 工具位移(mm)")
    for i, j in itertools.combinations([r["idx"] for r in rows], 2):
        d = np.abs(imgs[i].astype(np.int16) - imgs[j].astype(np.int16))
        mad = float(d.mean())
        frac = float((d > 10).mean() * 100)
        dc = (float(np.linalg.norm(cens[i] - cens[j])) if cens[i] is not None and cens[j] is not None else -1)
        dt = float(np.linalg.norm(tcps[i] - tcps[j]) * 1000)
        print(f"  #{i} vs #{j}: 灰度差 {mad:5.2f} · 变化像素 {frac:5.1f}% · 板质心 {dc:6.1f}px · 工具位移 {dt:6.1f}mm")
    print("\n判读: 若'变化像素'很小 (≲2%) 而工具位移几十 mm ⇒ 画面内容没跟着机械臂动")


if __name__ == "__main__":
    main()
