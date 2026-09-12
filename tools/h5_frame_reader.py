# -*- coding: utf-8 -*-
"""🖼️ h5 数据集单帧/信息读取器 (INTACT venv 跑; gui-venv 无 h5py)

控制台数据集查看器要能翻 stable-wm-cache 下的 h5 (zmax_insert*.h5 / tworoom / cube)。
gui-venv311 没有 h5py → 用 INTACT venv 起短进程读, 一次调用输出所需内容。

用法:
  # 信息 (JSON, 含**每回合真实帧数**, 供查看器设置滑块上限 — 不许再用假的 300/100)
  .venv/bin/python tools/h5_frame_reader.py --h5 /path/x.h5 --info
  # 取某回合第 F 帧 → PNG (RGB 原图, 供查看器显示)
  .venv/bin/python tools/h5_frame_reader.py --h5 /path/x.h5 --ep 0 --frame 10 --out /tmp/f.png
  # 取该帧的 action / observation (JSON, 供状态页真实显示)
  .venv/bin/python tools/h5_frame_reader.py --h5 /path/x.h5 --ep 0 --frame 10 --vec
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np


def _open(h5):
    import h5py                                             # noqa: PLC0415
    try:
        import hdf5plugin                                   # noqa: F401,PLC0415
    except Exception:
        pass                                                # tworoom/cube 的 blosc 需要它
    return h5py.File(h5, "r")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", required=True)
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--ep", type=int, default=0)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--vec", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.h5):
        print(json.dumps({"ok": False, "error": f"文件不存在: {a.h5}"}, ensure_ascii=False))
        return 2
    f = _open(a.h5)
    keys = set(f.keys())
    L = np.asarray(f["ep_len"][:], np.int64) if "ep_len" in keys else np.zeros(0, np.int64)
    off = np.asarray(f["ep_offset"][:], np.int64) if "ep_offset" in keys \
        else np.concatenate([[0], np.cumsum(L)[:-1]]).astype(np.int64)

    if a.info:
        info = {"ok": True, "path": a.h5, "keys": sorted(keys),
                "episodes": int(len(L)), "frames": int(L.sum()),
                "ep_len": [int(x) for x in L[:2000]],           # 每回合真实帧数 (滑块上限)
                "action_dim": (int(f["action"].shape[1]) if "action" in keys else None),
                "obs_dim": (int(f["observation"].shape[1]) if "observation" in keys else None),
                "pixels_shape": (list(f["pixels"].shape[1:]) if "pixels" in keys else None)}
        mt = f.attrs.get("meta")
        if isinstance(mt, (str, bytes)):
            try:
                info["meta"] = json.loads(mt)
            except Exception:
                pass
        f.close()
        print(json.dumps(info, ensure_ascii=False))
        return 0

    e = max(0, min(int(a.ep), max(len(L) - 1, 0)))
    n_ep = int(L[e]) if len(L) else 0
    fr = max(0, min(int(a.frame), max(n_ep - 1, 0)))
    gi = int(off[e]) + fr if len(L) else fr
    out = {"ok": True, "ep": e, "frame": fr, "ep_len": n_ep, "global_index": gi}
    if "action" in keys:
        out["action"] = [round(float(x), 5) for x in np.asarray(f["action"][gi]).ravel()]
    if "observation" in keys:
        out["observation"] = [round(float(x), 4) for x in np.asarray(f["observation"][gi]).ravel()[:39]]
    if a.out and "pixels" in keys:
        px = np.asarray(f["pixels"][gi])                        # (H,W,3) uint8
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        try:
            import cv2                                        # noqa: PLC0415
            cv2.imwrite(a.out, cv2.cvtColor(px, cv2.COLOR_RGB2BGR))
        except Exception:
            try:
                from PIL import Image                         # noqa: PLC0415
                Image.fromarray(px).save(a.out)
            except Exception as ex:
                out.update({"ok": False, "error": f"写图失败: {type(ex).__name__}: {ex}"})
        out["png"] = a.out
        out["frame_std"] = round(float(px.std()), 2)             # 黑帧判据 (>5 = 真图)
    f.close()
    print(json.dumps(out if a.vec or a.out else {"ok": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
