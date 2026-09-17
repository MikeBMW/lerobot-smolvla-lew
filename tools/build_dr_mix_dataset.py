# -*- coding: utf-8 -*-
"""组装混合训练集 (仿真原集 + DR 集), 硬链接不重复占盘。

训练集: 原仿真 1800 张 (data/yolo_peg) + DR 集去掉 3 个整 episode (ep000-002, 共 900 张)
验证集: DR 的 ep000-002 (900 张, 整场景留出) + 仿真 hold-out 600 张
口径: 三类 hand/peg/hole; 同一 data.yaml; 训练/评测集分离 (原集 train=val=images 的 mAP 虚高问题不继承)
"""
import glob, json, os, shutil

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
SIM = f"{ROOT}/data/yolo_peg"
DR = f"{ROOT}/data/yolo_peg_dr"
HOLD = f"{ROOT}/data/yolo_peg_holdout"
OUT = f"{ROOT}/data/yolo_peg_drmix"
VAL_EPS = ("ep000", "ep001", "ep002")

import argparse as _ap
_p = _ap.ArgumentParser(description="组装 sim+DR 混合训练集 (硬链接)")
_p.add_argument("--sim", default=SIM)
_p.add_argument("--dr", default=DR)
_p.add_argument("--holdout", default=HOLD)
_p.add_argument("--out", default=OUT)
_p.add_argument("--val-eps", nargs="*", default=list(VAL_EPS), help="整场景留作 val 的 episode 前缀")
_a = _p.parse_args()
SIM, DR, HOLD, OUT, VAL_EPS = _a.sim, _a.dr, _a.holdout, _a.out, tuple(_a.val_eps)


def link(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy(src, dst)


def stem(p):
    return os.path.splitext(os.path.basename(p))[0]


for sub in ("images/train", "images/val", "labels/train", "labels/val"):
    os.makedirs(f"{OUT}/{sub}", exist_ok=True)

cnt = {"sim_train": 0, "dr_train": 0, "dr_val": 0, "hold_val": 0}
for img in sorted(glob.glob(f"{SIM}/images/*.png")):
    lb = f"{SIM}/labels/{stem(img)}.txt"
    if os.path.exists(lb):
        link(img, f"{OUT}/images/train/{stem(img)}.png")
        link(lb, f"{OUT}/labels/train/{stem(img)}.txt")
        cnt["sim_train"] += 1

for img in sorted(glob.glob(f"{DR}/images/*.png")):
    lb = f"{DR}/labels/{stem(img)}.txt"
    if not os.path.exists(lb):
        continue
    is_val = stem(img).split("_")[0] in VAL_EPS
    split = "val" if is_val else "train"
    link(img, f"{OUT}/images/{split}/{stem(img)}.png")
    link(lb, f"{OUT}/labels/{split}/{stem(img)}.txt")
    cnt["dr_val" if is_val else "dr_train"] += 1

for img in sorted(glob.glob(f"{HOLD}/images/*.png")):
    lb = f"{HOLD}/labels/{stem(img)}.txt"
    if os.path.exists(lb):
        link(img, f"{OUT}/images/val/hold_{stem(img)}.png")
        link(lb, f"{OUT}/labels/val/hold_{stem(img)}.txt")
        cnt["hold_val"] += 1

with open(f"{OUT}/data.yaml", "w") as f:
    f.write(f"path: {OUT}\ntrain: images/train\nval: images/val\nnc: 3\nnames: ['hand', 'peg', 'hole']\n")

meta = {"train": cnt["sim_train"] + cnt["dr_train"], "val": cnt["dr_val"] + cnt["hold_val"], "detail": cnt,
        "note": "sim_train=原仿真集(1800) · dr_train=DR 集(留出 ep000-002 作 val) · hold_val=未训过的非 DR 仿真 hold-out"}
json.dump(meta, open(f"{OUT}/meta.json", "w"), ensure_ascii=False, indent=1)
print(f"混合集: train={meta['train']} (仿真 {cnt['sim_train']} + DR {cnt['dr_train']}) · "
      f"val={meta['val']} (DR留出 {cnt['dr_val']} + 仿真holdout {cnt['hold_val']}) → {OUT}")
