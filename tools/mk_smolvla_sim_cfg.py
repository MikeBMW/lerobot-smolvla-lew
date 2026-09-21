#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mk_smolvla_sim_cfg.py — 按 v10 真配置(resume_cfg.json)生成本次 L3(smolvla_lew) 训练配置

口径与 GUI「训练」节点一致: dataset=图像+state 数据集 · policy=smolvla_lew ·
  input_features {image[3,480,480], state[39]} → action[4] · 从 v10 ckpt 继续。
本次为**有界验证跑**(steps 可控, save_freq 高): 先证明训练链真能跑起来出 loss, 再谈长跑。
用法: gui-venv311/bin/python tools/mk_smolvla_sim_cfg.py --steps 300 --out config_smolvla_lew_sim.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

REPO = "/home/ubuntu/lerobot-smolvla-lew"
SRC = os.path.join(REPO, "outputs", "train", "smolvla_lew_v10", "resume_cfg.json")
DS = "data/smolvla_peg_v8_d1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--out", default="config_smolvla_lew_sim.yaml")
    ap.add_argument("--outdir", default="outputs/train/smolvla_lew_sim")
    a = ap.parse_args()
    cfg = json.load(open(SRC, encoding="utf-8"))

    cfg["dataset"]["repo_id"] = DS
    cfg["dataset"]["root"] = DS
    cfg["num_workers"] = 4                     # 4060 本机, 别抢满 CPU
    cfg["batch_size"] = a.batch
    cfg["steps"] = a.steps
    cfg["save_freq"] = max(a.steps, 500)       # 有界跑: 只存最后
    cfg["log_freq"] = 10
    cfg["output_dir"] = a.outdir
    cfg["job_name"] = os.path.basename(a.outdir)
    cfg["policy"]["device"] = "cuda"
    cfg["policy"]["pretrained_path"] = os.path.join(REPO, "outputs/train/smolvla_lew_v10/checkpoints/last/pretrained_model")
    if not os.path.isdir(cfg["policy"]["pretrained_path"]):
        print("⚠️ 续训权重不在: %s → 去掉 pretrained_path(从基座起)" % cfg["policy"]["pretrained_path"])
        cfg["policy"].pop("pretrained_path", None)
    # wandb: 沿用原配置字段集(只把 enable 关掉) —— 别自造字段名, draccus 会报 "fields not valid"
    if isinstance(cfg.get("wandb"), dict):
        cfg["wandb"]["enable"] = False
    else:
        cfg["wandb"] = {"enable": False}
    p = os.path.join(REPO, a.out)
    yaml.safe_dump(cfg, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
    print("✅ 配置写出: %s  (steps=%d batch=%d dataset=%s device=%s)"
          % (p, a.steps, a.batch, DS, cfg["policy"]["device"]))
    print("   续训自: %s" % cfg["policy"].get("pretrained_path", "(基座)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
