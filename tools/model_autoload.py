#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""model_autoload.py — 重启自动加载 L2 YOLO / L3 SmolVLA / L4 INTACT 的**单一真源 + 真加载器**

老倪需求 (2026-09-28): 「下次重启，自动加载 L2 YOLO、L3 SmolVLA、L4 INTACT 等模型」

设计 (与既有件一致, 不另造一套):
  · 指针登记表 = `models/active_models.json` (唯一真源, 层级 → 在役指针/权重)
      - L2 = `models/yolo_peg_live.pt`        (在役软链指针; 换模型=换软链, 不覆盖文件)
      - L3 = `outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model`
             (与引擎 state_space_sim_real.py `SS_L3_CK` 默认值**同源**, 不写第二份)
      - L4 = INTACT 稳定指针 `intact_l4_current` (STABLEWM_HOME 下 config.json + weights.pt 软链)
  · 加载器 = 复用引擎**已经在用**的加载路径 (不是我自己拼的):
      - L2: ultralytics `YOLO(ptr)` + 真帧推理 (真机帧来自视频流 8791; 取不到才退空白帧并如实标注)
      - L3: `lerobot.policies.smolvla_lew.SmolVLALewPolicy.from_pretrained` + 官方
            `make_pre_post_processors` (与 state_space_sim_real.py:1203-1220 逐行同口径)
      - L4: `lerobot.policies.intact.runtime.model_adapter.IntactRuntime` 子进程桥 hello
            → 真加载权重并回 `trained=True` (trained=False 必须给 reason, 不许装成功)
  · 入口:  `autoload()`  —— 控制台启动时后台线程调用 (tools/gui/studio.py main() 内,
            与既有 `_yolo_ensure_aligner` 预热同一个位置), 也可命令行单独跑。
  · 取证:  每层落 `reports/model_autoload_<ts>.json` (指针解析/真实路径/sha16/加载模式/耗时/判据)

用法:
  ./gui-venv311/bin/python tools/model_autoload.py                 # 解析 + 真加载验证 (L2+ 轻量 L3/L4)
  ./gui-venv311/bin/python tools/model_autoload.py --deep          # 连 L3 权重也真 from_pretrained
  ./gui-venv311/bin/python tools/model_autoload.py --only L4 --json
  ./gui-venv311/bin/python tools/model_autoload.py --resolve       # 只解析指针, 不加载
  ./gui-venv311/bin/python tools/model_autoload.py --write-registry # 写回登记表 (首次/指针变更后)
  ./gui-venv311/bin/python tools/model_autoload.py --hook-status   # 重启挂钩现状 (控制台/unit/cron)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_PATH = os.path.join(ROOT, "models", "active_models.json")
REPORT_DIR = os.path.join(ROOT, "reports")
INTACT_CACHE = os.environ.get("ZMAX_INTACT_CACHE", "/home/ubuntu/stable-wm-cache")
STREAM = os.environ.get("ZMAX_STREAM", "http://127.0.0.1:8791")


# ─────────────────────────── 登记表 (单一真源) ───────────────────────────
def default_registry() -> dict:
    return {
        "schema": "zmax-active-models/1",
        "note": "各层在役模型指针 (重启自动加载的真源)。换模型 = 改这里的指针/软链, 不要覆盖权重文件。",
        "L2": {
            "kind": "yolo",
            "name": "L2 · YOLO 光模块检测 (真机域在役)",
            "path": "models/yolo_peg_live.pt",
            "pointer": True,
            "note": "软链指针 → 真机域标定权重; 引擎仿真链另有 peg_v1 权重 (仿真/真机不同域, 见 node_logic._yolo_ensure_aligner 决策记录)",
            "role": "检测 (2D→3D 输入) · 全量训练入口 tools/yolo_annot_train.py",
        },
        "L3": {
            "kind": "smolvla",
            "name": "L3 · SmolVLA+LEW 策略 (在役运行时 ckpt)",
            "path": "outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model",
            "env_override": "SS_L3_CK",
            "note": "与 state_space_sim_real.py 的 SS_L3_CK 默认值同源 (引擎真跑的就是它)",
            "role": "策略执行 (xyz 由模型出) · LoRA 适配入口 tools/joint_train_all.py --only L3 --lora-l3",
        },
        "L4": {
            "kind": "intact",
            "name": "L4 · INTACT-JEPA 意图-动作 (在役稳定指针)",
            "path": os.path.join(INTACT_CACHE, "checkpoints", "intact_l4_current"),
            "policy": "intact_l4_current",
            "cache": INTACT_CACHE,
            "runtime": "root",
            "note": "官方加载器认文件夹格式 (config.json + 恰好一个 weights.pt 软链) — 换模型只换软链",
            "role": "零搜索意图-动作 chunk · LoRA 适配入口 tools/joint_train_all.py --only L4 --lora-l4 (训完必 merge_lora_ckpt.py)",
        },
    }


def load_registry(create: bool = False) -> dict:
    if os.path.isfile(REG_PATH):
        try:
            d = json.load(open(REG_PATH, encoding="utf-8"))
            if isinstance(d, dict) and d.get("L2") and d.get("L3") and d.get("L4"):
                return d
        except Exception as e:                                              # noqa: BLE001
            print("⚠️ 登记表不可读 (%s), 用内置默认: %s" % (REG_PATH, e))
    d = default_registry()
    if create:
        write_registry(d)
    return d


def write_registry(d: dict) -> None:
    os.makedirs(os.path.dirname(REG_PATH), exist_ok=True)
    d = dict(d)
    d["updated"] = time.strftime("%F %T")
    json.dump(d, open(REG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _abs(p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def _sha16(p: str) -> str:
    """指针/文件 sha16 (软链取**真实目标**; 目录返回 None)。"""
    try:
        if os.path.isdir(p):
            return None
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        return h.hexdigest()[:16]
    except Exception:                                                       # noqa: BLE001
        return None


def resolve_layer(key: str, ent: dict) -> dict:
    """解析指针 → 真实路径 (含软链真实目标/sha16/字节数)。找不到如实报, 不编造。"""
    p = _abs(ent.get("path") or "")
    out = {"layer": key, "kind": ent.get("kind"), "name": ent.get("name"),
           "declared": ent.get("path"), "path": p, "exists": os.path.exists(p)}
    if ent.get("kind") == "intact":
        lab = os.path.join(p, "config.json")
        w = os.path.join(p, "weights.pt")
        out["folder_format"] = bool(os.path.isfile(lab) and os.path.isfile(w))
        out["weights"] = os.path.realpath(w) if os.path.isfile(w) else None
        out["exists"] = bool(out["folder_format"])
        out["sha16"] = _sha16(out["weights"]) if out.get("weights") else None
        if out["weights"]:
            out["size_mb"] = round(os.path.getsize(out["weights"]) / 1e6, 1)
        return out
    if os.path.exists(p):
        out["realpath"] = os.path.realpath(p)
        out["symlink"] = os.path.islink(p)
        if os.path.isdir(p):
            files = sorted(os.listdir(p))
            out["files"] = files[:12]
            wf = [f for f in files if f.endswith((".safetensors", ".pt", ".bin"))]
            out["weight_file"] = wf[0] if wf else None
            if out.get("weight_file"):
                wp = os.path.join(p, out["weight_file"])
                out["sha16"] = _sha16(wp)
                out["size_mb"] = round(os.path.getsize(wp) / 1e6, 1)
        else:
            out["sha16"] = _sha16(p)
            out["size_mb"] = round(os.path.getsize(p) / 1e6, 1)
    return out


# ─────────────────────────── 各层真加载器 ───────────────────────────
def _gpu_free_mb() -> int:
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        used, total = [int(x) for x in o.split(",")]
        return total - used
    except Exception:                                                       # noqa: BLE001
        return -1


def load_l2(ent: dict, deep: bool = True) -> dict:
    """L2 真加载: ultralytics 解析权重 + (真帧) 推理一次 → 类别名/检出数。"""
    r = {"layer": "L2", "loader": "ultralytics.YOLO(models/yolo_peg_live.pt)", "ok": False}
    p = _abs(ent["path"])
    if not os.path.exists(p):
        r["reason"] = "权重不存在: %s" % p
        return r
    t0 = time.time()
    try:
        from ultralytics import YOLO
        m = YOLO(p)
        r["classes"] = list(getattr(m, "names", {}).values()) if getattr(m, "names", None) else []
        r["n_classes"] = len(r["classes"])
        r["loaded_relpath"] = os.path.relpath(os.path.realpath(p), ROOT)
        if deep:
            import numpy as np
            frame = None
            try:                                                            # 真机帧优先进模型
                import urllib.request
                raw = urllib.request.urlopen(
                    "%s/snapshot/arm.jpg?_=%d" % (STREAM, int(time.time())), timeout=8).read()
                import cv2
                frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                r["frame_src"] = "video_stream_8791/arm.jpg(%dB)" % len(raw)
            except Exception as e:                                          # noqa: BLE001
                r["frame_src"] = "⚠️ 取不到视频流帧 (%s) → 退空白帧, 仅证模型可前向" % type(e).__name__
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
            res = m.predict(frame, verbose=False, conf=0.25)
            boxes = int(len(res[0].boxes)) if res else 0
            r["inference"] = {"n_boxes": boxes, "imgsz": [int(x) for x in res[0].orig_shape]}
        r["ok"] = True
    except Exception as e:                                                  # noqa: BLE001
        r["reason"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    r["secs"] = round(time.time() - t0, 2)
    return r


def load_l3(ent: dict, deep: bool = True) -> dict:
    """L3 真加载: 引擎同款 from_pretrained + 官方预处理器; 轻量模式=真读 config/权重头。"""
    r = {"layer": "L3", "loader": "SmolVLALewPolicy.from_pretrained (与引擎 SS_L3_CK 同源)", "ok": False}
    p = _abs(os.environ.get(ent.get("env_override", "SS_L3_CK")) or ent["path"])
    if not os.path.isdir(p):
        r["reason"] = "ckpt 目录不存在: %s" % p
        return r
    t0 = time.time()
    try:
        cfg = json.load(open(os.path.join(p, "config.json"), encoding="utf-8"))
        r["type"] = cfg.get("type")
        r["n_obs_steps"] = cfg.get("n_obs_steps")
        r["ckpt_relpath"] = os.path.relpath(p, ROOT)
        sf = os.path.join(p, "model.safetensors")
        if os.path.isfile(sf):
            with open(sf, "rb") as f:                                       # safetensors 头 = 前 8B 长度
                n = int.from_bytes(f.read(8), "little")
                hdr = json.loads(f.read(n).decode("utf-8"))
            keys = [k for k in hdr if k != "__metadata__"]
            r["weights"] = {"file": "model.safetensors", "n_tensors": len(keys),
                            "size_mb": round(os.path.getsize(sf) / 1e6, 1),
                            "param_elems": None}
            try:                                                            # 参数量 = 各 tensor shape 乘积 (头里就有)
                import math
                tot = 0
                for k in keys:
                    s = hdr[k].get("shape") or []
                    tot += int(math.prod(s)) if s else 1
                r["weights"]["param_elems"] = tot
            except Exception:                                               # noqa: BLE001
                pass
            r["ok_light"] = True
        else:
            r["reason"] = "缺 model.safetensors"
        if deep:
            free = _gpu_free_mb()
            r["gpu_free_mb"] = free
            if 0 < free < 2500:
                r["deep"] = "跳过 (GPU 空闲 %dMB < 2500MB, 与训练共存时不抢显存; 引擎用到时自会加载)" % free
            else:
                sys.path.insert(0, os.path.join(ROOT, "src"))
                import torch
                from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
                from lerobot.policies.factory import make_pre_post_processors
                dev = os.environ.get("SS_L3_DEV") or ("cuda" if torch.cuda.is_available() else "cpu")
                pol = SmolVLALewPolicy.from_pretrained(p)
                pol.eval()
                pol.to(dev)
                pre, post = make_pre_post_processors(
                    pol.config, pretrained_path=p,
                    preprocessor_overrides={"device_processor": {"device": str(dev)}},
                    postprocessor_overrides={"device_processor": {"device": str(dev)}})
                n = sum(x.numel() for x in pol.parameters())
                r["deep"] = {"device": dev, "n_params": int(n),
                             "pre_ok": pre is not None, "post_ok": post is not None,
                             "n_action_steps": getattr(pol.config, "n_action_steps", None)}
                # 🚀 写回引擎的类级缓存 (真"预加载" → 重启后 L3 已就绪, 引擎首帧零加载)
                try:
                    sim_mod = sys.modules.get("state_space_sim_real")
                    if sim_mod is not None and hasattr(sim_mod, "RealStateSpaceSim"):
                        _c = sim_mod.RealStateSpaceSim
                        setattr(_c, "_L3_CACHE", (pol, pre, post))
                        setattr(_c, "_L3_DEV", dev)
                        r["deep"]["engine_cache_warmed"] = True
                    else:
                        r["deep"]["engine_cache_warmed"] = "(引擎未导入: 由 GUI 启动钩子调用时才会写回)"
                except Exception as e:                                      # noqa: BLE001
                    r["deep"]["engine_cache_warmed"] = "失败: %s" % e
                del pol
                try:
                    import torch as _t
                    _t.cuda.empty_cache()
                except Exception:                                           # noqa: BLE001
                    pass
        r["ok"] = bool(r.get("ok_light"))
    except Exception as e:                                                  # noqa: BLE001
        r["reason"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    r["secs"] = round(time.time() - t0, 2)
    return r


def load_l4(ent: dict, deep: bool = True) -> dict:
    """L4 真加载: 跨 venv 桥 hello → worker 真加载权重并回 trained/dims/reason。"""
    r = {"layer": "L4", "loader": "IntactRuntime(model_adapter) hello — INTACT venv 子进程", "ok": False}
    t0 = time.time()
    try:
        cache = ent.get("cache") or INTACT_CACHE
        os.environ["STABLEWM_HOME"] = cache
        os.environ.setdefault("LOCAL_DATASET_DIR", cache)
        os.environ["INTACT_POLICY"] = ent.get("policy", "intact_l4_current")
        os.environ["INTACT_RUNTIME"] = ent.get("runtime", "root")
        os.environ.setdefault("INTACT_DEVICE", "cpu")     # 权威: 不与 GPU 训练抢显存
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.policies.intact.runtime.model_adapter import IntactRuntime
        rt = IntactRuntime(policy="direct", policy_name=os.environ["INTACT_POLICY"],
                           runtime_kind=ent.get("runtime", "root"), autostart=False)
        _av, _why = rt.available()
        r["bridge_available"] = {"ok": bool(_av), "why": _why, "repo": rt.repo, "venv": rt.venv_python}
        if not _av:
            r["reason"] = "桥不可用: %s" % _why
            return r
        ok = rt.start()                     # 内部 _rpc({"cmd":"hello"}) — worker 真加载权重
        r["handshake"] = {"trained": bool(rt.trained), "dims": getattr(rt, "dims", None),
                          "reason": getattr(rt, "reason", None),
                          "runtime_kind": getattr(rt, "runtime_kind", None),
                          "policy_name": getattr(rt, "policy_name", None),
                          "device": getattr(rt, "device", None), "start_ok": bool(ok)}
        r["ok"] = bool(ok and rt.trained)
        if not r["ok"]:
            r["reason"] = "hello 未就绪: trained=%s · reason=%s" % (rt.trained, getattr(rt, "reason", None))
        r["weights_in_use"] = getattr(rt, "policy_name", None) or ent.get("policy")
        try:
            rt.close()
        except Exception:                                                   # noqa: BLE001
            pass
    except Exception as e:                                                  # noqa: BLE001
        import traceback
        r["reason"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        r["traceback_tail"] = traceback.format_exc().strip().splitlines()[-3:]
    r["secs"] = round(time.time() - t0, 2)
    return r


LOADERS = {"L2": load_l2, "L3": load_l3, "L4": load_l4}


# ─────────────────────────── 编排 ───────────────────────────
def autoload(log=None, only=("L2", "L3", "L4"), deep=None, quiet=False) -> dict:
    """重启自动加载入口 (GUI 启动后台线程 / CLI 共用)。

    对每层: 解析指针 → 真加载 → 落报告; 逐层串行 (8GB 卡上不并跑两个模型)。
    deep=None 时按 env ZMAX_AUTOLOAD_DEEP (默认 1) 决定是否做 L3 权重真前向加载。
    """
    def _say(s):
        if log:
            try:
                log(s)
            except Exception:                                               # noqa: BLE001
                pass
        elif not quiet:
            print(s, flush=True)

    if deep is None:
        deep = os.environ.get("ZMAX_AUTOLOAD_DEEP", "1") != "0"
    reg = load_registry(create=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    rep = {"ts": time.strftime("%F %T"), "trigger": "startup_autoload",
           "registry": os.path.relpath(REG_PATH, ROOT), "deep": bool(deep), "layers": {}}
    _say("🚀 模型重启自动加载 (真源 %s) — 逐层串行, 每层真加载并取证"
         % os.path.relpath(REG_PATH, ROOT))
    for k in ("L2", "L3", "L4"):
        if k not in only:
            continue
        ent = reg[k]
        rs = resolve_layer(k, ent)
        layer = {"resolve": rs, "name": ent.get("name")}
        if not rs.get("exists"):
            layer["ok"] = False
            layer["reason"] = "指针解析失败 (声明的路径不存在): %s" % rs.get("declared")
            rep["layers"][k] = layer
            _say("   ❌ %s 指针解析失败: %s" % (k, layer["reason"]))
            continue
        lr = LOADERS[k](ent, deep=deep)
        layer.update(lr)
        rep["layers"][k] = layer
        if lr.get("ok"):
            extra = ""
            if k == "L2":
                extra = " · 类别 %s · 真帧检出 %s" % (lr.get("classes"), (lr.get("inference") or {}).get("n_boxes"))
            if k == "L3":
                w = lr.get("weights") or {}
                extra = " · 权重 %sMB/%s tensors%s" % (w.get("size_mb"), w.get("n_tensors"),
                                                     (" · 真加载 %s" % (lr.get("deep") or {}).get("device")
                                                      if isinstance(lr.get("deep"), dict) else
                                                      " · " + str(lr.get("deep"))))
            if k == "L4":
                extra = " · trained=%s · %s" % ((lr.get("handshake") or {}).get("trained"),
                                               (lr.get("handshake") or {}).get("dims"))
            _say("   ✅ %s 已加载 · %s (%.1fs)%s" % (k, rs.get("realpath") or rs.get("weights") or rs["path"],
                                                   lr.get("secs") or 0, extra))
        else:
            _say("   ❌ %s 加载失败(如实上报, 不假装): %s" % (k, lr.get("reason")))
    rep["ok"] = all(v.get("ok") for v in rep["layers"].values()) and bool(rep["layers"])
    try:
        os.makedirs(REPORT_DIR, exist_ok=True)
        rp = os.path.join(REPORT_DIR, "model_autoload_%s.json" % ts)
        json.dump(rep, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        rep["report"] = rp
        _say("📄 自动加载报告: %s  (判据: %s)"
             % (os.path.relpath(rp, ROOT), "全部就绪" if rep["ok"] else "有层未就绪"))
    except Exception as e:                                                  # noqa: BLE001
        _say("⚠️ 报告写盘失败: %s" % e)
    return rep


def hook_status() -> dict:
    """重启挂钩现状: systemd 单元 / 控制台进程 / 启动代码位置。"""
    out = {"studio_unit": None, "console_pids": [], "startup_hook": "tools/gui/studio.py main(): "
           "import model_autoload → threading.Thread(autoload)"}
    try:
        u = subprocess.run(["systemctl", "--user", "cat", "zmax-studio"], capture_output=True, text=True)
        out["studio_unit"] = {"rc": u.returncode, "enabled": subprocess.run(
            ["systemctl", "--user", "is-enabled", "zmax-studio"], capture_output=True,
            text=True).stdout.strip(),
            "exec": [l for l in u.stdout.splitlines() if l.startswith(("ExecStart", "WorkingDirectory"))]}
    except Exception as e:                                                  # noqa: BLE001
        out["studio_unit"] = {"err": str(e)}
    try:
        o = subprocess.run(["pgrep", "-f", "studio.py"], capture_output=True, text=True).stdout.split()
        out["console_pids"] = [int(x) for x in o]
    except Exception:                                                       # noqa: BLE001
        pass
    out["startup_code"] = "tools/gui/studio.py (main, QApplication 之后 YOLO 预热同处)"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="重启自动加载 L2/L3/L4 模型 (真源 + 真加载器)")
    ap.add_argument("--only", default="L2,L3,L4")
    ap.add_argument("--deep", action="store_true", help="L3 也真 from_pretrained (默认按 env ZMAX_AUTOLOAD_DEEP=1)")
    ap.add_argument("--light", action="store_true", help="L3 只验权重文件/头, 不真加载进显存")
    ap.add_argument("--resolve", action="store_true", help="只解析指针 (不加载)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-registry", action="store_true")
    ap.add_argument("--hook-status", action="store_true")
    a = ap.parse_args()
    only = tuple(x.strip() for x in a.only.split(",") if x.strip())

    if a.write_registry:
        write_registry(load_registry())
        print("✅ 已写登记表 %s (L2/L3/L4 指针)" % os.path.relpath(REG_PATH, ROOT))
        return 0
    if a.hook_status:
        print(json.dumps(hook_status(), ensure_ascii=False, indent=1))
        return 0
    if a.resolve:
        reg = load_registry(create=True)
        rows = {k: resolve_layer(k, reg[k]) for k in only}
        print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else "")
        if not a.json:
            for k, v in rows.items():
                print("%-3s %-8s exists=%-5s %s" % (k, v["kind"], v["exists"],
                                                   v.get("realpath") or v.get("weights") or v["path"]))
        return 0 if all(v["exists"] for v in rows.values()) else 1
    deep = None if (not a.deep and not a.light) else (not a.light)
    rep = autoload(only=only, deep=deep)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
