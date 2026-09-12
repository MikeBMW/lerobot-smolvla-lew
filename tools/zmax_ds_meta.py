# -*- coding: utf-8 -*-
"""📇 数据集台账: 扫描 h5 数据集 → 写 zmax_datasets.json (控制台数据集管理页读它)

为什么需要: gui-venv311 没装 h5py, 控制台读不了 h5 里的 attrs/统计 → 数据集管理页看不到
我们的 INTACT 域内数据 (zmax_insert*.h5) 与官方数据 (tworoom/cube)。所以由 INTACT venv
(有 h5py) 生成一份 json 台账, 控制台只读 json。

台账每项: 名称/路径/大小/回合/帧/动作维/观测维/done率/帧std/来源/用途/时间
用法 (INTACT venv):
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/zmax_ds_meta.py
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

def _cache_candidates():
    """stable_worldmodel 缓存位置 (与 swm.data.utils.get_cache_dir 同序, 再补本机实测路径)。
    swm 官方: $STABLEWM_HOME → 默认 ~/.stable_worldmodel; 本机另用 ~/stable-wm-cache。"""
    cands = [os.environ.get("STABLEWM_HOME"), os.environ.get("LOCAL_DATASET_DIR"),
             os.path.expanduser("~/.stable_worldmodel"), os.path.expanduser("~/stable-wm-cache")]
    out, seen = [], set()
    for c in cands:
        if not c:
            continue
        c = os.path.expanduser(c)
        if c in seen or not os.path.isdir(c):
            continue
        seen.add(c)
        out.append(c)
    return out


CACHE, DS_DIR = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"), None

# 用途/来源标注 (人工维护: 让面板上"这数据是干嘛的"一眼可见)
PURPOSE = {
    "zmax_insert": ("INTACT 域内微调 v1 (36回合)", "Z-MAX 六层引擎真链路"),
    "zmax_insert_v2": ("INTACT 域内微调 v2 (300回合, 动作头权重1.0)", "Z-MAX 六层引擎真链路"),
    "tworoom": ("INTACT 官方基准任务", "INTACT 官方数据集"),
    "cube_single_expert": ("INTACT 官方基准任务", "INTACT 官方数据集"),
}


def _scan(ds_dir: str) -> list:
    """扫一个 datasets/ 目录 → 行 (含 h5 真实统计; 读不了就记 error, 不编数)。"""
    import h5py                                             # noqa: PLC0415 (局部 import: 只有本函数需要)
    rows = []
    for fn in sorted(os.listdir(ds_dir)):
        if not fn.endswith((".h5", ".hdf5")):
            continue
        p = os.path.join(ds_dir, fn)
        name = fn.rsplit(".", 1)[0]
        rec = {"name": name, "file": fn, "path": p, "cache": os.path.dirname(ds_dir),
               "size_gb": round(os.path.getsize(p) / 1e9, 2),
               "mtime": time.strftime("%F %T", time.localtime(os.path.getmtime(p))),
               "purpose": PURPOSE.get(name, ("未标注", "?"))[0],
               "source": PURPOSE.get(name, ("", "?"))[1],
               "readable": False}
        try:
            with h5py.File(p, "r") as f:
                keys = set(f.keys())
                rec["keys"] = sorted(keys)
                L = np.asarray(f["ep_len"][:], np.int64) if "ep_len" in keys else None
                rec["episodes"] = int(len(L)) if L is not None else None
                rec["frames"] = int(L.sum()) if L is not None else int(f["action"].shape[0])
                if "action" in keys:
                    rec["action_dim"] = int(f["action"].shape[1])
                if "observation" in keys:
                    rec["obs_dim"] = int(f["observation"].shape[1])
                # 帧有效性抽样 (黑帧红线: std<=5 = 蒙眼, 不许当数据)
                if "pixels" in keys:
                    n = f["pixels"].shape[0]
                    idx = np.linspace(0, n - 1, min(16, n)).astype(int)
                    stds = [float(np.asarray(f["pixels"][int(i)]).std()) for i in idx]
                    rec["frame_std_min"] = round(min(stds), 2)
                    rec["frame_std_max"] = round(max(stds), 2)
                    rec["frames_real"] = bool(min(stds) > 5.0)
                mt = f.attrs.get("meta")
                if isinstance(mt, (str, bytes)):
                    try:
                        m = json.loads(mt)
                        rec["episodes"] = m.get("episodes", rec.get("episodes"))
                        rec["frames"] = m.get("frames", rec.get("frames"))
                        rec["done_rate"] = m.get("done_rate")
                        if m.get("ep_frame_std_min") is not None:
                            rec["frame_std_min"] = m.get("ep_frame_std_min")
                            rec["frame_std_max"] = m.get("ep_frame_std_max")
                            rec["frames_real"] = bool(m.get("ep_frame_std_min", 0) > 5.0)
                        rec["meta_source"] = m.get("source")
                    except Exception:
                        pass
                rec["readable"] = True
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        rows.append(rec)
    return rows


def main():
    import h5py                                             # noqa: PLC0415
    try:
        import hdf5plugin                                   # noqa: F401,PLC0415
    except Exception:                                       # tworoom/cube 的 pixels 用 blosc(32001)
        print("⚠️ hdf5plugin 未装 → 官方 tworoom/cube 的 pixels 可能读不了")
    cands = _cache_candidates()
    if not cands:
        print("❌ 找不到 stable_worldmodel 缓存 (STABLEWM_HOME / ~/.stable_worldmodel / ~/stable-wm-cache)")
        return 2
    print(f"缓存候选: {cands}")
    rows, outs = [], []
    for c in cands:
        ds_dir = os.path.join(c, "datasets")
        if not os.path.isdir(ds_dir) or not any(f.endswith((".h5", ".hdf5"))
                                                for f in os.listdir(ds_dir)):
            continue
        rows += _scan(ds_dir)
        outs.append(os.path.join(ds_dir, "zmax_datasets.json"))
    if not rows:
        print("❌ 任何缓存里都没有 h5 数据集")
        return 2

    payload = {"cache": cands[0], "caches": cands, "ds_dir": os.path.join(cands[0], "datasets"),
               "generated": time.strftime("%F %T"), "count": len(rows), "datasets": rows,
               "note": "由 tools/zmax_ds_meta.py (INTACT venv) 生成; 控制台数据集管理页只读此 json; "
                       "缓存顺序 = swm 官方 ($STABLEWM_HOME → ~/.stable_worldmodel) + 本机 ~/stable-wm-cache"}
    for o in outs:
        with open(o, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"→ {o}")
    print(f"   台账 {len(rows)} 个数据集")
    for r in rows:
        if r.get("readable"):
            print(f"   {r['name']:<20} {r['size_gb']:>7.2f}GB · 回合 {r.get('episodes')} · "
                  f"帧 {r.get('frames')} · act {r.get('action_dim')}D · "
                  f"odim {r.get('obs_dim')} · 帧std {r.get('frame_std_min')}~{r.get('frame_std_max')} · "
                  f"真图 {r.get('frames_real')} · {r['purpose']} · {r.get('cache')}")
        else:
            print(f"   {r['name']:<20} {r['size_gb']:>7.2f}GB · ⚠️ {str(r.get('error'))[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
