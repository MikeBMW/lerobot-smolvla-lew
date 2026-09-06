#!/usr/bin/env python3
"""convert_mw_raw_to_ss.py — metaworld raw trace → 状态空间训练 npz (2026-09-06)

输入: data/ss_mw_raw/s*.npz (collect_mw_teacher_data.py 产物, obs43/u_ff_vec/stage/force 全量)
输出: data/ss_mw_ss/s*.npz — {states: obs[:,:39], actions: u_ff_vec(教师建议), stages, success}
      对齐 build_ss_dataset.py 输入格式 (39D/4D) → data/ss_mw_lerobot 标准 LeRobot 数据集。

说明: action = 教师 u_ff 建议 (解析律输出, 蒸馏目标, 与引擎 export_dataset 同语义);
      obs43 后 4D 触觉仅供右脑/接触标签, 左脑输入取前 39D 视觉。
"""
import glob
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "ss_mw_raw")
OUT = os.path.join(ROOT, "data", "ss_mw_ss")
os.makedirs(OUT, exist_ok=True)


def main():
    npzs = sorted(glob.glob(os.path.join(RAW, "*.npz")))
    if not npzs:
        print(f"❌ 无 raw 数据: {RAW} (先跑 tools/collect_mw_teacher_data.py)")
        return 1
    n_ep = n_ok = total = 0
    for npz in npzs:
        d = np.load(npz, allow_pickle=True)
        meta = d["meta"][0]
        obs = np.asarray(d["obs"], dtype=np.float32)
        u = np.asarray(d["u_ff_vec"], dtype=np.float32)
        if obs.ndim != 2 or obs.shape[1] < 39 or u.shape[1] != 4 or len(obs) != len(u):
            print(f"  ⚠️ {os.path.basename(npz)}: 维度异常 obs{obs.shape} u{u.shape}, 跳过")
            continue
        ok = bool(meta.get("success"))
        out_npz = os.path.join(OUT, os.path.basename(npz))
        np.savez_compressed(out_npz,
                            states=obs[:, :39].astype(np.float32),
                            actions=u.astype(np.float32),
                            stages=np.asarray(d["stage"], dtype=object),
                            success=np.array([ok]),
                            task_name=np.array("peg-insert-side-v3"))
        n_ep += 1
        n_ok += ok
        total += len(obs)
        print(f"  {'✅' if ok else '⚠️'} s{meta.get('seed')}: {len(obs)}帧 · "
              f"止于{meta.get('stage_final')} · analytic={meta.get('analytic')}")
    print(f"\n=== 转换完成: {n_ep} episode ({n_ok} 成功) {total} 帧 → {OUT} ===")
    print(f"下一步: python3 tools/build_ss_dataset.py {OUT} "
          f"{os.path.join(ROOT, 'data', 'ss_mw_lerobot')}")


if __name__ == "__main__":
    main()
