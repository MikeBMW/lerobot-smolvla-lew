#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 **设备名 + 能力** 解析出该用哪个 /dev/videoN —— 别再写死索引。

现场根因 (2026-09-28): `tools/boot_restore.sh` 里写死 `--local-dev 2 --local2-dev 0`,
而本机 video2 是笔记本相机的 **GREY 640x360 (IR/灰度) 那一路** —— 没有红外照明时整幅近黑
(实测 mean=6.0 / median=0 / 96% 像素 <20); 而 VL 安全闸把 "local" 当**笔记本相机(全局视角)**:
快反射层判『遮挡/糊化』⇒ 所有运动类原子技能一律拒发 (老倪: 「原子技能又不好使了」)。
video0 才是同一台相机的 MJPG 彩色那一路 (实测 mean=112 / Laplacian=260), video4 是 MAXHUB 顶视。

用法:
    python3 tools/cam_dev_resolve.py          # 打印 LOCAL=<n> / LOCAL2=<n> (找不到给 -1)
    python3 tools/cam_dev_resolve.py --json   # 机器可读 + 每个候选设备的实测理由

判据(全部实测, 不猜):
  ① local  = 卡名含 "Integrated RGB" **且** 支持 MJPG (彩色)   ← 排除同名的 GREY(IR) 节点
  ② local2 = 卡名含 "MAXHUB"                                   ← 顶视
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

VID = "/sys/class/video4linux"


def _name(dev: str) -> str:
    try:
        with open(os.path.join(VID, dev, "name"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _formats(dev: str):
    """该设备支持的像素格式集合 (v4l2-ctl; 设备被占用也能查, 不需要独占)。"""
    try:
        r = subprocess.run(["v4l2-ctl", "-d", "/dev/" + dev, "--list-formats"],
                           capture_output=True, text=True, timeout=6)
        return set(re.findall(r"'([A-Z0-9 ]{3,8})'", r.stdout or ""))
    except Exception:                                                       # noqa: BLE001
        return set()


def _idx(path: str) -> int:
    m = re.search(r"(\d+)$", path)
    return int(m.group(1)) if m else -1


def pick(prefer_rgb_name: str, prefer_top_name: str):
    devs = sorted(glob.glob(os.path.join(VID, "video*")), key=_idx)
    rows = []
    for p in devs:
        d = os.path.basename(p)
        fmts = _formats(d)
        rows.append({"dev": d, "name": _name(d), "formats": sorted(fmts)})

    def _has_mjpg(r):
        return "MJPG" in r["formats"]

    local = next((r["dev"] for r in rows
                  if prefer_rgb_name.lower() in r["name"].lower() and _has_mjpg(r)), None)
    if local is None:
        local = next((r["dev"] for r in rows if _has_mjpg(r)), None)     # 退一步: 任意彩色
    top = next((r["dev"] for r in rows
                if prefer_top_name.lower() in r["name"].lower() and _has_mjpg(r)
                and r["dev"] != local), None)
    return local, top, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rgb-name", default="Integrated RGB", help="笔记本彩色相机的卡名关键字")
    ap.add_argument("--top-name", default="MAXHUB", help="顶视相机的卡名关键字")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    local, top, rows = pick(a.rgb_name, a.top_name)
    n = lambda d: int(re.sub(r"\D", "", d)) if d else -1                          # noqa: E731
    if a.json:
        print(json.dumps({"local": n(local), "local2": n(top), "cands": rows},
                         ensure_ascii=False, indent=1))
    else:
        print("LOCAL=%d" % n(local))
        print("LOCAL2=%d" % n(top))
    return 0 if local else 1


if __name__ == "__main__":
    sys.exit(main())
