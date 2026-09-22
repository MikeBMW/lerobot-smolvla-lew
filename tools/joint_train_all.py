#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚀 全系统联合训练编排器 (L4 INTACT · L3 SmolVLA · L2 YOLO · 大模型层体检)

老倪 (09-22): 「全面，全系统联合训练，保证 大模型层，L4 INTACT, L3 Smolvla ,L2 YOLO 和 2D转3D 深度。
              包括标定参数接口；联合整体训练，适配或增加 LoRA, 你来进行架构优化。总之，要有完备的
              L4 L3 L2 的模型训练，推理，配置，模块化，sim to real 的全系统数据闭环解决方案；
              注意，不要发出真机控制指令，但是你可以采集真机的数据，适配仿真和真机器人接口」

本编排器把**各层已有且验证过的训练入口**统一成一条流水线 (不另造训练逻辑, 只做编排+取证):
  · L4 INTACT  : INTACT-JEPA train.py (数据 zmax_v6, 续自当前在役权重) —— 支持 LoRA 适配
  · L3 SmolVLA : lerobot lerobot_train (policy=smolvla_lew, 从 v10 ckpt 续) —— 走 lerobot **原生 PEFT/LoRA**
  · L2 YOLO    : tools/yolo_annot_train.py (真机标注帧域适应微调, 基座=在役软链)
  · 大模型层   : 权重/接口就绪体检 (Qwen2.5-VL-3B / SmolVLM2 / DeepSeek key), 不做训练

工程约束 (老倪红线)
  · **不发任何真机控制指令**: 全部是本机 GPU 训练任务; 真机侧只读采集由 tap 常驻负责 (本编排器不碰)。
  · **不干扰生产程序**: 只在空闲 GPU 上跑, 跑前查显存; 不 kill 任何非本编排器启动的进程。
  · **零回退**: 每层都从**当前在役权重**续训 (LoRA 则基座冻结), 不覆盖旧产物 (新目录/新名字)。
  · **取证**: 每阶段落 reports/joint_train_<ts>/<stage>.json (命令/日志/退出码/耗时/自证) + 汇总表。

用法:
  gui-venv311/bin/python tools/joint_train_all.py --dry-run          # 只打印计划
  gui-venv311/bin/python tools/joint_train_all.py --only L4 --steps 200
  gui-venv311/bin/python tools/joint_train_all.py                    # 全跑 (默认有界步数)
  gui-venv311/bin/python tools/joint_train_all.py --env-check        # 各层前置条件体检
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTACT = "/home/ubuntu/INTACT-JEPA"
CACHE = "/home/ubuntu/stable-wm-cache"
PY_GUI = os.path.join(ROOT, "gui-venv311", "bin", "python")
PY_INTACT = os.path.join(INTACT, ".venv", "bin", "python")
PY_LEROBOT = "/home/ubuntu/lerobot-venv/bin/python"
LORA_MOD = os.path.join(ROOT, "tools", "lora_inject.py")

# 在役权重 (续训起点; 与 docs/design/handoff_*.md 口径一致)
L4_INIT = os.path.join(CACHE, "checkpoints", "intact_goal_optical_insert_v6d9_s3072", "weights_epoch_1.pt")
L3_CKPT = os.path.join(ROOT, "outputs", "train", "smolvla_lew_sim", "checkpoints", "000300")
L2_BASE = os.path.join(ROOT, "models", "yolo_peg_live.pt")


def _run_stream(cmd, cwd, env, log_path, timeout=None):
    """跑子进程并把 stdout+stderr 同时写日志 (老倪要求训练全程可见), 返回 (rc, secs)。"""
    t0 = time.time()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "wb") as lf:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, bufsize=1)
        for line in iter(p.stdout.readline, b""):
            lf.write(line)
            lf.flush()
            try:
                sys.stdout.write(line.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                pass
        p.wait(timeout=timeout)
    return p.returncode, round(time.time() - t0, 1)


def gpu_free_mb():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
        used, total = [int(x) for x in out.strip().splitlines()[0].split(",")]
        return total - used
    except Exception:  # noqa: BLE001
        return -1


def wait_gpu(need_mb, timeout_s=600, poll=15):
    t0 = time.time()
    while True:
        free = gpu_free_mb()
        if free < 0 or free >= need_mb:
            return free
        if time.time() - t0 > timeout_s:
            print(f"⚠️ 等 GPU {need_mb}MB 超时 ({timeout_s}s), 当前空闲 {free}MB — 仍继续 (让训练自己 OOM 前先记证)")
            return free
        print(f"   … 等 GPU: 需 {need_mb}MB, 现空闲 {free}MB ({(time.time()-t0):.0f}s)")
        time.sleep(poll)


# ───────────────────────── 阶段定义 ─────────────────────────
def build_stages(a) -> list:
    ts = time.strftime("%Y%m%d_%H%M%S")
    mroot = os.path.join(ROOT, "reports", f"joint_train_{ts}")

    # L4: INTACT 续训 (+LoRA)
    l4_name = f"intact_goal_optical_insert_v6lora_{a.steps}"
    l4_cmd = [
        PY_INTACT, "train.py",
        "--config-name=intact_goal_optical_insert_v6", "data=zmax_v6",
        f"output_model_name={l4_name}",
        f"init_weights_path={L4_INIT}", "init_zero_skill_branch=false",
        "trainer.max_epochs=1", f"+trainer.limit_train_batches={a.steps}",
    ]
    l4_env = {
        "PATH": os.path.join(INTACT, ".venv", "bin") + ":" + os.environ.get("PATH", ""),
        "STABLEWM_HOME": CACHE, "LOCAL_DATASET_DIR": CACHE,
        "ZMAX_LORA": "1" if a.lora_l4 else "0",
        "ZMAX_LORA_MOD": LORA_MOD, "ZMAX_LORA_R": str(a.lora_r),
        "ZMAX_LORA_ALPHA": str(a.lora_r * 2),
        "ZMAX_LORA_TARGETS": "to_qkv,net.,predictor,action,encoder",
        "ZMAX_LORA_OUT": os.path.join(mroot, "lora_l4_init.pt"),
        "HF_HUB_OFFLINE": "1",
    }

    # L3: SmolVLA+LEW (+lerobot 原生 PEFT LoRA)
    #   ⚠️ PEFT 段**写进 YAML** 而不是走 `--peft.xxx` 命令行: draccus 对 `peft: PeftConfig|None=None`
    #   这种可空子配置的命令行覆盖不可靠 (父项 None 时子项无处挂) → 直接改生成的 yaml 最稳。
    cfg3 = os.path.join(ROOT, f"config_smolvla_lew_lora_{a.steps}.yaml")
    # ⚠️ LoRA 目标 all-linear 会给视觉塔也挂适配器 → 8GB 卡的激活额外开销把 batch8 顶爆
    #   (2026-09-22 实测 torch.OutOfMemoryError: 需 816MiB, 仅余 330MiB) → LoRA 轮降 batch 到 4
    #   并开 expandable_segments 抗碎片。
    b3 = 2 if a.lora_l3 else 8
    l3_targets = [t for t in a.l3_targets.split(",") if t]
    gen3 = [PY_GUI, os.path.join(ROOT, "tools", "mk_smolvla_sim_cfg.py"),
            "--steps", str(a.steps), "--batch", str(b3), "--out", cfg3,
            "--outdir", f"outputs/train/smolvla_lew_lora_{a.steps}"]
    l3_cmd = [PY_LEROBOT, "-m", "lerobot.scripts.lerobot_train", f"--config_path={cfg3}"]
    l3_env = {"PATH": "/home/ubuntu/lerobot-venv/bin:" + os.environ.get("PATH", ""),
              "PYTHONPATH": os.path.join(ROOT, "src"),
              "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
              "HF_HUB_OFFLINE": "1", "WANDB_MODE": "disabled"}
    post3 = []
    pre3 = [{"cmd": gen3, "cwd": ROOT, "env": l3_env,
             "log": os.path.join(mroot, "L3_mkcfg.log")}]
    if a.lora_l3:
        _code = (
            "import yaml,sys\n"
            f"p={cfg3!r}\n"
            "c=yaml.safe_load(open(p))\n"
            "c['peft']={'method_type':'LORA','r':%d,'lora_alpha':%d,"
            f"'target_modules':{l3_targets!r},'full_training_modules':[]}}\n"
            "yaml.safe_dump(c,open(p,'w'),sort_keys=False,allow_unicode=True)\n"
            "print('[L3] 已写入 peft(LoRA) 段:',c['peft'])\n" % (a.lora_r, a.lora_r * 2)
        )
        # ⚠️ 顺序铁律: mkcfg 生成 → **写 peft 段** → 才启动训练。写成 post 会在训练**之后**才补,
        #   等于整轮没开 LoRA (2026-09-22 实测踩到: 日志里 'peft': None, use_peft=False)。
        pre3.append({"cmd": [PY_GUI, "-c", _code], "cwd": ROOT, "env": l3_env,
                     "log": os.path.join(mroot, "L3_peft_patch.log")})

    # L2: YOLO 真机标注微调
    l2_cmd = [PY_GUI, os.path.join(ROOT, "tools", "yolo_annot_train.py"),
              "--epochs", str(a.yolo_epochs), "--imgsz", "640",
              "--name", f"annot_lora_{ts}"]
    if not a.yolo_no_base and os.path.exists(L2_BASE):
        l2_cmd += ["--base", L2_BASE]
    l2_env = {"PATH": os.path.dirname(PY_GUI) + ":" + os.environ.get("PATH", "")}

    stages = [
        {"id": "L4", "layer": "L4 INTACT (安全+物理导航)", "gpu_mb": 6000, "est_min": 8,
         "desc": ("INTACT 续训 + LoRA 适配 (基座冻结, 只训 lora_A/B)" if a.lora_l4
                  else "INTACT 续训 (全参)"),
         "cwd": INTACT, "cmd": l4_cmd, "env": l4_env, "log": os.path.join(mroot, "L4.log"),
         "evidence": [os.path.join(CACHE, "checkpoints", l4_name)],
         "note": f"起点 {os.path.basename(os.path.dirname(L4_INIT))}/{os.path.basename(L4_INIT)}"},
        {"id": "L3", "layer": "L3 SmolVLA (长程序列规划)", "gpu_mb": 6000, "est_min": 6,
         "desc": ("SmolVLA+LEW 续训 + lerobot 原生 PEFT(LoRA)" if a.lora_l3
                  else "SmolVLA+LEW 续训 (全参)"),
         "pre": pre3,
         "cwd": ROOT, "cmd": l3_cmd, "env": l3_env, "log": os.path.join(mroot, "L3.log"),
         "evidence": [os.path.join(ROOT, f"outputs/train/smolvla_lew_lora_{a.steps}")],
         "note": f"起点 {os.path.relpath(L3_CKPT, ROOT)}"},
        {"id": "L2", "layer": "L2 YOLO (检测) + 2D→3D", "gpu_mb": 4000, "est_min": 5,
         "desc": "真机标注帧域适应微调 (基座=在役软链)",
         "cwd": ROOT, "cmd": l2_cmd, "env": l2_env, "log": os.path.join(mroot, "L2.log"),
         "evidence": [os.path.join(ROOT, "data/yolo_annot/dataset")],
         "note": f"基座 {os.path.relpath(L2_BASE, ROOT)} (软链)"},
        {"id": "LLM", "layer": "大模型层 (VLM/VLA 意图)", "gpu_mb": 0, "est_min": 0,
         "desc": "权重/接口就绪体检 (无训练; 上大模型须显存协商)",
         "cwd": ROOT, "cmd": [sys.executable, os.path.join(ROOT, "tools", "llm_layer_check.py")],
         "env": {}, "log": os.path.join(mroot, "LLM.log"), "evidence": [], "note": "只读体检"},
    ]
    for s in stages:
        s["env_full"] = {**os.environ, **s["env"]}
        s["mroot"] = mroot
    return stages, mroot


def env_check(stages) -> int:
    print("🔎 各层前置条件体检")
    print("─" * 78)
    bad = 0
    checks = {
        "L4": [(PY_INTACT, "INTACT venv python"), (L4_INIT, "L4 起点权重"),
               (os.path.join(CACHE, "datasets", "optical_insert_v6_disturb.h5"), "v6 训练数据"),
               (LORA_MOD, "LoRA 模块")],
        "L3": [(PY_LEROBOT, "lerobot venv python"), (L3_CKPT, "L3 起点 ckpt"),
               (os.path.join(ROOT, "tools/mk_smolvla_sim_cfg.py"), "L3 配置生成器"),
               (os.path.join(ROOT, "outputs/train/smolvla_lew_v10/resume_cfg.json"), "v10 配置模板")],
        "L2": [(PY_GUI, "gui venv python"), (L2_BASE, "YOLO 基座软链"),
               (os.path.join(ROOT, "data/yolo_annot/dataset/data.yaml"), "真机标注数据集")],
    }
    for s in stages:
        if s["id"] not in checks:
            continue
        print(f"\n[{s['id']}] {s['layer']}")
        for p, what in checks[s["id"]]:
            ok = os.path.exists(p)
            if not ok:
                bad += 1
            print(f"   {'✅' if ok else '❌'} {what:<18} {p}")
    # L3 peft 可用性
    r = subprocess.run([PY_LEROBOT, "-c", "import peft;print(peft.__version__)"],
                       capture_output=True, text=True)
    ok = r.returncode == 0
    bad += 0 if ok else 1
    print(f"   {'✅' if ok else '❌'} L3 PEFT/LoRA 依赖  peft {r.stdout.strip() or '(缺: uv pip install --python ' + PY_LEROBOT + ' peft)'}")
    print("─" * 78)
    print(f"GPU 空闲 {gpu_free_mb()} MB")
    print("✅ 前置齐全" if bad == 0 else f"⚠️ {bad} 项缺失")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Z-MAX 全系统联合训练编排器")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="只跑某些层, 逗号分隔 (L4,L3,L2,LLM)")
    ap.add_argument("--skip", default="", help="跳过某层")
    ap.add_argument("--steps", type=int, default=200, help="各层有界步数 (L4/L3)")
    ap.add_argument("--yolo-epochs", type=int, default=30)
    ap.add_argument("--yolo-no-base", action="store_true", help="YOLO 不从在役软链续 (从 COCO 重训)")
    ap.add_argument("--lora-l4", dest="lora_l4", action="store_true", default=True)
    ap.add_argument("--no-lora-l4", dest="lora_l4", action="store_false")
    ap.add_argument("--lora-l3", dest="lora_l3", action="store_true", default=True)
    ap.add_argument("--no-lora-l3", dest="lora_l3", action="store_false")
    ap.add_argument("--lora-r", type=int, default=8)
    ap.add_argument("--l3-targets", default="q_proj,k_proj,v_proj,o_proj",
                    help="L3 LoRA 目标模块 (默认只挂语言注意力投影, 不挂视觉塔 —— 8GB 卡实测)"
                         "all-linear 会 OOM")
    ap.add_argument("--env-check", action="store_true")
    ap.add_argument("--gpu-wait", type=int, default=900, help="等 GPU 空闲的最长秒数")
    a = ap.parse_args()

    stages, mroot = build_stages(a)
    sel = [s for s in stages if (not a.only or s["id"] in a.only.split(","))
           and s["id"] not in (a.skip.split(",") if a.skip else [])]

    if a.env_check:
        return env_check(stages)

    print(f"🚀 全系统联合训练 — {len(sel)} 层 · 证据目录 {os.path.relpath(mroot, ROOT)}")
    print(f"   有界步数 {a.steps} · LoRA L4={a.lora_l4}(r={a.lora_r}) L3={a.lora_l3} · "
          f"YOLO {a.yolo_epochs} epochs · GPU 空闲 {gpu_free_mb()} MB")
    print("   红线: 全为本机 GPU 训练, 不发任何真机指令; 不 kill 非本编排器进程; 旧产物不覆盖")
    print("─" * 78)
    for s in sel:
        print(f"[{s['id']}] {s['layer']} — {s['desc']}")
        print(f"     起点 {s['note']} | 预计 {s['est_min']}min | 需显存 {s['gpu_mb']}MB")
        print(f"     $ (cd {s['cwd']}) {' '.join(s['cmd'])}")
        for k, v in sorted(s["env"].items()):
            if k != "PATH":
                print(f"       env {k}={v}")
        for p in s.get("pre", []):
            print(f"       pre: {' '.join(p['cmd'])}")
    if a.dry_run:
        print("\n(--dry-run: 未执行)")
        return 0

    os.makedirs(mroot, exist_ok=True)
    rows = []
    for s in sel:
        print("\n" + "=" * 78)
        print(f"▶ [{s['id']}] {s['desc']}")
        if s["gpu_mb"]:
            free = wait_gpu(s["gpu_mb"], timeout_s=a.gpu_wait)
            print(f"   GPU 空闲 {free} MB (需 {s['gpu_mb']} MB)")
        rc_pre = 0
        for p in s.get("pre", []):
            print(f"   前置: {' '.join(p['cmd'][:4])} …")
            rc_pre, _ = _run_stream(p["cmd"], p["cwd"], {**os.environ, **p.get("env", {})}, p["log"])
            if rc_pre != 0:
                break
        t0 = time.time()
        rc, secs = (rc_pre, 0.0) if rc_pre != 0 else _run_stream(s["cmd"], s["cwd"], s["env_full"], s["log"])
        rc_post = 0
        for p in (s.get("post") or []):
            print(f"   后置: {' '.join(p['cmd'][:3])} …")
            rc_post, _ = _run_stream(p["cmd"], p["cwd"], {**os.environ, **p.get("env", {})}, p["log"])
            if rc_post != 0:
                break
        if rc == 0 and rc_post != 0:
            rc = rc_post
        ev = [{"path": e, "exists": os.path.exists(e),
               "size_mb": (round(os.path.getsize(e) / 1e6, 1) if os.path.isfile(e) else None)}
              for e in s["evidence"]]
        row = {"stage": s["id"], "layer": s["layer"], "desc": s["desc"], "cmd": s["cmd"],
               "rc": rc, "secs": secs, "log": s["log"], "evidence": ev,
               "ts": time.strftime("%F %T")}
        rows.append(row)
        with open(os.path.join(mroot, "stages.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  {'✅' if rc == 0 else '❌'} rc={rc} 用时 {secs}s  日志 {os.path.relpath(s['log'], ROOT)}")

    summary = {"generated_at": time.strftime("%F %T"), "steps": a.steps,
               "lora": {"L4": a.lora_l4, "L3": a.lora_l3, "r": a.lora_r},
               "gpu_free_mb_at_end": gpu_free_mb(), "rows": rows}
    with open(os.path.join(mroot, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\n" + "=" * 78)
    print(f"{'层':<5}{'rc':>4}{'秒':>9}  产物")
    for r in rows:
        evs = ", ".join(f"{os.path.basename(x['path'])}{'✔' if x['exists'] else '✘'}" for x in r["evidence"]) or "—"
        print(f"{r['stage']:<5}{r['rc']:>4}{r['secs']:>9.1f}  {evs}")
    print(f"\n汇总: {os.path.relpath(os.path.join(mroot, 'summary.json'), ROOT)}")
    return 0 if all(r["rc"] == 0 for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
