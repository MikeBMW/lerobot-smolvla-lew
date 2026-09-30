#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_annot_train.py — 用**标定工程师标好的真机图片**训练/微调 YOLO 检测模型

老倪 2026-09-17: 「yolo 模型可以通过保存的图片进行模型训练」

流程 (先体检再训练, 拒绝脏数据):
  1. 读 data/yolo_annot/dataset/data.yaml → 校验 (图片/标注配对, 类别范围, 坐标范围) —— 有错直接退出 2
  2. 选基座权重: `--base auto` 优先找**现有仿真权重**做域适应微调 (仿真权重在真机 0 检出, 微调是正路);
     找不到就用 --model (默认 yolov8n.pt)
  3. ultralytics 训练 (device 自动: cuda 可用就用 GPU)
  4. 训练后**真推理验证**: 在 val 图上跑 N 张, 打印检出数/置信度 → 证明模型真能识别标定的目标

用法:
  gui-venv311/bin/python tools/yolo_annot_train.py --epochs 100 --imgsz 640 --name annot_v1
  gui-venv311/bin/python tools/yolo_annot_train.py --no-base          # 从 COCO 预训练重头训
  gui-venv311/bin/python tools/yolo_annot_train.py --base outputs/yolo_peg/xxx/weights/best.pt
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yolo_annot_dataset as yad                                          # noqa: E402

# 候选基座权重: 仿真 peg 检测权重 (域适应起点) —— 真机帧上当前 0 检出, 微调后应显著改善
_BASE_CANDS = [
    "outputs/yolo_peg_full/*/weights/best.pt",
    "outputs/yolo_peg/*/weights/best.pt",
    "outputs/yolo_annot*/**/weights/best.pt",
    "models/yolo*/*.pt", "models/yolo*.pt",
    "runs/detect/**/weights/best.pt",
]


def find_base(repo="."):
    # 🎯 2026-09-18: **真机在役权重优先** (models/yolo_peg_live.pt = 标定微调后的真机域权重),
    #   其次才是最新产物, 最后才是仿真域权重 —— 域适应从"已经在真机上有检出"的权重继续,
    #   而不是每次从仿真域重来 (实测仿真权重在真机帧 0 检出)。
    live = os.path.join(repo, "models", "yolo_peg_live.pt")
    if os.path.isfile(live):
        return live
    cands = []
    for pat in _BASE_CANDS:
        cands += glob.glob(os.path.join(repo, pat), recursive=True)
    cands = [c for c in cands if os.path.isfile(c)]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def live_eval_report(a, best: str) -> None:
    """🎯 训练后**真机实时帧**同口径对照 (老倪门槛: 有提升才认; 数字必须来自真推理)。

    对照组 = **在役权重** models/yolo_peg_live.pt (没有就退回 peg_v1 仿真权重);
    评测帧 = 训练**之后**新采的新鲜 cam_rs.png (真机帧, 与 L2 旁路同源)。
    """
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ev = os.path.join(repo, "tools", "yolo_live_eval.py")
    if not os.path.isfile(ev):
        print("⚠️ 缺 tools/yolo_live_eval.py → 跳过真机帧对照")
        return
    cur = os.path.join(repo, "models", "yolo_peg_live.pt")
    ws = [w for w in (cur, best) if os.path.isfile(w)]
    out = os.path.join(repo, "reports", f"yolo_live_eval_{a.name}.json")
    vis = os.path.join(repo, "reports", f"yolo_live_vis_{a.name}")
    cmd = [sys.executable, ev, "--weights", *ws, "--frames", str(a.live_frames),
           "--imgsz", str(a.imgsz), "--conf", "0.25", "--out", out, "--vis-dir", vis]
    print("=" * 78)
    print(f"[真机帧对照] {' vs '.join(os.path.basename(w) for w in ws)} "
          f"→ 采 {a.live_frames} 张新鲜真机帧 (训练后新采, 未见过)")
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:                                                     # noqa: BLE001
        print(f"⚠️ 真机帧对照失败: {type(e).__name__}: {e}")
        return
    try:
        d = json.load(open(out, encoding="utf-8"))
        rs = {os.path.basename(r["weights"]): r for r in d["results"]}
        new = rs.get(os.path.basename(best))
        old = rs.get(os.path.basename(cur)) if os.path.isfile(cur) else None
        if new:
            print(f"   新权重: peg 检出 {new['frames_with_peg']}/{new['n_frames']} 帧 · "
                  f"conf mean {new['peg_conf_mean']} max {new['peg_conf_max']}")
        if old:
            print(f"   在役  : peg 检出 {old['frames_with_peg']}/{old['n_frames']} 帧 · "
                  f"conf mean {old['peg_conf_mean']} max {old['peg_conf_max']}")
            verdict = ("✅ 有提升 (检出率↑ 或 conf↑)" if (new and (
                new["peg_rate"] > old["peg_rate"]
                or (new["peg_rate"] == old["peg_rate"] and (new["peg_conf_mean"] or 0) >
                    (old["peg_conf_mean"] or 0) + 0.02))) else "➖ 持平/回退 → 按纪律不上默认档")
            print(f"   判定: {verdict}")
        print(f"   可视化(画框): {vis}  数据: {out}")
        print(f"   上在役 (单点切换): ln -sfn {os.path.abspath(best)} {cur}")
    except Exception as e:                                                     # noqa: BLE001
        print(f"⚠️ 解析对照结果失败: {type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(yad.ROOT_DEFAULT, "dataset"))
    ap.add_argument("--root", default=yad.ROOT_DEFAULT, help="标定数据根 (体检用)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--base", default="auto", help="auto=自动找现有权重微调 / none / 具体 .pt 路径")
    ap.add_argument("--device", default="", help="留空=自动 (有 CUDA 用 0, 否则 cpu)")
    ap.add_argument("--name", default="annot_" + time.strftime("%m%d_%H%M"))
    ap.add_argument("--project", default="outputs/yolo_annot")
    ap.add_argument("--verify", type=int, default=8, help="训练后在 N 张 val 图上真推理验证")
    ap.add_argument("--force", action="store_true", help="体检有错也继续 (不推荐)")
    # ── 🚀 2026-09-18 全面升级 (老倪: 「你是专业的 YOLO 感知模型工程师, 全面升级训练程序」) ──
    ap.add_argument("--patience", type=int, default=60, help="早停耐心 (val 不升即停)")
    ap.add_argument("--cos-lr", action="store_true", default=True, help="余弦学习率 (默认开)")
    ap.add_argument("--no-cos-lr", dest="cos_lr", action="store_false")
    ap.add_argument("--cache", action="store_true", default=True, help="缓存图像 (小数据集提速)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--live-eval", type=int, default=30,
                    help="训练后在**新鲜真机帧**上评测 (0=跳过). 交付门槛: 与在役权重同口径对照")
    ap.add_argument("--live-frames", type=int, default=40, help="采多少张新鲜真机帧做评测")
    ap.add_argument("--detached", action="store_true",
                    help="用 systemd-run 起独立单元跑 (不挂在控制台 cgroup 下 → 关/重启控制台不会杀掉训练)")
    a = ap.parse_args()

    # ── 0. --detached: 自我重入到独立 systemd 单元 (必须先做, 否则后续全是主进程) ──
    if a.detached and not os.environ.get("YOLO_ANNOT_DETACHED"):
        log = os.path.join(yad.ROOT_DEFAULT, "train.log")
        args = [x for x in sys.argv[1:] if x != "--detached"]
        unit = "yolo-annot-" + time.strftime("%m%d-%H%M%S")
        cmd = ("env YOLO_ANNOT_DETACHED=1 " + shlex.quote(sys.executable) + " "
               + shlex.quote(os.path.abspath(__file__)) + " " + " ".join(shlex.quote(x) for x in args)
               + f" > {shlex.quote(log)} 2>&1")
        rc = os.system(f"systemd-run --user --collect --unit {shlex.quote(unit)} "
                       f"--working-directory {shlex.quote(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))} "
                       f"bash -lc {shlex.quote(cmd)}")
        print(f"🚀 已用独立单元 {unit}.service 启动训练 (rc={rc>>8}) · 日志 {log}\n"
              f"   查看: systemctl --user status {unit} · journalctl --user -u {unit} -f\n"
              f"   好处: 关掉/重启控制台不会杀掉训练 (systemd 默认会连带杀同 cgroup 的子进程)")
        return 0 if rc == 0 else 3

    # ── 1. 体检 ──
    print("=" * 78)
    r = yad.check_dataset(a.root, strict=True)
    print(f"[体检] 图片 {r['n_images']} · 标注 {r['n_labels']} · 框 {r['n_boxes']} · "
          f"背景样本 {r['n_empty_label']} · 类别分布 {r['per_class']}")
    for e in r["errors"][:10]:
        print("   ❌", e)
    for w in r["warnings"][:5]:
        print("   ⚠️", w)
    if r["errors"] and not a.force:
        print("❌ 体检不通过 → 先修数据 (或 --force 强行继续)")
        return 2
    yml = os.path.join(a.data, "data.yaml")
    if not os.path.isfile(yml):
        print(f"❌ 缺 {yml} → 先跑: python3 tools/yolo_annot_dataset.py --build --check")
        return 2
    ytxt = open(yml, encoding="utf-8").read()
    names = yad.load_classes(a.root)
    print(f"[数据集] {yml}")
    for ln in ytxt.strip().splitlines():
        print("   " + ln)
    if r["n_images"] < 10:
        print(f"⚠️ 只有 {r['n_images']} 张 → 能跑通管线, 但精度别指望 (建议首轮 ≥100 张覆盖多位置/光照)")

    # ── 2. 基座权重 ──
    import torch
    from ultralytics import YOLO
    dev = a.device or ("0" if torch.cuda.is_available() else "cpu")
    if a.base == "auto":
        b = find_base(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        base = b or a.model
        print(f"[基座] auto → {base}" + ("  (现有权重 → 域适应微调)" if b else "  (没找到现有权重 → COCO 预训练)"))
    elif a.base.lower() in ("none", "no", "false"):
        base = a.model
        print(f"[基座] {base} (重头训)")
    else:
        base = a.base
        print(f"[基座] 指定 {base}")
    print(f"[设备] {dev} · torch {torch.__version__} · cuda={torch.cuda.is_available()}")
    print(f"[参数] epochs={a.epochs} imgsz={a.imgsz} batch={a.batch} 类别={names} nc={len(names)}")
    print("=" * 78, flush=True)

    # ── 3. 训练 ──
    t0 = time.time()
    model = YOLO(base)
    model.train(data=yml, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=dev,
                project=a.project, name=a.name, workers=a.workers, verbose=True,
                exist_ok=True, plots=True,
                patience=a.patience, cos_lr=a.cos_lr, cache=a.cache, seed=a.seed)
    dt = time.time() - t0

    # ── 4. 找 best.pt + 真推理验证 ──
    best = None
    for pat in (os.path.join(a.project, a.name, "weights", "best.pt"),
                os.path.join("runs", "detect", a.project, a.name, "weights", "best.pt"),
                os.path.join("runs", "detect", "outputs", a.project, a.name, "weights", "best.pt")):
        if os.path.isfile(pat):
            best = pat
            break
    if best is None:
        c = glob.glob(os.path.join("runs", "**", a.name, "weights", "best.pt"), recursive=True)
        best = c[0] if c else None
    print("=" * 78)
    print(f"⏱ 训练完成: {dt/60:.1f} 分钟 ({a.epochs} 轮) · 权重 {best}")
    if best:
        m = YOLO(best)
        imgs = sorted(glob.glob(os.path.join(a.data, "images", "val", "*")))
        imgs = imgs[:max(1, a.verify)]
        ndet, confs, lines = 0, [], []
        for p in imgs:
            res = m.predict(p, conf=0.25, verbose=False)[0]
            n = len(res.boxes)
            c = [float(x) for x in (res.boxes.conf if res.boxes is not None else [])]
            ndet += n
            confs += c
            lines.append(f"   {os.path.basename(p)}: {n} 框" +
                         (f" · conf {min(c):.2f}~{max(c):.2f}" if c else " (无检出)"))
        print(f"[真推理验证] val 抽样 {len(imgs)} 张 → 共检出 {ndet} 框 · "
              f"平均 conf {sum(confs)/len(confs):.3f}" if confs else
              f"[真推理验证] val 抽样 {len(imgs)} 张 → 0 框 (数据太少/未收敛?)")
        for l in lines:
            print(l)
        print("   权重路径(给 Orin 部署): " + best)
    # ── 5. 🎯 真机实时帧同口径对照 (交付门槛: 有提升才认; 数字来自真推理) ──
    if a.live_eval and best:
        live_eval_report(a, best)
    print("✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
