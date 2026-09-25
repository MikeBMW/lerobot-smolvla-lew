#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_runner.py — APP 训练控制节点的**真实训练**执行器
==================================================================
老倪令 (2026-09-25): 「训练控制节点 app 的训练要保证是真实模型训练」

背景 — 原 `training_backend.py` 的三个硬伤 (实测):
  ① 解释器写死 "/home/xspace/miniconda3/envs/lerobot/bin/python" → Mac 上必失败
  ② 进度正则 r'Training:\\s+(\\d+)%' 与脚本实际输出('Step N: loss=…'/'DONE: x%')不匹配
     → 进度条永远 0% = 假进度
  ③ 训练本体是 3 episode / batch=1 的合成循环, 不是真训练

本执行器:
  · 跑**真训练链** (每个 task 都有真实数据/权重/指标)
  · 输出格式严格产出 `Training: N%` (兼容 GUI 既有正则, 不用改前端)
  · 同时输出 `ZMAX_METRIC {json}` 结构化指标行 (供 APP 展示真实 loss/R²)
  · 结束时输出 `ZMAX_RESULT {json}` (ckpt 路径 / 真实指标 / 是否过闸)

任务:
  manifold  流形引擎 (训练总目标) — collect→train, 真实 LOSO R², 闸 ≥0.30  [已验证]
  yolo      L2 YOLO 检测 — 真机标注数据域适应微调                        [需数据]
  smolvla   L3 SmolVLA — lerobot 原生训练                              [需依赖]
  demo      快速冒烟 (小规模真跑, 用于验证链路)

用法 (由 training_backend.py 调用):
  python train_runner.py --task manifold --steps 220 --workdir <repo>
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _g1(m, default=None):
    """安全取正则第 1 组 (m 可能是 None)"""
    return m.group(1) if m else default


def emit(line: str):
    """所有输出都 flush (GUI 要实时看到)"""
    print(line, flush=True)


def progress(pct: float, msg: str = ""):
    """GUI 进度正则要求的确切格式: 'Training:  42%'"""
    emit(f"Training: {int(max(0, min(100, pct))):3d}%   {msg}")


def metric(**kw):
    emit("ZMAX_METRIC " + json.dumps(kw, ensure_ascii=False))


def result(**kw):
    emit("ZMAX_RESULT " + json.dumps(kw, ensure_ascii=False))


def _run(cmd, cwd, tag):
    """跑子进程并把输出透传 (带前缀), 返回 (rc, 采集到的关键行)"""
    emit(f"[{tag}] $ {' '.join(str(c) for c in cmd)}")
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1)
    except Exception as e:
        emit(f"[{tag}] ❌ 启动失败: {type(e).__name__}: {e}")
        return 127, []
    lines = []
    if p.stdout is not None:
        for ln in p.stdout:
            ln = ln.rstrip()
            if not ln:
                continue
            lines.append(ln)
            emit(f"[{tag}] {ln}")
    p.wait()
    return p.returncode, lines


# ─────────────────────────── 任务: 流形引擎 ───────────────────────────
def task_manifold(a) -> int:
    """真实流形引擎训练: collect(真物理仿真) → train(真反向传播) → LOSO R²"""
    data = os.path.join(a.workdir, "data", "manifold_geo_v1.npz")
    os.makedirs(os.path.dirname(data), exist_ok=True)

    progress(2, "采集流形几何数据 (真物理仿真)")
    rc, lines = _run([sys.executable, "tools/collect_mani_geo_data.py",
                      "--clean", str(a.clean), "--jitter", str(a.jitter),
                      "--out", data], a.workdir, "collect")
    if rc != 0:
        emit(f"❌ 采集失败 rc={rc}")
        result(ok=False, stage="collect", rc=rc)
        return rc
    frames = next((int(_g1(re.search(r"(\d+) 帧", l), "0") or 0)
                   for l in reversed(lines) if "落盘" in l and "帧" in l), None)
    metric(stage="collect", frames=frames, data=data)
    progress(30, f"采集完成 {frames} 帧")

    progress(35, "训练流形预测器 (真反向传播)")
    env = dict(os.environ)
    env["ZMAX_PROGRESS_EMIT"] = "1"        # 让训练脚本按 epoch 发 Training: N%
    try:
        p = subprocess.Popen([sys.executable, "tools/train_mani_geo_predictor.py"],
                             cwd=a.workdir, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    except Exception as e:
        emit(f"❌ 训练启动失败: {type(e).__name__}: {e}")
        result(ok=False, stage="train")
        return 1

    import glob
    before = set(glob.glob(os.path.join(a.workdir, "reports", "mani_geo_predictor_*.json")))
    for ln in p.stdout:
        ln = ln.rstrip()
        if not ln:
            continue
        emit(f"[train] {ln}")
        # 训练脚本的逐折行 → 映射进度
        m = re.match(r"^\[(s\d+)\]", ln)
        if m:
            progress(40 + min(50, 5 * len(before)), f"折 {m.group(1)} 评估完成")
        m2 = re.search(r"epoch\s*(\d+)\s*/\s*(\d+)", ln, re.I)
        if m2:
            e, tot = int(m2.group(1)), max(1, int(m2.group(2)))
            progress(35 + 55 * e / tot, f"epoch {e}/{tot}")
    p.wait()
    rc = p.returncode

    # 读真实指标
    after = set(glob.glob(os.path.join(a.workdir, "reports", "mani_geo_predictor_*.json")))
    new = sorted(after - before) or sorted(after)
    loso = gate = frames2 = None
    if new:
        try:
            d = json.load(open(new[-1], encoding="utf-8"))
            m = d.get("ckpt_meta", {})
            loso = m.get("loso_r2_mean")
            frames2 = m.get("frames")
            gate = (loso is not None and loso >= 0.30)
        except Exception as e:
            emit(f"⚠️ 报告解析失败: {e}")
    progress(100, "训练结束")
    result(ok=(rc == 0), stage="done", rc=rc, loso_r2=loso, gate_pass=gate,
           frames=frames2, report=(new[-1] if new else None),
           ckpt=os.path.join("checkpoints", "manifold_predictor", "mani_geo.pt"))
    if loso is not None:
        metric(final=True, loso_r2=loso, gate_pass=gate, gated_at=0.30)
    emit(f"{'✅' if gate else '⚠️'} 流形训练完成: LOSO R² = {loso} "
         f"({'过闸' if gate else '未过闸'})")
    return rc


# ─────────────────────────── 任务: L2 YOLO ───────────────────────────
def task_yolo(a) -> int:
    ds = os.path.join(a.workdir, "data", "yolo_annot", "dataset", "data.yaml")
    if not os.path.exists(ds):
        emit(f"❌ 缺真机标注数据集: {ds}")
        emit("   (data/ 被 gitignore, 需现场标注后构建: "
             "python3 tools/yolo_annot_dataset.py --build)")
        result(ok=False, stage="precheck", reason="missing_dataset", path=ds)
        return 2
    progress(5, "L2 YOLO 域适应微调")
    rc, lines = _run([sys.executable, "tools/yolo_annot_train.py",
                      "--data", os.path.dirname(ds), "--epochs", str(a.epochs),
                      "--imgsz", "480", "--batch", str(a.batch),
                      "--workers", "0", "--device", "cpu", "--name", a.run_name],
                     a.workdir, "yolo")
    w = next((l for l in reversed(lines) if "best.pt" in l), None)
    progress(100, "YOLO 训练结束")
    result(ok=(rc == 0), stage="done", rc=rc, weights=w)
    return rc


# ─────────────────────────── 任务: L3 SmolVLA ───────────────────────────
def task_smolvla(a) -> int:
    entry = os.path.join(a.workdir, "src", "lerobot", "scripts", "lerobot_train.py")
    if not os.path.exists(entry):
        emit(f"❌ 缺 lerobot 训练入口: {entry}")
        result(ok=False, stage="precheck", reason="missing_entry")
        return 2
    cfg = a.config or ""
    cmd = [sys.executable, entry]
    if cfg:
        cmd += ["--config_path", cfg]
    cmd += ["--steps", str(a.steps)]
    progress(5, "L3 SmolVLA 训练")
    rc, lines = _run(cmd, a.workdir, "smolvla")
    los = None
    for l in reversed(lines):
        _m = re.search(r"loss[:=][^\d]*([\d.]+)", l)
        if _m:
            los = float(_m.group(1))
            break
    progress(100, "SmolVLA 训练结束")
    result(ok=(rc == 0), stage="done", rc=rc, loss=los)
    return rc


# ─────────────────────────── 任务: 冒烟 ───────────────────────────
def task_demo(a) -> int:
    """小规模真跑 (真仿真+真反向传播), 用于验证链路, 不是假数据"""
    a.clean, a.jitter = 2, 0
    emit("🧪 冒烟模式: 小规模但**真跑** (真物理仿真 + 真反向传播)")
    return task_manifold(a)


def main():
    ap = argparse.ArgumentParser(description="APP 训练控制节点 · 真实训练执行器")
    ap.add_argument("--task", default="manifold",
                    choices=["manifold", "yolo", "smolvla", "demo"])
    ap.add_argument("--workdir", default=os.path.dirname(os.path.dirname(HERE)))
    ap.add_argument("--steps", type=int, default=220)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--clean", type=int, default=14)
    ap.add_argument("--jitter", type=int, default=4)
    ap.add_argument("--run-name", default="zmax_app_train")
    ap.add_argument("--config", default="")
    a = ap.parse_args()
    a.workdir = os.path.abspath(a.workdir)
    emit(f"═══ Z-MAX 真实训练 · task={a.task} · workdir={a.workdir} ═══")
    emit(f"解释器: {sys.executable}")
    t0 = time.time()
    rc = {"manifold": task_manifold, "yolo": task_yolo,
          "smolvla": task_smolvla, "demo": task_demo}[a.task](a)
    emit(f"═══ 结束 rc={rc} · 用时 {time.time()-t0:.1f}s ═══")
    return rc


if __name__ == "__main__":
    sys.exit(main())
