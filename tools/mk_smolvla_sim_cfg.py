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

REPO = "/home/ubuntu/zmax"
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
    # 🎯 2026-10-01 老倪「按你的建议来 · 所有模型都要有梯度 · 要结果」:
    #   LEW(世界模型)损失原来 pred=6 步 vs target=1 步 ⇒ 只能比 1 步(实测 lew_loss≈0.0006, 等于没训)。
    #   原因: 视频窗 T=2 而动作窗 T=7(chunk 6+1)。对齐口径 = 视频取 **chunk+1 = 7 帧**
    #   [t, t+1, ..., t+6], 与 predictor 的 6 步预测一一对应; 帧距按数据集 fps(实测 25) = 0.24s,
    #   与 6 步动作块时长一致。SSD_VIDEO_WINDOW=0 可退回原口径。
    try:
        import json as _json
        _fps = _json.load(open(os.path.join(DS, "meta", "info.json"), encoding="utf-8")).get("fps", 25)
    except Exception:
        _fps = 25
    _n = int(os.environ.get("SSD_VIDEO_WINDOW", "7"))
    # 🎯 真正生效的口径是**策略自己的**: DatasetConfig 不认 delta_timestamps(实测 DecodingError),
    #   而模型侧 num_video_frames 决定视频窗, n_obs_steps 决定观测帧数;
    #   ⚠️ 世界模型 pos_embedding 是按 num_frames 学的参数 ⇒ 改这里必须重训(不能热启)。
    if _n > 1:
        cfg["policy"]["num_video_frames"] = _n
        cfg["policy"]["n_obs_steps"] = _n
        print("   🎯 视频窗对齐: num_video_frames=n_obs_steps=%d (0~%.3fs @ %sfps, 需重训 pos_embedding)" % (_n, (_n - 1) / float(_fps), _fps))

    # ★ 2026-09-26 老倪: "gpu训练负载不能小于一半" —— 原 4 workers 导致 GPU 等数据掉到 0%
    #   32 核机器 → 提到 12 workers + prefetch 8（CPU 侧并行, 不增显存）
    import os as _o
    cfg["num_workers"] = int(_o.environ.get("ZMAX_NUM_WORKERS", "12"))
    cfg["batch_size"] = a.batch
    cfg["prefetch_factor"] = int(_o.environ.get("ZMAX_PREFETCH", "8"))
    cfg["steps"] = a.steps
    cfg["save_freq"] = max(a.steps, 500)       # 有界跑: 只存最后
    cfg["log_freq"] = 10
    cfg["output_dir"] = a.outdir
    cfg["job_name"] = os.path.basename(a.outdir)
    cfg["policy"]["device"] = "cuda"
    _base = os.path.join(REPO, "outputs/train/smolvla_lew_v10/checkpoints/last/pretrained_model")
    # 🎯 窗口 ≠2 时用**重建过 pos_embedding** 的那份副本(原始 ckpt 的 pos_embedding 是 2 帧, 直接加载会
    #    size mismatch —— 实测确认这就是"视频窗一直没对齐"的真因); 不变更原始 ckpt。
    _win7 = os.path.join(REPO, "outputs/train/smolvla_lew_v10_win7/pretrained_model")
    cfg["policy"]["pretrained_path"] = _win7 if (int(os.environ.get("SSD_VIDEO_WINDOW", "7")) > 1
                                                 and os.path.isdir(_win7)) else _base
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
