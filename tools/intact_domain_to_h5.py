# -*- coding: utf-8 -*-
"""📦 npz → INTACT 官方 h5 数据集 (必须用 INTACT 自己的 venv 跑, gui-venv 无 h5py)

schema (对齐官方 formats/hdf5.py): 每个 key 一个 dataset + 必需的 ep_len / ep_offset
  pixels(N,224,224,3 uint8, gzip) · action(N,4 f32) · observation(N,39 f32)
  ep_len(E) · ep_offset(E) · ep_idx(N) · step_idx(N)

--validate: 直接用官方 swm.data.load_dataset 读回来 (真正的闸: 官方加载器认不认我们的文件)
用法:
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_domain_to_h5.py \
     --npz reports/zmax_insert_raw.npz --out-name zmax_insert --validate
"""
import argparse
import json
import os
import sys
import time

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", required=True)
    ap.add_argument("--out-name", default="zmax_insert")
    ap.add_argument("--dest", default=os.environ.get("LOCAL_DATASET_DIR",
                                                     "/home/ubuntu/stable-wm-cache") + "/datasets")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--delete-npz", action="store_true")
    a = ap.parse_args()

    import h5py                                    # noqa: PLC0415

    d = np.load(a.npz, allow_pickle=True)
    L = np.asarray(d["ep_len"], dtype=np.int64)
    off = np.asarray(d["ep_offset"], dtype=np.int64)
    pix = d["pixels"]
    act = np.asarray(d["action"], dtype=np.float32)
    obs = np.asarray(d["observation"], dtype=np.float32)
    ep_idx = np.asarray(d["ep_idx"], dtype=np.int32)
    step_idx = np.asarray(d["step_idx"], dtype=np.int64)
    meta = d["meta"][0] if "meta" in d.files else {}
    assert int(L.sum()) == pix.shape[0] == act.shape[0] == obs.shape[0], "帧数/长度不一致"
    assert len(L) == len(off), "ep_len/ep_offset 长度不一致"

    os.makedirs(a.dest, exist_ok=True)
    out = os.path.join(a.dest, f"{a.out_name}.h5")
    t0 = time.time()
    with h5py.File(out, "w") as f:
        f.create_dataset("pixels", data=pix, dtype=np.uint8,
                         chunks=(32, pix.shape[1], pix.shape[2], 3),
                         compression="gzip", compression_opts=4)
        f.create_dataset("action", data=act, dtype=np.float32)
        f.create_dataset("observation", data=obs, dtype=np.float32)
        f.create_dataset("ep_len", data=L)
        f.create_dataset("ep_offset", data=off)
        f.create_dataset("ep_idx", data=ep_idx)
        f.create_dataset("step_idx", data=step_idx)
        f.attrs["meta"] = json.dumps({**meta, "npz": os.path.basename(a.npz),
                                      "written": time.strftime("%F %T")}, ensure_ascii=False)
        f.attrs["provenance"] = "tools/intact_domain_to_h5.py (INTACT venv)"
    sz = os.path.getsize(out)
    print(f"✅ {out}  {sz/1e6:.1f}MB  (回合 {len(L)} · 帧 {int(L.sum())} · "
          f"动作维 {act.shape[1]} · {time.time()-t0:.0f}s)")

    if a.validate:
        os.environ.setdefault("LOCAL_DATASET_DIR", os.path.dirname(a.dest))
        os.environ.setdefault("STABLEWM_HOME", os.path.dirname(a.dest))
        import stable_worldmodel as swm         # noqa: PLC0415
        ds = swm.data.load_dataset(a.out_name, cache_dir=os.path.dirname(a.dest),
                                  num_steps=8, frameskip=2,
                                  keys_to_load=["pixels", "action", "observation"],
                                  keys_to_cache=["action", "observation"])
        print(f"  官方 load_dataset OK: len={len(ds)} · get_dim(action)={ds.get_dim('action')} "
              f"· get_dim(pixels)={ds.get_dim('pixels')}")
        it = ds[0]
        print(f"  取一个样本: keys={sorted(it.keys()) if isinstance(it, dict) else type(it)}")
        if isinstance(it, dict):
            for k in ("pixels", "action"):
                if k in it:
                    v = np.asarray(it[k])
                    print(f"    {k}: shape={v.shape} mean={float(v.mean()):.4f} "
                          f"std={float(v.std()):.4f} finite={bool(np.isfinite(v).all())}")
        if a.delete_npz:
            os.remove(a.npz)
            print(f"  已删中间 npz ({os.path.basename(a.npz)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
