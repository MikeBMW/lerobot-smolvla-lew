#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_mount_test.py — 终极判定: 相机到底装在哪 / 板到底动不动

用**图像本身**说话 (不依赖任何姿态约定):
  ① 每个样本: 20 点板的**像素质心** + 该位姿 TCP → 若 TCP 大幅变化而质心几乎不动 ⇒ 板在相机里没动
  ② 两两样本做 cv2.phaseCorrelate 求**整幅画面位移** (px):
       画面位移 ≈ 27px 级 (工具动 34mm @0.5m, fx=394) ⇒ 相机跟着机械臂动 (eye-in-hand ✓)
       画面位移 ≈ 0px 而板质心也不动              ⇒ 相机没动 (相机固定, 板跟着臂动?)
用法: gui-venv311/bin/python tools/handeye_mount_test.py [--session DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
from handeye_solve_ls import detect, _quat_order, _q2R   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    a = ap.parse_args()
    sess = a.session or sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
    raw = [json.loads(l) for l in open(os.path.join(sess, "poses.jsonl"), encoding="utf-8") if l.strip()]
    rows = []
    for r in raw:
        img = cv2.imread(r["img"])
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cs, _ = detect(g)
        cen = cs.mean(axis=0) if cs is not None else None
        rows.append({"idx": r["idx"], "tcp": r["tcp"], "cen": cen, "gray": g, "img": r["img"]})
    print(f"会话 {os.path.basename(sess.rstrip('/'))} · 样本 {len(rows)}\n")
    print("① 板像素质心 vs TCP (工具位移 mm / 质心位移 px)")
    base = rows[0]
    for r in rows:
        if r["cen"] is None:
            print(f"  #{r['idx']}: 板未检出 · TCP {[round(v, 4) for v in r['tcp']]}")
            continue
        d_tcp = float(np.linalg.norm(np.array(r["tcp"]) - np.array(base["tcp"])) * 1000)
        d_px = float(np.linalg.norm(r["cen"] - base["cen"])) if base["cen"] is not None else float("nan")
        print(f"  #{r['idx']}: 工具位移 {d_tcp:6.1f}mm → 板质心位移 {d_px:6.1f}px · "
              f"质心 [{r['cen'][0]:.1f}, {r['cen'][1]:.1f}]")
    print("\n② 整幅画面位移 (phaseCorrelate, 相对 #1)")
    for r in rows[1:]:
        try:
            (dx, dy), resp = cv2.phaseCorrelate(np.float32(base["gray"]), np.float32(r["gray"]))
        except Exception as e:                                                 # noqa: BLE001
            print(f"  #{r['idx']}: 失败 {type(e).__name__}")
            continue
        d_tcp = float(np.linalg.norm(np.array(r["tcp"]) - np.array(base["tcp"])) * 1000)
        print(f"  #{r['idx']}: 画面位移 ({dx:6.1f}, {dy:6.1f})px 相关度 {resp:.3f} · 工具位移 {d_tcp:6.1f}mm")
    print("\n判读要点: 工具位移几十 mm 时, 若画面位移 ≈0 且板质心 ≈不动 → 相机没跟着动;")
    print("          若画面位移随工具位移变化 (约 fx*Δ/距) → 相机确实装在臂上 (eye-in-hand ✓)")


if __name__ == "__main__":
    main()
