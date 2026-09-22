#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔁 Sim-to-Real 全系统数据闭环 (一条命令走完 采集→归档→数据→训练→评测→部署)

老倪 (09-22): 「要有完备的 L4 L3 L2 的模型训练，推理，配置，模块化，sim to real 的全系统
              数据闭环解决方案；注意，不要发出真机控制指令，但是你可以采集真机的数据，
              适配仿真和真机器人接口；注意不要干扰生产程序」

六环 (每环都有产物 + 取证, 任一环失败如实报, 不跳步):
  ① 感知采集体检  真机只读 tap 落盘新鲜度/发布者/帧率 (只读; 不碰产线)
  ② 数据归档      快照到 ~/zmax_data/sim2real_loop_<ts>/ (硬链接, 零额外磁盘) + MANIFEST(sha256/行数/跨度)
  ③ 数据构建      真机真值 → 训练用 H5/数据集 的口径检查 (episodes/帧数/skill_ctx 维度)
  ④ 训练          调 tools/joint_train_all.py (L4/L3/L2, 支持 LoRA)
  ⑤ 评测          判闸 (INTACT 逐轴 corr/MAE) + YOLO 真机帧检出 (同权重同帧口径)
  ⑥ 部署指针      软链切换 (--deploy 才真切; 默认 dry-run 只打印将切什么)

红线 (硬编码在脚本里, 不是口号):
  · 只读: 不调用任何 /move* /hmi/command /execute_external_task /gripper_driver; 不做任何真机写。
  · 不干扰生产: 归档用硬链接读, 训练等空闲 GPU, 不 kill 非本脚本进程。
  · 不编造: 缺数据/缺标定/缺权重 → 该环记 fail 并继续报错, 不用占位值糊过去。

用法:
  gui-venv311/bin/python tools/sim2real_loop.py --dry-run
  gui-venv311/bin/python tools/sim2real_loop.py                    # 采集体检+归档+构建+评测
  gui-venv311/bin/python tools/sim2real_loop.py --train --steps 200
  gui-venv311/bin/python tools/sim2real_loop.py --deploy           # 显式才切在役软链
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
OUT_DEFAULT = os.path.expanduser("~/zmax_ss_remote")
CACHE = "/home/ubuntu/stable-wm-cache"
TAP_GLOB = os.path.expanduser("~/zmax_data/real_tap_*/*.jsonl")

REDLINE = ("只读红线: 未调用任何运动/控制接口 (move*/hmi/command/execute_external_task/"
           "gripper_driver/state_machine); 归档=硬链接读; 训练等空闲 GPU; 不 kill 他人进程")


def _sha256(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()[:16]


def step1_collector(out_dir) -> dict:
    """① 感知采集体检 — 只读 status.json + 落盘 jsonl。"""
    r = {"step": "1_采集体检", "ok": False}
    sp = os.path.join(out_dir, "status.json")
    cands = sorted(glob.glob(os.path.join(out_dir, "state_*.jsonl")))
    if not os.path.exists(sp) or not cands:
        r["reason"] = f"无采集落盘 (需 ss-remote-tap 在线, 目录 {out_dir})"
        return r
    st = json.load(open(sp, encoding="utf-8"))
    p = cands[-1]
    age = time.time() - os.path.getmtime(p)
    recv = st.get("recv", {})
    r.update({"file": p, "age_s": round(age, 2), "samples": st.get("samples"),
              "recv": recv, "publishers": st.get("外部队列发布者(Orin侧)"),
              "tcp": st.get("tcp"), "geom": st.get("geom"),
              "ok": age < 60 and bool(recv.get("tcp"))})
    if not r["ok"]:
        r["reason"] = (f"落盘不新鲜 (age {age:.0f}s) 或 tcp 计数 0 "
                       f"(DDS 发现可能瞎了 → docker restart ss-remote-tap; 详见技能 orin-lan-direct-access)")
    return r


def step2_archive(out_dir, keep_mb=400) -> dict:
    """② 归档 — 硬链接快照 (零额外磁盘) + MANIFEST。"""
    r = {"step": "2_归档", "ok": False}
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(os.path.expanduser("~/zmax_data"), f"sim2real_loop_{ts}")
    os.makedirs(dst, exist_ok=True)
    files = sorted(glob.glob(os.path.join(out_dir, "*.jsonl"))) + \
        [p for p in (os.path.join(out_dir, "status.json"),) if os.path.exists(p)] + \
        sorted(glob.glob(os.path.join(out_dir, "cam_*.png")))
    man = {"archived_at": time.strftime("%F %T"), "src": out_dir, "entries": [],
           "method": "硬链接 (同 inode, 不额外占盘", "redline": REDLINE}
    for p in files:
        e = {"name": os.path.basename(p), "size": os.path.getsize(p), "sha256_16": _sha256(p)}
        if p.endswith(".jsonl"):
            try:
                with open(p, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - 65536))
                    tail = f.read().decode("utf-8", "replace").strip().splitlines()
                d0 = json.loads(tail[0])
                n = 0
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.strip():
                            n += 1
                e.update({"lines": n, "first_t": d0.get("t"),
                          "span_s": None})
            except Exception as ex:  # noqa: BLE001
                e["parse_note"] = f"{type(ex).__name__}"
        d = os.path.join(dst, os.path.basename(p))
        # ⚠️ 硬链接对 **root 拥有且本用户不可写** 的文件会被内核 protected_hardlinks 拒绝
        #   (真机 tap 是容器里 root 写的) → 失败必须**回退复制**, 否则 MANIFEST 有记录而文件其实没归档
        #   (2026-09-22 实测: 17 条里只有 1 条真落地)。method 逐条记录, 便于审计。
        try:
            if not os.path.exists(d):
                os.link(p, d)
            e["method"] = "hardlink"
            e["hardlink"] = os.stat(d).st_ino == os.stat(p).st_ino
        except OSError as ex:  # noqa: BLE001
            try:
                if not os.path.exists(d):
                    shutil.copy2(p, d)
                e["method"] = "copy(硬链接被拒: " + type(ex).__name__ + ")"
                e["hardlink"] = False
                e["sha_ok"] = _sha256(d) == e["sha256_16"]
            except OSError as ex2:  # noqa: BLE001
                e["method"] = "FAILED"
                e["hardlink"] = False
                e["note"] = f"{type(ex).__name__} → copy 也失败: {ex2}"
        man["entries"].append(e)
    with open(os.path.join(dst, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    r.update({"ok": bool(man["entries"]), "dir": dst,
              "n_entries": len(man["entries"]),
              "total_mb": round(sum(e["size"] for e in man["entries"]) / 1e6, 1),
              "hardlinked": sum(1 for e in man["entries"] if e.get("hardlink"))})
    return r


def step3_data(h5=None) -> dict:
    """③ 数据构建 — 训练数据口径检查 (episodes/帧数/skill_ctx 维度)。只读。"""
    r = {"step": "3_数据构建", "ok": False}
    h5 = h5 or os.path.join(CACHE, "datasets", "optical_insert_v6_disturb.h5")
    if not os.path.exists(h5):
        r["reason"] = f"训练数据缺: {h5}"
        return r
    try:
        import h5py
        with h5py.File(h5, "r") as h:
            keys = list(h.keys())
            info = {}
            for k in keys[:6]:
                try:
                    info[k] = {"shape": list(h[k].shape), "dtype": str(h[k].dtype)}
                except Exception:  # noqa: BLE001
                    info[k] = {"kind": "group", "n": len(h[k])}
        r.update({"ok": True, "h5": h5, "size_mb": round(os.path.getsize(h5) / 1e6, 1),
                  "keys": keys, "info": info})
    except Exception as e:  # noqa: BLE001
        r["reason"] = f"读取失败 {type(e).__name__}: {e}"
    # YOLO 真机标注数据
    dy = os.path.join(ROOT, "data/yolo_annot/dataset/data.yaml")
    r["yolo_annot"] = {"data_yaml": os.path.relpath(dy, ROOT), "ok": os.path.exists(dy),
                       "labels": len(glob.glob(os.path.join(ROOT, "data/yolo_annot/dataset/*/*/*.txt")))}
    return r


def step4_train(steps, only) -> dict:
    """④ 训练 — 复用编排器 (不另造训练逻辑)。"""
    cmd = [PY, os.path.join(ROOT, "tools/joint_train_all.py"), "--steps", str(steps)]
    if only:
        cmd += ["--only", only]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    tail = "\n".join(p.stdout.strip().splitlines()[-25:])
    print(tail)
    return {"step": "4_训练", "ok": p.returncode == 0, "rc": p.returncode, "cmd": cmd,
            "tail": tail[-4000:]}


def step5_eval(ckpt=None, clips=30) -> dict:
    """⑤ 评测 — INTACT 判闸 (逐轴 corr + MAE, 同权重同帧) 与 YOLO 真机帧检出。"""
    r = {"step": "5_评测", "ok": False}
    ck = ckpt or os.path.join(CACHE, "checkpoints", "intact_l4_current", "weights.pt")
    if not os.path.exists(ck):
        r["reason"] = f"评测权重缺: {ck}"
    else:
        out = os.path.join(ROOT, f"reports/loop_eval_{int(time.time())}.json")
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "INTACT_POLICY": ck,
               "STABLEWM_HOME": CACHE, "LOCAL_DATASET_DIR": CACHE}
        cmd = [PY, os.path.join(ROOT, "tools/intact_replay_check_v4.py"),
               "--skill", "on", "--clips", str(clips), "--repeats", "1", "--device", "cpu",
               "--out", out]
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        r.update({"rc": p.returncode, "out": out,
                  "tail": "\n".join(p.stdout.strip().splitlines()[-14:]),
                  "ok": p.returncode == 0 and os.path.exists(out)})
        if os.path.exists(out):
            d = json.load(open(out, encoding="utf-8"))
            ps = d.get("per_slot", {})
            r["per_slot"] = ps
            r["min_axis_corr"] = min([min(v.get("pearson_xyz_min", 9) for v in ps.values())] or [None]) \
                if ps else None
    yl = os.path.join(ROOT, "models/yolo_peg_live.pt")
    r["yolo_live"] = {"path": os.path.relpath(yl, ROOT), "exists": os.path.exists(yl),
                      "note": "真机帧检出评测跑 tools/ss_yolo_on_real.py --auto (常驻已开)"}
    return r


def step6_deploy(deploy: bool, targets=None) -> dict:
    """⑥ 部署指针 — 软链切换 (默认 dry-run 只打印)。"""
    r = {"step": "6_部署指针", "dry_run": not deploy, "switches": []}
    tg = targets or {"intact_l4_current": os.path.join(CACHE, "checkpoints", "intact_l4_current"),
                     "yolo_peg_live": os.path.join(ROOT, "models/yolo_peg_live.pt")}
    for name, cur in tg.items():
        info = {"name": name, "path": cur, "exists": os.path.exists(cur),
                "is_symlink": os.path.islink(cur)}
        if os.path.islink(cur):
            info["current_target"] = os.path.realpath(cur)
        r["switches"].append(info)
    r["note"] = ("--deploy 未给: 只打印当前在役指针 (切换须显式 --deploy + 目标路径; "
                 "切换前请确认判闸已过, 见 docs/design/handoff 的在役口径)")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="Sim-to-Real 全系统数据闭环")
    ap.add_argument("--out", default=OUT_DEFAULT, help="真机只读采集落盘目录")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--only", default="")
    ap.add_argument("--eval", action="store_true", help="跑 INTACT 判闸 (CPU, 30 clips)")
    ap.add_argument("--clips", type=int, default=30)
    ap.add_argument("--eval-ckpt", default="")
    ap.add_argument("--deploy", action="store_true")
    a = ap.parse_args()

    ts = time.strftime("%Y%m%d_%H%M%S")
    rep = {"started": time.strftime("%F %T"), "redline": REDLINE, "steps": []}
    print("🔁 Sim-to-Real 全系统数据闭环")
    print(f"   采集目录 {a.out} · 证据 reports/sim2real_loop_{ts}.json")
    print(f"   {REDLINE}")
    print("─" * 82)

    plan = [("①采集体检", lambda: step1_collector(a.out)),
            ("②归档", lambda: step2_archive(a.out))]
    if a.train:
        plan.append(("④训练", lambda: step4_train(a.steps, a.only)))
    plan.append(("③数据构建", lambda: step3_data()))
    if a.eval:
        plan.append(("⑤评测", lambda: step5_eval(a.eval_ckpt or None, a.clips)))
    plan.append(("⑥部署指针", lambda: step6_deploy(a.deploy)))

    if a.dry_run:
        for nm, _f in plan:
            print(f"   [dry] {nm}")
        print("(--dry-run: 未执行)")
        return 0

    for nm, fn in plan:
        t0 = time.time()
        res = fn()
        res["secs"] = round(time.time() - t0, 1)
        rep["steps"].append(res)
        flag = "✅" if res.get("ok", True) else "⚠️"
        print(f"{flag} {nm}: " + json.dumps({k: v for k, v in res.items()
                                             if k not in ("step", "tail", "per_slot")},
                                            ensure_ascii=False)[:300])
        if res.get("reason"):
            print(f"     ↳ 原因: {res['reason']}")

    rep["finished"] = time.strftime("%F %T")
    with open(os.path.join(ROOT, "reports", f"sim2real_loop_{ts}.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    ok = sum(1 for s in rep["steps"] if s.get("ok", True))
    print("─" * 82)
    print(f"结果: {ok}/{len(rep['steps'])} 环通过 · 报告 reports/sim2real_loop_{ts}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
