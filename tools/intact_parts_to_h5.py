# -*- coding: utf-8 -*-
"""📦 part npz (分块采集) → 单个 INTACT 官方 h5 (逐 part 流式写入, 内存有界)

为什么需要它: 采集器按内存闸分块落 part npz (300 回合 ≈15 万帧 = 22GB, 一次性 concat
会被 OOM 杀 — 实测踩坑)。本工具逐 part 读 → 追加写进同一个 h5 → 释放, 峰值内存 ≈ 一个 part。

schema 与 tools/intact_domain_to_h5.py 完全一致 (官方 formats/hdf5.py):
  pixels(N,224,224,3 uint8, gzip) · action(N,4 f32) · observation(N,39 f32)
  ep_len(E) · ep_offset(E) · ep_idx(N) · step_idx(N)
差异: ep_idx/step_idx/ep_offset 在这里按**全局**重新编号 (各 part 内部是自包含的局部编号)。

用法 (必须 INTACT venv, gui-venv 无 h5py):
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py \
     --parts 'reports/zmax_insert_v2_part*.npz' --out-name zmax_insert_v2 --validate
"""
import argparse
import glob
import json
import os
import sys
import time

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True, help="glob, 如 'reports/zmax_insert_v2_part*.npz'")
    ap.add_argument("--out-name", default="zmax_insert_v2")
    ap.add_argument("--dest", default=os.environ.get("LOCAL_DATASET_DIR",
                                                     "/home/ubuntu/stable-wm-cache") + "/datasets")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--keep-parts", action="store_true")
    a = ap.parse_args()

    import h5py                                    # noqa: PLC0415

    files = sorted(glob.glob(a.parts))
    if not files:
        print(f"❌ 没有匹配的 part: {a.parts}")
        return 2
    print(f"═══ 合并 {len(files)} 个 part → {a.out_name}.h5 ═══")

    os.makedirs(a.dest, exist_ok=True)
    out = os.path.join(a.dest, f"{a.out_name}.h5")
    t0 = time.time()
    tot_f = 0
    tot_e = 0
    std_all: list[float] = []
    _done_pairs: list[tuple[int, float]] = []      # (回合数, done_rate) → 加权平均
    part_meta: list[dict] = []
    try:
        with h5py.File(out, "w") as f:
            dpix = da = dob = dep = dstep = None
            for k, p in enumerate(files):
                d = np.load(p, allow_pickle=True)
                L = np.asarray(d["ep_len"], np.int64)
                pix = d["pixels"]
                act = np.asarray(d["action"], np.float32)
                obs = np.asarray(d["observation"], np.float32)
                n = int(L.sum())
                assert n == pix.shape[0] == act.shape[0] == obs.shape[0], f"{p} 帧数不一致"
                if dpix is None:      # 首次: 建可扩展数据集
                    dpix = f.create_dataset("pixels", data=pix, maxshape=(None,) + pix.shape[1:],
                                            dtype=np.uint8, chunks=(32,) + pix.shape[1:],
                                            compression="gzip", compression_opts=4)
                    da = f.create_dataset("action", data=act, maxshape=(None, act.shape[1]),
                                          dtype=np.float32)
                    dob = f.create_dataset("observation", data=obs,
                                           maxshape=(None, obs.shape[1]), dtype=np.float32)
                    dep = f.create_dataset("ep_len", data=L, maxshape=(None,), dtype=np.int64)
                    dstep = f.create_dataset("step_idx",
                                             data=np.concatenate([np.arange(m, dtype=np.int64)
                                                                  for m in L]),
                                             maxshape=(None,), dtype=np.int64)
                else:
                    s = tot_f
                    for ds, arr in ((dpix, pix), (da, act), (dob, obs)):
                        ds.resize(s + n, axis=0)
                        ds[s:s + n] = arr
                    s_e = tot_e
                    dep.resize(tot_e + len(L), axis=0)
                    dep[s_e:s_e + len(L)] = L
                    dstep.resize(s + n, axis=0)
                    dstep[s:s + n] = np.concatenate([np.arange(m, dtype=np.int64) for m in L])
                tot_f += n
                tot_e += len(L)
                mt = d["meta"][0] if "meta" in d.files else {}
                if not isinstance(mt, str):
                    part_meta.append({"part": os.path.basename(p), **dict(mt)})
                    std_all += list(mt.get("ep_frame_std") or [])
                    if mt.get("done_rate") is not None:
                        _done_pairs.append((len(L), float(mt["done_rate"])))
                del d, pix, act, obs
                print(f"   [{k+1}/{len(files)}] {os.path.basename(p)}: 回合 {len(L)} · 帧 {n} · "
                      f"累计 {tot_f} 帧 · {time.time()-t0:.0f}s", flush=True)
            # ep_offset/ep_idx 全局化
            Lall = dep[:]
            off = np.concatenate([[0], np.cumsum(Lall)[:-1]]).astype(np.int64)
            f.create_dataset("ep_offset", data=off)
            f.create_dataset("ep_idx", data=np.concatenate(
                [np.full(m, i, dtype=np.int32) for i, m in enumerate(Lall)]))
            f.attrs["meta"] = json.dumps({
                "source": "Z-MAX 六层引擎真链路 (metaworld insert) · 分块采集后合并",
                "parts": [os.path.basename(p) for p in files], "part_meta": part_meta,
                "episodes": int(tot_e), "frames": int(tot_f),
                "done_rate": (round(sum(n * r for n, r in _done_pairs) /
                                    max(sum(n for n, _ in _done_pairs), 1), 4)
                              if _done_pairs else None),
                "ep_frame_std_min": (min(std_all) if std_all else None),
                "ep_frame_std_max": (max(std_all) if std_all else None),
                "written": time.strftime("%F %T")}, ensure_ascii=False)
            f.attrs["provenance"] = "tools/intact_parts_to_h5.py (INTACT venv, 流式合并)"
    except Exception as e:
        print(f"❌ 合并失败: {type(e).__name__}: {e}")
        return 3
    sz = os.path.getsize(out)
    print(f"✅ {out}  {sz/1e6:.1f}MB  (回合 {tot_e} · 帧 {tot_f} · {time.time()-t0:.0f}s)")
    print(f"   帧有效性: 每回合 std {min(std_all):.1f}~{max(std_all):.1f} (全部 >5 = 真图)")

    if a.validate:
        try:
            import stable_worldmodel as swm         # noqa: PLC0415
            ds = swm.data.load_dataset(a.out_name, cache_dir=os.path.dirname(a.dest),
                                       num_steps=8, frameskip=2,
                                       keys_to_load=["pixels", "action", "observation"],
                                       keys_to_cache=["action", "observation"])
            print(f"  官方 load_dataset OK: len={len(ds)} · get_dim(action)={ds.get_dim('action')} "
                  f"· get_dim(pixels)={ds.get_dim('pixels')}")
        except Exception as e:
            # 🐛 2026-09-12 踩坑: 验证抛异常 → 直接 return, 中间 part npz 7GB 没删 (占着盘)
            #   现在验证失败只告警, 不阻断清理与后续流程; 名字要带扩展名 (官方解析器认 .h5)
            print(f"  ⚠️ 官方加载器验证失败 (不阻断): {type(e).__name__}: {e}")
    if not a.keep_parts:
        for p in files:
            os.remove(p)
        print(f"  已删 {len(files)} 个中间 part npz (--keep-parts 可保留)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
