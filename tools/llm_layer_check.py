#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 大模型层体检 (VLM/VLA 意图理解) — 只读, 不加载大权重到显存, 不发真机指令

老倪 (09-22): 「保证 大模型层, L4 INTACT, L3 Smolvla, L2 YOLO 和 2D转3D 深度」

体检内容 (全部只读):
  ① 权重就绪: HF 缓存里的 Qwen2.5-VL-3B-Instruct / SmolVLM2-500M (本机已有) 的体积与完整性
  ② 接口就绪: 引擎侧场景理解模块 (src/.../state_space/scene_vlm.py) 可导入 + 用到哪一路后端
  ③ 凭据就绪: DeepSeek API key (本机唯一可用云端大模型) 是否配置 (只报有无, 不打印密钥)
  ④ 显存预算: 3B 级 VLM 上卡需要多少空闲显存 (提示与训练错峰, 不抢训练 GPU)
  ⑤ 配置来源: config/robot/zmax_robot_spec.json + calib 注册表 → 大模型层提示词/几何上下文来源单一真源

输出 JSON 供编排器取证; 有缺项时退出码 1 (诚实报缺, 不编造)。
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HF = os.path.expanduser("~/.cache/huggingface/hub")


def _du_mb(p):
    tot = 0
    for r, _d, fs in os.walk(p):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return round(tot / 1e6, 1)


def check() -> dict:
    out = {"_ts": __import__("time").strftime("%F %T")}

    # ① 权重 (⚠️ "有快照目录"≠"权重下全了": 只下了 config 也会 has_snapshot=True → 必须按
    #    *.safetensors/*.bin 实际体积判定, 2026-09-22 实测踩到: Qwen2.5-VL-3B 目录只有 23MB
    #    = 只有小文件, 大权重没下; 不按体积判会把"没下完"报成 ✅)
    models = {}
    for key, pat, min_mb in (("qwen2.5-vl-3b", "models--Qwen--Qwen2.5-VL-3B-Instruct", 3000),
                             ("smolvlm2-500m", "models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct", 300),
                             ("intact-jepa", "models--INTACT-JEPA--INTACT", 100)):
        p = os.path.join(HF, pat)
        wfiles = []
        for r, _d, fs in os.walk(p):
            for f in fs:
                if f.endswith((".safetensors", ".bin", ".pt", ".pth")):
                    wfiles.append(os.path.join(r, f))
        wmb = round(sum(os.path.getsize(x) for x in wfiles) / 1e6, 1) if wfiles else 0.0
        models[key] = {"path": p, "exists": os.path.isdir(p),
                       "snapshot": bool(glob.glob(os.path.join(p, "snapshots", "*"))),
                       "weight_files": len(wfiles), "weight_mb": wmb,
                       "ready": wmb >= min_mb, "min_mb": min_mb}
    out["weights"] = models

    # ①b 本机**实际在用**的权重位置 (2026-09-22 修: 只查 HF 缓存会把"我们在役的权重"误报成未下全 ——
    #    INTACT 权重一直在 stable-wm-cache/checkpoints, 不在 HF hub 缓存里 → 假警报)
    local = {}
    CACHE = "/home/ubuntu/stable-wm-cache"
    l4_dir = os.path.join(CACHE, "checkpoints", "intact_l4_current")
    cands = glob.glob(os.path.join(CACHE, "checkpoints", "intact_goal_optical_insert_v6*_s3072", "weights_*.pt"))
    local["L4_INTACT_in_service"] = {
        "path": l4_dir, "exists": os.path.isdir(l4_dir),
        "target": (os.path.realpath(l4_dir) if os.path.isdir(l4_dir) else None),
        "n_ckpt_dirs": len({os.path.dirname(p) for p in cands}),
        "newest_ckpt_mb": (round(max(os.path.getsize(p) for p in cands) / 1e6, 1) if cands else 0.0),
        "ready": bool(cands) or os.path.isdir(l4_dir),
    }
    l3 = os.path.join(ROOT, "outputs/train/smolvla_lew_sim/checkpoints/000300")
    local["L3_SmolVLA"] = {"path": os.path.relpath(l3, ROOT), "exists": os.path.isdir(l3),
                           "ready": os.path.isdir(l3)}
    yl = os.path.join(ROOT, "models/yolo_peg_live.pt")
    local["L2_YOLO_live"] = {"path": os.path.relpath(yl, ROOT), "exists": os.path.exists(yl),
                             "target": (os.path.realpath(yl) if os.path.islink(yl) else None),
                             "ready": os.path.exists(yl)}
    out["local_weights"] = local

    sv = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/scene_vlm.py")
    out["engine_scene_vlm"] = {"path": os.path.relpath(sv, ROOT), "exists": os.path.exists(sv),
                               "importable": False, "note": ""}
    if os.path.exists(sv):
        try:
            spec = importlib.util.spec_from_file_location("zmax_scene_vlm", sv)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)                                      # noqa: F841
            out["engine_scene_vlm"]["importable"] = True
        except Exception as e:                                              # noqa: BLE001
            out["engine_scene_vlm"]["note"] = f"导入失败: {type(e).__name__}: {e}"

    # ③ 凭据 (只报有无)
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    cfg_hit = []
    for p in [os.path.expanduser("~/.hermes/config.yaml"), os.path.expanduser("~/.config/hermes/config.yaml")]:
        if os.path.exists(p):
            try:
                txt = open(p, encoding="utf-8", errors="replace").read()
                if "deepseek" in txt.lower():
                    cfg_hit.append(os.path.relpath(p, os.path.expanduser("~")))
            except OSError:
                pass
    out["creds"] = {"DEEPSEEK_API_KEY_env": bool(key), "deepseek_in_hermes_cfg": cfg_hit}

    # ④ 显存预算 (3B bf16 ≈ 6.0GB 权重 + KV/开销 ≈ 2GB)
    try:
        import subprocess
        used, total = [int(x) for x in subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True).stdout.strip().split(",")]
        out["gpu"] = {"used_mb": used, "total_mb": total, "free_mb": total - used,
                      "qwen3b_needs_mb": 8000,
                      "verdict": "可加载 (与训练错峰)" if total - used >= 8000 else "需等训练结束/错峰"}
    except Exception as e:                                                  # noqa: BLE001
        out["gpu"] = {"error": f"{type(e).__name__}: {e}"}

    # ⑤ 单一真源 (大模型层提示词里的几何/参数不许另写一份)
    spec = os.path.join(ROOT, "config/robot/zmax_robot_spec.json")
    calib = os.path.join(ROOT, "config/calib/zmax_calib.json")
    out["single_source"] = {"robot_spec": os.path.relpath(spec, ROOT) if os.path.exists(spec) else None,
                            "calib": os.path.relpath(calib, ROOT) if os.path.exists(calib) else None}

    # 判定: HF 缓存里只认"要从网上下的" (Qwen VL / SmolVLM 参考权重);
    #      L4/L3/L2 只看**本机在役权重**是否在位 (它们在 stable-wm-cache / models / outputs, 不在 HF 缓存)
    gaps = []
    # 🛠 2026-09-23 老倪: 全量 pipeline 跑通优先 —— qwen2.5-vl-3b 按**既定口径不启用**
    #   (L5 场景理解走 DeepSeek Vision API, 本地兜底 = smolvlm2-500m; 3B VL 需 8GB 显存, 8G 卡勿试),
    #   所以它只是 informational, **不算缺口** (原先把 gap 计成失败 → LLM 阶段 rc=1 拖垮整链)。
    for k in ("smolvlm2-500m",):
        v = (out.get("weights") or {}).get(k) or {}
        if not v.get("ready"):
            gaps.append(f"{k} 权重未下全 (实际 {v.get('weight_mb')}MB < 门槛 {v.get('min_mb')}MB)")
    _q = (out.get("weights") or {}).get("qwen2.5-vl-3b") or {}
    out["qwen3b_informational"] = (not _q.get("ready"))
    for k, v in local.items():
        if not v["ready"]:
            gaps.append(f"{k} 在役权重缺失 ({v['path']})")
    if not (out["creds"]["DEEPSEEK_API_KEY_env"] or cfg_hit):
        gaps.append("无云端大模型凭据 (DeepSeek key)")
    if not out["engine_scene_vlm"]["exists"]:
        gaps.append("引擎场景理解模块缺失")
    out["gaps"] = gaps
    return out


def main() -> int:
    r = check()
    print("🧠 大模型层体检 (只读)")
    print("─" * 76)
    for k, v in r["weights"].items():
        tag = "✅" if v["ready"] else ("⚠️ 未下全" if k == "qwen2.5-vl-3b" else "ℹ️ 缓存空(不影响在役)")
        print(f" HF缓存 {k:<16} {tag} {v['weight_mb']} MB / 门槛 {v['min_mb']} MB")
    for k, v in r["local_weights"].items():
        print(f" 在役   {k:<20} {'✅' if v['ready'] else '❌'} {v.get('path')}"
              + (f" → {os.path.basename(str(v.get('target')))}" if v.get("target") else ""))
    ev = r["engine_scene_vlm"]
    print(f"  引擎场景理解 scene_vlm.py: {'✅ 可导入' if ev['importable'] else '⚠️ ' + (ev['note'] or '缺')}")
    c = r["creds"]
    print(f"  凭据: DeepSeek key {'✅ env' if c['DEEPSEEK_API_KEY_env'] else ('✅ 配置文件 ' + ','.join(c['deepseek_in_hermes_cfg']) if c['deepseek_in_hermes_cfg'] else '❌ 无')}")
    g = r["gpu"]
    if "error" not in g:
        print(f"  显存: 空闲 {g['free_mb']} MB / 3B VL 级约需 {g['qwen3b_needs_mb']} MB → {g['verdict']}")
    print(f"  单一真源: robot_spec={r['single_source']['robot_spec']} calib={r['single_source']['calib']}")
    print("─" * 76)
    print("✅ 无缺口" if not r["gaps"] else "⚠️ 缺口: " + "; ".join(r["gaps"]))
    print(json.dumps(r, ensure_ascii=False))
    return 1 if r["gaps"] else 0


if __name__ == "__main__":
    sys.exit(main())
