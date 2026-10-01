#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sam3_finetune.py — SAM3 框提示式微调 **调用方** (CLI)

算法内核在 src/lerobot/policies/sam3_seg/finetune.py (与 segmenter.py 同层), 本文件只做:
参数解析 / 子命令编排 / 取证打印。**不**重写训练逻辑。

三个子命令 (按顺序跑):
  1. masks  冻结基座 + 框提示 → 教师伪标签掩膜 (落 PNG)。**必须先跑**, train 会检查缺不缺。
  2. train  真训练: LoRA(视觉塔后 N block + 文本塔) + 4 个头全量可训; 双闸 + 逐步日志 + 产物。
  3. verify 对产物做免基准判据 (lora_B 非零 = 训练过) —— 不加载 GPU。

用法:
  ./gui-venv311/bin/python tools/sam3_finetune.py masks
  ./gui-venv311/bin/python tools/sam3_finetune.py train --epochs 12 --out outputs/sam3_finetune/annot_v1
  ./gui-venv311/bin/python tools/sam3_finetune.py verify --adapter outputs/sam3_finetune/annot_v1/lora_adapter

VENV 硬规: 训练一律 ./gui-venv311/bin/python。
显存红线: 本机同刻只允许一个模型进程 (训练前 nvidia-smi 确认无别的 >1500MiB 进程)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from lerobot.policies.sam3_seg import finetune as FT          # noqa: E402


def _banner(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78, flush=True)


def cmd_masks(a):
    _banner("① 教师伪标签生成 (冻结基座 + 框提示 → 掩膜)")
    names = FT.read_class_names(a.dataset)
    tr = FT.scan_split(a.dataset, "train")
    va = FT.scan_split(a.dataset, "val")
    print(f"[data] 类名 {names} · train {len(tr)} 帧 · val {len(va)} 帧", flush=True)
    model, proc, minfo = FT.build_trainable_model(a.model_dir, size=a.size, vit_lora_blocks=0, log=print)
    model.eval()
    rep = FT.gen_teacher_masks(model, proc, tr + va, a.cache_dir, names, size=a.size, log=print)
    Path(a.cache_dir).mkdir(parents=True, exist_ok=True)
    (Path(a.cache_dir) / "teacher_report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    ious = sorted(r["iou_box"] for r in rep["rows"])
    print(f"[teacher] IoU(伪标签, GT框) 中位 {ious[len(ious)//2]:.3f} · 最大 {ious[-1]:.3f} · "
          f"最小 {ious[0]:.3f}  (src=sam3_teacher {rep['n_teacher']} / box_fallback {rep['n_fallback']})", flush=True)
    return 0


def cmd_train(a):
    _banner("② SAM3 框提示式微调 (真训练)")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res = FT.run_train(a, log=print)
    res["wall_s"] = time.time() - t0
    (out / "run_report.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))

    _banner("训练证据汇总")
    d, m = res["data"], res["model"]
    print(f"数据量     : train {d['n_train']} 帧 / {d['n_train_boxes']} 框 · val {d['n_val']} 帧 / {d['n_val_boxes']} 框"
          f" · 类 {d['classes']}")
    print(f"步数       : {res['steps']} 步 · 总耗时 {res['total_s']:.1f}s · **实测步速 {res['s_per_step']:.3f} s/step**")
    print(f"参数量     : 可训 {m['n_head_params']+m['n_lora_params']:,} "
          f"(头 {m['n_head_params']/1e6:.2f}M + 适配器 {m['n_lora_params']/1e6:.3f}M) / LoRA Linear {m['n_lora_linear']} 个")
    print(f"显存       : 峰值 {res['peak_gb']:.2f} GB (4060 8GB)")
    if res["hist"]:
        h = res["hist"]
        print(f"loss 曲线  : 首 {h[0]['loss']:.4f} → 末 {h[-1]['loss']:.4f} (step {h[0]['step']}→{h[-1]['step']})")
        for k in ("mask_bce", "mask_dice", "box_l1", "box_giou", "cls", "presence"):
            if k in h[0] and k in h[-1]:
                print(f"   {k:<11}: {h[0][k]:.4f} → {h[-1][k]:.4f}")
    g = res["gates"].get("final", {})
    print(f"闸一(免基准): lora_B 非零 {g.get('lora_B_nonzero')}/{g.get('lora_B_total')} · 最大|B| {g.get('lora_B_max',0):.3e}"
          f" ⇒ {'✅ 训过' if g.get('lora_B_nonzero') == g.get('lora_B_total') else '❌'}")
    print(f"闸二(折叠)  : ‖ΔW‖/‖W‖ 中位 {g.get('delta_ratio_median',0):.3e} vs bf16 eps {g.get('bf16_eps',0):.1e}"
          f" ⇒ {'⛔ 禁止折进 bf16' if g.get('delta_ratio_median',0) < g.get('bf16_eps',1) else '可折'}")
    dz = res["gates"].get("step2", {}).get("dead_zone", {})
    print(f"死区登记    : {json.dumps(dz, ensure_ascii=False) if dz else '无'}")
    if res.get("val_step0"):
        s0, s1 = res["val_step0"], res["val"]
        print(f"A/B(同口径) : 抖动框掩膜IoU(对**教师伪标签**) {s0['mask_iou_vs_teacher']:.4f} → {s1['mask_iou_vs_teacher']:.4f}"
              f" (Δ{res.get('val_delta_mask_iou'):+.4f})")
        print(f"              框IoU(对真标注GT框)     {s0['box_iou_vs_gt']:.4f} → {s1['box_iou_vs_gt']:.4f}"
              f" (Δ{res.get('val_delta_box_iou'):+.4f})   val {s1['n_queries']} 个 query")
        print(f"              精确框下掩膜IoU         {res['val_clean']['mask_iou_vs_teacher']:.4f}")
    print(f"产物       : {res['adapter_path']}  ({res['adapter_bytes']/1e6:.2f} MB, 仅适配器不落 3.4GB 基座)")
    print(f"报告       : {out}/run_report.json · {out}/train_log.jsonl · {out}/gates.json")
    return 0


def cmd_eval(a):
    _banner("④ 适配器加载自证 + 抖动鲁棒性扫描 (base vs base+adapter, 同 seed 同帧)")
    names = FT.read_class_names(a.dataset)
    va = FT.scan_split(a.dataset, "val")
    model, proc, minfo = FT.build_trainable_model(a.model_dir, size=a.size,
                                                  vit_lora_blocks=a.lora_vit_blocks, log=print)
    cache = FT.preencode(proc, va, a.size, names, log=print)
    jitters = [float(x) for x in a.jitters.split(",")]
    lora_sd = {k: v for k, v in model.named_parameters() if k.endswith((".lora_A", ".lora_B"))}
    print(f"[check] 注入后 lora_B 全为 0? 最大|lora_B| = "
          f"{max(float(v.detach().abs().max()) for k, v in lora_sd.items() if k.endswith('.lora_B')):.3e}"
          " ⇒ 此刻模型 == 冻结基座 (零初始化自证)", flush=True)
    tbl = {}
    for tag in ("base", "base+adapter"):
        if tag == "base+adapter":
            FT.apply_adapter(model, a.adapter, log=print)
        for j in jitters:
            r = FT.evaluate(model, va, names, cache, a, jitter=j, seed=a.seed, tag=f"{tag}@jitter{j}", log=print)
            tbl[(tag, j)] = r
    print("\n抖动   base掩膜IoU   +适配器掩膜IoU   Δ        |  base框IoU  +适配器框IoU   Δ")
    for j in jitters:
        b, t = tbl[("base", j)], tbl[("base+adapter", j)]
        print(f"{j:<6.2f} {b['mask_iou_vs_teacher']:<13.4f} {t['mask_iou_vs_teacher']:<16.4f} "
              f"{t['mask_iou_vs_teacher']-b['mask_iou_vs_teacher']:<+8.4f} | "
              f"{b['box_iou_vs_gt']:<11.4f} {t['box_iou_vs_gt']:<15.4f} {t['box_iou_vs_gt']-b['box_iou_vs_gt']:<+.4f}")
    print("\n⚠️ 口径提醒: 掩膜 IoU 的对照方是**教师伪标签(= 冻结基座自己的输出)** ⇒ "
          "基座在'与教师一致'这个指标上**本来就是上界**; 蒸馏只能逼近它, 不可能超过它。")
    print("   要看真收益得看**抖动加大时谁的衰减更慢** (鲁棒性), 或换人工掩膜标注做真值。")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_adapter.json").write_text(json.dumps(
        {f"{k[0]}@jitter{k[1]}": v for k, v in tbl.items()}, indent=1, ensure_ascii=False))
    print(f"\n报告: {out}/eval_adapter.json")
    return 0


def cmd_verify(a):
    _banner("③ 产物免基准判据 (lora_B 零初始化 ⇒ 非零即训练过)")
    from safetensors.torch import load_file
    f = Path(a.adapter) / "adapter_model.safetensors"
    sd = load_file(str(f))
    fam = {}
    for k, v in sd.items():
        if not k.endswith(".lora_B"):
            continue
        f_ = "vision(视觉塔)" if "vision_encoder" in k else ("text(文本塔)" if "text_encoder" in k else "other")
        d = fam.setdefault(f_, [0, 0, 0.0])
        m = float(v.float().abs().max())
        d[0] += 1
        d[1] += int(m > 0)
        d[2] = max(d[2], m)
    tot = nz = 0
    for k, (t, n, mx) in sorted(fam.items()):
        tot += t; nz += n
        print(f"   {k:<14} lora_B {t:>3} 条 · 非零 {n:>3} 条 · 最大|B| {mx:.6e} ⇒ {'✅ 训练过' if n else '❌ 从未更新'}")
    nA = sum(1 for k in sd if k.endswith(".lora_A"))
    nB = sum(1 for k in sd if k.endswith(".lora_B"))
    nbad = sum(1 for k in sd if ".base." in k)
    print(f"   键统计: lora_A {nA} · lora_B {nB} · 含 '.base.' 的键 {nbad} (必须为 0 —— 适配器文件不该带基座权重)")
    print(f"   ── 合计 {tot} 条 lora_B / {nz} 条非零 ⇒ {'✅ 全部模块族都训练过' if nz == tot else '⚠️ 有模块族未训练'}")
    print(f"   大小 {f.stat().st_size/1e6:.2f} MB · 文件时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(f.stat().st_mtime))}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="SAM3 框提示式微调 (LoRA + 部分参数)")
    ap.add_argument("cmd", choices=["masks", "train", "verify", "eval"])
    ap.add_argument("--jitters", default="0,0.08,0.16,0.24", help="eval 用: 提示框抖动扫描点")
    ap.add_argument("--model-dir", default=FT.SAM3_DIR)
    ap.add_argument("--dataset", default=FT.DATASET_DIR)
    ap.add_argument("--cache-dir", default=str(_REPO / "data" / "sam3_finetune_cache"),
                    help="教师伪标签落盘处 (默认 data/sam3_finetune_cache)")
    ap.add_argument("--out", default=str(_REPO / "outputs" / "sam3_finetune" / "annot_v1"))
    ap.add_argument("--adapter", default=None, help="verify 用: 适配器目录")
    ap.add_argument("--size", type=int, default=FT.SIZE)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--max-steps", type=int, default=0, help=">0 时冒烟跑 (不许把冒烟说成训好)")
    ap.add_argument("--lr-lora", type=float, default=2e-4)
    ap.add_argument("--lr-head", type=float, default=1e-4)
    ap.add_argument("--r", type=int, default=FT.R)
    ap.add_argument("--alpha", type=int, default=FT.ALPHA)
    ap.add_argument("--lora-vit-blocks", type=int, default=FT.VIT_LORA_BLOCKS,
                    help="LoRA 注入视觉塔**最后 N 个** block (8=4.91GB, 16=6.51GB, 32=OOM)")
    ap.add_argument("--gate-steps", type=int, default=2, help="梯度闸取证步数 (第1步判B, 第2步判A)")
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--w-mask", type=float, default=2.0)
    ap.add_argument("--w-box", type=float, default=1.0)
    ap.add_argument("--w-cls", type=float, default=0.5)
    ap.add_argument("--w-pres", type=float, default=1.0)
    ap.add_argument("--aug", choices=["none", "light"], default="light")
    ap.add_argument("--box-jitter", type=float, default=0.08,
                    help="提示框抖动幅度(框宽高的比例) —— 训练信号的非退化来源; 0=关(会退化成'复现自己')")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "verify":
        a.adapter = a.adapter or str(Path(a.out) / "lora_adapter")
        return cmd_verify(a)
    if a.cmd == "eval":
        a.adapter = a.adapter or str(Path(a.out) / "lora_adapter")
        return cmd_eval(a)
    if a.cmd == "masks":
        return cmd_masks(a)
    return cmd_train(a)


if __name__ == "__main__":
    sys.exit(main())
