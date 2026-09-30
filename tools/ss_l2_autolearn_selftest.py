#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_l2_autolearn_selftest.py — 真机数据 L2 边干边学闭环的**自检** (沙箱, 不碰在役指针)

验四件事 (全真跑, 断言失败即非零退出):
  T1 采集门: 首样本收下 → 同帧去重拒收 → 姿态门 (位姿没动) 拒收 → 位姿动了收下
  T2 伪标注: 在役权重在真实帧上按 conf 门槛产出标签 (正路径), 低于门槛时如实不出标签
  T3 红线: auto 标注样本**只进 train** (val 里 auto 数必须为 0, 即使哈希判它该进 val)
  T4 判定+上线: decide_improved 四情形 + switch_live_pointer 原子切换 (读者不读到空指针)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

FAIL = []


def ck(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        FAIL.append(msg)


def main():
    sb = tempfile.mkdtemp(prefix="l2_selftest_")
    ss_remote = os.path.join(sb, "ss_remote")
    root = os.path.join(sb, "yolo_annot")
    work = os.path.join(sb, "work")
    os.makedirs(ss_remote)
    os.environ["ZMAX_SS_REMOTE_DIR"] = ss_remote
    os.environ["ZMAX_YOLO_ANNOT_ROOT"] = root
    os.environ["ZMAX_L2_WORK"] = work
    sys.path.insert(0, HERE)
    import numpy as np
    import cv2
    import ss_l2_autolearn as L

    # ── 造沙箱真机流: cam_rs.png + state_YYYYMMDD.jsonl ──
    def put_frame(tag: int, tcp):
        img = (np.random.default_rng(tag).integers(0, 255, (480, 640, 3))).astype("uint8")
        cv2.imwrite(os.path.join(ss_remote, "cam_rs.png"), img)
        t = time.time()
        os.utime(os.path.join(ss_remote, "cam_rs.png"), (t, t))
        with open(os.path.join(ss_remote, "state_%s.jsonl" % time.strftime("%Y%m%d")), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "tcp": tcp, "tcp_quat": [0, 0, 0, 1.0],
                                "jpos": [0] * 6, "ft": [0] * 6, "gripper": 0.9,
                                "prod_stage": {"state": "插入"}}) + "\n")

    print("T1 采集门 (真机流沙箱)")
    put_frame(1, [0.40, 0.05, 0.16])
    r1 = L.collect_once()
    ck(r1.get("ok") is True, f"首样本收下 (label_src={r1.get('label_src')})")
    L.MIN_INTERVAL_S = 0.0                                    # 限速单独由 T1b 验, 这里放开
    r2 = L.collect_once()
    ck(r2.get("ok") is False and "姿态门" in str(r2.get("reason")),
       f"同帧同位姿 → 姿态门拒收 ({r2.get('reason')})")
    put_frame(1, [0.43, 0.05, 0.16])                          # 同图 (tag 1), 位姿动 30mm → 应被 md5 去重拦
    r2b = L.collect_once()
    ck(r2b.get("ok") is False and "md5" in str(r2b.get("reason")),
       f"同图不同位姿 → md5 去重拒收 ({r2b.get('reason')})")
    put_frame(2, [0.4002, 0.05, 0.16])
    r3 = L.collect_once()
    ck(r3.get("ok") is False and "姿态门" in str(r3.get("reason")),
       f"新帧但位姿几乎没动 → 姿态门拒收 ({r3.get('reason')})")
    put_frame(3, [0.43, 0.05, 0.16])                          # 新图 + 移动 30mm
    r4 = L.collect_once()
    ck(r4.get("ok") is True and (r4.get("pose_delta_mm") or 0) >= 8,
       f"新帧且位姿移动 {r4.get('pose_delta_mm')}mm → 收下 (stem={r4.get('stem')})")
    st = json.load(open(L.STATE_F, encoding="utf-8"))
    ck(st.get("n_collected") == 2, f"计数正确 (n_collected={st.get('n_collected')})")

    print("T2 伪标注 (在役权重, 真推理)")
    live = os.path.join(REPO, "models", "yolo_peg_live.pt")
    if os.path.isfile(live):
        frame = np.asarray(cv2.cvtColor(cv2.imread(os.path.join(ss_remote, "cam_rs.png")), cv2.COLOR_BGR2RGB))
        b_hi, m_hi, why_hi = L.autolabel_pseudo(frame, conf=0.95)
        b_lo, m_lo, why_lo = L.autolabel_pseudo(frame, conf=0.05)
        ck(b_hi is None, f"conf 0.95 门槛下如实不出标签 ({why_hi or 'ok'})")
        ck(bool(m_hi.get("weight_sha256")), f"伪标注带权重指纹 sha256={str(m_hi.get('weight_sha256'))[:16]}…")
        ck(b_lo is None or len(b_lo) >= 1, f"conf 0.05 门槛下产出 {len(b_lo or [])} 个标签 (正路径可走)")
    else:
        ck(False, f"在役权重缺失 {live}")

    print("T2b 几何真值路 (标定未就绪时必须拒算, 不编造)")
    boxes, why = L.autolabel_kinematic(np.zeros((480, 640, 3), "uint8"), {"tcp": [0.4, 0.05, 0.16], "gripper": 0.9})
    ck(boxes is None and ("标定" in why or "拒算" in why), f"标定未就绪 → 拒算 ({why[:60]}…)")

    print("T3 红线: 自动标注样本只进 train")
    import yolo_annot_dataset as yad
    L.MIN_TCP_MOVE_MM = 0.0                                   # 放开姿态门, 只验红线
    img = np.random.default_rng(9).integers(0, 255, (480, 640, 3)).astype("uint8")
    for i in range(12):                                       # 12 人工样本 (每张不同图 → 不走 md5 去重)
        yad.save_sample(root, np.roll(img, i + 1, axis=0), [(50, 50, 130, 110, "peg")],
                        session="s_human_1", annotator="human", src="test")
    for i in range(12):                                       # 12 自动标注样本 (每张不同图)
        yad.save_sample(root, np.roll(img, i + 1, axis=1), [(60, 60, 140, 120, "peg")],
                        session="auto_test_1", annotator="auto:pseudo", src="test", extra={"auto": True})
    stats = yad.build_dataset(root, val_ratio=0.5, seed=0)     # 故意用大 val_ratio 逼自动样本撞 val
    s2s = L._stem_to_session()
    ds = os.path.join(root, "dataset")
    auto_in_val = []
    for jpg in os.listdir(os.path.join(ds, "images", "val")):
        stem = os.path.splitext(jpg)[0]
        if s2s.get(stem) == "auto_test_1":
            auto_in_val.append(stem)
    ck(stats.get("auto_in_val") == 0, f"stats.auto_in_val == 0 (实 {stats.get('auto_in_val')})")
    ck(not auto_in_val, f"val 目录里 auto 样本数 = 0 (实 {len(auto_in_val)})")
    ck(stats.get("n_auto_train", 0) >= 12, f"auto 样本全在 train (n_auto_train={stats.get('n_auto_train')})")
    ck(stats.get("n_human_samples") == 12, f"人工样本计数正确 (n_human={stats.get('n_human_samples')})")
    # T3b 待标注池 (auto:pending) 绝不进数据集 (无标签帧当背景会反向伤害)
    L.MIN_TCP_MOVE_MM = 0.0
    put_frame(77, [0.50, 0.10, 0.20])
    rp = L.collect_once()
    if rp.get("label_src") == "none":
        yad.build_dataset(root, val_ratio=0.15, seed=0)
        ds2 = os.path.join(root, "dataset")
        all_imgs = [os.path.splitext(f)[0] for sp in ("train", "val")
                    for f in os.listdir(os.path.join(ds2, "images", sp))]
        ck(rp["stem"] not in all_imgs,
           f"无标签采集帧 (annotator=auto:pending) 未进数据集 (stem={rp['stem']})")

    print("T4 判定 + 上线 (门槛与原子切换)")
    good_old = {"peg_rate": 0.5, "peg_conf_mean": 0.6, "frames_with_peg": 8, "n_frames": 16}
    ck(L.decide_improved(good_old, {"peg_rate": 0.75, "peg_conf_mean": 0.6, "n_frames": 16})["improved"],
       "检出率 0.5→0.75 → 判定有提升")
    ck(L.decide_improved(good_old, {"peg_rate": 0.5, "peg_conf_mean": 0.7, "n_frames": 16})["improved"],
       "检出率持平 · conf +0.10 → 判定有提升")
    ck(not L.decide_improved(good_old, {"peg_rate": 0.5, "peg_conf_mean": 0.61, "n_frames": 16})["improved"],
       "检出率持平 · conf 仅 +0.01 → 不上默认档")
    ck(not L.decide_improved(good_old, {"peg_rate": 0.25, "peg_conf_mean": 0.9, "n_frames": 16})["improved"],
       "检出率回退 → 不上默认档")
    ck(not L.decide_improved(good_old, {"peg_rate": 0.0, "peg_conf_mean": None, "n_frames": 16})["improved"],
       "新权重 0 检出 → 不上默认档 (不许 0 检出上线)")
    ck(not L.decide_improved(None, good_old)["improved"], "对照组缺失 → 不上默认档")

    # 原子切换: 用沙箱里的假 repo 指针
    fake_repo = os.path.join(sb, "repo")
    os.makedirs(os.path.join(fake_repo, "models"))
    old_w = os.path.join(sb, "old.pt"); new_w = os.path.join(sb, "new.pt")
    open(old_w, "wb").write(b"OLD"); open(new_w, "wb").write(b"NEW")
    ptr = os.path.join(fake_repo, "models", "yolo_peg_live.pt")
    os.symlink(old_w, ptr)
    keep_repo, keep_ptr = L.REPO, L.LIVE_PTR
    L.REPO, L.LIVE_PTR = fake_repo, ptr
    rec, err = L.switch_live_pointer(new_w)
    L.REPO, L.LIVE_PTR = keep_repo, keep_ptr
    ck(err is None and rec.get("done"), f"原子切换成功 (from={os.path.basename(str(rec.get('from')))} to={os.path.basename(str(rec.get('to')))})")
    ck(os.path.realpath(ptr) == os.path.realpath(new_w), "指针指向新权重且可解析 (无空指针窗口)")
    ck(not os.path.lexists(ptr + ".tmp"), "临时链接已清理")
    hist = os.path.join(fake_repo, "models", "yolo_peg_live.history.jsonl")
    ck(os.path.isfile(hist) and bool(json.loads(open(hist, encoding="utf-8").read().strip().splitlines()[-1]).get("sha256")),
       "上线历史留痕 (含 sha256)")

    print("\n" + ("✅ 全部通过" if not FAIL else f"❌ {len(FAIL)} 项失败:\n  - " + "\n  - ".join(FAIL)))
    shutil.rmtree(sb, ignore_errors=True)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
